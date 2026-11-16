# Synthesise narration sentences with BreezyVoice (MediaTek Research, Apache-2.0), a CosyVoice-based voice-cloning
# TTS adapted for Taiwanese Mandarin (Traditional Chinese input, automatic 注音 via g2pw, good zh/en code-switching).
# The speaker prompt is the student's own narration from Coding-Basic-HW-2 (cloned with his consent; the video says
# the narration is synthesised).
#   cd BreezyVoice && python tts_breezy.py sentences.json outdir --ref ref.wav --ref-text "..." --model DIR
# sentences.json: [["key", "sentence text"], ...]  ->  outdir/key.wav
import argparse
import json
import os
import pathlib
import sys
import time

sys.path.insert(0, os.getcwd())  # run from the BreezyVoice checkout
from g2pw import G2PWConverter  # noqa: E402
from single_inference import CustomCosyVoice, single_inference  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("sentences")
ap.add_argument("outdir")
ap.add_argument("--ref", required=True)
ap.add_argument("--ref-text", required=True)
ap.add_argument("--model", default="MediaTek-Research/BreezyVoice")
args = ap.parse_args()

out = pathlib.Path(args.outdir)
out.mkdir(parents=True, exist_ok=True)
cosyvoice = CustomCosyVoice(args.model)
g2p = G2PWConverter()
items = [(k, t) for k, t in json.loads(pathlib.Path(args.sentences).read_text()) if not (out / f"{k}.wav").exists()]
for n, (k, text) in enumerate(items, 1):
    t0 = time.time()
    single_inference(args.ref, text, str(out / f"{k}.wav"), cosyvoice, g2p, args.ref_text)
    print(f"{n}/{len(items)} {k} in {time.time() - t0:.1f} s", flush=True)
