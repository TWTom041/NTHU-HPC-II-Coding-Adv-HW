# Results

`raw/` holds every job's output as written by the harness on nano4 (`/work/twtomtwcc00/mfc-adv/results/<TAG>`),
minus the compressed `.nsys-rep` / `.ncu-rep` files (kept on nano4 to save space). The top-level `*.txt` files are
the first results copied before the SSH connection to nano4 dropped (2026-11-16 05:20); everything after that is in `raw/`.

| `raw/<TAG>` | job | content |
|---|---|---|
| `bench_base_hllc`, `bench_inline` | 783950, 783958 | first 1-GPU benchmarks (baseline, commits 1-2) |
| `bench_all`, `bench_stream` | 783994, 784005 | commits 3-4 alone and cumulative; experiments (`exp_weno4`, `exp_wenoreg128`, `exp_stream`) |
| **`bench_final`** | 785519 | **all variants in one job**: base, every commit alone (`iso_*`) and cumulative, final, register sweep, WENO collapse(4); `compare_*.txt` bitwise checks, `determinism_base.txt` |
| `prof_base_hllc`, `prof_inline`, `prof_all` | 783951, 783961, 783995 | nsys kernel summaries + ncu raw CSVs (baseline, inline, pack, WENO experiments) |
| **`prof_final`** | 785520 | nsys + ncu of baseline and final |
| `test_base`, `test_opt` | 785415, 785521 | full `./mfc.sh test --gpu acc` on H200 for 3a9bb766 and 8cd486ab (`test.log.xz`, `summary.txt`) |
| `test_base_mpi`, `test_opt_mpi`, `test_opt_mpi2` | 785872, 785873, 785982 | rerun of the 8 two-rank tests with Open MPI oversubscription |
| `mgpu8` | 783997 | whole-node 1/2/4/8 GPU scaling, base and commit 4 |
| **`mgpu_final`** | 785522 | whole-node 1/2/4/8 GPU scaling, base and final, rdma_mpi F/T x binding none/numa |
| `mgpu4`, `mgpu4_final` | 783996, 786017 | 4-GPU jobs on shared nodes: not used (see report section 7) |

Analysis commands: `scripts/summarize_grind.py raw/bench_final/grind.csv`,
`scripts/nsys_groups.py raw/prof_final/nsys_{base,final}_cuda_gpu_kern_sum.csv`, `scripts/ncu_summary.py raw/prof_final/ncu_final_raw.csv`.
