from __future__ import annotations

from pathlib import Path
from typing import Any

from .assets import build_assets
from .config import load_config
from .events import EventLogger
from .extract import extract_document
from .identifiers import document_id as make_document_id, next_attempt_id
from .io import read_json, relative_to, sha256_file, write_json
from .manifest import (
    add_attempt, add_source_version, find_attempt, load_manifest,
    new_document_manifest, now, save_manifest,
)
from .page_sets import load_page_set, register_page_set, write_page_set
from .payload import build_payload
from .preprocessing import preprocess_document
from .raw_pages import map_png_folder
from .resolution import optimize_resolution
from .tool_runner import run_tool


def _config(toolkit_root: Path, tools: list[str] | None = None, custom: Path | None = None) -> dict[str, Any]:
    return load_config(toolkit_root, "full", tools, custom)


def _output_root(toolkit_root: Path, config: dict[str, Any]) -> Path:
    value = Path(config["project"]["output_root"])
    return value if value.is_absolute() else toolkit_root / value


def _new_document(
    toolkit_root: Path, config: dict[str, Any], requested_id: str | None
) -> tuple[Path, dict[str, Any]]:
    output_root = _output_root(toolkit_root, config)
    output_root.mkdir(parents=True, exist_ok=True)
    value = make_document_id(output_root, requested_id)
    document_root = output_root / value
    document_root.mkdir(parents=False, exist_ok=False)
    manifest = new_document_manifest(value, config)
    save_manifest(document_root, manifest)
    return document_root, manifest


def _document(toolkit_root: Path, document_id: str, config: dict[str, Any]) -> tuple[Path, dict[str, Any]]:
    document_root = _output_root(toolkit_root, config) / document_id
    return document_root, load_manifest(document_root)


def create_extract(
    toolkit_root: Path,
    input_pdf: Path,
    requested_id: str | None = None,
    custom_config: Path | None = None,
) -> tuple[Path, str]:
    if not input_pdf.is_file() or input_pdf.suffix.lower() != ".pdf":
        raise ValueError("extract create requires one PDF file")
    config = _config(toolkit_root, custom=custom_config)
    document_root, manifest = _new_document(toolkit_root, config, requested_id)
    checksum = sha256_file(input_pdf)
    source = add_source_version(manifest, kind="digital_pdf", path=input_pdf, checksum=checksum)
    namespace = document_root / "extract"
    attempt_id = next_attempt_id(namespace)
    attempt_root = namespace / attempt_id
    attempt_root.mkdir(parents=True, exist_ok=False)
    logger = EventLogger(document_root, config.get("logging", {}).get("redact_keys"))
    attempt = {
        "id": attempt_id, "state": "running", "path": relative_to(attempt_root, document_root),
        "source_version": source["id"], "started_at": now(),
    }
    add_attempt(manifest, "extract", attempt)
    save_manifest(document_root, manifest)
    try:
        observed = extract_document(input_pdf, attempt_root, int(config["project"]["render_dpi"]), logger)
        page_values = [{
            "image_path": attempt_root / page["render"]["path"],
            "source_index": int(page["page_index"]) + 1,
            "source_path": str(input_pdf.resolve()),
            "source_checksum": checksum,
            "split_part": "single",
        } for page in observed["pages"]]
        page_set_id, page_set_path, _ = write_page_set(
            document_root, attempt_root, "extract", attempt_id, page_values,
            observed=attempt_root / "observed" / "document.json", source_pdf=input_pdf,
        )
        register_page_set(document_root, manifest, page_set_id, page_set_path)
        attempt.update({"state": "completed", "page_set": page_set_id, "finished_at": now()})
        save_manifest(document_root, manifest)
        return document_root, page_set_id
    except Exception as exc:
        attempt.update({"state": "failed", "error": str(exc), "finished_at": now()})
        save_manifest(document_root, manifest)
        raise


