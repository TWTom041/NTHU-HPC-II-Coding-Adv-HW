# 影片講稿（每段對應一頁投影片；build_video.py 依「## 數字」切段、再依句號切句做 TTS 與字幕）

## 1
大家好，我是蔡昕翰。這支影片報告我的 Coding Adv 作業：在 nano4 的 H200 上優化 MFC。最後的結果是，單張 H200 快了一點五六倍，八張 H200 比單卡的原始版本快了七點八七倍，而且計算結果和原版逐個 byte 完全相同。另外說明一下，這支影片的旁白不是現場錄音，而是用聯發科的 BreezyVoice，以我自己之前的錄音當聲音樣本合成的。

## 2
MFC 是 SC26 學生叢集競賽的應用程式之一，是用 Fortran 加 OpenACC 寫的可壓縮多相流模擬程式。我在 nano4 上用一到八張 H200 做實驗。起點刻意選得和 HW1 一樣：同一個 commit、同一個測資。HW1 只能推測哪裡可以優化，這次要把那些推測變成可以驗證的假設。每一個改動都是獨立的 commit，都量五次取中位數，並且和原版的結果逐個 byte 比對。

## 3
測資是 MFC 官方拿來當效能指標的 3D performance test。它有八百一十萬個網格點、八條方程式，用 WENO 五階重建、HLLC Riemann solver 和三階 Runge Kutta。指標是 MFC 自己印出來的 grind time，也就是每個網格點、每條方程式、每次右手邊計算花幾奈秒，越小越好。每個版本交錯跑五次，五次之間的差距不到百分之一。正確性的部分，我把最後一步的守恆量逐 byte 和原版比較，另外再跑 MFC 自己的七百二十個 regression test。

## 4
先看原版。在一張 H200 上 grind time 是零點四零二六奈秒。WENO 重建佔了三成三，HLLC 佔兩成六，剩下大多是只搬資料的 streaming kernel。有一個有趣的觀察：H200 的記憶體頻寬比 H100 多了百分之四十三，但整體只快了百分之五。這表示最大的兩個 kernel 並不是被記憶體頻寬卡住，光換更快的記憶體幫不上忙。

## 5
HW1 的 profile 發現，HLLC 每次 launch 有將近十 GB 的 local memory 讀取。當時我推測，原因是 private 陣列用執行期才知道的 index 存取。所以第一個改動，就是在每個方向把這些 index 改成編譯期常數。結果 SASS 裡的 local load 指令數完全沒變，還是兩百二十二條，速度也沒變。也就是說，這個假設只對了一半。

## 6
繼續往下讀 PTX，才找到真正的原因。HLLC kernel 裡還有真的函式呼叫，例如計算音速的 subroutine。Fortran 的參數是傳參考，被傳進去的變數一定要有位址，所以整組 thread 私有的狀態都被放進了 local memory。編譯器的報告說這些函式有 inline，但那只是 host 端；在 device 端，一個 subroutine 裡有十二個 kernel，inline 的預算在後面就用完了。比較幾個 inline 選項之後，加上 smallsize 六十四，device 上的函式呼叫就全部消失了。

## 7
結果是只改一行 CMake 的編譯選項，grind time 從零點四零二六降到零點三六六五，快了百分之十，而且結果逐 byte 相同。local memory 的讀取指令從兩百二十二條降到七十四條，再加上前面的常數 index，只剩十二條。常數 index 那個改動單獨沒有效果，我在報告裡誠實記錄，保留它只是因為它讓剩下的 local memory 幾乎歸零。

## 8
接下來是兩個完全多餘的整場複製。第一個是 Riemann solver 算完之後，把 flux 複製到另一個 buffer，但兩邊的資料排列其實完全一樣。所以我讓下游直接指向 solver 的輸出 buffer，這個 kernel 就整個消失了。第二個是 WENO 的輸入，同一組資料在每次右手邊計算裡被複製了三次。現在只在資料真的改變時才複製一次。這兩個改動單獨分別快了百分之八和百分之五。

