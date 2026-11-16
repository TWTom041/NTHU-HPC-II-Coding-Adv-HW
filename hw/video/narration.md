# 影片講稿（每段對應一頁投影片；build_video.py 依「## 數字」切段、再依句號切句做 TTS 與字幕）

## 1
大家好，我是蔡昕翰。這支影片報告我的 Coding Adv 作業：在 nano4 的 H200 上優化 MFC。我會講我量了什麼、做了哪些優化、每個優化快了多少，以及我怎麼用 AI agent 完成這份作業。另外說明一下，這支影片的旁白是用開源的 Qwen3 TTS 合成的。

## 2
MFC 是 SC26 學生叢集競賽的應用程式之一，是用 Fortran 加 OpenACC 寫的可壓縮多相流模擬程式。我在 nano4 上用一到八張 H200 做實驗。起點刻意選得和 HW1 一樣：同一個 commit、同一個測資。HW1 只能推測哪裡可以優化，這次要把那些推測變成可以驗證的假設。每一個改動都是獨立的 commit，都量五次，並且和 baseline 的結果逐個 byte 比對。

## 3
測資是 MFC 官方拿來當效能指標的 3D performance test。它有八百一十萬個網格點、八條方程式，用 WENO 五階重建、HLLC Riemann solver 和三階 Runge Kutta。指標是 MFC 自己印出來的 grind time，也就是每個網格點、每條方程式、每次右手邊計算花幾奈秒，越小越好。每個版本交錯跑五次取中位數，五次之間的差距不到百分之零點五。正確性的部分，我把最後一步八個守恆量逐 byte 和 baseline 比較，另外再跑 MFC 自己的 regression test。

## 4
先看 baseline。在一張 H200 上 grind time 是零點四零二奈秒。WENO 重建佔了三成三，HLLC 佔兩成六，剩下大多是只搬資料的 streaming kernel。有一個有趣的觀察：H200 的記憶體頻寬比 H100 多了百分之四十三，但整體只快了百分之五。這表示最大的兩個 kernel 並不是被 HBM 頻寬卡住，光換更快的記憶體幫不上忙。

## 5
HW1 的 profile 發現，HLLC 每次 launch 有將近十 GB 的 local memory 讀取。當時我推測，原因是 private 陣列用執行期才知道的 index 存取。所以第一個優化，就是在每個方向把這些 index 改成編譯期常數。結果 SASS 裡的 local load 指令數完全沒變，還是兩百二十二條，速度也沒變。也就是說，這個假設只對了一半。

## 6
繼續往下讀 PTX，才找到真正的原因。HLLC kernel 裡還有真的函式呼叫，例如計算音速的 subroutine。Fortran 的參數是傳參考，被傳進去的變數一定要有位址，所以整組 thread 私有的狀態都被放進了 local memory。編譯器的報告說這些函式有 inline，但那只是 host 端；在 device 端，一個 subroutine 裡有十二個 kernel，inline 的預算在後面就用完了。我比較了幾個 inline 選項，加上 smallsize 六十四之後，device call 變成零，local load 從兩百二十二條降到十二條。

## 7
結果是只改一行 CMake 的編譯選項，grind time 從零點四零三六降到零點三六六八，快了百分之十，而且最終結果和 baseline 逐 byte 完全相同。HLLC 每個 Runge Kutta stage 少了二點四毫秒。常數 index 那個改動單獨沒有效果，我在報告裡誠實記錄，保留它只是因為它讓剩下的 local memory 幾乎歸零。

## 8
{{NARR_8}}

## 9
{{NARR_9}}

## 10
{{NARR_10}}

## 11
{{NARR_11}}

## 12
接下來講我怎麼用 AI agent。老實說，這份作業我幾乎整份交給了 agent：我只下了一句「把 eeclass 上的作業完成」。我做的事情是人才能做的部分：登入 eeclass、打開到 nano4 的 SSH 連線、在需要 sudo 的地方自己輸入密碼，以及回答它問我的選擇。選 MFC 和 nano4、用 HW1 的 commit 和測資當起點、優化的方向，都是主 agent 讀了作業和我的 HW1 報告之後決定的。主 agent 把背景整理成一份 brief，交給一個 worker agent；worker 透過 SSH 在 login node 編譯、用 Slurm 送量測。每個優化一個 commit，實驗放在旁邊的 branch，沒有贏就不進 main。這次讓結果可信的不是 prompt，而是規則：沒有證據的數字，不能寫進報告。

## 13
agent 也會做錯。第一，它一開始照 HW1 的推測修 HLLC，是看到 SASS 的 local load 數量沒變，才發現根因判斷錯了。第二，第一批 Slurm job 因為 MPI 的 binding 和 HPC X 的路徑設定失敗。第三，匯出 profiler 資料時，三個方向的 kernel 被合併成同一個名字。另外，中途 SSH 連線斷掉的時候，worker 停下來回報，而不是自己嘗試登入，這是 brief 裡事先寫好的規則。

## 14
{{NARR_14}}
