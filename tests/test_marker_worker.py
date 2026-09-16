from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from digital_pdf_toolkit.marker_worker import MarkerRuntime, collect_block_provenance, convert_pdf


class FakeBlock:
    def __init__(self, block_id: str, block_type: str, page_id: int, method: str | None) -> None:
        self.id = block_id
        self.block_type = block_type
        self.page_id = page_id
        self.text_extraction_method = method


class FakeDocument:
    def __init__(self, stage: str = "built") -> None:
        self.stage = stage
        self.pages = [FakeBlock("/page/0/Page/0", "Page", 0, None)]
        self._blocks = [
            FakeBlock("/page/0/Text/1", "Text", 0, "pdftext"),
            FakeBlock("/page/0/Text/2", "Text", 0, "surya"),
        ]

    def contained_blocks(self) -> list[FakeBlock]:
        return self._blocks

    def model_dump(self, **_kwargs: object) -> dict[str, object]:
        return {
            "stage": self.stage,
            "pages": [{
                "block_id": self.pages[0].id,
                "structure": [self._blocks[0].id, self._blocks[1].id],
                "lowres_image": Image.new("RGB", (20, 30), "white"),
                "highres_image": Image.new("L", (40, 60), "white"),
            }],
        }


def test_block_provenance_preserves_marker_method_and_marks_surya_as_ocr() -> None:
    payload = collect_block_provenance(FakeDocument())

    by_id = {item["block_id"]: item for item in payload["blocks"]}
    pages_by_id = {item["block_id"]: item for item in payload["pages"]}
    assert by_id["/page/0/Text/1"]["source_kind"] == "pdftext"
    assert by_id["/page/0/Text/2"]["text_extraction_method"] == "surya"
    assert by_id["/page/0/Text/2"]["source_kind"] == "ocr"
    assert pages_by_id["/page/0/Page/0"]["source_kind"] is None


def test_convert_pdf_writes_both_raw_formats_images_and_provenance(tmp_path: Path) -> None:
    input_pdf = tmp_path / "input.pdf"
    input_pdf.write_bytes(b"placeholder")
    output_dir = tmp_path / "output"
    document = FakeDocument()

    class FakeConverter:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def build_document(self, _path: str) -> FakeDocument:
            return document

        def resolve_dependencies(self, renderer: type) -> object:
            return renderer()

    class FakeJSONRenderer:
        def __call__(self, _document: FakeDocument) -> SimpleNamespace:
            return SimpleNamespace(kind="json")

    class FakeMarkdownRenderer:
        def __call__(self, _document: FakeDocument) -> SimpleNamespace:
            return SimpleNamespace(kind="markdown")

    def fake_save_output(rendered: SimpleNamespace, destination: str, basename: str) -> None:
        root = Path(destination)
        if rendered.kind == "json":
            (root / f"{basename}.json").write_text("{}", encoding="utf-8")
        else:
            (root / f"{basename}.md").write_text("# Raw", encoding="utf-8")
            (root / "figure_0.jpeg").write_bytes(b"image")
        (root / f"{basename}_meta.json").write_text("{}", encoding="utf-8")

    def fake_build_stages(
        _converter: FakeConverter, _path: str, capture: object
    ) -> FakeDocument:
        initial = FakeDocument("DocumentBuilder")
        capture("DocumentBuilder", initial)  # type: ignore[operator]
        document.stage = "PdfConverter.build_document"
        capture("PdfConverter.build_document", document)  # type: ignore[operator]
        return document

    runtime = MarkerRuntime(
        FakeConverter,
        FakeJSONRenderer,
        FakeMarkdownRenderer,
        lambda: {},
        fake_save_output,
        fake_build_stages,
    )

    convert_pdf(input_pdf, output_dir, runtime, mode="balanced", inference_backend="llamacpp")

    assert (output_dir / "result.json").read_text(encoding="utf-8") == "{}"
    assert (output_dir / "result.md").read_text(encoding="utf-8") == "# Raw"
    assert (output_dir / "figure_0.jpeg").read_bytes() == b"image"
    initial = json.loads((output_dir / "result" / "DocumentBuilder.json").read_text(encoding="utf-8"))
    final = json.loads(
        (output_dir / "result" / "PdfConverter.build_document.json").read_text(encoding="utf-8")
    )
    assert initial["stage"] == "DocumentBuilder"
    assert final["stage"] == "PdfConverter.build_document"
    assert initial["pages"][0]["lowres_image"] == {"width": 20, "height": 30, "mode": "RGB"}
    assert initial["pages"][0]["highres_image"] == {"width": 40, "height": 60, "mode": "L"}
    provenance = json.loads((output_dir / "block_provenance.json").read_text(encoding="utf-8"))
    assert provenance["schema_version"] == 2
    assert set(provenance) == {"schema_version", "DocumentBuilder", "PdfConverter.build_document"}
    assert len(provenance["DocumentBuilder"]["pages"]) == 1
    assert len(provenance["PdfConverter.build_document"]["blocks"]) == 2
