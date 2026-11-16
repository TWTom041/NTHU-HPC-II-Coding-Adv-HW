---
title: MFC GPU 優化報告（Coding-Adv-HW）
subtitle: 3D_performance_test on NVIDIA H200：HLLC 的 local memory、多餘的整場複製
author: 蔡昕翰 114000110
date: 2026-11-16
---

# 摘要

接續 HW-1（H100 profiling）的發現，在 nano4 的 H200 上對 MFC（commit 3a9bb766）做了六個 commit 的修改，全部以
`examples/3D_performance_test`（201³、兩流體 5-equation、WENO5-M + HLLC + RK3）量測。

- **單卡結果**：grind time 0.4026 → **0.2581 ns/gp/eq/rhs（1.56×）**，每個 RK stage 的 kernel 時間 25.4 → 15.9 ms（nsys）。所有版本最後一步的守恆量與原版**逐 byte 相同**。
- **HW-1 的三個建議**在 H200 上逐一驗證：
  1. HLLC 的 local memory 確實存在（每次 launch 9.8 GB load + 5.5 GB store），但主因不是 HW-1 推測的「runtime index」，而是 nvfortran 沒有把兩個小的 device 函式 inline 進 kernel。用 `-Minline=smallsize:64` 修正後快 10%。runtime-index 的修正單獨無效。
  2. WENO 的 register 壓力：只對 `m_weno` 設 `maxregcount:128`，occupancy 12.5% → 25%，WENO 快 29%。
  3. streaming kernel：兩個完全多餘的整場複製（finalize、每個 sweep 重複的 WENO pack）直接拿掉，另外把 collapse(4) 改成一個 thread 一個 cell，讓 flux difference 等 kernel 的頻寬從 41% 提高到 64%。
- **負面結果**：WENO collapse(4) 慢 8.7%；register 上限 96/160 都比 128 差；runtime-index 修正單獨沒有加速。
- **正確性**：MFC regression suite（H200，720 個測試）原版與最終版結果相同：678 passed、8 個 2-rank 測試因 Slurm 下的 `mpirun` slot 設定無法啟動；修正 launcher 後這 8 個也都通過（見 §5）。
- **多 GPU**：@@MGPU_SHORT@@

# 1. 測資選擇與理由

| 項目 | 說明 |
|---|---|
| Case | `examples/3D_performance_test`，原封不動（30 步、第 30 步輸出 restart）。8 條 PDE，201³ = 8.12 M cells，三方向 stretched grid，右側是 non-reflecting characteristic BC（-6），左側 reflective（-2） |
| 為什麼 | MFC 官方 figure of merit（`docs/documentation/expectedPerformance.md`）用的就是它；HW-1 也用它，HW-1 的 profile 結論可以直接當作這次的假設來驗證 |
| 指標 | MFC 自己印的 grind time（ns/gp/eq/rhs，每個 rank 取所有 RK stage 中的最小 stage 牆鐘時間，排除前 2 步暖機）。每個版本跑 5 次、交錯執行（A B C … A B C …），報中位數與 (max−min)/median |
| 規模 | 每個 kernel 約 8 M threads，H200 132 SM × 2048 = 270 K 常駐 thread 的 30 倍；GPU 忙碌率 98.5%（kernel 25.7 ms / stage 26.1 ms），量到的是 kernel 本身而不是 launch overhead |
| 正確性 | 每個版本最後一步的守恆量（`restart_data/lustre_30.dat`，8 × 8.12 M doubles）與 baseline 逐 byte 比較；另外跑 MFC 自己的 regression suite（`./mfc.sh test --gpu acc`） |

# 2. 實驗環境

