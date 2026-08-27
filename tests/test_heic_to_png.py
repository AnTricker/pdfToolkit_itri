from __future__ import annotations

import sys
import types
from pathlib import Path

from PIL import Image

from digital_pdf_toolkit.heic_to_png import convert_folder


def _fake_heif_plugin(monkeypatch) -> None:
    module = types.ModuleType("pillow_heif")
    module.register_heif_opener = lambda: None
    monkeypatch.setitem(sys.modules, "pillow_heif", module)


def test_heic_folder_converts_natural_order_and_ignores_other_files(tmp_path: Path, monkeypatch) -> None:
    _fake_heif_plugin(monkeypatch)
    Image.new("RGB", (10, 20), "red").save(tmp_path / "page10.heic", format="PNG")
    Image.new("RGB", (20, 10), "blue").save(tmp_path / "page2.heif", format="PNG")
    Image.new("RGB", (5, 5), "green").save(tmp_path / "ignored.png")

    outputs = convert_folder(tmp_path)

    assert [path.name for path in outputs] == ["p0001.png", "p0002.png"]
    assert outputs[0].parent == tmp_path / "scan_source_pages"
    with Image.open(outputs[0]) as first, Image.open(outputs[1]) as second:
        assert first.size == (20, 10)
        assert second.size == (10, 20)
        assert first.mode == second.mode == "RGB"


def test_heic_folder_refuses_nonempty_output(tmp_path: Path, monkeypatch) -> None:
    _fake_heif_plugin(monkeypatch)
    Image.new("RGB", (10, 10), "white").save(tmp_path / "page1.heic", format="PNG")
    output = tmp_path / "scan_source_pages"
    output.mkdir()
    (output / "old.png").write_bytes(b"old")

    try:
        convert_folder(tmp_path)
    except ValueError as exc:
        assert "must be empty" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("non-empty output should be rejected")
