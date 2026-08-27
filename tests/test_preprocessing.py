import shutil
import sys
import types
from pathlib import Path

import numpy as np
from PIL import Image

from digital_pdf_toolkit.preprocessing import preprocess_document
from digital_pdf_toolkit.paddle_preprocess_worker import main as paddle_worker_main
from digital_pdf_toolkit.page_sets import write_page_set


def test_png_sources_are_natural_sorted_partial_and_reorderable(tmp_path: Path) -> None:
    input_root = tmp_path / "input"
    input_root.mkdir()
    Image.new("RGB", (120, 240), "white").save(input_root / "page10.png")
    Image.new("RGB", (100, 200), "white").save(input_root / "page2.png")
    (input_root / "page3.png").write_bytes(b"not a png")
    attempt_root = tmp_path / "attempt"
    attempt_root.mkdir()
    config = {
        "project": {"render_dpi": 150},
        "preprocessing": {"custom_steps": ["qa"]},
        "resolution": {"low_dpi_warning": 150},
    }

    result = preprocess_document(
        tmp_path, input_root, attempt_root, "custom", config,
        {"page_order": [{"source_index": 3, "split_part": "single"}]},
    )

    assert [Path(value["source_path"]).name for value in result["page_values"]] == ["page10.png", "page2.png"]
    assert [value["image_path"].name for value in result["page_values"]] == ["p0001.png", "p0002.png"]
    assert len(result["failures"]) == 1
    assert not (attempt_root / "scan_source_pages").exists()


def test_preprocessing_zero_pages_is_represented_without_fake_output(tmp_path: Path) -> None:
    input_root = tmp_path / "input"
    input_root.mkdir()
    (input_root / "page1.png").write_bytes(b"broken")
    attempt_root = tmp_path / "attempt"
    attempt_root.mkdir()
    config = {
        "project": {"render_dpi": 150},
        "preprocessing": {"custom_steps": ["qa"]},
        "resolution": {"low_dpi_warning": 150},
    }
    result = preprocess_document(tmp_path, input_root, attempt_root, "custom", config)
    assert result["output_pages"] == 0
    assert result["page_values"] == []
    assert len(result["failures"]) == 1


def test_paddle_worker_loads_only_requested_module(tmp_path: Path, monkeypatch) -> None:
    input_root = tmp_path / "input"
    output_root = tmp_path / "output"
    input_root.mkdir()
    source = input_root / "p0001.png"
    Image.new("RGB", (20, 30), "white").save(source)
    captured: dict[str, object] = {}

    visualization_used = False

    class FakeResult:
        def __getitem__(self, key: str):
            if key != "output_img":
                raise KeyError(key)
            output = np.zeros((4, 6, 3), dtype=np.uint8)
            output[:, :] = [0, 0, 255]  # BGR red
            return output

        def save_to_img(self, save_path: str) -> None:
            nonlocal visualization_used
            visualization_used = True
            Image.new("RGB", (100, 10), "black").save(save_path)

    class FakeDocPreprocessor:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def predict(self, input: str, **kwargs):
            return [FakeResult()]

    paddleocr = types.ModuleType("paddleocr")
    paddleocr.DocPreprocessor = FakeDocPreprocessor
    monkeypatch.setitem(sys.modules, "paddleocr", paddleocr)
    monkeypatch.setattr(sys, "argv", [
        "paddle_preprocess_worker", "--input-dir", str(input_root),
        "--output-dir", str(output_root), "--mode", "dewarp",
        "--report", str(tmp_path / "report.json"),
    ])

    assert paddle_worker_main() == 0
    assert captured == {
        "use_doc_orientation_classify": False,
        "use_doc_unwarping": True,
    }
    assert visualization_used is False
    with Image.open(output_root / "p0001.png") as output:
        assert output.size == (6, 4)
        assert output.getpixel((0, 0)) == (255, 0, 0)


