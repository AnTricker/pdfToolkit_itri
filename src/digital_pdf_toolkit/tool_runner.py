from __future__ import annotations

import platform
import sys
from pathlib import Path
from typing import Any

from .events import EventLogger
from .identifiers import next_attempt_id
from .io import relative_to, sha256_file, stable_hash, write_json
from .manifest import add_attempt, now, save_manifest
from .process import run_process


def run_tool(
    tool: str,
    toolkit_root: Path,
    document_root: Path,
    manifest: dict[str, Any],
    page_set: dict[str, Any],
    config: dict[str, Any],
    logger: EventLogger,
) -> dict[str, Any]:
    tool_config = config["tools"][tool]
    if not page_set.get("pages"):
        raise ValueError("Analyze requires a non-empty page set")
    page_paths = resolve_analysis_pages(document_root, page_set)
    page_directories = {path.parent.resolve() for path in page_paths}
    if len(page_directories) != 1:
        raise ValueError("All analysis page images must share one directory")
    source_pdf = page_set.get("source_pdf")
    if tool == "mineru" and not source_pdf:
        raise ValueError("MinerU is only supported for extract page sets with a source PDF")

    namespace = document_root / "analyze" / tool
    attempt_id = next_attempt_id(namespace)
    attempt_root = namespace / attempt_id
    raw_dir = attempt_root / "raw"
    raw_dir.mkdir(parents=True, exist_ok=False)
    replacements = {
        "analysis_pages_dir": str(next(iter(page_directories))),
        "render_dir": str(next(iter(page_directories))),
        "input_pdf": str(source_pdf or ""),
        "input": str(source_pdf or ""),
        "raw_dir": str(raw_dir.resolve()),
    }
    native_command = [str(part).format(**replacements) for part in tool_config["command"]]
    command = ["conda", "run", "--no-capture-output", "-n", tool_config["environment"], *native_command]
    signature = stable_hash({
        "page_set": page_set["page_set_id"], "tool": tool,
        "version": tool_config.get("version"), "command": native_command,
    })
    attempt = {
        "id": attempt_id,
        "state": "running",
        "signature": signature,
        "path": relative_to(attempt_root, document_root),
        "input_page_set": page_set["page_set_id"],
        "started_at": now(),
    }
    add_attempt(manifest, "analyze", attempt, tool=tool)
    save_manifest(document_root, manifest)
    write_json(attempt_root / "command.json", {"command": command, "native_command": native_command, "tool_config": tool_config})
    write_json(attempt_root / "environment.json", {
        "platform": platform.platform(), "python": sys.version,
        "conda_environment": tool_config["environment"],
        "declared_tool_version": tool_config.get("version"),
    })
    try:
        exit_code, duration = run_process(
            command, document_root, attempt_root / "stdout.log", attempt_root / "stderr.log",
            logger, tool, attempt_id, int(config["project"]["heartbeat_seconds"]),
        )
        attempt.update({
            "state": "completed" if exit_code == 0 else "failed",
            "exit_code": exit_code,
            "duration_seconds": round(duration, 3),
            "finished_at": now(),
        })
    except Exception as exc:
        attempt.update({"state": "failed", "exit_code": None, "error": str(exc), "finished_at": now()})
    write_json(attempt_root / "status.json", attempt)
    save_manifest(document_root, manifest)
    logger.emit("analyze", attempt["state"].upper(), f"exit_code={attempt.get('exit_code')}", tool=tool, attempt=attempt_id, level="ERROR" if attempt["state"] == "failed" else "INFO")
    return attempt


def resolve_analysis_pages(document_root: Path, page_set: dict[str, Any]) -> list[Path]:
    paths: list[Path] = []
    for page in page_set.get("pages", []):
        stored = Path(page["path"])
        path = stored if stored.is_absolute() else document_root / stored
        if not path.is_file():
            raise ValueError(f"Page-set image is missing: {path}")
        expected = page.get("checksum")
        if expected is not None and sha256_file(path) != expected:
            raise ValueError(f"Page-set image checksum changed: {path}")
        paths.append(path)
    return paths