| 項目 | 內容 |
|---|---|
| 節點 | nano4 `25a-hgpn*`：8 × NVIDIA H200 141 GB（SXM, 700 W, HBM3e 4.8 TB/s, max SM clock 1980 MHz），2 × Xeon Platinum 8480+（2 NUMA node） |
| Driver / 編譯器 | driver 580.65.06（CUDA 13.0）；NVHPC 26.3（nvfortran，內附 CUDA 13.1、HPC-X 2.25.1 Open MPI 4.1） |
| Build | `./mfc.sh build -t pre_process simulation --gpu acc --case-optimization -i examples/3D_performance_test/case.py`，`MFC_CUDA_CC=90`；在 login node 的 `/tmp` 編譯（約 2.5–7 分鐘），只把 52 MB 的 binary 放到 `/work`（quota 只剩 2.5 GB） |
| 執行 | `mpirun --bind-to none -np 1 simulation`（Slurm cgroup 下 Open MPI 預設 bind core 0 會失敗；HPC-X 是 relocated install，需要 `OPAL_PREFIX`）。在 compute node 的 `/tmp` 執行，每個 job 先跑一次 pre_process 產生共用的初始條件 |
| Profiler | Nsight Systems 2025.x（`nsys profile -t cuda,nvtx,openacc`，完整 30 步）；Nsight Compute（`--clock-control none`，3 步、取最後一步每個 kernel 的值）；靜態資源：`cuobjdump -res-usage` 與 SASS 中 `LDL`/`STL` 指令數（`hw/scripts/kernel_resources.sh`） |

H100（HW-1）與 H200 的差別：H200 是同一顆 GH100 晶片，SM 數、clock、L2 都一樣，差在記憶體（HBM3e 141 GB、4.8 TB/s，
H100 SXM 是 80 GB、3.35 TB/s）。HW-1 在 H100 + NVHPC 24.7 量到 0.424 ns；這次 baseline 在 H200 + NVHPC 26.3 是
0.402 ns（兩個 job 的中位數 0.4022 / 0.4037，5 次重複的 spread ≤ 0.5%），只快 5%，與「頻寬多 43%」不成比例：因為主要的兩個 kernel（WENO 33%、HLLC 26%）在 H200 上分別是
latency bound 與 local-memory bound（見 §3），不是被 HBM 頻寬卡住；只有 streaming kernel 受惠於頻寬。

# 3. Baseline profile（1 × H200）

nsys，30 步（90 個 RK stage），每個 stage 的 kernel 時間（`hw/results/nsys_base.txt`）：

| kernel group | ms / stage | 占比 |
|---|---:|---:|
| WENO 重建（`s_weno` ×3 方向） | 8.60 | 33.4% |
| HLLC Riemann solver ×3 | 6.67 | 25.9% |
| Flux difference ×3（`s_compute_advection_source_term`） | 2.37 | 9.2% |
| Riemann finalize 複製（flux + flux_src） | 2.26 | 8.8% |
| WENO input pack ×3 | 2.03 | 7.9% |
| RK 更新（`s_tvd_rk`） | 1.13 | 4.4% |
| RHS 複製 `q_cons → q_cons_qp` | 0.74 | 2.9% |
| advection source ×3（`s_add_directional_…`） | 0.73 | 2.8% |
| cons → prim | 0.54 | 2.1% |
| halo / BC / characteristic BC / 其他 | 0.88 | 3.4% |
| **合計** | **25.73** | 100% |

stage 牆鐘時間 = 0.402 ns × 8 eq × 8.12 M = 26.1 ms，所以 GPU 忙碌 98.5%。ncu 每個 kernel 的指標在
`hw/results/ncu_base_vs_hllc.txt`。

主要觀察（ncu，最後一個 time step）：

- **WENO（`s_weno`，33%）**：188–196 registers/thread，理論 occupancy 12.5%，FP64 pipe 29%，DRAM 只用 13%。與 HW-1 在 H100 上一樣是 latency bound。
- **HLLC（`s_hllc_riemann_solver`，26%）**：y、z 方向每次 launch 有 **9.8 GB local load + 5.5 GB local store**（x 方向 4.8 + 4.7 GB），DRAM 4.4 GB（理想值約 1.8 GB）。與 HW-1 在 H100 量到的 15.7 GB 是同一個問題。
- **Streaming kernel（共約 36%）**：`s_finalize_riemann_solver`、`s_pack_weno_input_arr`、flux difference、`s_tvd_rk`、RHS copy 都只跑到 H200 DRAM 峰值的 31–41%（約 1.6–2.0 TB/s）。其中有兩個是**完全多餘的整場複製**：
  - `s_finalize_riemann_solver` 把 `flux_rsx_vf(j,k,l,i)` 複製到 `flux_n(id)%vf(i)%sf(j,k,l)`：兩邊 layout 完全一樣（名稱裡的 rsx 是歷史遺留，現在三個方向都是自然順序），每個 sweep 讀寫 9 個場，2.3 ms/stage（8.9%）。
  - `s_pack_weno_input_arr` 每個 sweep 都把同一組 `q_prim_qp`（含 ghost cell）複製進 `v_rs_weno`，一個 RHS 做三次，2.0 ms/stage（7.9%）。

