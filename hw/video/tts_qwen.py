# Synthesise narration sentences with Qwen3-TTS (open weights, Apache-2.0) on a CUDA GPU.
#   1. VoiceDesign model creates one reference clip for the narrator persona (cached as ref.wav),
#   2. the Base model clones that reference for every sentence, so the voice stays consistent.
#   python tts_qwen.py sentences.json outdir [--models DIR] [--device cuda:0]
# sentences.json: [["01_00", "sentence text"], ...]  ->  outdir/01_00.wav (24 kHz mono)
import argparse
import json
import pathlib

import opencc
import soundfile as sf
import torch
from qwen_tts import Qwen3TTSModel

REF_TEXT = "大家好，這是我這次作業的報告。我會先說明我量了什麼、怎麼量，再一個一個介紹每個優化帶來的效果。"
REF_INSTRUCT = ("台灣年輕男性研究生，二十多歲，標準台灣國語口音，音色清晰溫和、中音域，"
                "語速適中偏穩，像在研討會上做技術簡報，自信、自然、不誇張，咬字清楚。")

ap = argparse.ArgumentParser()
ap.add_argument("sentences")
ap.add_argument("outdir")
ap.add_argument("--models", default="models")
ap.add_argument("--device", default="cuda:0")
ap.add_argument("--batch", type=int, default=8)
args = ap.parse_args()

# The model is trained mostly on Simplified Chinese: feed it Simplified (same pronunciation, fewer misreadings).
t2s = opencc.OpenCC("t2s")
out = pathlib.Path(args.outdir)
out.mkdir(parents=True, exist_ok=True)
models = pathlib.Path(args.models)
# V100 has no bf16; fp16 + SDPA works there, bf16 elsewhere.
major = torch.cuda.get_device_capability(args.device)[0]
dtype = torch.bfloat16 if major >= 8 else torch.float16
kw = dict(device_map=args.device, dtype=dtype, attn_implementation="sdpa")

ref = out / "ref.wav"
if not ref.exists():
    design = Qwen3TTSModel.from_pretrained(str(models / "Qwen3-TTS-12Hz-1.7B-VoiceDesign"), **kw)
    wavs, sr = design.generate_voice_design(text=t2s.convert(REF_TEXT), language="Chinese", instruct=REF_INSTRUCT)
    sf.write(ref, wavs[0], sr)
    del design
    torch.cuda.empty_cache()

clone = Qwen3TTSModel.from_pretrained(str(models / "Qwen3-TTS-12Hz-1.7B-Base"), **kw)
prompt = clone.create_voice_clone_prompt(ref_audio=str(ref), ref_text=t2s.convert(REF_TEXT))

items = [(i, t2s.convert(t)) for i, t in json.loads(pathlib.Path(args.sentences).read_text())
         if not (out / f"{i}.wav").exists()]
for k in range(0, len(items), args.batch):
    chunk = items[k:k + args.batch]
    wavs, sr = clone.generate_voice_clone(text=[t for _, t in chunk], language=["Chinese"] * len(chunk),
                                          voice_clone_prompt=prompt)
    for (i, _), w in zip(chunk, wavs):
        sf.write(out / f"{i}.wav", w, sr)
    print(f"{k + len(chunk)}/{len(items)}", flush=True)