def test_paddle_working_size_and_stage_artifacts_are_persisted(tmp_path: Path) -> None:
    input_root = tmp_path / "input"
    input_root.mkdir()
    Image.new("RGB", (4000, 2000), "white").save(input_root / "page1.png")
    attempt_root = tmp_path / "attempt"
    attempt_root.mkdir()
    config = {
        "project": {"render_dpi": 150},
        "preprocessing": {"custom_steps": ["orientation"], "paddle_max_long_edge": 1000},
        "resolution": {"low_dpi_warning": 150},
        "conda": {"paddle_env": "unused"},
    }

    def fake_runner(toolkit_root, input_dir, output_dir, mode, environment):
        output_dir.mkdir(exist_ok=True)
        completed = []
        for source in input_dir.glob("*.png"):
            with Image.open(source) as image:
                assert max(image.size) == 1000
            shutil.copyfile(source, output_dir / source.name)
            completed.append(source.name)
        return {
            "completed": completed, "failed": [], "command_exit_code": 0,
            "_stdout": "worker output", "_stderr": "",
        }

    result = preprocess_document(
        tmp_path, input_root, attempt_root, "custom", config, paddle_runner=fake_runner
    )

    with Image.open(result["page_values"][0]["image_path"]) as output:
        assert output.size == (1000, 500)
    assert (attempt_root / "orientation-report.json").exists()
    assert (attempt_root / "orientation-stdout.log").read_text(encoding="utf-8") == "worker output"
    assert (attempt_root / "orientation-stderr.log").read_text(encoding="utf-8") == ""


def test_geometry_qa_excludes_extreme_page_before_dpi_and_page_set(tmp_path: Path) -> None:
    input_root = tmp_path / "input"
    input_root.mkdir()
    Image.new("RGB", (100, 200), "white").save(input_root / "page1.png")
    Image.new("RGB", (100, 200), "white").save(input_root / "page2.png")
    attempt_root = tmp_path / "attempt"
    attempt_root.mkdir()
    config = {
        "project": {"render_dpi": 150},
        "preprocessing": {"custom_steps": ["orientation"], "paddle_max_long_edge": 3000},
        "resolution": {"low_dpi_warning": 150},
        "conda": {"paddle_env": "unused"},
    }

    def fake_runner(toolkit_root, input_dir, output_dir, mode, environment):
        completed = []
        for source in input_dir.glob("*.png"):
            target = output_dir / source.name
            if source.name.startswith("s0002-"):
                Image.new("RGB", (1000, 50), "white").save(target)
            else:
                Image.new("RGB", (200, 100), "white").save(target)
            completed.append(source.name)
        return {"completed": completed, "failed": [], "command_exit_code": 0}

    result = preprocess_document(
        tmp_path, input_root, attempt_root, "custom", config, paddle_runner=fake_runner
    )

    assert result["output_pages"] == 1
    assert [item["status"] for item in result["page_qa"]] == ["passed", "failed"]
    failed_qa = result["page_qa"][1]
    assert set(failed_qa["violations"]) == {"long_edge_growth", "aspect_growth"}
    assert "dpi" not in failed_qa
    assert result["failures"][0]["stage"] == "qa"
    _, _, page_set = write_page_set(
        tmp_path, attempt_root, "preprocess", "attempt-001_test", result["page_values"]
    )
    assert page_set["page_count"] == 1
    assert page_set["pages"][0]["source_index"] == 1


def test_geometry_qa_all_failed_produces_zero_pages(tmp_path: Path) -> None:
    input_root = tmp_path / "input"
    input_root.mkdir()
    Image.new("RGB", (100, 200), "white").save(input_root / "page1.png")
    attempt_root = tmp_path / "attempt"
    attempt_root.mkdir()
    config = {
        "project": {"render_dpi": 150},
        "preprocessing": {"custom_steps": ["dewarp"]},
        "resolution": {"low_dpi_warning": 150},
        "conda": {"paddle_env": "unused"},
    }

    def fake_runner(toolkit_root, input_dir, output_dir, mode, environment):
        names = []
        for source in input_dir.glob("*.png"):
            Image.new("RGB", (1000, 50), "white").save(output_dir / source.name)
            names.append(source.name)
        return {"completed": names, "failed": [], "command_exit_code": 0}

    result = preprocess_document(
        tmp_path, input_root, attempt_root, "custom", config, paddle_runner=fake_runner
    )

    assert result["output_pages"] == 0
    assert result["page_values"] == []
    assert result["page_qa"][0]["status"] == "failed"
    assert result["failures"][0]["stage"] == "qa"
