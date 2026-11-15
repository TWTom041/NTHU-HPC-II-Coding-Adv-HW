# Results

Measurements that were copied back from nano4 before the SSH ControlMaster connection to nano4 dropped
(2026-11-16 ~05:20 Asia/Taipei). The files below are verbatim outputs of the harness (`summarize_grind.py`,
`compare.py`, `nsys_groups.py`, `ncu_summary.py`, `kernel_resources.sh`) as printed in the job outputs.

Jobs that were still queued/running at that moment write to `/work/twtomtwcc00/mfc-adv/results/` on nano4 and are
**not** in this directory yet: `bench_all` (all variants incl. alias/pack and the experiments), `bench_stream`,
`prof_all`, `mgpu4`, `mgpu8`, `test_base`, `test_opt`. Pull them with

```bash
rsync -a twtomtwcc00@nano4.nchc.org.tw:/work/twtomtwcc00/mfc-adv/results/ hw/results/raw/
```

| file | content |
|---|---|
| `bench_base_hllc.txt` | job 783950, node 25a-hgpn012: base vs commit 1, 5 interleaved reps, bitwise compare, determinism |
| `bench_inline.txt` | job 783958: base, commit 2 alone (`iso_inline`), commit 1, commits 1+2 (`inline`), bitwise compares |
| `nsys_base.txt` | job 783951: nsys kernel groups of the baseline, ms per RK stage (30 steps, 90 stages) |
| `ncu_base_vs_hllc.txt` | job 783951: ncu per-kernel metrics, last of 3 steps |
| `kernel_resources.txt` | registers and SASS LDL/STL of the hot kernels for base / hllc / iso_inline / inline |