# 4. 優化

## 4.1 HLLC 的 local memory：真正原因是沒有被 inline 的 device call（commit `82882c42`，−9%）

**一開始的假設（HW-1）錯了一半。** HW-1 推論 local memory 來自「private 陣列用 runtime index 存取」，例如
`vel_L(dir_idx(1))`，`dir_idx` 是 module 變數。我先做了這個修正（§4.2），結果 SASS 中 y/z HLLC kernel 的 `LDL`
指令仍然是 222 條、`STL` 57 條，grind time 沒變。

讀 PTX 才找到主因：y、z 方向的 5-equation HLLC kernel 裡有真的 `call.uni m_variables_conversion_s_compute_speed_of_sound_`
（3 次）與 `m_riemann_state_s_accumulate_mixture_properties_`（2 次），x 方向也還有 3 個 speed-of-sound call。
Fortran 參數是 by reference 傳遞，被傳進去的 `rho_L, gamma_L, pi_inf_L, alpha_L(:) …` 全部必須有位址，於是整組 thread-private
狀態都被放進 local memory（PTX 裡 416 B 的 `__local_depot`，kernel 一開始就 `st.local` 清零這些純量）。`-Minfo=inline`
卻報告這些函式「cross-inlined」——host 端有 inline，device 端沒有。

只重編 `m_riemann_solver_hllc` 測試不同 `-Minline` 選項（每次約 20 秒，數 PTX 的 call 與 SASS 的 LDL/STL）：

| `-Minline=lib:...` 加上 | 5-eq HLLC kernel 內的 device call | y/z kernel LDL / STL |
|---|---|---|
| （原本） | x：3，y：5，z：5 | 222 / 57 |
| `totalsize:5000000,size:5000` | 只剩 z：3 | z 仍 210 / 69，x、y 12 / 8 |
| **`smallsize:64`** | **0** | **12 / 8** |

`s_hllc_riemann_solver` 一個 subroutine 裡有 4 種模型 × 3 方向 = 12 個 kernel，nvfortran 的 per-procedure inline 預算在
後面的 kernel 用完了。`smallsize:N` 讓小於 N 的函式一律 inline（這兩個函式的 size 是 39 與 13）。修改在
`cmake/MFCTargets.cmake:58-63`（第二階段 IPO 的 `-Minline` 參數）。

證據（`hw/results/bench_inline.txt`、`kernel_resources.txt`、`ncu_base_vs_hllc.txt`）：

| 版本 | y/z HLLC REG | y/z LDL / STL | grind（中位數，5 次） | 相對 base | 最終守恆量 |
|---|---:|---:|---:|---:|---|
| base | 143 / 136 | 222 / 57 | 0.4037（0.4020–0.4039） | 1.000 | — |
| 只有 4.1（`iso_inline`） | 144 / 151 | 74 / 8 | 0.3668（0.3664–0.3678） | **1.101** | bit-identical |
| 4.2 + 4.1（`inline`） | 146 / 156 | 12 / 8 | 0.3670（0.3656–0.3674） | 1.100 | bit-identical |

baseline 的 ncu：HLLC y/z 每次 launch 9.8 GB local load + 5.5 GB local store、DRAM 4.36 GB（38% 峰值），理論 occupancy
18.8%。inline 之後 grind 降 0.037 ns，相當於每個 RK stage 少 2.4 ms（HLLC 原本 6.67 ms/stage）；inline 版本的 nsys / ncu
對照見 §5。registers 稍增（+10），但不再有 local memory 的來回。

## 4.2 HLLC 方向 index 改為編譯期常數（commit `06ee1a63`，單獨無效、與 4.1 合併後再減少 LDL）

