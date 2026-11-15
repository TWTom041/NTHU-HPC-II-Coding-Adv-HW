#!/bin/bash
#SBATCH -J mfc-mgpu
#SBATCH -A ACD110018
#SBATCH -p dev
#SBATCH --exclude=25a-hgpn001,25a-hgpn062
#SBATCH -N 1
#SBATCH --gres=gpu:8
#SBATCH --ntasks-per-node=8
#SBATCH -c 12
#SBATCH -t 02:00:00
#SBATCH -o /work/twtomtwcc00/mfc-adv/logs/%x-%j.out
#
# Strong scaling of the 201^3 case on 1/2/4/8 H200 of one node: variants x GPU counts x rdma_mpi (F/T) x binding.
# One MPI rank per GPU (MFC picks device = node-local rank mod #GPUs).
#   sbatch --export=ALL,VARIANTS="base final",NGPUS="1 2 4 8",REPS=3,TAG=mgpu hw/scripts/multigpu.sbatch
# BINDS: "none" = --bind-to none; "numa" = 4 ranks per NUMA domain, each bound to its domain (GPU 0-3 sit on NUMA 0,
# GPU 4-7 on NUMA 1 on nano4; checked in topo.txt).
set -uo pipefail
source /work/twtomtwcc00/mfc-adv/scripts/env.sh
VARIANTS=${VARIANTS:-base}
NGPUS=${NGPUS:-"1 2 4 8"}
RDMAS=${RDMAS:-"F T"}
BINDS=${BINDS:-"none numa"}
REPS=${REPS:-3}
TAG=${TAG:-mgpu-$SLURM_JOB_ID}
CASEDIR=${CASEDIR:-$ADV_CASE}
RES=$ADV_WORK/results/$TAG
RUN=/tmp/mfcadv-$SLURM_JOB_ID
mkdir -p "$RES" "$RUN"

{
    echo "job=$SLURM_JOB_ID node=$(hostname) date=$(date -Iseconds)"
    nvidia-smi topo -m
    nvidia-smi --query-gpu=index,name,pci.bus_id --format=csv
    lscpu | grep -E "NUMA node|Model name"
    for v in $VARIANTS; do echo "--- $v"; cat "$ADV_WORK/bin/$v/info.txt"; done
} > "$RES/topo.txt" 2>&1

# initial condition written by pre_process with the same rank count (same domain decomposition) as the run
for g in $NGPUS; do
    mkdir -p "$RUN/ic$g"
    cp "$ADV_WORK/inp/$CASEDIR/"*.inp "$RUN/ic$g/"
    (cd "$RUN/ic$g" && mpirun --bind-to none -np "$g" "$ADV_WORK/bin/base/pre_process" > pre.log 2>&1) ||
        { tail "$RUN/ic$g/pre.log"; exit 1; }
done

echo "variant,ngpu,rdma,bind,rep,grind_ns,time_avg_s" > "$RES/grind.csv"
for r in $(seq 1 "$REPS"); do
    for v in $VARIANTS; do
        for g in $NGPUS; do
            for rdma in $RDMAS; do
                for b in $BINDS; do
                    [ "$g" = 1 ] && [ "$b" != none ] && continue
                    if [ "$b" = numa ]; then bopt="--map-by ppr:4:numa --bind-to numa"; else bopt="--bind-to none"; fi
                    d=$RUN/$v-$g-$rdma-$b-$r
                    mkdir -p "$d"
                    cp "$RUN/ic$g/simulation.inp" "$d/"
                    sed -i "/^&end/i rdma_mpi = $rdma" "$d/simulation.inp"
                    cp -r "$RUN/ic$g/restart_data" "$d/"
                    (cd "$d" && mpirun $bopt -np "$g" -x UCX_WARN_UNUSED_ENV_VARS=n "$ADV_WORK/bin/$v/simulation" > sim.log 2>&1)
                    gr=$(awk '/Performance:/{print $2}' "$d/sim.log")
                    ta=$(grep -o 'Time Avg = *[0-9.E+-]*' "$d/sim.log" | tail -1 | awk '{print $4}')
                    echo "$v,$g,$rdma,$b,$r,${gr:-NaN},${ta:-NaN}" >> "$RES/grind.csv"
                    [ -z "$gr" ] && tail -20 "$d/sim.log" > "$RES/fail_$v-$g-$rdma-$b-$r.log"
                    if [ "$r" = 1 ] && [ "$b" = none ]; then
                        mv "$d/restart_data/lustre_30.dat" "$RUN/final_$v-$g-$rdma.dat" 2>/dev/null
                    fi
                    rm -rf "$d"
                done
            done
        done
    done
done

# multi-rank results must match the 1-GPU result of the same binary (halo exchange correctness)
for v in $VARIANTS; do
    for f in "$RUN"/final_"$v"-*.dat; do
        [ -f "$f" ] || continue
        python3 "$ADV_WORK/scripts/compare.py" "$RUN/final_$v-1-F.dat" "$f" > "$RES/compare_$(basename "$f" .dat).txt"
    done
done
rm -rf "$RUN"
