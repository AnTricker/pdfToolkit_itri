# Digital PDF Toolkit：專案概念說明（舊版 0.1）

> 本文件保存舊版設計背景。現行 `0.2` page-set／preprocess 架構與 commands 請以根目錄 `README.md` 為準；新版不讀取或遷移舊 output。

## 1. 專案想解決的問題

Digital PDF 通常已經包含文字、字型、座標、圖片、向量圖形與頁面結構。若一開始就把整頁交給 LLM／VLM 重新理解，容易忽略這些原始數位資訊，也會引入不可追溯、不可重現的推論結果。

本專案的核心想法是：

> 先以 PDF 原生結構與成熟工具，完整取出可觀察、可追溯的內容；視覺與語意理解留給下游。

主要產物不是 Markdown、摘要或問答，而是能作為後續 embedding、VLM、資料庫或其他應用輸入的 structured JSON 與視覺 assets。

## 2. 核心原則

### 2.1 原始事實與工具分析分離

資料分成兩個基本層次：

1. `observed`
   - PDF 直接提供的 page、native char、text span、font、bbox、image、vector、metadata。
   - 是不可被其他工具覆寫的基準事實。

2. `tool-derived`
   - PaddleOCR、MinerU、Surya 等工具產生的 layout、OCR、table、formula、chart 與 reading-order 結果。
   - 必須保存來源工具、版本、設定、attempt 與原始輸出。

即使工具內部整合了 LLM／VLM，也仍可作為完整工具使用；限制是不由本專案自行設計 prompt、直接呼叫通用模型或把工具推論偽裝成 PDF 原始事實。

### 2.2 文件與簡報使用同一套方法論

直式文件與橫式簡報都具有：

- 跨頁的線性 page order。
- 頁內的 x／y 空間結構。
- text、image、vector、table、formula、chart 等不同元素。

因此不建立兩套互斥 pipeline。文件與簡報共用 native extraction、座標、provenance、tool adapters 與 payload；差異只存在於各工具偵測出的 region 類型與實際表現。

### 2.3 先忠實取出，不提前重建語意

PDF 階段關注的是「取出什麼、位於哪裡、來源為何」，不負責判斷：

- 某張圖支持哪個論點。
- diagram label 與 node 的語意關係。
- 跨頁內容是否在概念上相關。
- chart、figure 或 formula 的完整語意。

視覺區域保存 page render、bbox 與 exact crop；下游可以把 crop、native text、OCR text 與 structured JSON 一起交給 VLM。

## 3. 統一底座與獨立工具結果

### 3.1 Native extraction

底層採用：

- PyMuPDF：PDF 開啟、page、native text、image、vector、metadata 與 rendering。
- pdfplumber：char、line、rect、curve 與精細 geometry 補強。

Native text 保證 char-level provenance；OCR text 僅承諾工具實際提供的 line／word-level bbox，不人工平均切割或虛構 char bbox。

### 3.2 分析工具 bake-off

第一輪同時保留三套成熟工具：

- PaddleOCR ecosystem：中文、OCR、layout、table、formula、chart 專項能力。
- MinerU：完整 document parsing 與 hybrid pipeline。
- Surya：multilingual OCR、layout、table、formula 與簡報型文件的獨立比較。

三套結果：

- 不融合。
- 不投票。
- 不平均 bbox。
- 不建立自訂綜合 score。
- 不強制轉成完全相同的儲存 schema。

每個工具保留原生 JSON 與自己的 output layout。下游透過各自的 `RunReader` adapter 取得共同操作能力，例如 pages、regions、text、crop 與 provenance；互通責任放在程式介面，而不是要求所有工具丟失特有欄位以配合單一格式。

## 4. OCR 的角色

OCR 是條件式 fallback，不是正常 Digital PDF 的預設文字來源。

- native text 正常：保存 native chars，不跑不必要的 OCR。
- image-only page／region：允許 OCR。
- native text layer 損壞或亂碼：保留原結果並標示品質，再啟用 OCR。
- mixed native＋raster：兩種來源分開保存，避免混為同一文字層。

語言 profile 包含：

- `zh`
- `en`
- `mixed`
- `auto`

`auto` 優先依 native Unicode script 判斷；沒有可用 native text 時使用 mixed profile。MVP 涵蓋繁中、簡中、英文與中英混排，不處理手寫。

