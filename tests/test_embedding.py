from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from digital_pdf_toolkit.config import load_config
from digital_pdf_toolkit.embedding import (
    build_knowledge_base,
    discover_surya_indexes,
    parse_surya_text,
    prepare_records,
)


class FakeEmbedder:
    model_id = "fake/qwen3vl"
    revision = "test"
    dimension = 3
    dtype = "float32"
    normalize_embeddings = True

    def encode_texts(self, values: list[str]) -> np.ndarray:
        return np.asarray([[float(len(value)), 1.0, 0.0] for value in values], dtype=np.float32)

    def encode_images(self, values: list[Path]) -> np.ndarray:
        assert all(path.is_file() for path in values)
        return np.asarray([[0.0, 1.0, 1.0] for _ in values], dtype=np.float32)

    def split_text(self, value: str) -> list[str]:
        return [value]


def _region(page: int, kind: str, text: str, order: int, crop: str | None = None, **extra: object) -> dict:
    value = {
        "page_index": page,
        "type": kind,
        "text": text,
        "reading_order": order,
        "exact_crop": crop,
        "skipped": False,
        "error": False,
        "provenance": {"block_index": order},
    }
    value.update(extra)
    return value


def _fixture(tmp_path: Path) -> tuple[Path, Path]:
    run = tmp_path / "surya"
    assets = run / "assets"
    crops = assets / "crops"
    crops.mkdir(parents=True)
    Image.new("RGB", (4, 4), "white").save(crops / "text.png")
    Image.new("RGB", (4, 4), "black").save(crops / "table.png")
    Image.new("RGB", (4, 4), "blue").save(crops / "image.png")
    Image.new("RGB", (4, 4), "red").save(crops / "skipped.png")
    payload = {
        "tool": "surya",
        "regions": {
            "heading": _region(0, "sectionheader", "<h1>1. Safety</h1>", 0),
            "header-0": _region(0, "pageheader", "Manual", 1),
            "body-0": _region(0, "text", "<p>Hello &amp; world</p>", 2, "assets/crops/text.png"),
            "table-0": _region(0, "table", "<table><tr><th>A</th><th>B</th></tr><tr><td>1</td><td>2</td></tr></table>", 3, "assets/crops/table.png"),
            "image-0": _region(0, "picture", "", 4, "assets/crops/image.png"),
            "missing-0": _region(0, "unknown", "", 5),
            "skipped-0": _region(0, "picture", "", 6, "assets/crops/skipped.png", skipped=True),
            "header-1": _region(1, "pageheader", "Manual", 0),
            "body-1": _region(1, "text", "Second page", 1),
        },
    }
    index = assets / "index.json"
    index.write_text(json.dumps(payload), encoding="utf-8")
    return run, index


def _config() -> dict:
    return {
        "embedding_preprocess": {
            "text_when_nonempty": True,
            "image_when_text_empty": True,
            "persist_headings_across_pages": True,
            "aggregate_repeated_regions": True,
            "independent_text_types": ["table", "form"],
        }
    }


def test_html_preprocessing_preserves_table_and_list_semantics() -> None:
    plain, structured = parse_surya_text(
        "<p>A &amp; B</p><ul><li>first</li><li>second</li></ul>"
        "<table><tr><th>X</th><th>Y</th></tr><tr><td>1</td><td>2</td></tr></table>"
    )
    assert "A & B" in plain
    assert "- first" in structured
    assert "| X | Y |" in structured


def test_routing_dedup_heading_and_vector_rows(tmp_path: Path) -> None:
    run, index = _fixture(tmp_path)
    records, warnings = prepare_records([index], _config()["embedding_preprocess"])
    assert len(records) == 7
    assert len(warnings) == 1
    assert [record["id"] for record in records] == [
        record["id"] for record in prepare_records([index], _config()["embedding_preprocess"])[0]
    ]

    result = build_knowledge_base(run, tmp_path / "output", _config(), FakeEmbedder())
    manifest = json.loads((result / "manifest.json").read_text(encoding="utf-8"))
    output_records = [json.loads(line) for line in (result / "records.jsonl").read_text(encoding="utf-8").splitlines()]
    assert manifest["counts"] == {
        "records": 7,
        "text_vectors": 4,
        "image_vectors": 1,
        "provenance_only": 2,
        "warnings": 1,
    }
    assert np.load(result / "vectors" / "text.npy").shape == (4, 3)
    assert np.load(result / "vectors" / "image.npy").shape == (1, 3)
    assert [path.name for path in (result / "crops").iterdir()] == ["image-0.png"]
    assert all(record["metadata"]["heading_path"] == ["1. Safety"] for record in output_records if record["metadata"]["scope"] == "page")
    table = next(record for record in output_records if record["metadata"]["types"] == ["table"])
    assert table["vector_ref"]["kind"] == "text_vector"
    assert "table-0.png" not in {path.name for path in (result / "crops").iterdir()}
    root = next(record for record in output_records if record["metadata"]["scope"] == "document_root")
    assert root["metadata"]["region_ids"] == ["header-0", "header-1"]
    assert root["metadata"]["page_indexes"] == [0, 1]


def test_numeric_batch_discovery_and_config_override(tmp_path: Path) -> None:
    root = tmp_path / "run"
    expected = []
    for name in ("1", "2"):
        path = root / name / "assets" / "index.json"
        path.parent.mkdir(parents=True)
        path.write_text('{"regions": {}}', encoding="utf-8")
        expected.append(path.resolve())
    assert discover_surya_indexes(root) == expected

    project_root = Path(__file__).resolve().parents[1]
    override = tmp_path / "override.yml"
    override.write_text("embedding:\n  modes:\n    qwen3vl:\n      runtime:\n        batch_size: 2\n", encoding="utf-8")
    config = load_config(project_root, override)
    assert config["embedding"]["modes"]["qwen3vl"]["runtime"]["batch_size"] == 2
    assert config["embedding"]["modes"]["qwen3vl"]["model_id"] == "Qwen/Qwen3-VL-Embedding-8B"


def test_embedding_failure_does_not_publish_manifest(tmp_path: Path) -> None:
    run, _ = _fixture(tmp_path)

    class BrokenEmbedder(FakeEmbedder):
        def encode_texts(self, values: list[str]) -> np.ndarray:
            raise RuntimeError("expected test failure")

    output = tmp_path / "failed"
    with pytest.raises(RuntimeError, match="expected test failure"):
        build_knowledge_base(run, output, _config(), BrokenEmbedder())
    assert not (output / "knowledge_base" / "manifest.json").exists()