`src/simulation/m_riemann_solver_hllc.fpp:177-185, 1551-1552`：在每個 sweep 方向的 Fypp 展開裡加一個 `block`，用
`integer, parameter :: dir_idx(3) = [2, 1, 3]` 這類具名常數遮蔽（shadow）module 的 runtime `dir_idx` / `dir_flg`（值完全相同，原本在
`s_populate_riemann_states_variables_buffers` 裡設定）。這樣 kernel 內所有 `vel_L(dir_idx(i))` 的 subscript 都是常數。

- 單獨套用：SASS LDL 222 → 222（因為 call 還在），grind time 0.4027 vs 0.4037（差異在雜訊內）。
- 與 4.1 一起：LDL 74 → 12、STL 8 → 8（只有 4.1 時是 74 / 8），grind time 0.3670 vs 0.3668（只有 4.1）：**沒有可量測的差異**。
- 保留理由：改動 9 行、結果 bit-identical，讓剩下的 local memory 幾乎歸零；但這裡誠實記錄它不是速度來源。

## 4.3 Riemann flux：別名取代 finalize 複製（commit `b92b23ae`）

- `src/simulation/m_riemann_solvers.fpp:106-115`：`flux_rsx_vf`、`flux_src_rsx_vf` 改用與 `flux_n` 相同的 `idwbuff` 邊界配置（涵蓋 solver 寫的所有面：sweep 方向 −1:m，其他方向 0:n / 0:p）。
- `src/simulation/m_rhs.fpp:574-619` 新增 `s_alias_riemann_flux_buffers`：把 `flux_n(1)%vf(l)%sf` 與 `flux_src_n(1)` 的 advection 列以 pointer bounds-remapping 指到這兩個 buffer 的切片（`GPU_ENTER_DATA(attach=…)`），`flux_n(2:3)` 原本就 alias 到 `flux_n(1)`，重新指一次即可。`m_start_up.fpp:947` 在 Riemann module 初始化後呼叫。
- `src/simulation/m_riemann_state.fpp:1188-1195` 等：`flux_rsx_aliased` 為真時 `s_finalize_riemann_solver` 跳過 flux 與 flux_src 的複製（cylindrical 的 `flux_gsrc` 仍照舊複製）。
- 安全性：這些 buffer 本來就是「每個 sweep 的暫存」——所有 consumer（flux difference、characteristic BC 修改邊界 flux、NC source term）都在下一個 sweep 的 Riemann solve 之前用完；IGR 與 hypoelastic dual-pass HLLD（第二次 finalize 會重填 flux_n）不啟用。副作用：少配置一份 sys_size 個場的 flux。

證據（`hw/results/raw/bench_all`、`prof_all`；同一個 job、5 次交錯重複）：

| 版本 | grind（中位數） | 相對 base | nsys：finalize 複製 ms/stage |
|---|---:|---:|---:|
| base | 0.4028 | 1.000 | 2.03 |
| 只有 4.3（`iso_alias`，套在 3a9bb766 上） | 0.3721 | 1.082 | 0 |
| 4.2 + 4.1（`inline`） | 0.3661 | 1.100 | 2.03 |
| 4.2 + 4.1 + 4.3（`alias`） | 0.3360 | 1.199 | 0 |

finalize 的 6 個 kernel（每方向 flux 一個、flux_src 一個）從 nsys 中完全消失，省下約 2.2 ms/stage，
與預期（9 個場 × 8.2 M × 16 B ≈ 1.2 GB／sweep，在 1.8 TB/s 下約 0.6 ms）一致。最終守恆量與 baseline bit-identical。
把 `flux_rsx_vf` 宣告成 `target` 之後，HLLC kernel（ncu）在 `inline` 是 1.37 / 1.42 / 1.43 ms（x/y/z），在 `pack`（含此 commit）是 1.41 / 1.42 / 1.44 ms，沒有觀察到 aliasing 造成的明顯損失（x 方向 +3%）。

## 4.4 WENO 輸入每個 RHS 只 pack 一次（commit `bbc66c82`）

- `src/simulation/m_weno.fpp:27-32, 1010-1016`：記住 `v_rs_weno` 目前裝的是哪一組場（第一個場的 pointer 與個數），同一組就跳過 `s_pack_weno_input_arr`。
- `src/simulation/m_weno.fpp:921-927` 新增 `s_weno_input_changed`；`src/simulation/m_rhs.fpp:695-696` 在每次 RHS 重新計算 `q_prim_qp`（cons→prim + halo）之後呼叫。
- 其他呼叫（viscous 梯度、拆開重建的 surface tension / `weno_Re_flux` 路徑）傳入不同的場組合，仍然每次重新 pack，行為不變。

