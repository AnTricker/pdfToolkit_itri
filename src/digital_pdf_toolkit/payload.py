from __future__ import annotations

from pathlib import Path
from typing import Any

from .identifiers import next_attempt_id
from .io import read_json, relative_to, write_json
from .manifest import add_attempt, find_attempt, now, save_manifest
from .page_sets import load_page_set


def build_payload(
    document_root: Path,
    manifest: dict[str, Any],
    tool: str,
    analyze_attempt_id: str,
) -> Path:
    analyze_attempt = find_attempt(manifest, "analyze", analyze_attempt_id, tool)
    if analyze_attempt.get("state") != "completed":
        raise ValueError(f"Analyze attempt is not completed: {tool}/{analyze_attempt_id}")
    page_set_path, page_set = load_page_set(document_root, manifest, analyze_attempt["input_page_set"])
    assets_path = document_root / analyze_attempt["path"] / "assets" / "index.json"
    if not assets_path.exists():
        raise ValueError(f"Assets are not completed for {tool}/{analyze_attempt_id}")
    assets = read_json(assets_path)
    namespace = document_root / "finalize"
    attempt_id = next_attempt_id(namespace)
    attempt_root = namespace / attempt_id
    payload = {
        "schema_version": "0.2",
        "kind": "document_handoff",
        "created_at": now(),
        "document_id": manifest["document_id"],
        "reference_base": "../..",
        "selection": {
            "tool": tool,
            "analyze_attempt": analyze_attempt_id,
            "input_page_set": page_set["page_set_id"],
        },
        "page_set": relative_to(page_set_path, document_root),
        "observed": page_set.get("observed"),
        "tool_result_root": relative_to(document_root / analyze_attempt["path"] / "raw", document_root),
        "assets_index": relative_to(assets_path, document_root),
        "page_renders": [page["path"] for page in page_set["pages"]],
        "exact_crops": [region["exact_crop"] for region in assets["regions"].values()],
        "contains": {
            "embedding_vectors": False, "vlm_interpretation": False,
            "semantic_relationships": False, "llm_captions": False,
        },
    }
    write_json(attempt_root / "manifest.json", payload)
    attempt = {
        "id": attempt_id, "state": "completed",
        "path": relative_to(attempt_root, document_root),
        "tool": tool, "analyze_attempt": analyze_attempt_id,
        "input_page_set": page_set["page_set_id"], "finished_at": now(),
    }
    add_attempt(manifest, "finalize", attempt)
    save_manifest(document_root, manifest)
    return attempt_root / "manifest.json"
