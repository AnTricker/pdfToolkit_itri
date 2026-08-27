from __future__ import annotations

import re
from pathlib import Path

import pytest
from PIL import Image

from digital_pdf_toolkit import runs
from digital_pdf_toolkit.process import ProcessResult


def _png(path: Path) -> None:
    Image.new("RGB", (20, 30), "white").save(path)


def _config(output_root: Path) -> dict:
    return {
        "project": {"output_root": str(output_root), "render_dpi": 150, "heartbeat_seconds": 30},
        "metadata": {"sampling_interval_seconds": 1.0},
        "conda": {"core_env": "digital-pdf-core", "surya_env": "digital-pdf-surya"},
        "logging": {"redact_keys": []},
        "surya2": {
            "environment": "digital-pdf-surya", "version": "test",
            "command": ["surya_ocr", "{input_dir}", "--output_dir", "{output_dir}"],
        },
    }


def test_allocate_run_root_uses_mode_and_collision_suffix(tmp_path: Path) -> None:
    config = _config(tmp_path / "output")
    first = runs.allocate_run_root(tmp_path, config, "surya2")
    second = runs.allocate_run_root(tmp_path, config, "surya2")

    assert re.fullmatch(r"\d{8}_surya2", first.name)
    assert second.name == first.name + "_02"


def test_prepare_png_batches_moves_natural_order_into_tens(tmp_path: Path) -> None:
    for number in [10, 2, 1, 11, 3, 4, 5, 6, 7, 8, 9]:
        _png(tmp_path / f"page{number}.png")

    batches = runs.prepare_png_batches(tmp_path)

    assert [batch for batch, _ in batches] == ["1", "2"]
    assert [Path(item["path"]).name for item in batches[0][1]] == [f"page{i}.png" for i in range(1, 11)]
    assert [item["page_index"] for _, images in batches for item in images] == list(range(11))
    assert len(list((tmp_path / "1").glob("*.png"))) == 10
    assert len(list((tmp_path / "2").glob("*.png"))) == 1


def test_existing_batches_are_strictly_validated(tmp_path: Path) -> None:
    first = tmp_path / "1"
    third = tmp_path / "3"
    first.mkdir()
    third.mkdir()
    for index in range(10):
        _png(first / f"p{index}.png")
    _png(third / "p10.png")

    with pytest.raises(ValueError, match="consecutively"):
        runs.prepare_png_batches(tmp_path)


def test_mixed_top_level_and_numeric_batches_are_rejected(tmp_path: Path) -> None:
    _png(tmp_path / "page.png")
    (tmp_path / "1").mkdir()

    with pytest.raises(ValueError, match="cannot mix"):
        runs.prepare_png_batches(tmp_path)


def test_batched_surya_continues_after_failure_without_running_external_tool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    input_root = tmp_path / "input"
    input_root.mkdir()
    for index in range(11):
        _png(input_root / f"p{index + 1:04d}.png")
    config = _config(tmp_path / "output")
    monkeypatch.setattr(runs, "load_config", lambda *_: config)
    called: list[str] = []

    def fake_batch(_root: Path, result_root: Path, _images: list[dict], _config: dict) -> bool:
        result_root.mkdir(parents=True)
        called.append(result_root.name)
        return result_root.name != "1"

    monkeypatch.setattr(runs, "run_surya_batch", fake_batch)

    output, failed = runs.run_surya2(tmp_path, input_root)

    assert called == ["1", "2"]
    assert failed == ["1"]
    assert sorted(path.name for path in output.iterdir()) == ["1", "2"]
    terminal = capsys.readouterr().out
    assert "Completed: 1 batches" in terminal
    assert "Failed: 1 batches (1)" in terminal


def test_pdf_batch_tree_is_mirrored_without_real_render_or_surya(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = tmp_path / "document.pdf"
    pdf.write_bytes(b"placeholder")
    config = _config(tmp_path / "output")
    monkeypatch.setattr(runs, "load_config", lambda *_: config)

    def fake_render(_pdf: Path, target: Path, _dpi: int) -> list[Path]:
        target.mkdir()
        outputs = []
        for index in range(11):
            path = target / f"p{index + 1:04d}.png"
            _png(path)
            outputs.append(path)
        return outputs

    monkeypatch.setattr(runs, "render_pdf", fake_render)
    monkeypatch.setattr(
        runs,
        "run_surya_batch",
        lambda _root, result_root, _images, _config: (result_root.mkdir(parents=True) or True),
    )

    output, failed = runs.run_surya2(tmp_path, pdf)

    assert failed == []
    assert sorted(path.name for path in (output / "rendered_png").iterdir()) == ["1", "2"]
    assert (output / "1").is_dir()
    assert (output / "2").is_dir()


def test_extract_orchestration_is_flat_without_real_pdf_processing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = tmp_path / "document.pdf"
    pdf.write_bytes(b"placeholder")
    config = _config(tmp_path / "output")
    monkeypatch.setattr(runs, "load_config", lambda *_: config)

    def fake_extract(_pdf: Path, root: Path, _dpi: int, _logger: object) -> dict:
        (root / "pages").mkdir()
        (root / "page_renders").mkdir()
        (root / "embedded_images").mkdir()
        (root / "document.json").write_text("{}", encoding="utf-8")
        return {}

    monkeypatch.setattr(runs, "extract_document", fake_extract)

    output = runs.run_extract(tmp_path, pdf)

    assert (output / "document.json").is_file()
    assert not (output / "observed").exists()
    assert not (output / "metadata").exists()
    assert not (output / "manifest.json").exists()


def test_surya_batch_normalizes_results_and_writes_assets_metadata_and_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_root = tmp_path / "input"
    source_root.mkdir()
    source = source_root / "page1.png"
    _png(source)
    result_root = tmp_path / "result"
    config = _config(tmp_path / "output")

    def fake_process(_command: list[str], _cwd: Path, _stdout: Path, _stderr: Path, _logger: object, _heartbeat: int, _interval: float) -> ProcessResult:
        nested = result_root / "page1"
        nested.mkdir(parents=True)
        (nested / "results.json").write_text(
            '{"page1.png": [{"image_bbox": [0, 0, 20, 30], "blocks": []}]}',
            encoding="utf-8",
        )
        return ProcessResult(0, 0.25, "start", "finish", [], ["no hardware sampler"])

    monkeypatch.setattr(runs, "run_process", fake_process)

    succeeded = runs.run_surya_batch(
        tmp_path,
        result_root,
        [{"path": str(source), "page_index": 0, "batch": None, "batch_position": 1}],
        config,
    )

    assert succeeded is True
    assert (result_root / "results.json").is_file()
    assert (result_root / "assets" / "index.json").is_file()
    assert (result_root / "metadata" / "summary.json").is_file()
    assert (result_root / "metadata" / "samples.csv").is_file()
    assert '"state": "completed"' in (result_root / "status.json").read_text(encoding="utf-8")
