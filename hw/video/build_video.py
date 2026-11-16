# Build hw/video/presentation.mp4 (+ presentation.srt):
#   1. Marp renders hw/video/slides.md to 1920x1080 PNGs,
#   2. hw/video/narration.md is split per slide ("## n") and per sentence; each sentence is synthesised with
#      BreezyVoice (tts_breezy.py: Taiwanese-Mandarin voice cloning, prompted with the student's own HW-2 narration)
#      on a GPU host over ssh (default: art, 4x V100). WAVs are cached in audio/<sha1>.wav, so editing the narration
#      only re-synthesises the changed sentences,
#   3. ffmpeg makes one segment per slide (still image + concatenated sentence audio + pause), concatenates them and
#      burns the subtitles in (libass); the SRT is also written next to the MP4.
#   python hw/video/build_video.py
# Needs npx (marp-cli), a Chrome/Chromium, ffmpeg with libass, Noto Sans CJK TC, and on the TTS host: a BreezyVoice
# checkout + venv + weights and the speaker prompt voice/ref.wav + voice/ref.txt (TTS_HOST / TTS_DIR below; the
# prompt recording is kept off the public repo).
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import tempfile

TTS_HOST = os.environ.get("TTS_HOST", "twtom@10.121.240.40")
TTS_DIR = os.environ.get("TTS_DIR", "/mnt/data/twtom/tts")
TTS_GPU = os.environ.get("TTS_GPU", "0,1,2,3")  # one TTS process per listed GPU on the TTS host
GAP, PAUSE = 0.18, 0.5  # silence between sentences / after each slide [s]
TEMPO = 1.1  # BreezyVoice copies the prompt's relaxed pace; 1.1x keeps the talk inside the 10-minute limit
here = pathlib.Path(__file__).resolve().parent
cache = here / "audio"
cache.mkdir(exist_ok=True)
tmp = pathlib.Path(tempfile.mkdtemp(dir="/dev/shm"))
chrome = next((p for p in ["/opt/google/chrome/chrome", shutil.which("chromium"), shutil.which("google-chrome"),
                           shutil.which("brave-browser")] if p and os.path.exists(p)), None)
env = dict(os.environ, TMPDIR=str(tmp), **({"CHROME_PATH": chrome} if chrome else {}))

subprocess.run(["npx", "-y", "@marp-team/marp-cli@latest", str(here / "slides.md"), "--images", "png", "--image-scale",
                "1.5", "--allow-local-files", "-o", str(tmp / "s.png")], check=True, env=env, stdout=subprocess.DEVNULL,
               stderr=subprocess.DEVNULL)
slides = sorted(tmp.glob("s.*.png"))
segs = [s.strip() for s in re.split(r"^## \d+\s*$", (here / "narration.md").read_text(), flags=re.M)[1:]]
assert len(segs) == len(slides), (len(segs), len(slides))
sentences = [[x.strip() for x in re.findall(r"[^。！？]+[。！？]?", s.replace("\n", "")) if x.strip()] for s in segs]


# Spoken form for the TTS (subtitles keep the written form): spell out acronyms/model numbers the voice misreads.
SAY = {"H200": "H 兩百", "H100": "H 一百", "nano4": "nano 四", "HW1": "HW 一", "MFC": "M F C", "HLLC": "H L L C",
       "WENO": "WENO", "PTX": "P T X", "SASS": "S A S S", "CMake": "C make", "GPU": "G P U", "MPI": "M P I",
       "HPC X": "H P C X", "SSH": "S S H", "AI agent": "A I agent", "HBM": "H B M",
       "SC26": "S C 二十六", "3D": "三 D", " GB": " G B", "SM": "S M", "srun": "S run", "rdma mpi": "R D M A M P I",
       "Coding Adv": "Coding advanced", "eeclass": "E E class", "sudo": "sudo", "brief": "brief"}


def spoken(text):
    for k in sorted(SAY, key=len, reverse=True):
        text = text.replace(k, SAY[k])
    return text


def key(text):
    return hashlib.sha1(("breezy:" + spoken(text)).encode()).hexdigest()[:16]


