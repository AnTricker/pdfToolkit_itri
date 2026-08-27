# Digital PDF Toolkit

將 scanned PNG、scanned PDF 或 Digital PDF 建立為 `page_set`，再交給 Paddle／Surya／MinerU analyze，最後產生 `document_handoff`。每個 command 只做一件事，不自動判斷輸入或串接下一階段。

## 最低運算 smoke test

原則：每份文件只使用 1 頁、PNG 長邊約 `1200–1600px`、只選一個已下載模型的 OCR tool。

### Scanned PNG

```cmd
scripts\windows\pages.cmd create smoke-scans
scripts\windows\analyze.cmd create <doc-folder> --page-set <page-set-attempt-folder> --tools paddle
scripts\windows\finalize.cmd create <doc-folder> --tool paddle --attempt <analyze-attempt-folder>
```

### Digital PDF

```cmd
scripts\windows\extract.cmd create smoke.pdf
scripts\windows\analyze.cmd create <doc-folder> --page-set <page-set-attempt-folder> --tools paddle
scripts\windows\finalize.cmd create <doc-folder> --tool paddle --attempt <analyze-attempt-folder>
```

Linux 將入口換成：

```bash
./scripts/linux/<mode>.sh
```

完整流程：

```text
Scanned PNG → pages create → analyze → finalize
Digital PDF → extract create → analyze → finalize
```

## Pipeline

```text
HEIC/HEIF folder
  └─ (可選) heic-to-png
          │
          ▼
Scanned PDF / PNG folder
  ├─ pages create ───────────────────────────────┐
  └─ (可選) preprocess create/retry ─────────────┤
                                                  ├─ page_set
Digital PDF ── extract create ────────────────────┘
                                                        │
                                                        ├─ (可選) resolution optimize
                                                        ▼
                                                  analyze create
                                                        ▼
                                                  finalize create
```

## Folder name 傳參

CLI 的識別參數都對應 output 中的 folder name：

| 參數 | 輸入 | 範例 |
|---|---|---|
| `<doc-folder>` / `document-id` | document folder | `doc-0820-0901` |
| `--page-set` | page-set attempt folder | `attempt-001_0820-0901` |
| `--attempt` | analyze/report attempt folder | `attempt-001_0820-0906` |
| `--from` | preprocess parent attempt folder | `attempt-001_0820-0901` |

`--page-set` 可直接輸入 attempt folder name。只有同一 document 的不同 producer 恰好產生完全同名 attempt 時，才需用完整名稱消歧義，例如 `pages:attempt-001_0820-0901`。

目前沒有其他必須使用 opaque ID、不能使用 folder name 的介面。`--tool`／`--tools` 是工具名稱。

## Setup

```cmd
scripts\windows\setup.cmd
```

```bash
./scripts/linux/setup.sh
```

| Environment | 工具 |
|---|---|
| `digital-pdf-core` | PyMuPDF、pdfplumber、Pillow、pillow-heif、OpenCV |
| `digital-pdf-paddle` | PaddleOCR、PaddleX、UVDoc |
| `digital-pdf-surya` | Surya |
| `digital-pdf-mineru` | MinerU |

## （可選）HEIC to PNG

只將手機 HEIC／HEIF 轉成 PNG；不建立 document、attempt、mapping 或 page set。

### 最簡指令

```cmd
scripts\windows\heic-to-png.cmd phone-photos
```

```bash
./scripts/linux/heic-to-png.sh phone-photos
```

### 可設參數

```cmd
scripts\windows\heic-to-png.cmd phone-photos --output converted-pages
```

```bash
./scripts/linux/heic-to-png.sh phone-photos --output converted-pages
```

| I/O | 內容 |
|---|---|
| Input | 一個 folder；只讀頂層 `.heic`／`.heif`，natural sort |
| Output | 預設 `<input>/scan_source_pages/pNNNN.png`，或由 `--output` 指定 |

Output folder 必須不存在或為空。每個 HEIC 只取 primary image並套用 EXIF orientation。

## （可選）Preprocess

處理 scanned PDF／PNG 的 split、透視、orientation、dewarp、deskew、光照、去噪、對比與裁切。它會自行建立 document 與 preprocess page set，但不是 analyze 必經步驟；原圖足夠時直接使用 `pages create`。

### 最簡指令