## 9
WENO 是 latency bound 的 kernel。它每個 thread 用了將近兩百個 register，所以每個 SM 只能放很少的 warp，occupancy 只有百分之十二點五。我只對 WENO 這個模組把 register 上限設成一百二十八。這樣會產生 spill，每次 launch 多了五到八 GB 的 local memory 存取，但 occupancy 加倍，WENO 反而快了百分之二十九。我也試了九十六和一百六十，都比一百二十八差。有趣的是，這和 HLLC 剛好相反：在 HLLC，local memory 是負擔；在 WENO，warp 的數量比 spill 更重要。

## 10
最後一個是幾個只搬資料的 kernel。原本的迴圈把方程式和三個空間方向攤平成一維，每個元素都要用六十四位元的除法，把一維 index 還原成四個 index，結果指令比資料還多。我改成一個 thread 負責一個網格點，在 thread 裡依序算八條方程式，算術完全不變。指令數降到原本的四成，記憶體頻寬的使用率從四成左右升到六成以上。

## 11
把六個 commit 疊起來，grind time 從零點四零二六降到零點二五八一，總共快了一點五六倍。每個 Runge Kutta stage 的 kernel 時間從二十五點四毫秒降到十五點九毫秒。每一個版本最後一步的守恆量都和原版逐 byte 相同。MFC 的 regression test，原版和最終版的結果也完全一樣。

## 12
接著看多張 GPU。這是在同一個節點上的 strong scaling。最大的非程式槓桿是 GPU aware MPI，也就是 rdma mpi 這個選項，光是打開它，八張卡就快了一點五八倍。加上程式優化之後，八張卡的 grind time 是零點零五一二奈秒，比預設設定的八張卡快兩點二倍，比單卡的原版快七點八七倍。不過 kernel 變快之後，halo exchange 佔的比例變大，八張卡的平行效率從百分之七十降到六十三，這是下一步要處理的地方。

## 13
也有沒成功的實驗。把 WENO 的迴圈攤平以提高 occupancy，結果指令數加倍，反而慢了百分之八點七。register 上限九十六和一百六十都輸給一百二十八。另外有兩個四卡的 job 剛好和別人共用節點，慢了一到兩成，我把它們丟掉並記錄下來。還沒做的，包括把兩個小 kernel 融合，以及讓 halo exchange 和計算重疊。

## 14
接下來講我怎麼用 AI agent。老實說，這份作業我幾乎整份交給了 agent：我只下了一句「把 eeclass 上的作業完成」。我做的事情是人才能做的部分：登入 eeclass、打開到 nano4 的 SSH 連線、在需要 sudo 的地方自己輸入密碼，以及回答它問我的選擇。選 MFC 和 nano4、用 HW1 的 commit 和測資當起點、優化的方向，都是主 agent 讀了作業和我的 HW1 報告之後決定的。主 agent 把背景整理成一份 brief，交給一個 worker agent；worker 透過 SSH 在 login node 編譯、用 Slurm 送量測。每個優化一個 commit，實驗放在旁邊的 branch，沒有贏就不進 main。這次讓結果可信的不是 prompt，而是規則：沒有證據的數字，不能寫進報告。

## 15
agent 也會做錯。第一，它一開始照 HW1 的推測修 HLLC，是看到 SASS 的 local load 數量沒變，才發現根因判斷錯了。第二，第一批 Slurm job 因為 MPI 的 binding 和 HPC X 的路徑設定失敗。第三，regression test 第一次全部失敗，因為 MFC 選了 srun，但這個 MPI 沒有 Slurm 的支援。第四，匯出 profiler 資料時，三個方向的 kernel 被合併成同一個名字。另外，中途 SSH 連線斷掉的時候，worker 停下來回報，而不是自己嘗試登入，這是 brief 裡事先寫好的規則。

## 16
總結一下。單張 H200 從零點四零二六降到零點二五八一奈秒，快一點五六倍；八張 H200 是零點零五一二奈秒。六個 commit 每個都有量測和 profiler 的證據，最終結果和原版逐 byte 相同。HW1 提出的三個方向都得到驗證，但其中一個的原因猜錯了。這次最大的收穫是：先看 PTX 和 SASS，再相信 profiler 的分類。謝謝大家。
