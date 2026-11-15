#!/bin/bash
# Build one case-optimized OpenACC variant of MFC on the nano4 login node and stage the binaries.
#
#   hw/scripts/build_variant.sh NAME GIT_REF [CASE_PY]
#
# env: NVHPC_VER (default 26.3), FFLAGS (extra Fortran flags, e.g. "-gpu=maxregcount:128"), JOBS (default 32)
# result: $ADV_WORK/bin/NAME/{simulation,pre_process,info.txt,resources.txt}
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
source "$HERE/env.sh"
NAME=$1
REF=$2
CASE=${3:-examples/3D_performance_test/case.py}
SRC=$ADV_ROOT/base
WT=$ADV_ROOT/wt/$NAME

if [ ! -d "$WT" ]; then
    git -C "$SRC" worktree add -q --detach "$WT" "$REF"
else
    git -C "$WT" checkout -q --detach "$REF"
fi
cd "$WT"
echo "[$(date +%T)] building $NAME @ $(git rev-parse --short HEAD) NVHPC=$NVHPC_VER FFLAGS='${FFLAGS:-}'"
t0=$(date +%s)
./mfc.sh build -t pre_process simulation --gpu acc --case-optimization -i "$CASE" -j "${JOBS:-32}" > "build_$NAME.log" 2>&1 ||
    { tail -40 "build_$NAME.log"; exit 1; }
t1=$(date +%s)
SIM=$(ls -t build/install/*/bin/simulation | head -1)
PRE=$(ls -t build/install/*/bin/pre_process | head -1)
STAGING=build/staging/$(basename "$(dirname "$(dirname "$SIM")")")

OUT=$ADV_WORK/bin/$NAME
mkdir -p "$OUT"
cp "$SIM" "$PRE" "$OUT/"
{
    echo "name=$NAME"
    echo "git=$(git rev-parse HEAD)"
    echo "describe=$(git log -1 --format='%h %s')"
    echo "nvhpc=$NVHPC_VER ($(nvfortran --version | sed -n 2p))"
    echo "fflags=${FFLAGS:-}"
    echo "case=$CASE"
    echo "build_seconds=$((t1 - t0))"
    echo "built=$(date -Iseconds) on $(hostname)"
} > "$OUT/info.txt"
"$HERE/kernel_resources.sh" "$STAGING" > "$OUT/resources.txt"
echo "[$(date +%T)] done $NAME in $((t1 - t0)) s -> $OUT"
