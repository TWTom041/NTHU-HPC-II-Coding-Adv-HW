# Coding-Adv-HW: MFC GPU optimisation on NVIDIA H200 (nano4)

This repository is MFC at upstream commit `3a9bb7662db5fb3139e2ee8cbdd6651e4dbe768e` plus six optimisation commits
and this `hw/` directory (harness, results, report). Student: 蔡昕翰 (114000110).

Headline (1 x H200, `examples/3D_performance_test`, NVHPC 26.3, median of 5): grind time 0.4026 -> **0.2581 ns/gp/eq/rhs
(1.56x)**, final state bit-identical to upstream.

| commit | change | cumulative grind (ns) |
|---|---|---:|
| `3a9bb766` | upstream baseline | 0.4026 |
| `06ee1a63` | HLLC: compile-time direction maps (BLOCK-local `dir_idx`/`dir_flg` constants) | 0.4031 |
| `82882c42` | NVHPC: `-Minline=...,smallsize:64` so small `!$acc routine seq` helpers are always inlined into kernels | 0.3657 |
| `b92b23ae` | Riemann: `flux_n`/`flux_src_n` point into the Riemann output buffers, finalize copy removed | 0.3355 |
| `bbc66c82` | WENO: input pack done once per RHS evaluation instead of once per sweep | 0.3153 |
| `039ee7bc` | NVHPC: `-gpu=maxregcount:128` for `m_weno` only | 0.2774 |
| `8cd486ab` | streaming kernels (RHS copy, flux difference, RK update): one thread per cell | 0.2581 |

Experiment branches (not merged): `exp-weno4` (WENO `collapse(4)`, slower), `exp-wenoflags` (per-file flag sweep),
`exp-stream` (became `8cd486ab`).

- Report (zh-TW): [`report.md`](report.md) / [`report.pdf`](report.pdf); agent timeline: [`AGENT_LOG.md`](AGENT_LOG.md)
- Raw and summarised measurements: [`results/`](results/)
- Slides: [`video/slides.pdf`](video/slides.pdf) (Marp source [`video/slides.md`](video/slides.md)); presentation video
  [`video/presentation.mp4`](video/presentation.mp4) with subtitles [`video/presentation.srt`](video/presentation.srt).
  Narration [`video/narration.md`](video/narration.md) is synthesised with Qwen3-TTS (`video/tts_qwen.py`, a designed
  narrator voice, not a clone of anyone); rebuild with `python3 hw/video/build_video.py`.

## Reproduce (nano4)

```bash
# 1. login node: build staged variants (case-optimized OpenACC, NVHPC 26.3) into /work/$USER/mfc-adv/bin/<name>
git clone https://github.com/TWTom041/NTHU-HPC-II-Coding-Adv-HW.git /tmp/$USER-mfcadv/base
mkdir -p /work/$USER/mfc-adv && cp -r /tmp/$USER-mfcadv/base/hw/scripts /work/$USER/mfc-adv/
S=/work/$USER/mfc-adv/scripts           # (paths in env.sh assume user twtomtwcc00; edit ADV_ROOT/ADV_WORK otherwise)
$S/build_variant.sh base 3a9bb766
$S/build_variant.sh opt  8cd486ab
# inputs: ./mfc.sh run examples/3D_performance_test/case.py -t pre_process simulation --case-optimization --gpu acc -n 1 --dry-run
#         then copy examples/3D_performance_test/{pre_process,simulation}.inp to $ADV_WORK/inp/3D_performance_test/

# 2. compute nodes
sbatch --export=ALL,VARIANTS="base opt",REPS=5,TAG=bench   $S/bench_1gpu.sbatch    # grind time + bitwise compare
sbatch --export=ALL,VARIANTS="base opt",TAG=prof           $S/profile_1gpu.sbatch  # nsys + ncu
sbatch --export=ALL,VARIANTS="base opt",NGPUS="1 2 4 8",TAG=mgpu $S/multigpu.sbatch
sbatch --export=ALL,REF=3a9bb766,TAG=test_base $S/regtest.sbatch                   # ./mfc.sh test on H200
sbatch --export=ALL,REF=8cd486ab,TAG=test_opt  $S/regtest.sbatch

# 3. analysis
python3 $S/summarize_grind.py results/bench/grind.csv
python3 $S/nsys_groups.py results/prof/nsys_base_cuda_gpu_kern_sum.csv results/prof/nsys_opt_cuda_gpu_kern_sum.csv
python3 $S/ncu_summary.py results/prof/ncu_opt_raw.csv
```

Report PDF: `hw/build_report.sh` (pandoc + LuaLaTeX, Noto Sans CJK TC).
