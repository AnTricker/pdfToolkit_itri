from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image

from .io import read_json, relative_to, write_json


def make_page_set_id(producer: str, attempt_id: str) -> str:
    return f"{producer}:{attempt_id}"


def write_page_set(
    document_root: Path,
    attempt_root: Path,
    producer: str,
    attempt_id: str,
    page_values: list[dict[str, Any]],
    *,
    observed: Path | None = None,
    source_pdf: Path | None = None,
    external_paths: bool = False,
) -> tuple[str, Path, dict[str, Any]]:
    pages: list[dict[str, Any]] = []
    for index, value in enumerate(page_values, start=1):
        image_path = Path(value["image_path"])
        with Image.open(image_path) as image:
            width, height = image.size
        page = {
            "page_id": f"p{index:04d}",
            "page_index": index - 1,
            "path": str(image_path.resolve()) if external_paths else relative_to(image_path, document_root),
            "width_px": width,
            "height_px": height,
            "source_index": int(value["source_index"]),
            "source_path": str(value["source_path"]),
            "source_checksum": value["source_checksum"],
            "split_part": value.get("split_part", "single"),
            "dpi": value.get("dpi"),
            "dpi_kind": value.get("dpi_kind"),
        }
        if value.get("image_checksum") is not None:
            page["checksum"] = value["image_checksum"]
        pages.append(page)
    page_set_id = make_page_set_id(producer, attempt_id)
    payload: dict[str, Any] = {
        "schema_version": "0.2",
        "kind": "page_set",
        "page_set_id": page_set_id,
        "producer": {"mode": producer, "attempt": attempt_id},
        "page_count": len(pages),
        "coordinate_system": {"origin": "top_left", "unit": "pixel"},
        "storage": "external" if external_paths else "workspace",
        "pages": pages,
    }
    if observed is not None:
        payload["observed"] = relative_to(observed, document_root)
    if source_pdf is not None:
        payload["source_pdf"] = str(source_pdf.resolve())
    path = attempt_root / "page_set.json"
    write_json(path, payload)
    return page_set_id, path, payload


def register_page_set(
    document_root: Path, manifest: dict[str, Any], page_set_id: str, path: Path
) -> None:
    manifest.setdefault("page_sets", {})[page_set_id] = relative_to(path, document_root)


def load_page_set(
    document_root: Path, manifest: dict[str, Any], page_set_id: str
) -> tuple[Path, dict[str, Any]]:
    page_sets = manifest.get("page_sets", {})
    relative = page_sets.get(page_set_id)
    if not relative and ":" not in page_set_id:
        matches = [(key, value) for key, value in page_sets.items() if key.partition(":")[2] == page_set_id]
        if len(matches) == 1:
            _, relative = matches[0]
        elif len(matches) > 1:
            candidates = ", ".join(key for key, _ in matches)
            raise ValueError(f"Ambiguous page set attempt '{page_set_id}'; candidates: {candidates}")
    if not relative:
        raise ValueError(f"Unknown page set: {page_set_id}")
    path = document_root / relative
    return path, read_json(path)


def page_paths(document_root: Path, page_set: dict[str, Any]) -> list[Path]:
    return [document_root / page["path"] for page in page_set["pages"]]
