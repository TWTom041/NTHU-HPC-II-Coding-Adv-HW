#!/bin/bash
# Per-kernel static resources of the hot-path modules from the cubins kept by -gpu=keep:
# registers (cuobjdump -res-usage) and the number of local-memory load/store instructions (LDL/STL) in SASS.
#   hw/scripts/kernel_resources.sh BUILD_STAGING_DIR
set -euo pipefail
export LC_ALL=C
D=$1
printf "%-62s %5s %5s %5s\n" kernel REG LDL STL
for m in m_riemann_solver_hllc m_weno m_rhs m_time_steppers m_riemann_state m_variables_conversion; do
    f=$D/$m.fpp.n001.cubin
    [ -f "$f" ] || continue
    join -j1 \
        <(cuobjdump -res-usage "$f" | awk '/Function/{sub(":","",$2); n=$2} /REG:/{split($1,a,":"); print n, a[2]}' | sort) \
        <(cuobjdump -sass "$f" | awk '/Function :/{n=$3; l[n]+=0; s[n]+=0} /LDL/{l[n]++} /STL/{s[n]++} END{for (k in l) print k, l[k], s[k]}' | sort) |
        awk -v m="$m" '$1 ~ m {printf "%-62s %5d %5d %5d\n", $1, $2, $3, $4}'
done
