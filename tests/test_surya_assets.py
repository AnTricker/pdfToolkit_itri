from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from digital_pdf_toolkit.assets import build_surya_assets
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
                "blocks": [{"label": "Text", "bbox": [10, 20, 30, 40], "html": "mapped"}],
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