def create_pages(toolkit_root: Path, input_dir: Path) -> tuple[Path, str, dict[str, Any]]:
    mapped = map_png_folder(input_dir)
    config = _config(toolkit_root)
    document_root, manifest = _new_document(toolkit_root, config, None)
    source = add_source_version(
        manifest, kind="png_folder", path=input_dir,
        checksum=mapped["checksum"], files=mapped["files"],
    )
    namespace = document_root / "pages"
    attempt_id = next_attempt_id(namespace)
    attempt_root = namespace / attempt_id
    attempt_root.mkdir(parents=True, exist_ok=False)
    attempt = {
        "id": attempt_id, "state": "running", "path": relative_to(attempt_root, document_root),
        "source_version": source["id"], "started_at": now(),
    }
    add_attempt(manifest, "pages", attempt)
    save_manifest(document_root, manifest)
    if not mapped["page_values"]:
        attempt.update({
            "state": "failed", "error": "No valid PNG pages were found",
            "failures": len(mapped["failures"]), "finished_at": now(),
        })
        save_manifest(document_root, manifest)
        raise ValueError("pages create found zero valid PNG pages")
    page_set_id, page_set_path, _ = write_page_set(
        document_root, attempt_root, "pages", attempt_id, mapped["page_values"], external_paths=True,
    )
    register_page_set(document_root, manifest, page_set_id, page_set_path)
    attempt.update({
        "state": "completed", "page_set": page_set_id,
        "output_pages": len(mapped["page_values"]), "failures": len(mapped["failures"]),
        "finished_at": now(),
    })
    save_manifest(document_root, manifest)
    return document_root, page_set_id, mapped


def _load_overrides(document_root: Path, path: Path | None) -> dict[str, Any]:
    workspace_path = document_root / "preprocess" / "overrides.json"
    if path is not None:
        value = read_json(path)
        write_json(workspace_path, value)
        return value
    if workspace_path.exists():
        return read_json(workspace_path)
    write_json(workspace_path, {})
    return {}


def _run_preprocess(
    toolkit_root: Path,
    document_root: Path,
    manifest: dict[str, Any],
    input_path: Path,
    profile: str,
    config: dict[str, Any],
    overrides: dict[str, Any],
    debug: bool,
    parent_attempt: str | None = None,
) -> tuple[str, dict[str, Any]]:
    namespace = document_root / "preprocess"
    attempt_id = next_attempt_id(namespace)
    attempt_root = namespace / attempt_id
    attempt_root.mkdir(parents=True, exist_ok=False)
    attempt = {
        "id": attempt_id, "state": "running", "path": relative_to(attempt_root, document_root),
        "profile": profile, "parent_attempt": parent_attempt, "started_at": now(),
    }
    add_attempt(manifest, "preprocess", attempt)
    save_manifest(document_root, manifest)
    try:
        result = preprocess_document(toolkit_root, input_path, attempt_root, profile, config, overrides, debug=debug)
        source = add_source_version(
            manifest, kind=result["input"]["kind"], path=input_path,
            checksum=result["input"]["checksum"], files=result["input"]["files"],
        )
        attempt["source_version"] = source["id"]
        if not result["page_values"]:
            attempt.update({"state": "failed", "error": "No pages were produced", "finished_at": now()})
            save_manifest(document_root, manifest)
            raise ValueError("Preprocessing produced zero pages")
        page_set_id, page_set_path, _ = write_page_set(
            document_root, attempt_root, "preprocess", attempt_id, result["page_values"]
        )
        register_page_set(document_root, manifest, page_set_id, page_set_path)
        attempt.update({
            "state": "completed", "page_set": page_set_id,
            "warnings": len(result["warnings"]), "failures": len(result["failures"]), "finished_at": now(),
        })
        save_manifest(document_root, manifest)
        return page_set_id, result
    except Exception as exc:
        if attempt.get("state") != "failed":
            attempt.update({"state": "failed", "error": str(exc), "finished_at": now()})
            save_manifest(document_root, manifest)
        raise


def create_preprocess(
    toolkit_root: Path,
    input_path: Path,
    profile: str,
    requested_id: str | None = None,
    custom_config: Path | None = None,
    overrides_path: Path | None = None,
    debug: bool = False,
) -> tuple[Path, str, dict[str, Any]]:
    config = _config(toolkit_root, custom=custom_config)
    document_root, manifest = _new_document(toolkit_root, config, requested_id)
    overrides = _load_overrides(document_root, overrides_path)
    page_set_id, result = _run_preprocess(
        toolkit_root, document_root, manifest, input_path, profile, config, overrides, debug
    )
    return document_root, page_set_id, result


