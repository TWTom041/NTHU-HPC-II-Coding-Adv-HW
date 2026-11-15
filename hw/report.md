---
title: MFC GPU 優化報告（Coding-Adv-HW）
subtitle: 3D_performance_test on NVIDIA H200：HLLC 的 local memory、多餘的整場複製
author: 蔡昕翰 114000110
date: 2026-11-16
---

# 摘要

接續 HW-1（H100 profiling）的發現，在 nano4 的 H200 上對 MFC（commit 3a9bb766）做了四個 commit 的修改，全部以
`examples/3D_performance_test`（201³、兩流體 5-equation、WENO5-M + HLLC + RK3）量測。

@@SUMMARY@@

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

@@ALIAS_EVIDENCE@@

## 4.4 WENO 輸入每個 RHS 只 pack 一次（commit `bbc66c82`）

- `src/simulation/m_weno.fpp:27-32, 1010-1016`：記住 `v_rs_weno` 目前裝的是哪一組場（第一個場的 pointer 與個數），同一組就跳過 `s_pack_weno_input_arr`。
- `src/simulation/m_weno.fpp:921-927` 新增 `s_weno_input_changed`；`src/simulation/m_rhs.fpp:695-696` 在每次 RHS 重新計算 `q_prim_qp`（cons→prim + halo）之後呼叫。
- 其他呼叫（viscous 梯度、拆開重建的 surface tension / `weno_Re_flux` 路徑）傳入不同的場組合，仍然每次重新 pack，行為不變。

@@PACK_EVIDENCE@@

# 5. 累積加速與正確性

@@CUMULATIVE@@

# 6. 多 GPU（同一節點 strong scaling）

@@MGPU@@

# 7. 負面結果與沒有採用的實驗

@@NEGATIVE@@

# 8. AI agent 的使用方式

- **誰決定什麼**：學生決定題目（MFC、nano4 H200）、起點（與 HW-1 相同的 commit 與 case，讓 HW-1 的結論變成可驗證的假設）、限制（quota、不可輸入密碼、截止時間），並要求 agent 完成程式、量測與報告（投影片、影片、繳交由學生自己做）。
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
