#!/bin/bash
# Render hw/report.md to hw/report.pdf (pandoc + LuaLaTeX; xelatex's xdvipdfmx rejects the Noto CJK .ttc here).
set -euo pipefail
cd "$(dirname "$0")"
pandoc report.md -o report.pdf --pdf-engine=lualatex --toc \
    -V CJKmainfont="Noto Sans CJK TC" -V mainfont="Noto Sans CJK TC" -V monofont="DejaVu Sans Mono" \
    -V geometry:margin=14mm -V fontsize=10pt -V colorlinks=true -V linkcolor=blue
echo "wrote $(pwd)/report.pdf"
