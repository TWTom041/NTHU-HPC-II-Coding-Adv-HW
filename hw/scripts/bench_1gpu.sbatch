#!/bin/bash
#SBATCH -J mfc-bench
#SBATCH -A ACD110018
#SBATCH -p dev
#SBATCH --exclude=25a-hgpn001,25a-hgpn062
#SBATCH -N 1
#SBATCH --gres=gpu:1
#SBATCH -c 12
#SBATCH -t 01:00:00
#SBATCH -o /work/twtomtwcc00/mfc-adv/logs/%x-%j.out
#
# Grind-time benchmark of several staged variants on ONE H200, interleaved (v1 v2 ... v1 v2 ...) so that
# drift affects all variants alike. One shared initial condition (pre_process of PRE_VARIANT).
# Also keeps the final state of each variant (and of a 2nd run of the first variant, for a determinism
# check) and compares it with the first variant using compare.py.
#
#   sbatch --export=ALL,VARIANTS="base hllc",REPS=5,TAG=hllc hw/scripts/bench_1gpu.sbatch
set -uo pipefail
source /work/twtomtwcc00/mfc-adv/scripts/env.sh
VARIANTS=${VARIANTS:-base}
REPS=${REPS:-5}
TAG=${TAG:-bench-$SLURM_JOB_ID}
CASEDIR=${CASEDIR:-$ADV_CASE}
PRE_VARIANT=${PRE_VARIANT:-base}
STEP_STOP=${STEP_STOP:-}
RES=$ADV_WORK/results/$TAG
RUN=/tmp/mfcadv-$SLURM_JOB_ID
mkdir -p "$RES" "$RUN/ic"
ref=${VARIANTS%% *}

{
    echo "job=$SLURM_JOB_ID node=$(hostname) date=$(date -Iseconds)"
    echo "variants=$VARIANTS reps=$REPS case=$CASEDIR"
    nvidia-smi --query-gpu=name,uuid,driver_version,clocks.max.sm,clocks.max.mem,power.limit,temperature.gpu --format=csv
    for v in $VARIANTS; do echo "--- $v"; cat "$ADV_WORK/bin/$v/info.txt"; done
} > "$RES/node.txt"

cp "$ADV_WORK/inp/$CASEDIR/"*.inp "$RUN/ic/"
if [ -n "$STEP_STOP" ]; then
    sed -i "s/^t_step_stop = .*/t_step_stop = $STEP_STOP/; s/^t_step_save = .*/t_step_save = $STEP_STOP/" "$RUN/ic/simulation.inp"
fi
STOP=$(awk -F' = ' '/^t_step_stop/{print $2}' "$RUN/ic/simulation.inp")
(cd "$RUN/ic" && $MPIRUN -np 1 "$ADV_WORK/bin/$PRE_VARIANT/pre_process" > pre.log 2>&1) || { tail "$RUN/ic/pre.log"; exit 1; }

echo "variant,rep,grind_ns,time_avg_s,wall_s" > "$RES/grind.csv"
for r in $(seq 1 "$REPS"); do
    for v in $VARIANTS; do
        d=$RUN/$v-$r
        mkdir -p "$d"
        cp "$RUN/ic/simulation.inp" "$d/"
        cp -r "$RUN/ic/restart_data" "$d/"
        t0=$(date +%s.%N)
        (cd "$d" && $MPIRUN -np 1 "$ADV_WORK/bin/$v/simulation" > sim.log 2>&1)
        t1=$(date +%s.%N)
        g=$(awk '/Performance:/{print $2}' "$d/sim.log")
        ta=$(grep -o 'Time Avg = *[0-9.E+-]*' "$d/sim.log" | tail -1 | awk '{print $4}')
        echo "$v,$r,${g:-NaN},${ta:-NaN},$(awk -v a="$t0" -v b="$t1" 'BEGIN{printf "%.2f", b - a}')" >> "$RES/grind.csv"
        if [ "$r" -le 2 ]; then
            mv "$d/restart_data/lustre_${STOP}.dat" "$RUN/final_${v}_$r.dat" 2>/dev/null
            [ "$r" = 1 ] && cp "$d/sim.log" "$RES/sim_$v.log"
        fi
        rm -rf "$d"
    done
done

for v in $VARIANTS; do
    [ -f "$RUN/final_${v}_1.dat" ] || continue
    python3 "$ADV_WORK/scripts/compare.py" "$RUN/final_${ref}_1.dat" "$RUN/final_${v}_1.dat" --json "$RES/compare_${v}.json" > "$RES/compare_${v}.txt"
done
python3 "$ADV_WORK/scripts/compare.py" "$RUN/final_${ref}_1.dat" "$RUN/final_${ref}_2.dat" > "$RES/determinism_${ref}.txt"
python3 "$ADV_WORK/scripts/summarize_grind.py" "$RES/grind.csv" | tee "$RES/summary.txt"
rm -rf "$RUN"
