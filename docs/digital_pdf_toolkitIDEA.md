# Digital PDF Toolkit MVP 實作計畫（舊版 0.1）

> 本文件為歷史摘要。現行 `0.2` 架構與 commands 請以根目錄 `README.md` 為準。

## Summary

在既有 repository 內新增完全獨立的 `digital_pdf_toolkit/`，未來可直接拆成單獨 repo。MVP 建立可重跑、可追溯的 Digital PDF 工具評測框架；不修改現有 `text/image/vector` pipelines。

核心流程：

```text
PDF
→ PyMuPDF + pdfplumber observed extraction
→ PaddleOCR / MinerU / Surya 獨立分析
→ 各工具原生 JSON、overlay、exact crops
→ 每份文件人工選擇工具結果
→ 建立靜態下游 payload
```

實作期間不安裝大型環境、不下載模型、不跑真實 PDF；只執行 fixtures、mock、CLI、config 與 shell syntax 等必要驗證。

## Implementation

### 1. 獨立專案骨架與環境

- 建立 `digital_pdf_toolkit/`，內含 `src/`、`tests/`、`config/`、`environments/`、`scripts/internal/`、`docs/`。
- 提供 core、PaddleOCR、MinerU、Surya 四套獨立 Conda environment／requirements 文件。
- 以 Linux／WSL Bash 為標準，scripts 使用 `conda run -n <env>`，不依賴互動式 `conda activate`。
- 三套分析工具預設 sequential 執行；每個 process 結束後釋放資源。
- 工具版本、模型位置與 runtime 選項分開配置；不建立每模組 `.env`。

### 2. 使用者介面與設定

提供三個主要 commands：

```bash
./setup.sh
./run.sh <pdf-or-directory>
./finalize.sh <run-id> <tool>
```

支援必要進階操作：

```bash
./run.sh file.pdf --tools paddle,mineru
./run.sh file.pdf --profile extract-only
./run.sh --resume <run-id> --profile analyze-only
./run.sh --resume <run-id> --rerun mineru
./finalize.sh <batch-run> --selections selections.yml
```

設定優先序固定為：

```text
CLI > profile > tool config > default
```

設定檔分為：

- `default.yml`：共用預設值。
- `local.yml`：本機 output、model、Conda 等路徑，不進版控。
- `profiles/`：`full`、`extract-only`、`analyze-only`。
- `tools/`：PaddleOCR、MinerU、Surya 原生選項。
- 單一 `.env` 僅供未來敏感值使用；MVP 不把一般設定放入 `.env`。

### 3. Stages、輸出與互通介面

Stages：

```text
setup
extract
analyze:paddle / analyze:mineru / analyze:surya
assets:<tool>
select
payload
```

- `extract` 使用 PyMuPDF＋pdfplumber，保存 page、char/span、font、bbox、image、vector、metadata、page render 與 provenance。
- Canonical bbox 採左上原點、x 向右、y 向下、PDF point、rotation 已套用。
- OCR/native text 嚴格分流；native 支援 char-level，OCR 僅保證 line/word-level。
- 各工具保存自己的原生 schema，不強制統一欄位；raw output 永久保留。
- 下游以 Paddle、MinerU、Surya 各自的 `RunReader` adapter 提供共同操作能力：pages、regions、text、crop、provenance。
- 每個工具依其 bbox 產生 page overlay 與 `exact_crop`；不產生 context crop。
- 不融合、不投票、不建立人工 score，也不在此階段推導 diagram semantic relationships。
- 每份 PDF manifest 可選不同 tool attempt；batch 使用 `selections.yml`。
- `finalize.sh` 只更新 selection 並建立 payload，不重新執行 parser 或模型。
- Payload 以相對路徑引用 observed data、selected tool result、page renders、exact crops 與 provenance；不包含 embedding、VLM interpretation、LLM caption 或 RAG chunks。

### 4. Cache、attempt 與 logging

- 每個 stage 獨立保存 `pending/running/completed/failed/cached`。
- Cache signature 包含 PDF checksum、工具／模型版本與 resolved config。
- 相同 signature 已完成時略過；設定或版本改變時自動建立新 attempt。
- `--rerun <tool>` 即使命中 cache 仍新增 attempt，永不覆寫舊結果。
- 一個工具失敗不阻止其他不相依工具完成。
- Terminal 顯示簡短即時狀態；無 page progress 時顯示 elapsed heartbeat。
- 保存整體 `run.log`、structured `events.jsonl`，以及每個 attempt 的 command、environment、status、stdout、stderr、exit code 與 duration。
- Logs 過濾 secret，不輸出完整敏感 environment。

## Verification and Documentation

只執行新 folder 內的 targeted verification：

- 人工 fixtures 模擬 PaddleOCR、MinerU、Surya 原生輸出，驗證三個 adapters。
- 測試 canonical coordinate conversion、rotation、crop transform 與 bbox containment。
- 測試 config precedence、profiles、I/O resolution 與 manifest serialization。
- 測試 cache hit、failed stage、resume、`--rerun` attempt preservation。
- 測試單檔／批次 selection，以及 payload 不觸發任何 analyzer。
- 測試 terminal events、persistent logs 與 secret filtering。
- 執行 CLI `--help`／argument tests、Python targeted tests、`bash -n`。
- 不執行 `setup.sh`、真實 PDF、模型 inference、模型下載、完整 repository test suite。

README 必須寫清楚：

- 架構、stages、Conda environments、安裝與三個主要 commands。
- 工具與語言設定、`zh/en/mixed/auto` OCR profiles。
- output layout、schema ownership、RunReader 概念。
- cache、attempt、resume、rerun、logs 與錯誤恢復。
- 如何準備 corpus、檢查 JSON／overlay／crops、逐檔 finalize。
- 明確標示實作期間未執行真實工具驗證。

`docs/DEFERRED_OPTIONS.md` 記錄不納入 MVP 的選項：parallel execution、page/region selection、context crop、HTML review、tool fusion、Docling/Marker/Camelot/GMFT、商用授權處理及真正 VLM／embedding integration。

## Assumptions

- 工具內部可使用已整合的 LLM／VLM，但其輸出一律視為 tool-derived，不得覆寫 observed facts。
- MVP 語言涵蓋繁中、簡中、英文與中英混排；不處理手寫。
- 所有 browser 可正常開啟且不需未知密碼的 PDF 均可輸入；無法結構化的內容以 render/crop 與 warning 保底。
- 真實 corpus、模型安裝、效能測試與最終工具選擇由使用者在交付後執行。
