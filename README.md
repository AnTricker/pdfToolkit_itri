# Digital PDF Toolkit

本專案提供 HEIC 轉 PNG、PNG 合併 PDF、Digital PDF native extraction、Surya OCR 與 Marker 文件分析。

---
## Setup

```bash
./scripts/linux/setup.sh
```

```cmd
scripts\windows\setup.cmd
```

建立／更新 `digital-pdf-core`、`digital-pdf-surya` 與 `digital-pdf-marker`。

ROCm embedding 環境需明確指定與主機相容的 PyTorch wheel index，避免誤裝其他 build：

```bash
PYTORCH_ROCM_INDEX_URL=https://download.pytorch.org/whl/rocm6.4 \
  ./scripts/linux/setup-embedding.sh
```

## Commands

### HEIC to PNG

```bash
./scripts/linux/heic-to-png.sh phone-photos
./scripts/linux/heic-to-png.sh phone-photos --output converted-pages
```

預設輸出至 `<input>/scan_source_pages/`。只處理 input root 的 `.heic/.heif`，依 natural filename order 產生 `p0001.png...`。

---
### PNG to PDF

```bash
./scripts/linux/png-to-pdf.sh png-folder
./scripts/linux/png-to-pdf.sh png-folder --output document.pdf
```

只處理 input root 的 `.png`，依 natural filename order 合併為單一 PDF。預設輸出為 `<input>/<folder-name>.pdf`，不覆寫既有檔案。

---
### Extract

```bash
./scripts/linux/extract.sh document.pdf
./scripts/linux/extract.sh document.pdf --config config/custom.yml
```

輸出 native text、geometry、embedded images 與 page renders：

```text
output/MMDDHHmm_extract/
├─ document.json
├─ pages/
├─ page_renders/
├─ embedded_images/
├─ command.json
├─ environment.json
├─ status.json
├─ run.log
└─ events.jsonl
```

---
### Surya2

```bash
./scripts/linux/surya2.sh png-folder
./scripts/linux/surya2.sh document.pdf
./scripts/linux/surya2.sh png-folder --config config/custom.yml
```

PNG 不超過 10 張時，結果直接位於 `output/MMDDHHmm_surya2/`。超過 10 張時，input PNG 會依 natural order 移入 `1/、2/…`，每批 10 張，並循序執行：

```text
output/MMDDHHmm_surya2/
├─ 1/
├─ 2/
└─ 3/
```

PDF 會先 render：

```text
output/MMDDHHmm_surya2/
├─ rendered_png/
└─ result/                 # 不超過 10 頁
```

超過 10 頁時，`rendered_png/` 與 result root 都使用相同數字 batch folders。每個 result folder 包含：

```text
results.json
assets/crops/
assets/overlays/
assets/index.json
metadata/summary.json
metadata/samples.csv
command.json
environment.json
status.json
stdout.log
stderr.log
run.log
events.jsonl
```

既有 batch folder 必須從 `1/` 連續編號；每個 folder 可包含 1–10 張。重新執行會全部重跑並建立新的 timestamp output。自動分批仍以每批 10 張切分，最後一批可不足 10 張。

---
### Marker

```bash
./scripts/linux/marker.sh document.pdf
./scripts/linux/marker.sh png-folder
./scripts/linux/marker.sh document.pdf --config config/custom.yml
```

Marker 接受單一 PDF 或僅含第一層 PNG 的 folder。PNG folder 會依 natural order 轉成保留於 output 的 `input.image-only.pdf`，再交由 Marker 分析。除了官方 JSON、Markdown 與原生擷取圖片外，`result/` 保存 Marker 兩個原始 Document 階段；`block_provenance.json` 保存兩階段的 `text_extraction_method`，並將 `surya` 標示為 `ocr`：

```text
output/MMDDHHmm_marker/
├─ result.json
├─ result.md
├─ result_meta.json
├─ result/
│  ├─ DocumentBuilder.json
│  └─ PdfConverter.build_document.json
├─ block_provenance.json
├─ input.image-only.pdf       # 僅 PNG folder 輸入
├─ input_manifest.json        # 僅 PNG folder 輸入
├─ <Marker 原生圖片>
├─ metadata/
├─ command.json
├─ environment.json
├─ status.json
├─ stdout.log
├─ stderr.log
├─ run.log
└─ events.jsonl
```

Marker 預設固定使用 `balanced` mode，並透過 `llama.cpp` 的 `llama-server` 執行 Surya VLM；不啟用額外 LLM、強制 OCR、額外 crop 或 embedding normalization。

---
### Qwen3VL embedding

```bash
./scripts/linux/qwen3vl.sh output/MMDDHHmm_surya2
./scripts/linux/qwen3vl.sh output/MMDDHHmm_surya2/1/assets/index.json --config config/local.yml
```

接受單一 Surya `assets/index.json`、單批 run 或數字 batch run。OCR 文字非空時只建立 `text_vector`；文字為空且 crop 可讀時才建立 `image_vector` 並複製 crop：

```text
output/MMDDHHmm_qwen3vl/knowledge_base/
├─ manifest.json
├─ records.jsonl
├─ vectors/
│  ├─ text.npy
│  └─ image.npy
└─ crops/
```

模型與 runtime 設定在 `config/embedding.yml`，可由 `config/local.yml` 或 `--config` 覆寫。`HF_TOKEN`、`HF_HOME` 等主機值由 shell／deployment environment 注入，不寫入 YAML。

## Output naming

Run folder 使用本機時間 `MMDDHHmm_<mode>`。同分鐘、同 mode 的後續 run 依序使用 `_02`、`_03`。

## Configuration

- `config/default.yml`：output root、render DPI、heartbeat、metadata sampling 與 logging。
- `config/surya2.yml`：Surya environment、version 與實際 native command。
- `config/marker.yml`：Marker environment、version 與 worker command。
- `config/embedding.yml`：embedding mode、model adapter、runtime 與 preprocessing。
- `--config` 指定的 YAML 最後套用，可覆蓋以上設定。

Batch size 固定為 10，不開放調整。
