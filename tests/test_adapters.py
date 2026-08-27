import json
from pathlib import Path

import pytest
from PIL import Image

from digital_pdf_toolkit.adapters import create_reader
from digital_pdf_toolkit.assets import build_assets
from digital_pdf_toolkit.events import EventLogger


FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize("tool", ["paddle", "mineru", "surya"])
def test_reader_exposes_interoperable_operations(tool: str) -> None:
    reader = create_reader(tool, FIXTURES / tool)
    regions = list(reader.regions(0))

    assert reader.pages() == [0]
    assert len(regions) == 1
    assert regions[0].type == "table"
    assert reader.text(regions[0].id) == "A1"
    assert reader.provenance(regions[0].id)["tool"] == tool


def test_unknown_reader_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unknown tool"):
        create_reader("unknown", FIXTURES)


def test_surya_reader_maps_source_page_to_page_set_index(tmp_path: Path) -> None:
    (tmp_path / "results.json").write_text(
        """{
            "p0141": [{
                "image_bbox": [0, 0, 100, 200],
                "blocks": [{
                    "label": "Text",
                    "bbox": [10, 20, 30, 40],
                    "html": "<p>mapped</p>"
                }]
            }]
        }""",
        encoding="utf-8",
    )

    reader = create_reader("surya", tmp_path)
    reader = reader.with_page_mapping({"p0141": 0})  # type: ignore[attr-defined]

    assert reader.pages() == [0]
    assert [region.text for region in reader.regions(0)] == ["<p>mapped</p>"]


def test_surya_assets_use_raw_filename_for_mapping_and_overlay(tmp_path: Path) -> None:
    source_root = tmp_path / "input" / "15"
    source_root.mkdir(parents=True)
    source_path = source_root / "p0141.png"
    Image.new("RGB", (100, 200), "white").save(source_path)

    attempt_path = Path("analyze/surya/attempt-001")
    raw_root = tmp_path / attempt_path / "raw" / "15"
    raw_root.mkdir(parents=True)
    (raw_root / "results.json").write_text(
        json.dumps(
            {
                "p0141": [
                    {
                        "image_bbox": [0, 0, 100, 200],
                        "blocks": [
                            {
                                "label": "Text",
                                "bbox": [10, 20, 30, 40],
                                "html": "<p>mapped</p>",
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    result = build_assets(
        "surya",
        {"id": "attempt-001", "state": "completed", "path": str(attempt_path)},
        tmp_path,
        {
            "page_set_id": "pages:attempt-001",
            "pages": [
                {
                    "page_index": 0,
                    "source_index": 1,
                    "path": str(source_path.relative_to(tmp_path)),
                    "width_px": 100,
                    "height_px": 200,
                }
            ],
        },
        EventLogger(tmp_path),
    )

    assert result is not None
    assert len(result["regions"]) == 1
    region = next(iter(result["regions"].values()))
    assert region["page_index"] == 0
    assert (tmp_path / region["exact_crop"]).is_file()
    assert result["overlays"]["0"].endswith("overlays/p0141.png")
    assert (tmp_path / result["overlays"]["0"]).is_file()
