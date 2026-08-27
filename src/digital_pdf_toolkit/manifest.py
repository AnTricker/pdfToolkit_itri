from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .io import read_json, relative_to, write_json


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_document_manifest(document_id: str, config: dict[str, Any]) -> dict[str, Any]:
    timestamp = now()
    return {
        "schema_version": "0.2",
        "kind": "document",
        "document_id": document_id,
        "created_at": timestamp,
        "updated_at": timestamp,
        "resolved_config": config,
        "source_versions": [],
        "attempts": {
            "pages": [],
            "extract": [],
            "preprocess": [],
            "resolution": [],
            "analyze": {},
            "finalize": [],
        },
        "page_sets": {},
    }


def load_manifest(document_root: Path) -> dict[str, Any]:
    return read_json(document_root / "manifest.json")


def save_manifest(document_root: Path, manifest: dict[str, Any]) -> None:
    manifest["updated_at"] = now()
    write_json(document_root / "manifest.json", manifest)


def add_source_version(
    manifest: dict[str, Any],
    *,
    kind: str,
    path: Path,
    checksum: str,
    files: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    resolved_path = str(path.resolve())
    for existing in reversed(manifest["source_versions"]):
        if (
            existing.get("kind") == kind
            and existing.get("path") == resolved_path
            and existing.get("checksum") == checksum
        ):
            return existing
    value: dict[str, Any] = {
        "id": f"source-{len(manifest['source_versions']) + 1:03d}",
        "kind": kind,
        "path": resolved_path,
        "checksum": checksum,
        "created_at": now(),
    }
    if files is not None:
        value["files"] = files
    manifest["source_versions"].append(value)
    return value


def add_attempt(
    manifest: dict[str, Any],
    mode: str,
    attempt: dict[str, Any],
    *,
    tool: str | None = None,
) -> None:
    if mode == "analyze":
        if tool is None:
            raise ValueError("Analyze attempts require a tool")
        manifest["attempts"]["analyze"].setdefault(tool, []).append(attempt)
    else:
        manifest["attempts"].setdefault(mode, []).append(attempt)


def find_attempt(
    manifest: dict[str, Any], mode: str, attempt_id: str, tool: str | None = None
) -> dict[str, Any]:
    attempts = (
        manifest.get("attempts", {}).get("analyze", {}).get(tool, [])
        if mode == "analyze"
        else manifest.get("attempts", {}).get(mode, [])
    )
    for attempt in attempts:
        if attempt.get("id") == attempt_id:
            return attempt
    label = f"{mode}/{tool}" if tool else mode
    raise ValueError(f"Unknown attempt: {label}/{attempt_id}")