```cmd
scripts\windows\preprocess.cmd create scans --profile full
```

```bash
./scripts/linux/preprocess.sh create scans --profile full
```

### 可設參數

```cmd
scripts\windows\preprocess.cmd create scan.pdf --profile geometry-only --debug
scripts\windows\preprocess.cmd create scans --profile custom --config config\scan-custom.yml
scripts\windows\preprocess.cmd retry doc-0820-0901 --from attempt-001_0820-0901 --overrides overrides.json
scripts\windows\preprocess.cmd report doc-0820-0901 --attempt attempt-002_0820-0910
```

```bash
./scripts/linux/preprocess.sh create scan.pdf --profile geometry-only --debug
./scripts/linux/preprocess.sh create scans --profile custom --config config/scan-custom.yml
./scripts/linux/preprocess.sh retry doc-0820-0901 --from attempt-001_0820-0901 --overrides overrides.json
./scripts/linux/preprocess.sh report doc-0820-0901 --attempt attempt-002_0820-0910
```

| Profile | 內容 |
|---|---|
| `full` | 完整幾何與清理，不含 binarization |
| `geometry-only` | 幾何校正、crop、QA |
| `cleanup-only` | lighting、denoise、contrast、crop、QA |
| `custom` | 依 `preprocessing.custom_steps` |

| 參數 | 說明 |
|---|---|
| `--profile` | Profile，預設 `full` |
| `--document-id` | 自訂新 document folder name |
| `--overrides` | rotate、split、preprocess page order |
| `--config` | 覆蓋 render/preprocess/QA config |
| `--debug` | 保存中間影像 |

| I/O | 內容 |
|---|---|
| Input | 一份 PDF，或只讀頂層 PNG 的 folder |
| Output | `output/doc-*/preprocess/attempt-*/` 與 page set |

```text
preprocess/attempt-NNN_MMDD-HHmm/
├─ scan_source_pages/          # PDF input only
├─ processed_pages/pNNNN.png
├─ debug/                      # --debug only
├─ preprocessing.json
├─ overrides.snapshot.json
├─ orientation/dewarp reports and logs
└─ page_set.json
```

單頁失敗會略過並發布 partial page set；全部失敗才回傳非零 exit code。Geometry QA 通過後才計算 DPI。

## （可選）Resolution

對既有 page set 使用 Pillow Lanczos 放大至目標 A4-equivalent DPI。它必須在 Create／Extract／Preprocess 之後、Analyze 之前執行；高於目標不降採樣。

### 最簡指令

```cmd
scripts\windows\resolution.cmd optimize doc-0820-0901 --page-set attempt-001_0820-0901
```

```bash
./scripts/linux/resolution.sh optimize doc-0820-0901 --page-set attempt-001_0820-0901
```

### 可設參數

```cmd
scripts\windows\resolution.cmd optimize doc-0820-0901 --page-set attempt-001_0820-0901 --target-dpi 300
scripts\windows\resolution.cmd report doc-0820-0901 --attempt attempt-001_0820-0912
```

```bash
./scripts/linux/resolution.sh optimize doc-0820-0901 --page-set attempt-001_0820-0901 --target-dpi 300
./scripts/linux/resolution.sh report doc-0820-0901 --attempt attempt-001_0820-0912
```

| I/O | 內容 |
|---|---|
| Input | document folder＋page-set attempt folder |
| Output | `resolution/attempt-*/pages/`、`resolution.json`、新 page set |

`--target-dpi` 預設為 300。DPI 是依 pixels 與 A4 尺寸推算的 QA estimate。

## Create：Scanned PNG

將原始 PNG folder 直接映射成 external page set，不做 preprocess 或 resolution。

### 最簡指令

```cmd
scripts\windows\pages.cmd create scans
```

```bash
./scripts/linux/pages.sh create scans
```

| I/O | 內容 |
|---|---|
| Input | 一個 folder；只讀頂層 `.png`，filename natural sort |
| Output | 新 document、`pages/attempt-*/page_set.json` |

不複製、不改名、不處理影像。壞圖略過，全部無效才失敗。Page set 保存絕對路徑、pixel dimensions 與 SHA-256。

需要增刪頁面或調整順序時，直接修改 input folder 內容／filename，再重新執行一次 `pages create`，產生新的 document。

## Extract：Digital PDF

