from __future__ import annotations

from pathlib import Path

import fitz
import pytest
from PIL import Image

from digital_pdf_toolkit.png_to_pdf import convert_folder


def _png(path: Path, size: tuple[int, int], color: str) -> None:
    Image.new("RGB", size, color).save(path)


def test_png_folder_converts_natural_order_and_ignores_other_files(tmp_path: Path) -> None:
    _png(tmp_path / "page10.png", (30, 40), "red")
    _png(tmp_path / "page2.PNG", (20, 10), "blue")
    (tmp_path / "ignored.txt").write_text("ignored", encoding="utf-8")

    output = convert_folder(tmp_path)

    assert output == tmp_path / f"{tmp_path.name}.pdf"
    document = fitz.open(output)
    try:
        assert document.page_count == 2
        assert document[0].rect.width == pytest.approx(15)
        assert document[0].rect.height == pytest.approx(7.5)
        assert document[1].rect.width == pytest.approx(22.5)
        assert document[1].rect.height == pytest.approx(30)
    finally:
        document.close()


def test_png_folder_rejects_empty_input(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="No top-level"):
        convert_folder(tmp_path)


def test_png_folder_refuses_to_overwrite(tmp_path: Path) -> None:
    _png(tmp_path / "page1.png", (10, 10), "white")
    output = tmp_path / "combined.pdf"
    output.write_bytes(b"existing")

    with pytest.raises(ValueError, match="already exists"):
        convert_folder(tmp_path, output)
