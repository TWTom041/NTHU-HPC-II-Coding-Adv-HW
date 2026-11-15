# Build hw/report.pdf from hw/report.md (Markdown + $$LaTeX$$ display math -> HTML + MathML -> headless Chromium PDF).
#   uv run --with markdown --with latex2mathml python hw/build_report.py
import os
import pathlib
import re
import subprocess
import tempfile

import latex2mathml.converter
import markdown

here = pathlib.Path(__file__).resolve().parent
src = (here / "report.md").read_text()

# YAML-ish front matter
meta = {}
if src.startswith("---\n"):
    head, src = src[4:].split("\n---\n", 1)
    for line in head.splitlines():
        k, v = line.split(":", 1)
        meta[k.strip()] = v.strip()

# display math $$...$$ outside fenced code blocks -> MathML placeholders
parts = re.split(r"(```.*?```)", src, flags=re.S)
math = []


def repl(m):
    math.append(latex2mathml.converter.convert(m.group(1).strip(), display="block"))
    return f"\n\nMATHBLOCK{len(math) - 1}\n\n"


src = "".join(p if p.startswith("```") else re.sub(r"\$\$(.+?)\$\$", repl, p, flags=re.S) for p in parts)

body = markdown.markdown("[TOC]\n\n" + src, extensions=["tables", "fenced_code", "toc", "sane_lists"],
                         extension_configs={"toc": {"toc_depth": "1-2", "title": "目錄"}})
for i, mm in enumerate(math):
    body = body.replace(f"<p>MATHBLOCK{i}</p>", f'<div class="math">{mm}</div>')

css = """
@page { size: A4; margin: 18mm 16mm 18mm 16mm; }
body { font-family: 'Noto Sans CJK TC', 'Noto Sans', sans-serif; font-size: 10.5pt; line-height: 1.6; color: #1a1a1a; }
h1 { font-size: 17pt; color: #1f3d64; border-bottom: 2px solid #1f3d64; padding-bottom: 3px; margin-top: 1.4em; break-before: page; }
h2 { font-size: 13pt; color: #1f3d64; margin-top: 1.2em; break-after: avoid; }
h3 { font-size: 11pt; break-after: avoid; }
.title-page { height: 250mm; display: flex; flex-direction: column; justify-content: center; text-align: center; break-after: page; }
.title-page .t { font-size: 24pt; font-weight: 700; color: #1f3d64; margin-bottom: 0.6em; }
.title-page .st { font-size: 14pt; color: #444; }
.title-page .meta { margin-top: 3em; font-size: 11pt; color: #555; }
.toc { break-after: page; }
.toc > ul { list-style: none; padding-left: 0; }
.toc ul ul { list-style: none; padding-left: 1.4em; }
.toc a { color: #1a1a1a; text-decoration: none; }
.toctitle { font-size: 17pt; font-weight: 700; color: #1f3d64; }
table { border-collapse: collapse; margin: 0.8em 0; font-size: 9pt; width: 100%; break-inside: avoid; }
th, td { border: 1px solid #c8d0da; padding: 3px 6px; vertical-align: top; }
th { background: #eef2f7; }
tr:nth-child(even) td { background: #fafbfc; }
code { font-family: 'Noto Sans Mono CJK TC', 'DejaVu Sans Mono', monospace; font-size: 8.8pt; background: #f2f4f7; padding: 0 3px; border-radius: 3px; }
pre { background: #f5f7fa; border: 1px solid #dde3ea; padding: 8px 10px; border-radius: 4px; font-size: 8.5pt; line-height: 1.4; break-inside: avoid; white-space: pre-wrap; }
pre code { background: none; padding: 0; }
img[src$=".svg"] { width: 100%; }
img { display: block; max-width: 100%; margin: 0.6em auto; break-inside: avoid; }
p:has(> img) { break-inside: avoid; }
blockquote { border-left: 4px solid #9fb3c8; margin: 0.6em 0; padding: 0.2em 0.9em; color: #333; background: #f7f9fb; }
.math { margin: 0.7em 0; text-align: center; font-size: 11.5pt; }
a { color: #1f5fa8; }
hr { border: none; border-top: 1px solid #ccd; margin: 1.2em 0; }
"""
title = f"""<div class="title-page"><div class="t">{meta.get('title', '')}</div>
<div class="st">{meta.get('subtitle', '')}</div>
<div class="meta">{meta.get('author', '')}<br>{meta.get('date', '')}<br>
MFC 3a9bb766 · NVIDIA H200 @ nano4 · NVHPC 26.3</div></div>"""
html = f"""<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8"><title>{meta.get('title', '')}</title>
<style>{css}</style></head><body>{title}{body}</body></html>"""
(here / "report.html").write_text(html)

tmp = tempfile.mkdtemp(dir="/dev/shm")
env = dict(os.environ, TMPDIR=tmp)
out = here / "report.pdf"
subprocess.run([os.environ.get("CHROME", "/opt/brave.com/brave/brave"), "--headless=new", "--no-sandbox", "--disable-gpu",
                f"--user-data-dir={tmp}/profile", "--no-pdf-header-footer", "--virtual-time-budget=5000",
                f"--print-to-pdf={tmp}/report.pdf", (here / "report.html").as_uri()], check=True, env=env,
               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=180)
out.write_bytes(pathlib.Path(tmp, "report.pdf").read_bytes())
subprocess.run(["rm", "-rf", tmp])
print("wrote", out, out.stat().st_size, "bytes")