證據：

| 版本 | grind（中位數） | 相對 base | nsys：pack ms/stage |
|---|---:|---:|---:|
| base | 0.4028 | 1.000 | 2.01 |
| 只有 4.4（`iso_pack`） | 0.3823 | 1.053 | 0.67 |
| 4.1–4.4（`pack`） | 0.3157 | 1.276 | 0.67 |

pack 從每個 stage 3 次變成 1 次（270 → 90 次 launch），時間正好剩 1/3。bit-identical。

## 4.5 WENO：只對 `m_weno` 限制 128 個 register（commit `039ee7bc`）

HW-1 的第二個建議。`cmake/MFCTargets.cmake:80-87` 只對 `m_weno.fpp.f90` 加 `-gpu=maxregcount:128`（HLLC kernel 需要約 150 個
register，不能全域限制）。先在 side branch `exp-wenoflags` 用環境變數 `MFC_WENO_FLAGS` 試 96 / 128 / 160，128 效果最好後才寫進 CMake。

| 版本 | WENO regs | 理論 / 實際 occupancy | local ld / st（GB/launch） | FP64 pipe | WENO ms/stage | grind |
|---|---:|---:|---:|---:|---:|---:|
| `pack`（預設） | 188–196 | 12.5 / 12.2% | 0 / 0 | 29% | 8.46 | 0.3157 |
| `pack` + maxregcount:128 | 128 | 25 / 24% | 5.2–7.7 / 2.2–2.5 | 39–43% | 6.01 | 0.2776 |

限制 register 之後有 spill（每次 launch 5–8 GB 的 local load），但大多被 L1（hit 58–84%）與 L2 接住；occupancy 加倍讓
FP64 指令鏈的延遲被藏住，WENO 快 29%，整體再快 12%。這與 HLLC 的情況（local memory 是負擔）相反：WENO 是 latency bound，
多一倍的 warp 比少掉的 spill 重要。結果仍 bit-identical（register 配置不改變算術）。

register 上限掃描（都套在 commit 4 之上，`bench_final`，5 次中位數）：96 → 0.2965、**128 → 0.2774**、160 → 0.2825、不限制（188–196）→ 0.3153 ns。
160 個 register 時理論 occupancy 只有 18.75%（65536 / (160 × 32) = 12 warps/SM）；96 時較差的原因推測是 spill 量更大（[推論]，96/160 沒有另外跑 ncu）。128 是最佳點。最終版 SASS：WENO kernel 128 registers、38–43 LDL / 40–45 STL。

## 4.6 Streaming kernel：每個 thread 一個 cell（commit `8cd486ab`）

RHS 複製（`m_rhs.fpp:646-656`）、三個方向的 flux difference（`m_rhs.fpp:1157-1170, 1234-1247, 1397-1410`）與 RK 更新
（`m_time_steppers.fpp:486-506`）原本是 `collapse(4)` 遍歷（方程, z, y, x）：每個元素都要從攤平的 index 還原 4 個 index
（`s_compute_rhs` 的 loop index 是 64-bit，等於 64-bit 除法）並重新讀 derived type 的 descriptor，ncu 量到每個元素約
250–320 條指令、DRAM 只用 31–41%。改成 `collapse(3)` 遍歷 cell、thread 內循序跑 8 條方程式，算術完全不變。

| 版本 | grind（中位數，5 次） | 相對前一版 |
|---|---:|---:|
| `pack` | 0.3160 | 1.000 |
| `pack` + 4.6（`exp_stream`） | 0.2961 | 1.067 |

ncu（`hw/results/raw/prof_final`，與 base 比較）：