# ---- TTS (remote GPU), only for sentences not in the cache --------------------------------------------------------
todo = sorted({(key(t), spoken(t)) for ss in sentences for t in ss if not (cache / f"{key(t)}.wav").exists()})
if todo:
    # One BreezyVoice process per GPU (~30-50 s per sentence on a V100), sentences dealt round-robin.
    gpus = TTS_GPU.split(",")
    job = f"{TTS_DIR}/job-{os.getpid()}"
    for g in range(len(gpus)):
        (tmp / f"sentences{g}.json").write_text(json.dumps(todo[g::len(gpus)], ensure_ascii=False))
    subprocess.run(["ssh", TTS_HOST, f"mkdir -p {job}/out"], check=True)
    subprocess.run(["scp", "-q", *[str(tmp / f"sentences{g}.json") for g in range(len(gpus))],
                    str(here / "tts_breezy.py"), f"{TTS_HOST}:{job}/"], check=True)
    procs = [subprocess.Popen(["ssh", TTS_HOST, f"cd {TTS_DIR}/BreezyVoice && . ../bv/bin/activate && "
                               f"export PYTHONUTF8=1 HF_HOME={TTS_DIR}/hf CUDA_VISIBLE_DEVICES={gpu} && "
                               f"python {job}/tts_breezy.py {job}/sentences{g}.json {job}/out "
                               f"--ref {TTS_DIR}/voice/ref.wav --ref-text \"$(cat {TTS_DIR}/voice/ref.txt)\" "
                               f"--model {TTS_DIR}/models/BreezyVoice > {job}/log{g}.txt 2>&1"])
             for g, gpu in enumerate(gpus)]
    failed = [g for g, p in enumerate(procs) if p.wait() != 0]
    subprocess.run(["rsync", "-a", "--exclude", "*.json", "--exclude", "*.txt", "--exclude", "*.py",
                    f"{TTS_HOST}:{job}/out/", f"{cache}/"], check=True)
    if failed:
        raise SystemExit(f"TTS failed on GPU slot(s) {failed}; see {TTS_HOST}:{job}/log*.txt")
    subprocess.run(["ssh", TTS_HOST, f"rm -rf {job}"], check=True)
    print(f"synthesised {len(todo)} sentences")


def dur(p):
    return float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                                          "csv=p=0", str(p)]).decode())


def ts(t):
    h, r = divmod(t, 3600)
    m, s = divmod(r, 60)
    return f"{int(h):02d}:{int(m):02d}:{int(s):02d},{int(round((s - int(s)) * 1000)):03d}"


cues, parts, t0 = [], [], 0.0
silence = tmp / "gap.wav"
subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono", "-t", str(GAP),
                "-c:a", "pcm_s16le", str(silence)], check=True)
for i, img in enumerate(slides):
    lst, t = tmp / f"al{i:02d}.txt", t0
    lines = []
    for j, text in enumerate(sentences[i]):
        a = tmp / f"a{i:02d}_{j:02d}.wav"  # trim edge silence, tempo, uniform PCM for the concat demuxer
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(cache / f"{key(text)}.wav"), "-af",
                        "silenceremove=start_periods=1:start_threshold=-50dB,areverse,"
                        f"silenceremove=start_periods=1:start_threshold=-50dB,areverse,atempo={TEMPO}",
                        "-ar", "24000", "-ac", "1", "-c:a", "pcm_s16le", str(a)], check=True)
        d = dur(a)
        cues.append((t, t + d, text.rstrip("。")))
        t += d + GAP
        lines += [f"file '{a}'", f"file '{silence}'"]
    lst.write_text("\n".join(lines) + "\n")
    audio = tmp / f"audio{i:02d}.wav"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-af",
                    "loudnorm=I=-16:TP=-1.5:LRA=11", "-ar", "48000", "-ac", "1", str(audio)], check=True)
    seg_len = dur(audio) + PAUSE
    seg = tmp / f"seg{i:02d}.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-loop", "1", "-framerate", "10", "-i", str(img), "-i", str(audio),
                    "-af", f"apad=pad_dur={PAUSE}", "-t", f"{seg_len:.3f}", "-vf",
                    "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:white,format=yuv420p",
                    "-c:v", "libx264", "-tune", "stillimage", "-r", "10", "-c:a", "aac", "-b:a", "128k", "-ar", "48000",
                    str(seg)], check=True)
    parts.append(seg)
    t0 += seg_len
    print(f"slide {i + 1:2d}: {seg_len:6.1f} s, {len(sentences[i])} sentences")
srt = here / "presentation.srt"
srt.write_text("".join(f"{k + 1}\n{ts(a)} --> {ts(b)}\n{txt}\n\n" for k, (a, b, txt) in enumerate(cues)))
(tmp / "list.txt").write_text("".join(f"file '{p}'\n" for p in parts))
raw = tmp / "raw.mp4"
subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(tmp / "list.txt"), "-c",
                "copy", str(raw)], check=True)
style = ("FontName=Noto Sans CJK TC,FontSize=15,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BackColour=&H99000000,"
         "BorderStyle=4,Outline=0,Shadow=0,MarginV=14,Alignment=2")
shutil.copy(srt, tmp / "sub.srt")
out = here / "presentation.mp4"
subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(raw), "-vf", f"subtitles={tmp / 'sub.srt'}:force_style='{style}'",
                "-c:v", "libx264", "-tune", "stillimage", "-crf", "23", "-r", "10", "-c:a", "copy", "-movflags",
                "+faststart", str(out)], check=True)
shutil.rmtree(tmp)
print(f"total {t0:.1f} s ({t0 / 60:.2f} min), {len(cues)} subtitle cues -> {out} ({out.stat().st_size / 1e6:.1f} MB), {srt}")
