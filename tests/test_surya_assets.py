from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from digital_pdf_toolkit.assets import build_surya_assets
from digital_pdf_toolkit.adapters.surya import SuryaRunReader
from digital_pdf_toolkit.events import EventLogger


def test_assets_map_filename_to_global_page_index(tmp_path: Path) -> None:
    source = tmp_path / "p0011.png"
    Image.new("RGB", (100, 200), "white").save(source)
    result = tmp_path / "result"
    result.mkdir()
    (result / "results.json").write_text(
        json.dumps({
            "p0011.png": [{
                "image_bbox": [0, 0, 100, 200],
                "blocks": [{
                    "label": "Text",
                    "raw_label": "Text",
                    "reading_order": 3,
                    "bbox": [10, 20, 30, 40],
                    "polygon": [[10, 20], [30, 20], [30, 40], [10, 40]],
                    "html": "mapped",
                    "confidence": 0.95,
                    "skipped": False,
                    "error": False,
                }],
            }]
        }),
        encoding="utf-8",
    )

    index = build_surya_assets(
        result,
        [{"path": str(source), "page_index": 10, "batch": "2", "batch_position": 1}],
        EventLogger(result),
    )

    region = next(iter(index["regions"].values()))
    assert region["page_index"] == 10
    assert region["reading_order"] == 3
    assert region["polygon"] == [[10, 20], [30, 20], [30, 40], [10, 40]]
    assert region["raw_label"] == "Text"
    assert region["confidence"] == 0.95
    assert region["skipped"] is False
    assert region["error"] is False
    assert region["provenance"]["entry_index"] == 0
    assert region["provenance"]["page_entry_index"] == 0
    assert region["provenance"]["block_index"] == 0
    assert index["pages"]["10"]["batch"] == "2"
    assert (result / region["exact_crop"]).is_file()
    assert (result / index["overlays"]["10"]).is_file()


def test_assets_reject_result_without_filename_mapping(tmp_path: Path) -> None:
    source = tmp_path / "page.png"
    Image.new("RGB", (10, 10), "white").save(source)
    result = tmp_path / "result"
    result.mkdir()
    (result / "results.json").write_text(
        json.dumps({"different.png": [{"image_bbox": [0, 0, 10, 10], "blocks": []}]}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="no source image mapping"):
        build_surya_assets(
            result,
            [{"path": str(source), "page_index": 0, "batch": None, "batch_position": 1}],
            EventLogger(result),
        )


def test_assets_fall_back_to_layout_position_for_reading_order(tmp_path: Path) -> None:
    source = tmp_path / "page.png"
    Image.new("RGB", (20, 20), "white").save(source)
    result = tmp_path / "result"
    result.mkdir()
    (result / "results.json").write_text(
        json.dumps({
            "page.png": [{
                "image_bbox": [0, 0, 20, 20],
                "bboxes": [{"label": "Text", "position": 4, "bbox": [1, 1, 10, 10]}],
            }]
        }),
        encoding="utf-8",
    )

    index = build_surya_assets(
        result,
        [{"path": str(source), "page_index": 0, "batch": None, "batch_position": 1}],
        EventLogger(result),
    )

    region = next(iter(index["regions"].values()))
    assert region["reading_order"] == 4


def test_surya_provenance_distinguishes_page_and_block_indices(tmp_path: Path) -> None:
    results = tmp_path / "results.json"
    results.write_text(
        json.dumps({
            "document": [
                {"image_bbox": [0, 0, 20, 20], "blocks": []},
                {"image_bbox": [0, 0, 20, 20], "blocks": [
                    {"label": "Text", "bbox": [1, 1, 10, 10]},
                    {"label": "Text", "bbox": [2, 2, 11, 11]},
                ]},
            ]
        }),
        encoding="utf-8",
    )

    regions = list(SuryaRunReader(results).regions())

    assert [region.provenance["entry_index"] for region in regions] == [1, 1]
    assert [region.provenance["page_entry_index"] for region in regions] == [1, 1]
    assert [region.provenance["block_index"] for region in regions] == [0, 1]
