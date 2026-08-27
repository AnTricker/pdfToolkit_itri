# Deferred Options

下列能力刻意不納入 MVP。加入前應先以實際 corpus、硬體與 downstream 需求重新評估。

- **Parallel execution**：三套大型工具目前 sequential 執行，避免 GPU／RAM 競爭。
- **Page/region selection**：MVP 僅支援每份 PDF 選一個 tool attempt。
- **Context crop**：僅保存 exact crop；下游可依 bbox 按需擴張。
- **HTML review UI**：MVP 直接檢查 JSON、overlay 與 crop。
- **Tool fusion/scoring**：不投票、不平均 bbox、不建立人工 confidence score。
- **Additional tools**：Docling、Marker、Camelot、GMFT、Table Transformer 等先不整合。
- **Commercial licensing**：MVP 接受開源／copyleft 工具；商用前需重新檢查 code 與 model licenses。
- **VLM/embedding integration**：payload 僅為靜態 handoff，不執行模型或建立 vectors。
- **Semantic linking**：diagram node/edge、caption/reference 與跨頁語意關係留給 downstream。
- **Raw font forensics**：不解析 CMap、raw glyph code 或將公式還原為 LaTeX。

