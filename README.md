# Digital PDF Toolkit

本專案提供三個獨立 command：HEIC 轉 PNG、Digital PDF native extraction，以及具備自動分批與效能紀錄的 Surya OCR。

## Setup

```bash
./scripts/linux/setup.sh
```

```cmd
scripts\windows\setup.cmd
```

只建立／更新 `digital-pdf-core` 與 `digital-pdf-surya`。

## Commands

### HEIC to PNG

```bash
./scripts/linux/heic-to-png.sh phone-photos
./scripts/linux/heic-to-png.sh phone-photos --output converted-pages
```

預設輸出至 `<input>/scan_source_pages/`。只處理 input root 的 `.heic/.heif`，依 natural filename order 產生 `p0001.png...`。

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

既有 batch folder 必須從 `1/` 連續編號；除最後一批外恰為 10 張。重新執行會全部重跑並建立新的 timestamp output。

## Output naming

Run folder 使用本機時間 `MMDDHHmm_<mode>`。同分鐘、同 mode 的後續 run 依序使用 `_02`、`_03`。

## Configuration

- `config/default.yml`：output root、render DPI、heartbeat、metadata sampling 與 logging。
- `config/surya2.yml`：Surya environment、version 與實際 native command。
- `--config` 指定的 YAML 最後套用，可覆蓋以上設定。

Batch size 固定為 10，不開放調整。