| kernel | base：時間 / 指令數 / DRAM% | final：時間 / 指令數 / DRAM% |
|---|---|---|
| flux difference y（`@1183` → `@1235`） | 783 µs / 508 M / 41.5% | 512 µs / 201 M / 63.5% |
| flux difference z（`@1345` → `@1398`） | 795 µs / 497 M / 40.9% | 508 µs / 197 M / 64.0% |
| flux difference x | 709 µs / 501 M / 30.6% | 412 µs / 200 M / 52.5% |
| RHS 複製（`s_compute_rhs`） | 704 µs / 525 M / 34.0% | 397 µs / 185 M / 60.2% |
| RK 更新（`s_tvd_rk`） | 1100 µs / 653 M / 41.0% | 889 µs / 413 M / 50.3% |

DRAM 流量不變（例如 flux difference 都是 1.56 GB），指令數降到 40%，有效頻寬從約 2.0 TB/s 升到 3.0 TB/s（H200 峰值 4.8 TB/s 的 64%）。

# 5. 累積加速與正確性

同一個 job（`hw/results/raw/bench_final`，job 785519，node 25a-hgpn002），每個版本 5 次交錯重複；「單獨」= 只把該 commit
cherry-pick 到 3a9bb766 上；「累積」= main 上到該 commit 為止。所有版本最後一步的 8 × 8.12 M 個守恆量與 baseline
**逐 byte 相同**（`compare_*.txt`），baseline 本身兩次執行也逐 byte 相同（`determinism_base.txt`）。

| commit | 內容 | 單獨 grind | 單獨加速 | 累積 grind | 累積加速 |
|---|---|---:|---:|---:|---:|
| 3a9bb766 | baseline | 0.4026（spread 0.36%） | 1.000 | 0.4026 | 1.000 |
| 06ee1a63 | HLLC 方向常數 | 0.4031* | 1.00 | 0.4031* | 1.00 |
| 82882c42 | `-Minline=smallsize:64` | 0.3665 | 1.099 | 0.3657 | 1.101 |
| b92b23ae | flux 別名，去掉 finalize 複製 | 0.3718 | 1.083 | 0.3355 | 1.200 |
| bbc66c82 | WENO input 每個 RHS pack 一次 | 0.3820 | 1.054 | 0.3153 | 1.277 |
| 039ee7bc | `m_weno` maxregcount:128 | 0.3645 | 1.105 | 0.2774 | 1.451 |
| 8cd486ab | streaming kernel 每 thread 一個 cell | 0.3821 | 1.054 | **0.2581**（spread 0.93%） | **1.560** |

\* commit 1 來自 `bench_all`（同樣條件的前一個 job）：0.4031 vs base 0.4028。

單獨加速相乘是 1.099 × 1.083 × 1.054 × 1.105 × 1.054 = 1.46，小於累積的 1.56：各項省下的是不同 kernel 的時間，
整體變短之後同樣省下的毫秒數占比變大（例如 maxregcount:128 單獨 +10.5%，在 commit 4 之上 +13.7%）。

nsys 每個 RK stage 的 kernel 時間（`hw/results/raw/prof_final`，同一個 job 依序量 base 與 final）：

| kernel group | base ms/stage | final ms/stage | 對應 commit |
|---|---:|---:|---|
| WENO 重建 | 8.461 | 6.011 | 039ee7bc |
| WENO input pack | 2.011 | 0.667 | bbc66c82 |
| HLLC Riemann solver | 6.573 | 4.328 | 82882c42（+06ee1a63） |
| Riemann finalize 複製 | 2.028 | 0 | b92b23ae |
| flux difference | 2.341 | 1.448 | 8cd486ab |
| RK 更新 | 1.120 | 0.891 | 8cd486ab |
| RHS 複製 | 0.729 | 0.400 | 8cd486ab |
| advection source | 0.725 | 0.726 | — |
| cons → prim | 0.540 | 0.541 | — |
| halo / BC / CBC / 其他 | 0.867 | 0.872 | — |
| **合計** | **25.395** | **15.884**（1.60×） | |

**MFC regression suite**（`./mfc.sh test --gpu acc`，非 case-optimized 的 OpenACC build，H200，golden 容許誤差 1e-12，
`hw/scripts/regtest.sbatch`）：