從 Digital PDF 擷取 observable facts並 render page PNG，建立 extract page set；不執行 OCR。

### 最簡指令

```cmd
scripts\windows\extract.cmd create document.pdf
```

```bash
./scripts/linux/extract.sh create document.pdf
```

### 可設參數

```cmd
scripts\windows\extract.cmd create document.pdf --document-id my-document --config config\my.yml
```

```bash
./scripts/linux/extract.sh create document.pdf --document-id my-document --config config/my.yml
```

| 參數 | 說明 |
|---|---|
| `--document-id` | 自訂新 document folder name |
| `--config` | 覆蓋 config，例如 `project.render_dpi` |

| I/O | 內容 |
|---|---|
| Input | 一份 Digital PDF |
| Output | 新 document、observed facts、page renders 與 extract page set |

```text
extract/attempt-NNN_MMDD-HHmm/
├─ page_set.json
└─ observed/
   ├─ document.json
   ├─ pages/
   ├─ page_renders/pNNNN.png
   └─ embedded_images/
```

### Extract YAML 可設選項

`--config` YAML 會覆蓋 default/local config。Extract 實際使用：

| YAML key | 說明 |
|---|---|
| `project.output_root` | 新 document 的 workspace root |
| `project.render_dpi` | PDF render DPI；越高越清晰，但影像、儲存與後續運算越大 |
| `logging.redact_keys` | `run.log`／`events.jsonl` 要遮罩的敏感 key |

範例 `config/extract.yml`：

```yaml
project:
  output_root: "output"
  render_dpi: 150

logging:
  redact_keys: ["token", "secret", "password", "api_key", "authorization"]
```

`config/profiles/extract-only.yml` 目前只是保留的 profile metadata；明確的 `extract create` 不使用它控制行為。

## Analyze

對明確 page set 執行 OCR／layout。Analyze 不自動執行 preprocess/resolution，也不建立 input copy。

### 最簡指令

```cmd
scripts\windows\analyze.cmd create doc-0820-0901 --page-set attempt-001_0820-0901 --tools paddle
```

```bash
./scripts/linux/analyze.sh create doc-0820-0901 --page-set attempt-001_0820-0901 --tools paddle
```

### 可設參數

```cmd
scripts\windows\analyze.cmd create doc-0820-0901 --page-set attempt-001_0820-0901 --tools paddle,surya
scripts\windows\analyze.cmd create doc-0820-0901 --page-set attempt-001_0820-0901 --tools paddle --config config\analyze.yml
```

```bash
./scripts/linux/analyze.sh create doc-0820-0901 --page-set attempt-001_0820-0901 --tools paddle,surya
./scripts/linux/analyze.sh create doc-0820-0901 --page-set attempt-001_0820-0901 --tools paddle --config config/analyze.yml
```

| 參數 | 說明 |
|---|---|
| 第一個位置參數 | document folder name |
| `--page-set` | page-set attempt folder name |
| `--tools` | `paddle`、`surya`、`mineru`，可逗號分隔 |
| `--config` | 覆蓋 tool command/environment |

| I/O | 內容 |
|---|---|
| Input | document＋page set |
| Output | tool attempt、raw result、status/logs、crops/overlays |

```text
analyze/{paddle|surya|mineru}/attempt-NNN_MMDD-HHmm/
├─ raw/
├─ assets/
│  ├─ crops/
│  ├─ overlays/
│  └─ index.json
├─ command.json
├─ environment.json
├─ status.json
├─ stdout.log
└─ stderr.log
```

- Paddle／Surya 可分析 PNG page set。
- MinerU 只接受 extract page set及其 source PDF。
- External page set 在 analyze 前驗證檔案存在且 SHA-256 未變。
- 目前 Paddle 是完整 PP-StructureV3；最低負載測試請使用單張縮小 PNG。

### Analyze YAML 可設選項

Analyze 先讀 `config/tools/<tool>.yml`，再由 `--config` YAML 覆蓋：

| YAML key | 說明 |
|---|---|
| `project.output_root` | 尋找既有 document 的 workspace root，必須與建立時一致 |
| `project.heartbeat_seconds` | OCR subprocess 執行時的 heartbeat 秒數 |
| `logging.redact_keys` | Analyze logs 的敏感 key 遮罩 |
| `tools.<name>.version` | Signature／environment metadata；不負責安裝套件 |
| `tools.<name>.environment` | 執行 tool 的 Conda environment |
| `tools.<name>.command` | 真正執行的 command template；工具 flags 必須寫在此處 |
| `tools.<name>.options` | 描述性 metadata，目前不會自動轉成 command flags |

