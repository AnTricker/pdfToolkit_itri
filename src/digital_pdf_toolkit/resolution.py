from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from PIL import Image

from .io import write_json


A4_WIDTH_INCHES = 8.27
A4_HEIGHT_INCHES = 11.69


def a4_equivalent_dpi(width: int, height: int) -> float:
    short_px, long_px = sorted((width, height))
    return round(min(short_px / A4_WIDTH_INCHES, long_px / A4_HEIGHT_INCHES), 1)


def optimize_resolution(
    document_root: Path,
    parent_page_set: dict[str, Any],
    attempt_root: Path,
    target_dpi: int,
) -> dict[str, Any]:
    pages_root = attempt_root / "pages"
    pages_root.mkdir(parents=True, exist_ok=False)
    page_values: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for page in parent_page_set["pages"]:
        source = document_root / page["path"]
        output = pages_root / f"p{len(page_values) + 1:04d}.png"
        try:
            with Image.open(source) as opened:
                image = opened.convert("RGB")
                before = a4_equivalent_dpi(*image.size)
                scale = max(1.0, target_dpi / before)
                if scale > 1.0:
                    new_size = (round(image.width * scale), round(image.height * scale))
                    image = image.resize(new_size, Image.Resampling.LANCZOS)
                    action = "upscaled"
                else:
                    action = "unchanged"
                image.save(output)
                after = a4_equivalent_dpi(*image.size)
            page_values.append({
                "image_path": output,
                "source_index": page["source_index"],
                "source_path": page["source_path"],
                "source_checksum": page["source_checksum"],
                "split_part": page.get("split_part", "single"),
                "dpi": after,
                "dpi_kind": "a4_equivalent_estimate",
            })
            results.append({"page_id": page["page_id"], "action": action, "before_dpi": before, "after_dpi": after})
        except Exception as exc:
            failures.append({"page_id": page["page_id"], "path": page["path"], "error": str(exc)})
    result = {
        "schema_version": "0.2",
        "kind": "resolution_result",
        "input_page_set": parent_page_set["page_set_id"],
        "target_dpi": target_dpi,
        "dpi_kind": "a4_equivalent_estimate",
        "method": "Pillow.LANCZOS",
        "pages": results,
        "failures": failures,
    }
    write_json(attempt_root / "resolution.json", result)
    return {**result, "page_values": page_values}
