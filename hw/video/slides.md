---
marp: true
theme: default
paginate: true
size: 16:9
style: |
  section { font-family: 'Noto Sans CJK TC', sans-serif; font-size: 27px; padding: 40px 64px 120px 64px; }
  h1 { font-size: 40px; color: #1f3d64; margin-bottom: 14px; }
  h2 { font-size: 30px; color: #1f3d64; }
  table { font-size: 22px; }
  code { font-size: 0.88em; }
  .small { font-size: 19px; color: #555; }
  .big { font-size: 34px; font-weight: 700; color: #1f3d64; }
  .hl { color: #c0392b; font-weight: 700; }
  section.lead h1 { font-size: 48px; }
  section::after { font-size: 16px; }
---

<!-- _class: lead -->
# MFC 在 H200 上的 GPU 優化
## 1 卡 1.56×、8 卡 7.87×，結果逐 byte 相同

HPC-II Coding-Adv-HW · 蔡昕翰 114000110 · NVIDIA H200 @ nano4
<span class="small">repo: github.com/TWTom041/NTHU-HPC-II-Coding-Adv-HW · 旁白由 Qwen3-TTS 合成</span>

---

# 題目與出發點

- **MFC**：SC26 SCC 的 AP，可壓縮多相流 CFD（Fortran + OpenACC）
- 平台：nano4，**1–8 × H200**，NVHPC 26.3
- 起點 = HW-1：同一個 commit `3a9bb766`、同一個 case
- HW-1 只「推測」了優化方向 → 這次把推測變成**可驗證的假設**

<div class="big">每個改動：獨立 commit、5 次量測取中位數、和 baseline 逐 byte 比對</div>

---

# 測資與量測方法

| 項目 | 內容 |
|---|---|
| Case | `examples/3D_performance_test`：201³ = 8.1 M cells、8 條 PDE、WENO5-M + HLLC + RK3 |
| 為什麼 | MFC 官方 figure of merit（expectedPerformance.md）|
| 指標 | grind time（ns / gp / eq / rhs），越小越好 |
| 重複 | 每版本 5 次、交錯執行，報中位數；spread ≤ 0.5% |
| 正確性 | 最終守恆量 8 × 8.1 M doubles **逐 byte 比較** + MFC regression suite（720 tests）|

---

# Baseline profile（1 × H200，0.4026 ns）

| kernel group | ms / stage | 占比 |
|---|---:|---:|
| WENO 重建 ×3 | 8.60 | 33.4% |
| HLLC Riemann ×3 | 6.67 | 25.9% |
| flux difference ×3 | 2.37 | 9.2% |
| Riemann finalize **複製** | 2.26 | 8.8% |
| WENO input **pack** ×3 | 2.03 | 7.9% |
| 其他 streaming / BC | 3.80 | 14.8% |

- H100 → H200：頻寬 +43%，但只快 **5%** → 主角不是被 HBM 頻寬卡住

---

# HLLC：HW-1 的假設

- ncu：y/z 方向每次 launch **9.8 GB local load + 5.5 GB local store**
- HW-1 推測：private 陣列用 runtime index 存取（`vel_L(dir_idx(1))`）
- 修正：每個方向把 `dir_idx` / `dir_flg` 變成編譯期常數

| | LDL / STL（SASS） | grind |
|---|---:|---:|
| base | 222 / 57 | 0.4026 |
| 常數 index | <span class="hl">222 / 57</span> | 0.4031（沒變） |

<div class="big">假設只對了一半</div>

---

# 真正原因：device 端沒有 inline

- PTX 裡還有 `call` → `s_compute_speed_of_sound`、`s_accumulate_mixture_properties`
- Fortran **by reference** 傳參數 → 參數要有位址 → 整組狀態放進 local memory
- `-Minfo=inline` 說有 inline：**host 有，device 沒有**（一個 subroutine 12 個 kernel，inline 預算用完）

| `-Minline` 選項 | device call | y/z LDL / STL |
|---|---|---|
| 原本 | 3 / 5 / 5 | 222 / 57 |
| `totalsize,size` 加大 | 0 / 0 / 3 | 210 / 69 |
| **`smallsize:64`** | **0** | **12 / 8** |

---

# 結果：一行 CMake，快 10%

| 版本 | grind（ns） | 加速 | 最終狀態 |
|---|---:|---:|---|
| base | 0.4026 | 1.00× | — |
| `-Minline=…,smallsize:64` | **0.3665** | **1.10×** | bit-identical |

- HLLC y/z kernel 的 SASS LDL / STL：222 / 57 → **74 / 8**（再加常數 index：12 / 8）
- HLLC kernel 時間（base → 最終版）：6.57 → 4.33 ms / stage
- 常數 index 單獨無效：誠實記錄，保留只因它讓剩下的 local memory 歸零

---

# 兩個多餘的整場複製

- **Riemann finalize**：`flux_rsx_vf` → `flux_n`，兩邊 layout 完全一樣
  → 讓 `flux_n` 直接 **alias** 到 solver 的輸出 buffer
- **WENO input pack**：同一組 `q_prim_qp` 每個 RHS 複製 3 次
  → 記住 buffer 裡裝的是什麼，**每個 RHS 只 pack 一次**

| 改動 | kernel 時間（ms / stage） | 單獨加速 |
|---|---:|---:|
| flux alias | finalize 2.03 → **0** | 1.08× |
| pack once | pack 2.01 → **0.67** | 1.05× |

---

# WENO：用 spill 換 occupancy

- WENO 是 **latency bound**：188–196 registers → occupancy 只有 12.5%
- 只對 `m_weno` 加 `-gpu=maxregcount:128`（HLLC 需要約 150，不能全域限制）

| 上限 | occupancy | spill（GB / launch） | WENO ms / stage | grind |
|---|---:|---:|---:|---:|
| 不限（~192） | 12.5% | 0 | 8.46 | 0.3153 |
| 160 | 18.75% | | | 0.2825 |
| **128** | **25%** | 5–8 | **6.01** | **0.2774** |
| 96 | | （推測更多，未量） | | 0.2965 |

<div class="big">和 HLLC 相反：這裡 warp 數比 spill 重要</div>

---

# Streaming kernel：一個 thread 一個 cell

- RHS 複製、flux difference ×3、RK 更新：原本 `collapse(4)`（方程, z, y, x）
- 每個元素都要用 **64-bit 除法**還原 4 個 index → 指令比資料還多
- 改成 `collapse(3)` 遍歷 cell，thread 內跑 8 條方程式（算術不變）

| kernel | 指令數 | DRAM 使用率 | 時間 |
|---|---:|---:|---:|
| flux difference y | 508 M → **201 M** | 41% → **64%** | 783 → 512 µs |
| RHS 複製 | 525 M → 185 M | 34% → 60% | 704 → 397 µs |
| RK 更新 | 653 M → 413 M | 41% → 50% | 1100 → 889 µs |

---

# 累積加速（1 × H200）

| # | 改動 | 單獨 | 累積 grind | 累積加速 |
|---|---|---:|---:|---:|
| — | upstream | — | 0.4026 | 1.00× |
| 1 | HLLC 常數 index | 1.00× | 0.4031 | 1.00× |
| 2 | `-Minline=smallsize:64` | 1.10× | 0.3657 | 1.10× |
| 3 | flux alias | 1.08× | 0.3355 | 1.20× |
| 4 | WENO pack once | 1.05× | 0.3153 | 1.28× |
| 5 | `m_weno` 128 regs | 1.10× | 0.2774 | 1.45× |
| 6 | 一個 thread 一個 cell | 1.05× | **0.2581** | **1.56×** |

- kernel 時間 25.4 → 15.9 ms / stage；每一版最終守恆量都和 upstream **逐 byte 相同**
- regression suite：upstream 與最終版結果相同（678 passed，8 個 2-rank 測試修正 launcher 後通過）

---

# 多 GPU（單節點 8 × H200，strong scaling）

| GPUs | base | base + RDMA | final | **final + RDMA** |
|---:|---:|---:|---:|---:|
| 1 | 0.4029 | 0.4030 | 0.2581 | 0.2580 |
| 2 | 0.2523 | 0.2155 | 0.1675 | 0.1403 |
| 4 | 0.1598 | 0.1205 | 0.1150 | 0.0817 |
| 8 | 0.1132 | 0.0716 | 0.0933 | **0.0512** |

- GPU-aware MPI（`rdma_mpi=T`）是最大的非程式槓桿：8 卡 **1.58×**
- 8 卡 final + RDMA：比預設 8 卡快 **2.21×**、比單卡 baseline 快 **7.87×**
- kernel 變快後 halo exchange 比重變大：8 卡效率 70% → 63%

---

# 沒有採用的實驗

- WENO `collapse(4)`：occupancy 變高，但指令數加倍 → **慢 8.7%**
- register 上限 96 / 160：都輸給 128
- HLLC 常數 index 單獨：沒有可量測的加速
- 和別人共用節點的 4 卡 job：慢 12–19%（有一次慢 5 倍）→ 丟掉並記錄
- 還沒做：flux difference 與 advection source 融合（約 0.7 ms / stage）、halo exchange 與計算重疊

---

# 我怎麼用 AI agent

- 我：一句「把 eeclass 上的作業完成」＋ 只有人能做的事
  （登入 eeclass、開 nano4 SSH 連線、sudo 密碼、回答選擇題）
- 主 agent：讀作業與我的 HW1 報告 → 決定 MFC / nano4 / 起點 → 寫 brief
- worker agent：經 SSH ControlMaster 操作 nano4 → login node 編譯、Slurm 量測
- 每個優化一個 commit；實驗放 side branch，沒贏就不進 main

<div class="big">讓結果可信的是規則：沒有證據的數字不能進報告</div>

---

# agent 做錯的地方，以及怎麼被抓到

- HLLC 根因判斷錯（照 HW-1 推測改）→ **SASS 的 LDL 數沒變**才發現
- 第一批 sbatch 失敗：MPI binding、HPC-X relocated 路徑
- regression test 第一次全部失敗：MFC 選了 `srun`，但 HPC-X 沒有 Slurm PMI
- ncu 匯出時三個方向的 kernel 被合併成同一名稱
- SSH socket 中途斷線 → worker 停下來回報，不嘗試登入

---

# 結論

<div class="big">1 × H200：0.4026 → 0.2581 ns（1.56×）<br>8 × H200：0.0512 ns（比單卡 baseline 7.87×）</div>

- 六個 commit、每個都有量測與 profiler 證據，最終結果與 upstream 逐 byte 相同
- HW-1 的三個方向都驗證了，但其中一個的「原因」猜錯了
- 學到的：**先看 PTX / SASS，再相信 profiler 的分類**
- 每個優化都要能回答：快了多少、為什麼、結果還對不對