| run | upstream 3a9bb766 | 最終 8cd486ab |
|---|---|---|
| 完整 suite（720 個測試，執行 686 個、skip 34 個） | 678 passed / 8 failed / 34 skipped | 678 passed / 8 failed / 34 skipped |
| 失敗的 8 個 | 全部是 2 rank 的測試，`mpirun` 啟動失敗（"not enough slots"：job 只有 1 個 Slurm task） | 同一組 8 個 UUID（`0090B316 0DDE8A87 0FCCE9F1 75D7CC39 8C7AA13B AFBACA70 CB0DC420 CE232828`） |
| 只重跑這 8 個（`OMPI_MCA_rmaps_base_oversubscribe=true`） | 8 passed | 7 passed；`AFBACA70`（3D 2 ranks IBM sphere）的 `syscheck` 在 `MPI_Init` 內被 UCX（`libuct_ib`）abort，MFC 程式還沒開始執行；單獨重跑：passed。合計 8/8 |

也就是說，在相同環境下，修改沒有讓任何一個原本通過的測試失敗。多 rank 的正確性另外由 §6 驗證：1/2/4/8 卡的最終守恆量與單卡結果逐 byte 相同。
第一次送出的測試全部失敗（MFC 選了 `srun`，而這個 HPC-X 沒有 Slurm PMI），修正 launcher 後重跑；這段過程記在 `AGENT_LOG.md`。

# 6. 多 GPU（同一節點 strong scaling）

同一節點 1/2/4/8 張 H200、總網格固定 201³（strong scaling）、每張卡一個 MPI rank（MFC 用 node-local rank 選卡），
`hw/scripts/multigpu.sbatch`。數值是 MFC 的 grind time（以總網格點數換算，越小越好），3 次重複的中位數；每個卡數用同樣 rank 數的
pre_process 產生初始條件。變數：`rdma_mpi`（F：halo 先 D2H 再走 host MPI；T：GPU-aware MPI，HPC-X/UCX 直接傳 device buffer）
與 binding（none：`--bind-to none`；numa：每個 NUMA domain 4 個 rank 並綁在該 domain，GPU 0–3 在 NUMA 0、4–7 在 NUMA 1）。

**整節點 8 卡 job（`mgpu8`，job 783997，節點獨佔）**，baseline 與 commit 4（`pack`）：

| GPUs | base rdma=F | base rdma=T | pack rdma=F | pack rdma=T | pack rdma=T + numa |
|---:|---:|---:|---:|---:|---:|
| 1 | 0.4032 | 0.4033 | 0.3160 | 0.3158 | — |
| 2 | 0.2552 | 0.2158 | 0.2106 | 0.1712 | 0.1703 |
| 4 | 0.1600 | 0.1204 | 0.1360 | 0.0963 | 0.0960 |
| 8 | 0.1130 | 0.0718 | 0.1053 | 0.0586 | 0.0587 |

- **GPU-aware MPI 是多卡時最大的槓桿**：8 卡時 rdma_mpi=T 比 F 快 36%（base）／44%（pack）。rdma=F 時每次 halo exchange 都要 D2H、host MPI、H2D。
- **NUMA binding**：rdma=F 時有幫助（8 卡 base 0.1130 → 0.1087，pack 0.1053 → 0.0949，因為 host staging 走對的 socket），rdma=T 時沒有差別（資料不經過 host）。
- 8 卡 + rdma=T 的平行效率：base 0.4032 / (8 × 0.0718) = 70%，pack 0.3160 / (8 × 0.0586) = 67%。單卡越快，halo exchange 占比越高，效率略降——與 HW-1 的結論一致。
- 多 rank 的正確性：每個 (版本, 卡數, rdma) 的最終守恆量都與同一版本 1 卡的結果**逐 byte 相同**（`compare_final_*.txt`，16 個比較）。

@@MGPU_FINAL@@

# 7. 負面結果與沒有採用的實驗