def retry_preprocess(
    toolkit_root: Path,
    document_id: str,
    parent_attempt_id: str,
    overrides_path: Path | None = None,
    custom_config: Path | None = None,
    debug: bool = False,
) -> tuple[Path, str, dict[str, Any]]:
    config = _config(toolkit_root, custom=custom_config)
    document_root, manifest = _document(toolkit_root, document_id, config)
    parent = find_attempt(manifest, "preprocess", parent_attempt_id)
    parent_result = read_json(document_root / parent["path"] / "preprocessing.json")
    overrides = _load_overrides(document_root, overrides_path)
    page_set_id, result = _run_preprocess(
        toolkit_root, document_root, manifest, Path(parent_result["input"]["path"]),
        parent["profile"], config, overrides, debug, parent_attempt_id,
    )
    return document_root, page_set_id, result


def preprocess_report(toolkit_root: Path, document_id: str, attempt_id: str) -> dict[str, Any]:
    config = _config(toolkit_root)
    document_root, manifest = _document(toolkit_root, document_id, config)
    attempt = find_attempt(manifest, "preprocess", attempt_id)
    return read_json(document_root / attempt["path"] / "preprocessing.json")


def create_resolution(
    toolkit_root: Path,
    document_id: str,
    page_set_id: str,
    target_dpi: int | None = None,
) -> tuple[Path, str, dict[str, Any]]:
    config = _config(toolkit_root)
    document_root, manifest = _document(toolkit_root, document_id, config)
    _, parent_page_set = load_page_set(document_root, manifest, page_set_id)
    namespace = document_root / "resolution"
    attempt_id = next_attempt_id(namespace)
    attempt_root = namespace / attempt_id
    attempt_root.mkdir(parents=True, exist_ok=False)
    attempt = {
        "id": attempt_id, "state": "running", "path": relative_to(attempt_root, document_root),
        "input_page_set": page_set_id, "started_at": now(),
    }
    add_attempt(manifest, "resolution", attempt)
    save_manifest(document_root, manifest)
    result = optimize_resolution(
        document_root, parent_page_set, attempt_root,
        int(target_dpi or config.get("resolution", {}).get("target_dpi", 300)),
    )
    if not result["page_values"]:
        attempt.update({"state": "failed", "error": "No pages were produced", "finished_at": now()})
        save_manifest(document_root, manifest)
        raise ValueError("Resolution optimization produced zero pages")
    new_page_set_id, path, _ = write_page_set(
        document_root, attempt_root, "resolution", attempt_id, result["page_values"]
    )
    register_page_set(document_root, manifest, new_page_set_id, path)
    attempt.update({"state": "completed", "page_set": new_page_set_id, "failures": len(result["failures"]), "finished_at": now()})
    save_manifest(document_root, manifest)
    return document_root, new_page_set_id, result


def resolution_report(toolkit_root: Path, document_id: str, attempt_id: str) -> dict[str, Any]:
    config = _config(toolkit_root)
    document_root, manifest = _document(toolkit_root, document_id, config)
    attempt = find_attempt(manifest, "resolution", attempt_id)
    return read_json(document_root / attempt["path"] / "resolution.json")


def create_analysis(
    toolkit_root: Path,
    document_id: str,
    page_set_id: str,
    tools: list[str],
    custom_config: Path | None = None,
) -> tuple[Path, list[dict[str, Any]]]:
    config = _config(toolkit_root, tools, custom_config)
    document_root, manifest = _document(toolkit_root, document_id, config)
    _, page_set = load_page_set(document_root, manifest, page_set_id)
    logger = EventLogger(document_root, config.get("logging", {}).get("redact_keys"))
    attempts = []
    for tool in tools:
        attempt = run_tool(tool, toolkit_root, document_root, manifest, page_set, config, logger)
        if build_assets(tool, attempt, document_root, page_set, logger) is None and attempt.get("state") == "completed":
            attempt["state"] = "failed"
        save_manifest(document_root, manifest)
        attempts.append(attempt)
    return document_root, attempts


def create_finalize(
    toolkit_root: Path, document_id: str, tool: str, analyze_attempt_id: str
) -> Path:
    config = _config(toolkit_root)
    document_root, manifest = _document(toolkit_root, document_id, config)
    return build_payload(document_root, manifest, tool, analyze_attempt_id)
