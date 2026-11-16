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
  .big { font-size: 36px; font-weight: 700; color: #1f3d64; }
  .hl { color: #c0392b; font-weight: 700; }
  section.lead h1 { font-size: 48px; }
  section::after { font-size: 16px; }
---

<!-- _class: lead -->
# MFC 在 H200 上的 GPU 優化
## 從 HW-1 的 profile 假設，到量得到的加速

HPC-II Coding-Adv-HW · 蔡昕翰 114000110 · NVIDIA H200 @ nano4
<span class="small">repo: github.com/TWTom041/NTHU-HPC-II-Coding-Adv-HW</span>

---

# 題目與出發點

- **MFC**：SC26 SCC 的 AP，可壓縮多相流 CFD（Fortran + OpenACC）
- 平台：nano4，**1–8 × H200**，NVHPC 26.3
- 起點 = HW-1：同一個 commit `3a9bb766`、同一個 case
- HW-1 只「推測」了優化方向 → 這次把推測變成**可驗證的假設**

<div class="big">每個改動：獨立 commit、5 次交錯量測、和 baseline 逐 byte 比對</div>

---

# 測資與量測方法

| 項目 | 內容 |
|---|---|
| Case | `examples/3D_performance_test`：201³ = 8.1 M cells、8 條 PDE、WENO5-M + HLLC + RK3 |
| 為什麼 | MFC 官方 figure of merit（expectedPerformance.md）|
| 指標 | grind time（ns / gp / eq / rhs），越小越好 |
| 重複 | 每版本 5 次、交錯執行，報中位數；spread ≤ 0.5% |
| 正確性 | 最終守恆量 8 × 8.1 M doubles **逐 byte 比較** + MFC regression suite |

---

# Baseline profile（1 × H200，0.402 ns）

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
| base | 222 / 57 | 0.4037 |
| 常數 index | <span class="hl">222 / 57</span> | 0.4027（雜訊內） |

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
| base | 0.4037 | 1.00× | — |
| `-Minline=…,smallsize:64` | **0.3668** | **1.10×** | bit-identical |
| + 常數 index | 0.3670 | 1.10× | bit-identical |

- HLLC 每個 RK stage 少 2.4 ms
- 常數 index 單獨無效：誠實記錄，保留只因它讓 local memory 歸零

---

# 兩個多餘的整場複製

- **Riemann finalize**：`flux_rsx_vf` → `flux_n`，兩邊 layout 完全一樣（8.8%）
  → 讓 `flux_n` 直接 **alias** 到 solver 的輸出 buffer
- **WENO input pack**：同一組 `q_prim_qp` 每個 RHS 複製 3 次（7.9%）
  → 記住 buffer 裡裝的是什麼，**每個 RHS 只 pack 一次**

{{ALIAS_PACK_RESULT}}

---

# 累積加速與正確性

{{CUMULATIVE_TABLE}}

---

# 多 GPU（單節點 strong scaling）

{{MGPU_TABLE}}

---

# 沒有採用的實驗

{{NEGATIVE}}

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
- ncu 匯出時三個方向的 kernel 被合併成同一名稱
- SSH socket 中途斷線 → agent 停下來回報，不嘗試登入

---

# 結論

{{CONCLUSION}}

- 學到的：**先看 PTX / SASS，再相信 profiler 的分類**
- 每個優化都要能回答：快了多少、為什麼、結果還對不對
