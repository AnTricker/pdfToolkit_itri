from pathlib import Path

from PIL import Image

import digital_pdf_toolkit.workflow as workflow
from digital_pdf_toolkit.cli import build_parser
from digital_pdf_toolkit.io import read_json
from digital_pdf_toolkit.page_sets import load_page_set
from digital_pdf_toolkit.tool_runner import resolve_analysis_pages


def _config() -> dict:
    return {"project": {"schema_version": "0.2", "output_root": "output"}, "logging": {"redact_keys": []}}


def test_pages_create_maps_natural_sorted_external_pngs_and_skips_broken(tmp_path: Path, monkeypatch) -> None:
    input_root = tmp_path / "scans"
    input_root.mkdir()
    Image.new("RGB", (30, 40), "blue").save(input_root / "page10.png")
    Image.new("RGB", (10, 20), "red").save(input_root / "page2.png")
    (input_root / "page3.png").write_bytes(b"broken")
    monkeypatch.setattr(workflow, "_config", lambda toolkit_root: _config())

    args = build_parser().parse_args(["pages", "create", str(input_root)])
    assert args.input == input_root
    document_root, page_set_id, result = workflow.create_pages(tmp_path, input_root)

    assert [Path(value["source_path"]).name for value in result["page_values"]] == ["page2.png", "page10.png"]
    assert len(result["failures"]) == 1
    manifest = read_json(document_root / "manifest.json")
    page_set = read_json(document_root / manifest["page_sets"][page_set_id])
    short_id = page_set_id.partition(":")[2]
    _, short_page_set = load_page_set(document_root, manifest, short_id)
    assert short_page_set["page_set_id"] == page_set_id
    assert page_set["storage"] == "external"
    assert [Path(page["path"]).name for page in page_set["pages"]] == ["page2.png", "page10.png"]
    assert all(Path(page["path"]).is_absolute() for page in page_set["pages"])
    assert resolve_analysis_pages(document_root, page_set) == [input_root / "page2.png", input_root / "page10.png"]


def test_external_page_set_rejects_changed_referenced_file(tmp_path: Path, monkeypatch) -> None:
    input_root = tmp_path / "scans"
    input_root.mkdir()
    source = input_root / "page1.png"
    Image.new("RGB", (10, 20), "red").save(source)
    monkeypatch.setattr(workflow, "_config", lambda toolkit_root: _config())
    document_root, page_set_id, _ = workflow.create_pages(tmp_path, input_root)
    manifest = read_json(document_root / "manifest.json")
    page_set = read_json(document_root / manifest["page_sets"][page_set_id])
    Image.new("RGB", (10, 20), "blue").save(source)

    try:
        resolve_analysis_pages(document_root, page_set)
    except ValueError as exc:
        assert "checksum changed" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("changed external image should be rejected")
