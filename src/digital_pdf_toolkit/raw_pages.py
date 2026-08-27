from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image

from .image_ops import natural_key
from .io import sha256_file, stable_hash


def map_png_folder(input_dir: Path) -> dict[str, Any]:
    """Map valid top-level PNG files without copying or modifying them."""
    if not input_dir.is_dir():
        raise ValueError(f"pages create requires one input folder: {input_dir}")
    paths = sorted(
        (path for path in input_dir.iterdir() if path.is_file() and path.suffix.lower() == ".png"),
        key=natural_key,
    )
    if not paths:
        raise ValueError(f"No top-level PNG files found: {input_dir}")

    page_values: list[dict[str, Any]] = []
    files: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for source_index, path in enumerate(paths, start=1):
        try:
            checksum = sha256_file(path)
            with Image.open(path) as image:
                image.load()
                if image.width <= 0 or image.height <= 0:
                    raise ValueError("image has invalid dimensions")
            resolved = str(path.resolve())
            files.append({"source_index": source_index, "path": resolved, "checksum": checksum})
            page_values.append({
                "image_path": path.resolve(), "image_checksum": checksum,
                "source_index": source_index, "source_path": resolved,
                "source_checksum": checksum, "split_part": "single",
            })
        except Exception as exc:
            failures.append({"source_index": source_index, "path": str(path.resolve()), "error": str(exc)})
    return {
        "input": str(input_dir.resolve()),
        "checksum": stable_hash([(item["path"], item["checksum"]) for item in files]),
        "files": files, "page_values": page_values, "failures": failures,
    }
