from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from .adapters import create_reader
from .events import EventLogger
from .io import relative_to, write_json


COLORS = {
    "table": "#e63946", "figure": "#457b9d", "picture": "#457b9d",
    "image": "#457b9d", "formula": "#8338ec", "chart": "#fb8500", "text": "#2a9d8f",
}


def build_assets(
    tool: str,
    attempt: dict[str, Any],
    document_root: Path,
    page_set: dict[str, Any],
    logger: EventLogger,
) -> dict[str, Any] | None:
    if attempt.get("state") != "completed":
        return None
    attempt_root = document_root / attempt["path"]
    assets_root = attempt_root / "assets"
    crops_root = assets_root / "crops"
    overlays_root = assets_root / "overlays"
    crops_root.mkdir(parents=True, exist_ok=True)
    overlays_root.mkdir(parents=True, exist_ok=True)
    logger.emit("assets", "START", "building page-set crops and overlays", tool=tool, attempt=attempt["id"])
    page_map = {int(page["page_index"]): page for page in page_set["pages"]}
    dimensions = {index: (float(page["width_px"]), float(page["height_px"])) for index, page in page_map.items()}
    try:
        reader = create_reader(tool, attempt_root / "raw")
        page_mapping = {
            Path(page["path"]).stem: int(page["page_index"])
            for page in page_set["pages"]
        }
        if hasattr(reader, "with_page_mapping"):
            reader = reader.with_page_mapping(page_mapping)  # type: ignore[attr-defined]
        if hasattr(reader, "with_page_dimensions"):
            reader = reader.with_page_dimensions(dimensions)  # type: ignore[attr-defined]
        index: dict[str, Any] = {
            "tool": tool, "attempt": attempt["id"], "input_page_set": page_set["page_set_id"],
            "regions": {}, "overlays": {}, "warnings": [],
        }
        for page_index, page in page_map.items():
            source = Image.open(document_root / page["path"]).convert("RGB")
            overlay = source.copy()
            draw = ImageDraw.Draw(overlay)
            for region in reader.regions(page_index):
                try:
                    pixels = region.coordinates.to_pixels(source.width, source.height, source.width, source.height)
                    if pixels[2] <= pixels[0] or pixels[3] <= pixels[1]:
                        raise ValueError(f"empty crop bbox: {pixels}")
                    crop_path = crops_root / f"{region.id}.png"
                    source.crop(pixels).save(crop_path)
                    color = COLORS.get(region.type, "#ffbe0b")
                    draw.rectangle(pixels, outline=color, width=3)
                    draw.text((pixels[0] + 2, pixels[1] + 2), region.type, fill=color)
                    index["regions"][region.id] = {
                        "page_index": page_index, "type": region.type,
                        "tool_bbox": list(region.coordinates.bbox),
                        "coordinate_space": region.coordinates.space,
                        "render_bbox": list(pixels),
                        "exact_crop": relative_to(crop_path, document_root),
                        "text": region.text, "provenance": region.provenance,
                    }
                except Exception as exc:
                    index["warnings"].append({"region_id": region.id, "detail": str(exc)})
            overlay_path = overlays_root / Path(page["path"]).name
            overlay.save(overlay_path)
            index["overlays"][str(page_index)] = relative_to(overlay_path, document_root)
        write_json(assets_root / "index.json", index)
        logger.emit("assets", "DONE", f"regions={len(index['regions'])}", tool=tool, attempt=attempt["id"])
        return index
    except Exception as exc:
        logger.emit("assets", "FAILED", str(exc), tool=tool, attempt=attempt["id"], level="ERROR")
        attempt["assets_error"] = str(exc)
        return None
