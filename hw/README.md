# Coding-Adv-HW: MFC GPU optimisation on NVIDIA H200 (nano4)

This repository is MFC at upstream commit `3a9bb7662db5fb3139e2ee8cbdd6651e4dbe768e` plus four optimisation commits
and this `hw/` directory (harness, results, report). Student: 蔡昕翰 (114000110).

| commit | change |
|---|---|
| `06ee1a63` | HLLC: compile-time direction maps (BLOCK-local `dir_idx`/`dir_flg` constants) |
| `82882c42` | NVHPC: `-Minline=...,smallsize:64` so small `!$acc routine seq` helpers are always inlined into kernels |
| `b92b23ae` | Riemann: `flux_n`/`flux_src_n` point into the Riemann output buffers, finalize copy removed |
| `bbc66c82` | WENO: input pack done once per RHS evaluation instead of once per sweep |

- Report (zh-TW): [`report.md`](report.md) / [`report.pdf`](report.pdf); agent timeline: [`AGENT_LOG.md`](AGENT_LOG.md)
- Raw and summarised measurements: [`results/`](results/)

## Reproduce (nano4)

```bash
# 1. login node: build staged variants (case-optimized OpenACC, NVHPC 26.3) into /work/$USER/mfc-adv/bin/<name>
git clone https://github.com/TWTom041/NTHU-HPC-II-Coding-Adv-HW.git /tmp/$USER-mfcadv/base
mkdir -p /work/$USER/mfc-adv && cp -r /tmp/$USER-mfcadv/base/hw/scripts /work/$USER/mfc-adv/
S=/work/$USER/mfc-adv/scripts           # (paths in env.sh assume user twtomtwcc00; edit ADV_ROOT/ADV_WORK otherwise)
$S/build_variant.sh base 3a9bb766
$S/build_variant.sh opt  bbc66c82
# inputs: ./mfc.sh run examples/3D_performance_test/case.py -t pre_process simulation --case-optimization --gpu acc -n 1 --dry-run
#         then copy examples/3D_performance_test/{pre_process,simulation}.inp to $ADV_WORK/inp/3D_performance_test/

# 2. compute nodes
sbatch --export=ALL,VARIANTS="base opt",REPS=5,TAG=bench   $S/bench_1gpu.sbatch    # grind time + bitwise compare
sbatch --export=ALL,VARIANTS="base opt",TAG=prof           $S/profile_1gpu.sbatch  # nsys + ncu
sbatch --export=ALL,VARIANTS="base opt",NGPUS="1 2 4 8",TAG=mgpu $S/multigpu.sbatch
sbatch --export=ALL,REF=3a9bb766,TAG=test_base $S/regtest.sbatch                   # ./mfc.sh test on H200
sbatch --export=ALL,REF=bbc66c82,TAG=test_opt  $S/regtest.sbatch

# 3. analysis
python3 $S/summarize_grind.py results/bench/grind.csv
python3 $S/nsys_groups.py results/prof/nsys_base_cuda_gpu_kern_sum.csv results/prof/nsys_opt_cuda_gpu_kern_sum.csv
python3 $S/ncu_summary.py results/prof/ncu_opt_raw.csv
```

Report PDF: `uv run --with markdown --with latex2mathml python hw/build_report.py` (headless Chromium; set `CHROME=`).
