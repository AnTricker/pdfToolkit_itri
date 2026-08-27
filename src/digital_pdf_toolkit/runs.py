from __future__ import annotations

import platform
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .assets import build_surya_assets
from .config import load_config
from .events import EventLogger
from .extract import extract_document
from .sorting import natural_key
from .io import write_json
from .metadata import utc_now, write_metadata
from .process import ProcessResult, run_process


BATCH_SIZE = 10


def _output_root(toolkit_root: Path, config: dict[str, Any]) -> Path:
    value = Path(config["project"]["output_root"]).expanduser()
    return value if value.is_absolute() else toolkit_root / value


def allocate_run_root(toolkit_root: Path, config: dict[str, Any], mode: str) -> Path:
    output_root = _output_root(toolkit_root, config)
    output_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%m%d%H%M")
    base = f"{stamp}_{mode}"
    candidate = output_root / base
    suffix = 2
    while candidate.exists():
        candidate = output_root / f"{base}_{suffix:02d}"
        suffix += 1
    candidate.mkdir(parents=False, exist_ok=False)
    return candidate


def _environment_payload(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "platform": platform.platform(),
        "python": sys.version,
        "core_environment": config["conda"]["core_env"],
    }


def run_extract(toolkit_root: Path, input_pdf: Path, custom_config: Path | None = None) -> Path:
    input_pdf = input_pdf.expanduser().resolve()
    if not input_pdf.is_file() or input_pdf.suffix.lower() != ".pdf":
        raise ValueError(f"extract requires one PDF file: {input_pdf}")
    config = load_config(toolkit_root, custom_config)
    run_root = allocate_run_root(toolkit_root, config, "extract")
    logger = EventLogger(run_root, config["logging"].get("redact_keys"))
    command = ["extract", str(input_pdf)] + (["--config", str(custom_config)] if custom_config else [])
    write_json(run_root / "command.json", {"command": command, "resolved_config": config})
    write_json(run_root / "environment.json", _environment_payload(config))
    status: dict[str, Any] = {
        "mode": "extract", "state": "running", "input": str(input_pdf),
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    write_json(run_root / "status.json", status)
    try:
        extract_document(input_pdf, run_root, int(config["project"]["render_dpi"]), logger)
        status.update({"state": "completed", "finished_at": datetime.now(timezone.utc).isoformat()})
        write_json(run_root / "status.json", status)
        return run_root
    except Exception as exc:
        status.update({"state": "failed", "error": str(exc), "finished_at": datetime.now(timezone.utc).isoformat()})
        write_json(run_root / "status.json", status)
        logger.emit("extract", "FAILED", str(exc), level="ERROR")
        raise


def _pngs(directory: Path) -> list[Path]:
    return sorted(
        (path for path in directory.iterdir() if path.is_file() and path.suffix.lower() == ".png"),
        key=natural_key,
    )


def _ensure_unique_stems(paths: list[Path]) -> None:
    seen: dict[str, Path] = {}
    for path in paths:
        stem = path.stem.casefold()
        if stem in seen:
            raise ValueError(f"Duplicate PNG stems are not supported: {seen[stem].name}, {path.name}")
        seen[stem] = path


def _records(batch_paths: list[tuple[str | None, list[Path]]]) -> list[tuple[str | None, list[dict[str, Any]]]]:
    flat = [path for _, paths in batch_paths for path in paths]
    _ensure_unique_stems(flat)
    page_index = 0
    output: list[tuple[str | None, list[dict[str, Any]]]] = []
    for batch, paths in batch_paths:
        values = []
        for position, path in enumerate(paths, start=1):
            values.append({
                "path": str(path.resolve()), "filename": path.name, "page_index": page_index,
                "batch": batch, "batch_position": position,
            })
            page_index += 1
        output.append((batch, values))
    return output


def prepare_png_batches(input_dir: Path) -> list[tuple[str | None, list[dict[str, Any]]]]:
    input_dir = input_dir.expanduser().resolve()
    if not input_dir.is_dir():
        raise ValueError(f"PNG input is not a folder: {input_dir}")
    top_level = _pngs(input_dir)
    numeric = sorted(
        (path for path in input_dir.iterdir() if path.is_dir() and path.name.isdigit()),
        key=lambda path: int(path.name),
    )
    if top_level and numeric:
        raise ValueError("PNG folder cannot mix top-level PNG files with numeric batch folders")
    if numeric:
        expected_names = [str(index) for index in range(1, len(numeric) + 1)]
        if [path.name for path in numeric] != expected_names:
            raise ValueError(f"Batch folders must be consecutively named: {expected_names}")
        values: list[tuple[str | None, list[Path]]] = []
        for index, directory in enumerate(numeric):
            paths = _pngs(directory)
            required = range(1, BATCH_SIZE + 1) if index == len(numeric) - 1 else range(BATCH_SIZE, BATCH_SIZE + 1)
            if len(paths) not in required:
                expectation = "1-10" if index == len(numeric) - 1 else "10"
                raise ValueError(f"Batch {directory.name} must contain {expectation} PNG files")
            values.append((directory.name, paths))
        return _records(values)
    if not top_level:
        raise ValueError(f"No top-level PNG files or numeric batches found in: {input_dir}")
    _ensure_unique_stems(top_level)
    if len(top_level) <= BATCH_SIZE:
        return _records([(None, top_level)])
    batches: list[tuple[str | None, list[Path]]] = []
    for offset in range(0, len(top_level), BATCH_SIZE):
        name = str(offset // BATCH_SIZE + 1)
        destination = input_dir / name
        destination.mkdir(exist_ok=False)
        moved: list[Path] = []
        for source in top_level[offset:offset + BATCH_SIZE]:
            target = destination / source.name
            source.replace(target)
            moved.append(target)
        batches.append((name, moved))
    return _records(batches)


def render_pdf(pdf_path: Path, rendered_root: Path, dpi: int) -> list[Path]:
    try:
        import fitz
    except ImportError as exc:  # pragma: no cover - real core environment
        raise RuntimeError("PDF rendering requires PyMuPDF") from exc
    rendered_root.mkdir(parents=True, exist_ok=False)
    document = fitz.open(pdf_path)
    try:
        if document.needs_pass:
            raise PermissionError("PDF requires a password")
        outputs = []
        for index, page in enumerate(document, start=1):
            target = rendered_root / f"p{index:04d}.png"
            page.get_pixmap(dpi=dpi, alpha=False).save(target)
            outputs.append(target)
        if not outputs:
            raise ValueError("PDF contains no pages")
        return outputs
    finally:
        document.close()


def _normalize_results(result_root: Path) -> Path:
    matches = list(result_root.rglob("results.json"))
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one Surya results.json, found {len(matches)}")
    source = matches[0]
    target = result_root / "results.json"
    if source != target:
        if target.exists():
            raise ValueError(f"Cannot normalize duplicate Surya result: {target}")
        shutil.move(str(source), str(target))
        parent = source.parent
        while parent != result_root:
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent
    return target


def _native_command(config: dict[str, Any], input_dir: Path, result_root: Path) -> tuple[list[str], list[str]]:
    replacements = {"input_dir": str(input_dir.resolve()), "output_dir": str(result_root.resolve())}
    native = [str(part).format(**replacements) for part in config["surya2"]["command"]]
    command = [
        "conda", "run", "--no-capture-output", "-n",
        config["surya2"]["environment"], *native,
    ]
    return command, native


def _validate_config(config: dict[str, Any]) -> None:
    if float(config["metadata"]["sampling_interval_seconds"]) <= 0:
        raise ValueError("metadata.sampling_interval_seconds must be greater than zero")
    if int(config["project"]["heartbeat_seconds"]) <= 0:
        raise ValueError("project.heartbeat_seconds must be greater than zero")
    command = config["surya2"].get("command")
    if not isinstance(command, list) or not command:
        raise ValueError("surya2.command must be a non-empty list")


def run_surya_batch(
    toolkit_root: Path,
    result_root: Path,
    images: list[dict[str, Any]],
    config: dict[str, Any],
) -> bool:
    result_root.mkdir(parents=True, exist_ok=True)
    logger = EventLogger(result_root, config["logging"].get("redact_keys"))
    input_dir = Path(images[0]["path"]).parent
    command, native = _native_command(config, input_dir, result_root)
    write_json(result_root / "command.json", {"command": command, "native_command": native, "surya2": config["surya2"]})
    environment = _environment_payload(config)
    environment.update({
        "surya_environment": config["surya2"]["environment"],
        "declared_surya_version": config["surya2"].get("version"),
    })
    write_json(result_root / "environment.json", environment)
    status: dict[str, Any] = {
        "mode": "surya2", "state": "running", "input": str(input_dir),
        "image_count": len(images), "started_at": datetime.now(timezone.utc).isoformat(),
    }
    write_json(result_root / "status.json", status)
    interval = float(config["metadata"]["sampling_interval_seconds"])
    started_at = utc_now()
    started = time.monotonic()
    process_result: ProcessResult | None = None
    warnings: list[str] = []
    try:
        process_result = run_process(
            command, toolkit_root, result_root / "stdout.log", result_root / "stderr.log",
            logger, int(config["project"]["heartbeat_seconds"]), interval,
        )
        if process_result.exit_code != 0:
            raise RuntimeError(f"Surya exited with code {process_result.exit_code}")
        _normalize_results(result_root)
        build_surya_assets(result_root, images, logger)
        status.update({
            "state": "completed", "exit_code": process_result.exit_code,
            "duration_seconds": round(process_result.duration_seconds, 3),
            "finished_at": datetime.now(timezone.utc).isoformat(),
        })
        logger.emit("surya2", "DONE", f"images={len(images)}")
        return True
    except Exception as exc:
        status.update({
            "state": "failed", "exit_code": process_result.exit_code if process_result else None,
            "error": str(exc), "finished_at": datetime.now(timezone.utc).isoformat(),
        })
        logger.emit("surya2", "FAILED", str(exc), level="ERROR")
        return False
    finally:
        duration = process_result.duration_seconds if process_result else time.monotonic() - started
        samples = process_result.samples if process_result else []
        warnings.extend(process_result.warnings if process_result else ["Surya process did not start; hardware samples are unavailable"])
        try:
            write_metadata(
                result_root, command=command, image_count=len(images), started_at=process_result.started_at if process_result else started_at,
                finished_at=process_result.finished_at if process_result else utc_now(), duration=duration,
                exit_code=process_result.exit_code if process_result else None, samples=samples,
                warnings=warnings, interval=interval,
            )
        except Exception as exc:  # metadata never changes the Surya state
            logger.emit("metadata", "WARNING", str(exc))
        write_json(result_root / "status.json", status)


def run_surya2(toolkit_root: Path, input_path: Path, custom_config: Path | None = None) -> tuple[Path, list[str]]:
    input_path = input_path.expanduser().resolve()
    is_pdf = input_path.is_file() and input_path.suffix.lower() == ".pdf"
    if not is_pdf and not input_path.is_dir():
        raise ValueError(f"surya2 requires one PNG folder or PDF file: {input_path}")
    config = load_config(toolkit_root, custom_config)
    _validate_config(config)
    run_root: Path
    if is_pdf:
        run_root = allocate_run_root(toolkit_root, config, "surya2")
        rendered_root = run_root / "rendered_png"
        render_pdf(input_path, rendered_root, int(config["project"]["render_dpi"]))
        batches = prepare_png_batches(rendered_root)
        batched = batches[0][0] is not None
    else:
        batches = prepare_png_batches(input_path)
        batched = batches[0][0] is not None
        run_root = allocate_run_root(toolkit_root, config, "surya2")

    failed: list[str] = []
    completed = 0
    for batch, images in batches:
        if batched:
            result_root = run_root / str(batch)
            label = str(batch)
        elif is_pdf:
            result_root = run_root / "result"
            label = "result"
        else:
            result_root = run_root
            label = "result"
        if run_surya_batch(toolkit_root, result_root, images, config):
            completed += 1
        else:
            failed.append(label)
    if batched:
        print(f"Completed: {completed} batches")
        print(f"Failed: {len(failed)} batches" + (f" ({', '.join(failed)})" if failed else ""))
    return run_root, failed
