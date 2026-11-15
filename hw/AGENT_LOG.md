# AGENT_LOG — Coding-Adv-HW (MFC on nano4 H200)

Coding agent: Claude (Anthropic) running in the `omp` coding harness on the student's workstation, driving nano4 through
an existing SSH ControlMaster socket and Slurm (`-A ACD110018 -p dev`). The main agent wrote a brief
(`adv_brief.md`: assignment text, HW-1 findings, nano4 access and disk-quota rules) and delegated the whole
optimisation work to one worker agent (this log). Times are Asia/Taipei, 2026-11-16.

## What the humans decided

- The student chose MFC (not WRF), nano4 H200, and asked the agent to do the homework end to end except slides,
  video and eeclass submission.
- The student fixed the starting point: the same MFC commit and benchmark case as the HW-1 profiling report
  (3a9bb766, `examples/3D_performance_test`), so HW-1's findings become the hypotheses to test.
- Hard constraints given by the student: ~1 GB / 2.5 GB free in /home and /work (build on node-local or login
  `/tmp`, never touch existing files), no password logins, deadline 2026-11-17 20:00.

## Timeline of agent actions and decisions

| time | action | decision / evidence |
|---|---|---|
| 04:05 | Read brief, HW-1 report, MFC skill notes, earlier repos (style) | Plan: baseline on H200 first, then HW-1 section 6 items in order of expected payoff |
| 04:10 | Cloned MFC at 3a9bb766 locally and on nano4 login `/tmp`; first case-optimized OpenACC build (NVHPC 26.3) on the login node | Build takes ~2.5 min alone, ~7 min when 2-5 builds run in parallel: iterate on the login node, stage only binaries (52 MB each) to `/work` |
| 04:20 | Read `s_hllc_riemann_solver`; first hypothesis = runtime `dir_idx(i)` subscripts force `vel_L/R` into local memory | Implemented compile-time direction maps (commit 1) |
| 04:30 | Wrote harness: `build_variant.sh` (git worktree per variant), `bench_1gpu.sbatch` (interleaved repeats + bit-wise compare), `profile_1gpu.sbatch` (nsys + ncu), `kernel_resources.sh` (REG/LDL/STL from cubins) | First jobs failed: Open MPI could not bind to core 0 inside the Slurm cgroup, and singleton MPI_Init failed (relocated HPC-X). Fixed with `--bind-to none` and `OPAL_PREFIX` |
| 04:35 | SASS of commit 1 still had 222 LDL / 57 STL in the y/z HLLC kernels | **Hypothesis 1 was wrong / incomplete.** PTX showed real `call.uni` to `s_compute_speed_of_sound` and `s_accumulate_mixture_properties`; by-reference arguments live in local memory |
| 04:38 | Recompiled only `m_riemann_solver_hllc` with different `-Minline` options and counted calls/LDL in PTX/SASS | default: calls remain; `totalsize` bigger: all but the z kernel fixed; `smallsize:64`: all calls gone, LDL 222 -> 12. Chosen fix: `-Minline=...,smallsize:64` in CMake (commit 2) |
| 04:40 | Baseline H200 numbers: 0.4022 ns/gp/eq/rhs median of 5 (spread 0.5 %), kernel time 25.7 ms/stage; ncu: HLLC y/z 9.8 GB local loads + 5.5 GB local stores per launch | Same pathology as HW-1 on H100 (15.7 GB) |
| 04:45 | Commit 1 alone: 0.4024 (no change, bit-identical). Commit 2 alone and 1+2: 0.367 (-9 %), bit-identical | Kept both; commit 1 documented as "removes the remaining LDL, no measurable time" |
| 04:50 | nsys breakdown: `s_finalize_riemann_solver` (2.3 ms) and `s_pack_weno_input_arr` (2.0 ms) are pure same-layout copies, done per sweep | Commit 3: alias flux_n/flux_src_n to the Riemann output buffers (no copy). Commit 4: pack WENO input once per RHS instead of once per sweep |
| 05:00 | Experiments on side branches (not merged unless they win): WENO5 `collapse(4)` over variables, `-gpu=maxregcount:128` for `m_weno` only, per-cell `collapse(3)` streaming loops | measured with the same harness; see report section "negative results" |
| 05:10 | Created GitHub repo, pushed; regression suite (`./mfc.sh test --gpu acc`) on H200 for upstream and optimized commits | failure lists compared, see `hw/results/regtest` |

(The table is extended at the end of the run with the final measurements.)

## Places where the agent was wrong and how it was caught

1. **Root cause of the HLLC local memory.** HW-1 (written by the same student/agent workflow) attributed it to runtime
   indices into private arrays. On H200/NVHPC 26.3 the dominant cause is non-inlined device calls; caught by counting
   LDL/STL in SASS after the first fix and reading the PTX `call.uni` targets. The runtime-index fix is kept because it
   removes the remaining 74 -> 12 LDL, but it gives no measurable speedup by itself (reported as such).
2. **Harness launch failures** (cgroup binding, relocated HPC-X) were caught by the first sbatch logs, not assumed away.
3. **ncu export grouped all three sweep directions** under one kernel name; fixed by exporting with
   `--print-kernel-base mangled`.
