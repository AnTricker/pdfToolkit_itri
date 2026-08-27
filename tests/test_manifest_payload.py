from pathlib import Path

from PIL import Image

from digital_pdf_toolkit.io import read_json, relative_to, write_json
from digital_pdf_toolkit.manifest import add_attempt, new_document_manifest, save_manifest
from digital_pdf_toolkit.page_sets import register_page_set, write_page_set
from digital_pdf_toolkit.payload import build_payload


def test_finalize_uses_analyze_attempt_page_set(tmp_path: Path) -> None:
    document_root = tmp_path / "doc-0819-1430"
    document_root.mkdir()
    config = {"project": {"schema_version": "0.2"}}
    manifest = new_document_manifest(document_root.name, config)
    producer_root = document_root / "preprocess" / "attempt-001_0819-1432"
    pages_root = producer_root / "processed_pages"
    pages_root.mkdir(parents=True)
    page_image = pages_root / "p0001.png"
    Image.new("RGB", (100, 200), "white").save(page_image)
    page_set_id, page_set_path, _ = write_page_set(document_root, producer_root, "preprocess", "attempt-001_0819-1432", [{
        "image_path": page_image, "source_index": 1, "source_path": "scan1.png",
        "source_checksum": "abc", "split_part": "single",
    }])
    register_page_set(document_root, manifest, page_set_id, page_set_path)
    analyze_root = document_root / "analyze" / "paddle" / "attempt-001_0819-1500"
    (analyze_root / "raw").mkdir(parents=True)
    write_json(analyze_root / "assets" / "index.json", {
        "regions": {"r1": {"exact_crop": "analyze/paddle/attempt-001_0819-1500/assets/crops/r1.png"}}
    })
    add_attempt(manifest, "analyze", {
        "id": "attempt-001_0819-1500", "state": "completed",
        "path": relative_to(analyze_root, document_root), "input_page_set": page_set_id,
    }, tool="paddle")
    save_manifest(document_root, manifest)

    payload_path = build_payload(document_root, manifest, "paddle", "attempt-001_0819-1500")
    payload = read_json(payload_path)

    assert payload["kind"] == "document_handoff"
    assert payload["selection"]["input_page_set"] == page_set_id
    assert payload["page_renders"] == ["preprocess/attempt-001_0819-1432/processed_pages/p0001.png"]