| 實驗 | 結果 | 原因（profiler 證據） | 處理 |
|---|---|---|---|
| HLLC 方向 index 改常數（commit 1）單獨 | 0.4031 vs 0.4028，無效 | 真正的 local memory 來源是沒 inline 的 device call（§4.1），只改 index 時 LDL 222 → 222 | 保留（與 inline 合併後 LDL 74 → 12），報告標示「無可量測加速」 |
| WENO5 `collapse(4)`（每個 thread 一個變數 × cell，branch `exp-weno4`） | 0.3428 vs 0.3153，**慢 8.7%** | registers 188 → 130–140、occupancy 12.5 → 18.8%，但 warp 指令數 0.8 G → 1.45 G：每個變數都重新載入 stencil 係數與重算 index，FP64 pipe 29 → 23–26% | 不合併 |
| WENO `maxregcount:96` / `160` | 0.2965 / 0.2825，都比 128（0.2774）差 | 160：occupancy 只有 18.75%；96：推測是 spill 更多（未做 ncu） | 選 128 |
| `maxregcount` 全域套用 | 未採用 | HLLC 需要 146–156 registers，全域上限會讓它 spill；所以只對 `m_weno` 單一檔案設定 | 只設定 per-file |
| 4 卡 scaling job（`mgpu4`） | 1 卡就 2.18 ns，是其他所有量測的 5 倍 | 與 regression test job 同時在同一節點（25a-hgpn009）；原因未查明 | 整批丟棄，只用整節點 8 卡 job |

沒做的部分：§3 的 flux difference + advection source 融合（約 0.7 ms/stage，需要改動多種 `adv_src_mode` 分支）、
RHS 複製改成 alias（`q_cons_qp` 的 adv 欄位被 halo 填值，需要更仔細的證明），以及 NVHPC 25.9 vs 26.3 的比較，都因時間留給量測與正確性驗證而沒有做。

# 8. AI agent 的使用方式

- **誰決定什麼**：學生決定題目（MFC、nano4 H200）、起點（與 HW-1 相同的 commit 與 case，讓 HW-1 的結論變成可驗證的假設）、限制（quota、不可輸入密碼、截止時間），並要求 AI agent 完成整份作業。程式修改、量測與這份報告由 worker agent 完成；投影片、報告影片與 eeclass 繳交也應學生要求由主 agent 製作與處理（不是學生自己做的）。學生負責提出需求、提供 nano4 的登入連線（SSH ControlMaster；連線中斷時由學生重新開啟），以及最後的檢查。
- **流程**：主 agent 先寫 brief（作業說明、HW-1 摘要、nano4 存取與 quota 規則），再把整個優化工作交給一個 worker agent。worker 透過已建立的 SSH ControlMaster 操作 nano4：login node 編譯、Slurm 跑量測、`/work` 只放 binary 與小檔案。每個優化都是獨立 commit，另外在 side branch 上做實驗（失敗的不進 main）。
- **agent 做錯、怎麼被抓到**：(1) HLLC local memory 的根因判斷錯誤（見 §4.1–4.2），由「修完後 SASS 的 LDL 數沒變」抓到；(2) 第一批 sbatch 因為 MPI binding 與 HPC-X 路徑失敗；(3) ncu 匯出時三個方向的 kernel 被合併成同一名稱。詳見 `hw/AGENT_LOG.md`。
- **驗證原則**：每個速度數字都來自 5 次交錯重複；每個保留的修改都與 baseline 逐 byte 比較最終守恆量，並跑 MFC 的 regression suite。

# 9. 重現方式

見 `hw/README.md`。主要腳本：`hw/scripts/build_variant.sh`（以 git worktree 編譯任一 commit）、`bench_1gpu.sbatch`、
`profile_1gpu.sbatch`、`multigpu.sbatch`、`regtest.sbatch`、分析用 `summarize_grind.py`、`nsys_groups.py`、`ncu_summary.py`、`compare.py`。

# 參考資料

1. MFC repository, commit 3a9bb766；`docs/documentation/expectedPerformance.md`. https://github.com/MFlowCode/MFC
2. A. Radhakrishnan et al., "Method for portable, scalable, and performant GPU-accelerated simulation of multiphase compressible flow," CPC 302 (2024) 109238.
3. B. Wilfong et al., "MFC 5.0: An exascale many-physics flow solver," CPC 322 (2026) 110055.
4. NVIDIA HPC SDK 26.3 Compilers User's Guide：`-Minline`（`smallsize`、`totalsize`、`lib:`）、`-gpu=maxregcount`。
5. NVIDIA, CUDA C++ Best Practices Guide — Local Memory；Nsight Compute Profiling Guide — memory metrics.
6. 蔡昕翰, Coding-Basic-HW-1 MFC Profiling 報告（H100 vs MI100），2026.