## 5. 座標與視覺資產

正式 observed 座標採固定契約：

- 顯示方向左上為原點。
- x 向右、y 向下。
- 單位為 PDF point。
- bbox 格式為 `[x0, y0, x1, y1]`。
- page rotation 已套用。

各工具可使用 pixel、normalized 或其他座標，由 adapter 轉換；最終資料契約不隨工具漂移。

每頁保存完整 page render。視覺 region 只產生嚴格依 bbox 裁切的 exact crop，不預先產生 context crop。需要上下文時，下游可利用 page render 與 bbox 自行取得。

公式採取：

> best-effort native extraction + exact crop + quality status

不在 MVP 解析 raw CMap、glyph code、LaTeX 或公式語法樹。無法可靠解碼時，以 crop 保存忠實的視覺證據。

## 6. 執行與選擇概念

主要階段：

```text
setup
extract
analyze:paddle / analyze:mineru / analyze:surya
assets:<tool>
select
payload
```

主要人工 commands 維持最少：

```bash
./setup.sh
./run.sh <pdf-or-directory>
./finalize.sh <run-id> <tool>
```

第一次 bake-off 會保存三套工具結果、bbox overlays 與 exact crops，由使用者依文件實際表現選擇。不同 PDF 可以選擇不同工具，不必強迫全 corpus 使用同一個「總冠軍」。

選擇只更新 manifest，既有工具結果不刪除，也不重新跑 PDF 或模型。Payload 直接引用已完成的 observed data、selected tool result 與 assets。

## 7. 可重跑、可審查與可除錯

每個 stage／tool 都有獨立狀態與 attempt：

- `pending`
- `running`
- `completed`
- `failed`
- `cached`

Cache signature 由 PDF checksum、工具／模型版本與設定組成。相同輸入與設定已完成時可略過；`--rerun` 會新增 attempt，而不是覆寫舊結果。

執行期間：

- Terminal 顯示簡短即時狀態或 heartbeat。
- `run.log` 保存人類可讀紀錄。
- `events.jsonl` 保存 structured events。
- 每個 attempt 保存 command、environment、status、stdout、stderr、exit code 與 duration。
- Logs 不保存 token、password 等敏感內容。

三套大型工具預設 sequential 執行，避免 GPU、VRAM、RAM 與 model runtime 相互競爭。

## 8. Payload 的定位

Payload 是 extraction 專案與後續智慧處理之間的靜態 handoff，不是最終語意結果。

它包含：

- observed JSON。
- selected tool result 參照。
- page renders。
- exact crops。
- provenance 與 selection manifest。

它不包含：

- embedding vectors。
- VLM interpretation。
- semantic relationships。
- LLM captions。
- RAG chunks。

後續專案可以選擇單一工具結果，或在需要時讀取多套工具結果，再自行設計 embedding／VLM 策略。

## 9. 專案邊界與演進方向

MVP 接受所有不需未知密碼、可正常開啟的 PDF。能結構化的內容盡量結構化；無法解析的特殊物件以 page render／crop 與 warning 保底，不靜默遺漏。

目前刻意延後：

- 三工具平行執行。
- page／region 細粒度選擇。
- context crop。
- HTML review UI。
- 多工具結果融合。
- 自動工具選擇。
- diagram semantic linking。
- 真正的 VLM／embedding integration。
- Docling、Marker、Camelot、GMFT 等額外工具。
- 商用授權與部署最佳化。

這些不是被否定，而是在 native extraction、工具輸出與 handoff 契約實際驗證後，再依 corpus 證據逐步加入。

## 10. MVP 成功的判斷方式

MVP 的價值不由單一 benchmark 分數決定，而是確認：

- PDF native objects 沒有因工具分析而遺失。
- bbox overlay 與 exact crop 對位正確。
- native 與 OCR provenance 清楚分離。
- 中文、英文與 mixed 文件皆能產生可檢查結果。
- 三套工具能各自完成、失敗、恢復與重跑。
- 使用者能逐份文件選擇結果，並在不重跑模型下建立 payload。
- 下游能透過 adapters 讀取不同工具結果。

最終目標不是在 PDF 階段完成所有理解，而是建立一個可信、可換工具、可追溯的資料基礎，讓後續 VLM／embedding 得到更完整且有證據可回查的輸入。
