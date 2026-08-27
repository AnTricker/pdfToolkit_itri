from pathlib import Path

from PIL import Image

from digital_pdf_toolkit.resolution import optimize_resolution


def test_resolution_upscales_without_downsampling(tmp_path: Path) -> None:
    document_root = tmp_path / "doc"
    source_root = document_root / "source"
    source_root.mkdir(parents=True)
    low = source_root / "p0001.png"
    high = source_root / "p0002.png"
    Image.new("RGB", (827, 1169), "white").save(low)
    Image.new("RGB", (3308, 4676), "white").save(high)
    parent = {
        "page_set_id": "preprocess:attempt-001_0819-1432",
        "pages": [
            {"page_id": "p0001", "path": "source/p0001.png", "source_index": 1, "source_path": "a.png", "source_checksum": "a", "split_part": "single"},
            {"page_id": "p0002", "path": "source/p0002.png", "source_index": 2, "source_path": "b.png", "source_checksum": "b", "split_part": "single"},
        ],
    }
    attempt_root = document_root / "resolution" / "attempt"
    attempt_root.mkdir(parents=True)

    result = optimize_resolution(document_root, parent, attempt_root, 300)

    with Image.open(result["page_values"][0]["image_path"]) as image:
        assert image.width > 827
    with Image.open(result["page_values"][1]["image_path"]) as image:
        assert image.size == (3308, 4676)
    assert [page["action"] for page in result["pages"]] == ["upscaled", "unchanged"]