Command placeholders：

| Placeholder | 內容 |
|---|---|
| `{analysis_pages_dir}` | Page set 實際 PNG folder |
| `{raw_dir}` | Analyze attempt 的 raw output folder |
| `{input_pdf}` | Extract page set 的 source PDF，主要供 MinerU 使用 |

範例 `config/analyze.yml`：

```yaml
project:
  heartbeat_seconds: 30

tools:
  paddle:
    environment: "digital-pdf-paddle"
    command:
      - "paddleocr"
      - "pp_structurev3"
      - "-i"
      - "{analysis_pages_dir}"
      - "--save_path"
      - "{raw_dir}"
      - "--use_doc_orientation_classify"
      - "False"
      - "--use_doc_unwarping"
      - "False"
```

`config/profiles/analyze-only.yml` 目前同樣只是保留 metadata；`analyze create` 實際由 `config/tools/*.yml` 與 `--config` 控制。

## Finalize

將 completed analyze attempt 整理成 `document_handoff`，不重新執行 OCR，也不自動選擇最新 attempt。

### 最簡指令

```cmd
scripts\windows\finalize.cmd create doc-0820-0901 --tool paddle --attempt attempt-001_0820-0906
```

```bash
./scripts/linux/finalize.sh create doc-0820-0901 --tool paddle --attempt attempt-001_0820-0906
```

| I/O | 內容 |
|---|---|
| Input | document folder、tool name、completed analyze attempt folder |
| Output | `finalize/attempt-*/manifest.json` |

Handoff 綁定 OCR page set、raw result、assets index、page renders、exact crops，以及可用時的 Digital PDF observed facts。

## Output workspace

```text
output/
└─ doc-MMDD-HHmm[-NN]/
   ├─ manifest.json
   ├─ run.log
   ├─ events.jsonl
   ├─ pages/attempt-*/page_set.json
   ├─ extract/attempt-*/
   ├─ preprocess/attempt-*/
   ├─ resolution/attempt-*/
   ├─ analyze/{paddle|surya|mineru}/attempt-*/
   └─ finalize/attempt-*/manifest.json
```

`manifest.json` 保存 source versions、attempts、page-set registry、resolved config 與階段綁定。Attempts immutable；重新執行會建立新 folder。

## 常用 config

```yaml
project:
  output_root: "output"
  render_dpi: 150
  heartbeat_seconds: 30

preprocessing:
  custom_steps: []
  binarization: "adaptive"
  paddle_max_long_edge: 3000

resolution:
  low_dpi_warning: 150
  target_dpi: 300
```

Config 套用順序：

```text
config/default.yml
→ config/local.yml（若存在）
→ config/tools/<tool>.yml
→ config/profiles/full.yml
→ --config YAML
→ CLI parameters
```

## 各 Mode 使用工具

| Mode／入口 | 使用工具 | 用途 |
|---|---|---|
| `heic-to-png` | pillow-heif、Pillow | HEIC decode、EXIF orientation、PNG 輸出 |
| `preprocess` acquisition | PyMuPDF、Pillow | Scanned PDF render 或 PNG 讀取 |
| `preprocess` geometry/cleanup | OpenCV、Paddle orientation、UVDoc、Pillow | Split、透視、方向、dewarp、deskew 與清理 |
| `resolution` | Pillow Lanczos | 非 AI 解析度放大 |
| `pages create` | Pillow、SHA-256 | PNG 驗證、尺寸讀取與 external page-set mapping |
| `extract` | PyMuPDF、pdfplumber | Digital PDF observation、embedded images、page render |
| `analyze --tools paddle` | PaddleOCR / PP-StructureV3 | OCR、layout、table、formula 結構分析 |
| `analyze --tools surya` | Surya | OCR／layout 分析 |
| `analyze --tools mineru` | MinerU | Digital PDF 結構解析；需要 source PDF |
| Analyze assets | Tool adapter、Pillow | Bbox 轉換、crops、overlays |
| `finalize` | 專案內建 JSON/Python | 綁定 page set、OCR attempt、assets 與 handoff；不執行模型 |
