from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from digital_pdf_toolkit.config import load_config
from digital_pdf_toolkit.embedding import (
    _cluster_visual_candidates,
    _representative,
    _visual_match,
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
    Image.new("RGB", (8, 4), "red").save(crops / "skipped.png")
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
            "visual_dedup": {
                "enabled": True,
                "hash_size": 8,
                "resize": 32,
                "hamming_threshold": 6,
                "aspect_ratio_tolerance": 0.05,
                "min_distinct_pages": 3,
            },
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
    records, warnings, stats = prepare_records([index], _config()["embedding_preprocess"])
    assert len(records) == 7
    assert len(warnings) == 1
    assert stats == {
        "visual_candidates": 2,
        "visual_clusters": 2,
        "aggregate_visual_clusters": 0,
        "deduplicated_image_regions": 0,
    }
    assert [record["id"] for record in records] == [
        record["id"] for record in prepare_records([index], _config()["embedding_preprocess"])[0]
    ]

    result = build_knowledge_base(run, tmp_path / "output", _config(), FakeEmbedder())
    manifest = json.loads((result / "manifest.json").read_text(encoding="utf-8"))
    output_records = [json.loads(line) for line in (result / "records.jsonl").read_text(encoding="utf-8").splitlines()]
    assert manifest["counts"] == {
        "records": 7,
        "text_vectors": 4,
        "image_vectors": 2,
        "provenance_only": 1,
        "warnings": 1,
        "visual_candidates": 2,
        "visual_clusters": 2,
        "aggregate_visual_clusters": 0,
        "deduplicated_image_regions": 0,
    }
    assert np.load(result / "vectors" / "text.npy").shape == (4, 3)
    assert np.load(result / "vectors" / "image.npy").shape == (2, 3)
    assert sorted(path.name for path in (result / "crops").iterdir()) == [
        "image-0.png", "skipped-0.png",
    ]
    assert all(record["metadata"]["heading_path"] == ["1. Safety"] for record in output_records if record["metadata"]["scope"] == "page")
    table = next(record for record in output_records if record["metadata"]["types"] == ["table"])
    assert table["vector_ref"]["kind"] == "text_vector"
    assert "table-0.png" not in {path.name for path in (result / "crops").iterdir()}
    root = next(record for record in output_records if record["metadata"]["scope"] == "document_root")
    assert root["metadata"]["region_ids"] == ["header-0", "header-1"]
    assert root["metadata"]["page_indexes"] == [0, 1]
    skipped = next(record for record in output_records if "skipped-0" in record["metadata"]["region_ids"])
    assert skipped["vector_ref"]["kind"] == "image_vector"
    assert skipped["metadata"]["skipped"] is True


def test_three_page_visual_dedup_preserves_sources_and_one_crop(tmp_path: Path) -> None:
    run = tmp_path / "surya"
    assets = run / "assets"
    crops = assets / "crops"
    crops.mkdir(parents=True)
    source = Image.new("RGB", (24, 24), "white")
    pixels = source.load()
    for offset in range(5, 19):
        pixels[offset, offset] = (0, 0, 0)
        pixels[23 - offset, offset] = (0, 0, 0)
    regions = {}
    for page in range(3):
        filename = f"logo-{page}.png"
        source.save(crops / filename)
        regions[f"logo-{page}"] = _region(
            page,
            "picture",
            "",
            page + 2,
            f"assets/crops/{filename}",
            skipped=True,
            raw_label="Picture",
            confidence=0.5 + page / 10,
        )
    index = assets / "index.json"
    index.write_text(json.dumps({"tool": "surya", "regions": regions}), encoding="utf-8")

    result = build_knowledge_base(run, tmp_path / "output", _config(), FakeEmbedder())
    manifest = json.loads((result / "manifest.json").read_text(encoding="utf-8"))
    records = [json.loads(line) for line in (result / "records.jsonl").read_text(encoding="utf-8").splitlines()]

    assert len(records) == 1
    record = records[0]
    assert record["metadata"]["scope"] == "document_root"
    assert record["metadata"]["region_ids"] == ["logo-0", "logo-1", "logo-2"]
    assert record["metadata"]["page_indexes"] == [0, 1, 2]
    assert record["metadata"]["representative_region_id"] == "logo-0"
    assert record["metadata"]["visual_dedup"]["cluster_size"] == 3
    assert record["metadata"]["visual_dedup"]["distinct_page_count"] == 3
    assert [item["hamming_distance_to_representative"] for item in record["metadata"]["source_regions"]] == [0, 0, 0]
    assert all(item["skipped"] is True for item in record["metadata"]["source_regions"])
    assert all(
        {
            "region_id", "page_index", "reading_order", "type", "raw_label",
            "confidence", "skipped", "error", "crop", "source_provenance",
            "phash", "hamming_distance_to_representative",
        } <= item.keys()
        for item in record["metadata"]["source_regions"]
    )
    assert [path.name for path in (result / "crops").iterdir()] == ["logo-0.png"]
    assert np.load(result / "vectors" / "image.npy").shape == (1, 3)
    assert manifest["counts"]["visual_candidates"] == 3
    assert manifest["counts"]["aggregate_visual_clusters"] == 1
    assert manifest["counts"]["deduplicated_image_regions"] == 2


def test_two_page_duplicate_stays_separate_and_error_is_provenance_only(tmp_path: Path) -> None:
    run = tmp_path / "surya"
    assets = run / "assets"
    crops = assets / "crops"
    crops.mkdir(parents=True)
    for name in ("repeat-0.png", "repeat-1.png", "error.png"):
        Image.new("RGB", (12, 12), "gray").save(crops / name)
    regions = {
        "repeat-0": _region(0, "picture", "", 0, "assets/crops/repeat-0.png", skipped=True),
        "repeat-1": _region(1, "picture", "", 0, "assets/crops/repeat-1.png", skipped=True),
        "error": _region(2, "picture", "", 0, "assets/crops/error.png", error="decode failed"),
    }
    index = assets / "index.json"
    index.write_text(json.dumps({"regions": regions}), encoding="utf-8")

    records, warnings, stats = prepare_records([index], _config()["embedding_preprocess"])
    assert warnings == []
    assert stats["visual_candidates"] == 2
    assert stats["aggregate_visual_clusters"] == 0
    assert len([record for record in records if record["metadata"]["route"] == "image_vector"]) == 2
    error = next(record for record in records if record["metadata"]["region_ids"] == ["error"])
    assert error["metadata"]["route"] == "provenance_only"
    assert error["metadata"]["error"] == "decode failed"


def test_visual_matching_complete_link_and_representative_order() -> None:
    settings = {
        "enabled": True,
        "hamming_threshold": 1,
        "aspect_ratio_tolerance": 0.05,
    }
    assert not _visual_match(
        {"phash": 0, "aspect_ratio": 1.0},
        {"phash": 0, "aspect_ratio": 1.1},
        settings,
    )
    assert not _visual_match(
        {"phash": 0b000, "aspect_ratio": 1.0},
        {"phash": 0b111, "aspect_ratio": 1.0},
        settings,
    )

    def candidate(
        region_id: str,
        page: int,
        phash: int,
        area: int,
        sharpness: float,
        order: int = 0,
    ) -> dict:
        return {
            "id": region_id,
            "region": {"page_index": page, "reading_order": order},
            "visual": {
                "phash": phash,
                "aspect_ratio": 1.0,
                "area": area,
                "sharpness": sharpness,
            },
        }

    first = candidate("a", 0, 0b000, 100, 1.0)
    middle = candidate("b", 1, 0b001, 100, 2.0)
    last = candidate("c", 2, 0b011, 200, 0.5)
    clusters = _cluster_visual_candidates([last, middle, first], settings)
    assert [[entry["id"] for entry in cluster] for cluster in clusters] == [["a", "b"], ["c"]]
    assert _representative([first, middle])["id"] == "b"
    assert _representative([first, last])["id"] == "c"
    assert _representative([
        candidate("late-page", 2, 0, 100, 1.0),
        candidate("early-page", 1, 0, 100, 1.0),
    ])["id"] == "early-page"
    assert _representative([
        candidate("late-order", 1, 0, 100, 1.0, order=2),
        candidate("early-order", 1, 0, 100, 1.0, order=1),
    ])["id"] == "early-order"
    assert _representative([
        candidate("z", 1, 0, 100, 1.0),
        candidate("a", 1, 0, 100, 1.0),
    ])["id"] == "a"


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
