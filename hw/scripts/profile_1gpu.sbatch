#!/bin/bash
#SBATCH -J mfc-prof
#SBATCH -A ACD110018
#SBATCH -p dev
#SBATCH --exclude=25a-hgpn001,25a-hgpn062
#SBATCH -N 1
#SBATCH --gres=gpu:1
#SBATCH -c 12
#SBATCH -t 01:00:00
#SBATCH -o /work/twtomtwcc00/mfc-adv/logs/%x-%j.out
#
# nsys kernel summary (full 30-step run) and ncu metrics of the hot kernels (after the 2 warm-up steps)
# for each staged variant.
#   sbatch --export=ALL,VARIANTS="base hllc",TAG=prof-hllc hw/scripts/profile_1gpu.sbatch
# env: NCU=0 to skip ncu, NSYS=0 to skip nsys, KREGEX (ncu kernel filter), NCU_STEPS (default 3)
set -uo pipefail
source /work/twtomtwcc00/mfc-adv/scripts/env.sh
VARIANTS=${VARIANTS:-base}
TAG=${TAG:-prof-$SLURM_JOB_ID}
CASEDIR=${CASEDIR:-$ADV_CASE}
PRE_VARIANT=${PRE_VARIANT:-base}
KREGEX=${KREGEX:-regex:s_weno_|s_hllc_riemann_solver|s_finalize_riemann_solver|s_compute_advection_source_term|s_add_directional|s_tvd_rk|s_compute_rhs|s_pack_weno|s_convert_conservative}
RES=$ADV_WORK/results/$TAG
RUN=/tmp/mfcadv-$SLURM_JOB_ID
mkdir -p "$RES" "$RUN/ic"
nvidia-smi --query-gpu=name,uuid,driver_version,clocks.max.sm --format=csv > "$RES/node.txt"
hostname >> "$RES/node.txt"
nsys --version >> "$RES/node.txt"
ncu --version | tail -1 >> "$RES/node.txt"

cp "$ADV_WORK/inp/$CASEDIR/"*.inp "$RUN/ic/"
(cd "$RUN/ic" && $MPIRUN -np 1 "$ADV_WORK/bin/$PRE_VARIANT/pre_process" > pre.log 2>&1) || exit 1

for v in $VARIANTS; do
    if [ "${NSYS:-1}" = 1 ]; then
        d=$RUN/nsys-$v
        mkdir -p "$d" && cp "$RUN/ic/simulation.inp" "$d/" && cp -r "$RUN/ic/restart_data" "$d/"
        (cd "$d" && $MPIRUN -np 1 nsys profile -t cuda,nvtx,openacc -s none --cpuctxsw=none -o "$d/prof" -f true \
            "$ADV_WORK/bin/$v/simulation" > sim.log 2>&1)
        nsys stats -r cuda_gpu_kern_sum -f csv -o "$RES/nsys_$v" "$d/prof.nsys-rep" > /dev/null 2>&1
        nsys stats -r cuda_gpu_mem_time_sum -f csv -o "$RES/nsys_$v" "$d/prof.nsys-rep" > /dev/null 2>&1
        grep Performance "$d/sim.log" > "$RES/nsys_${v}_grind.txt"
        xz -T4 -c "$d/prof.nsys-rep" > "$RES/nsys_$v.nsys-rep.xz"
        rm -rf "$d"
    fi
    if [ "${NCU:-1}" = 1 ]; then
        d=$RUN/ncu-$v
        mkdir -p "$d" && cp "$RUN/ic/simulation.inp" "$d/" && cp -r "$RUN/ic/restart_data" "$d/"
        ns=${NCU_STEPS:-3}
        sed -i "s/^t_step_stop = .*/t_step_stop = $ns/; s/^t_step_save = .*/t_step_save = $ns/" "$d/simulation.inp"
        # profile only the stages of the last step (steps 0..ns-1; the first ones are warm-up)
        (cd "$d" && $MPIRUN -np 1 ncu --clock-control none --nvtx --nvtx-include "TIMESTEP/" -k "$KREGEX" \
            --launch-skip "${NCU_SKIP:-0}" --launch-count "${NCU_COUNT:-400}" \
            --section SpeedOfLight --section Occupancy --section LaunchStats --section MemoryWorkloadAnalysis \
            --section ComputeWorkloadAnalysis --section WarpStateStats \
            --metrics l1tex__t_bytes_pipe_lsu_mem_local_op_ld.sum,l1tex__t_bytes_pipe_lsu_mem_local_op_st.sum,dram__bytes_read.sum,dram__bytes_write.sum,sm__pipe_fp64_cycles_active.avg.pct_of_peak_sustained_active,launch__registers_per_thread,sm__warps_active.avg.pct_of_peak_sustained_active,sm__maximum_warps_per_active_cycle_pct,smsp__inst_executed.sum \
            -o "$d/ncu" -f "$ADV_WORK/bin/$v/simulation" > ncu.log 2>&1)
        tail -5 "$d/ncu.log" > "$RES/ncu_${v}_log.txt"
        ncu --import "$d/ncu.ncu-rep" --csv --page raw --print-kernel-base mangled > "$RES/ncu_${v}_raw.csv" 2>/dev/null
        xz -T4 -c "$d/ncu.ncu-rep" > "$RES/ncu_$v.ncu-rep.xz"
        rm -rf "$d"
    fi
done
rm -rf "$RUN"
