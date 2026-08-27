from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from PIL import Image

from .image_ops import (
    binarize,
    correct_lighting,
    crop_blank_border,
    denoise,
    deskew,
    enhance_contrast,
    natural_key,
    perspective_correct,
    rotate_quadrants,
    split_page,
)
from .io import read_json, sha256_file, stable_hash, write_json


STEP_ORDER = [
    "split", "perspective", "orientation", "dewarp", "deskew",
    "lighting", "denoise", "contrast", "crop", "binarization", "qa",
]
PROFILES = {
    "full": {"split", "perspective", "orientation", "dewarp", "deskew", "lighting", "denoise", "contrast", "crop", "qa"},
    "geometry-only": {"split", "perspective", "orientation", "dewarp", "deskew", "crop", "qa"},
    "cleanup-only": {"lighting", "denoise", "contrast", "crop", "qa"},
}


def _steps(profile: str, config: dict[str, Any]) -> list[str]:
    if profile == "custom":
        configured = config.get("preprocessing", {}).get("custom_steps", [])
        unknown = set(configured) - set(STEP_ORDER)
        if unknown:
            raise ValueError(f"Unknown preprocessing steps: {sorted(unknown)}")
        selected = set(configured)
    else:
        selected = PROFILES[profile]
    return [step for step in STEP_ORDER if step in selected]


def collect_sources(
    input_path: Path,
    attempt_root: Path,
    render_dpi: int,
) -> tuple[str, str, list[dict[str, Any]], list[dict[str, Any]]]:
    if input_path.is_file() and input_path.suffix.lower() == ".pdf":
        try:
            import fitz
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("PDF preprocessing requires PyMuPDF") from exc
        source_checksum = sha256_file(input_path)
        output = attempt_root / "scan_source_pages"
        output.mkdir(parents=True, exist_ok=False)
        document = fitz.open(input_path)
        sources = []
        files = []
        try:
            for index, page in enumerate(document, start=1):
                path = output / f"s{index:04d}.png"
                page.get_pixmap(dpi=render_dpi, alpha=False).save(path)
                sources.append({"source_index": index, "path": path, "original_path": str(input_path.resolve()), "checksum": source_checksum})
                files.append({"source_index": index, "path": str(input_path.resolve()), "page_index": index - 1, "checksum": source_checksum})
        finally:
            document.close()
        return "pdf", source_checksum, sources, files
    if input_path.is_dir():
        paths = sorted(
            (path for path in input_path.iterdir() if path.is_file() and path.suffix.lower() == ".png"),
            key=natural_key,
        )
        if not paths:
            raise ValueError(f"No top-level PNG files found: {input_path}")
        files = [
            {"source_index": index, "path": str(path.resolve()), "checksum": sha256_file(path)}
            for index, path in enumerate(paths, start=1)
        ]
        aggregate = stable_hash([(item["path"], item["checksum"]) for item in files])
        sources = [
            {"source_index": item["source_index"], "path": Path(item["path"]), "original_path": item["path"], "checksum": item["checksum"]}
            for item in files
        ]
        return "png_folder", aggregate, sources, files
    raise ValueError("Preprocess input must be a PDF file or a folder of top-level PNG files")


def _run_paddle_stage(
    toolkit_root: Path,
    input_dir: Path,
    output_dir: Path,
    mode: str,
    environment: str,
) -> dict[str, Any]:
    report = output_dir.parent / f"{mode}-report.json"
    worker = toolkit_root / "src" / "digital_pdf_toolkit" / "paddle_preprocess_worker.py"
    command = [
        "conda", "run", "--no-capture-output", "-n", environment,
        "python", str(worker), "--input-dir", str(input_dir),
        "--output-dir", str(output_dir), "--mode", mode, "--report", str(report),
    ]
    completed = subprocess.run(command, text=True, capture_output=True, check=False)
    if report.exists():
        value = read_json(report)
    else:
        value = {"completed": [], "failed": [{"name": "*", "error": completed.stderr.strip() or f"exit_code={completed.returncode}"}]}
    if completed.returncode != 0 and not any(item.get("name") == "*" for item in value.get("failed", [])):
        value.setdefault("failed", []).append({
            "name": "*",
            "error": completed.stderr.strip() or f"exit_code={completed.returncode}",
        })
    value["command_exit_code"] = completed.returncode
    value["_stdout"] = completed.stdout
    value["_stderr"] = completed.stderr
    return value


def _a4_equivalent_dpi(image: Image.Image) -> float:
    short_px, long_px = sorted(image.size)
    return round(min(short_px / 8.27, long_px / 11.69), 1)


def _geometry_qa(reference_size: tuple[int, int], output_size: tuple[int, int]) -> dict[str, Any]:
    reference_long = max(reference_size)
    output_long = max(output_size)
    reference_aspect = reference_long / min(reference_size)
    output_aspect = output_long / min(output_size)
    long_edge_growth = output_long / reference_long
    aspect_growth = output_aspect / reference_aspect
    violations: list[str] = []
    if long_edge_growth > 2.0:
        violations.append("long_edge_growth")
    if aspect_growth > 2.0:
        violations.append("aspect_growth")
    return {
        "reference_size": list(reference_size),
        "output_size": list(output_size),
        "long_edge_growth": round(long_edge_growth, 4),
        "aspect_growth": round(aspect_growth, 4),
        "thresholds": {"max_long_edge_growth": 2.0, "max_aspect_growth": 2.0},
        "status": "failed" if violations else "passed",
        "violations": violations,
    }


def _limit_long_edge(image: Image.Image, maximum: int | None) -> tuple[Image.Image, tuple[int, int] | None]:
    if maximum is None or max(image.size) <= maximum:
        return image, None
    if maximum <= 0:
        raise ValueError("preprocessing.paddle_max_long_edge must be positive or null")
    original = image.size
    scale = maximum / max(original)
    resized = image.resize(
        (max(1, round(image.width * scale)), max(1, round(image.height * scale))),
        Image.Resampling.LANCZOS,
    )
    return resized, original


def _persist_paddle_stage(attempt_root: Path, mode: str, report: dict[str, Any]) -> dict[str, Any]:
    stdout = str(report.pop("_stdout", ""))
    stderr = str(report.pop("_stderr", ""))
    write_json(attempt_root / f"{mode}-report.json", report)
    (attempt_root / f"{mode}-stdout.log").write_text(stdout, encoding="utf-8")
    (attempt_root / f"{mode}-stderr.log").write_text(stderr, encoding="utf-8")
    return {
        "mode": mode,
        "command_exit_code": report.get("command_exit_code"),
        "completed": len(report.get("completed", [])),
        "failed": len(report.get("failed", [])),
    }


def _apply_order(values: list[dict[str, Any]], overrides: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    requested = overrides.get("page_order")
    if not requested:
        return values, []
    by_key = {(int(value["source_index"]), value["split_part"]): value for value in values}
    ordered: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    used: set[tuple[int, str]] = set()
    for item in requested:
        key = (int(item["source_index"]), str(item.get("split_part", "single")))
        if key in used:
            warnings.append({"code": "page_order_target_duplicated", "source_index": key[0], "split_part": key[1]})
            continue
        value = by_key.get(key)
        if value is None:
            warnings.append({"code": "page_order_target_missing", "source_index": key[0], "split_part": key[1]})
            continue
        ordered.append(value)
        used.add(key)
    ordered.extend(value for value in values if (int(value["source_index"]), value["split_part"]) not in used)
    return ordered, warnings


def preprocess_document(
    toolkit_root: Path,
    input_path: Path,
    attempt_root: Path,
    profile: str,
    config: dict[str, Any],
    overrides: dict[str, Any] | None = None,
    *,
    debug: bool = False,
    paddle_runner: Any | None = None,
) -> dict[str, Any]:
    overrides = overrides or {}
    steps = _steps(profile, config)
    kind, source_checksum, sources, source_files = collect_sources(
        input_path, attempt_root, int(config["project"]["render_dpi"])
    )
    warnings: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    paddle_stages: list[dict[str, Any]] = []
    page_qa: list[dict[str, Any]] = []
    paddle_max_long_edge = config.get("preprocessing", {}).get("paddle_max_long_edge", 3000)
    if paddle_max_long_edge is not None:
        paddle_max_long_edge = int(paddle_max_long_edge)
        if paddle_max_long_edge <= 0:
            raise ValueError("preprocessing.paddle_max_long_edge must be positive or null")
    uses_paddle = bool({"orientation", "dewarp"}.intersection(steps))
    source_overrides = {str(key): value for key, value in overrides.get("sources", {}).items()}
    with tempfile.TemporaryDirectory(prefix="digital-pdf-preprocess-") as temporary:
        temporary_root = Path(temporary)
        pre_paddle = temporary_root / "pre-paddle"
        pre_paddle.mkdir()
        metadata: dict[str, dict[str, Any]] = {}
        for source in sources:
            source_index = int(source["source_index"])
            source_override = source_overrides.get(str(source_index), {})
            try:
                with Image.open(source["path"]) as opened:
                    image = rotate_quadrants(opened.convert("RGB"), int(source_override.get("rotate", 0)))
                pieces = (
                    split_page(image, str(source_override.get("split", "auto")))
                    if "split" in steps else ([("single", image)], [])
                )
                for code in pieces[1]:
                    warnings.append({"source_index": source_index, "code": code})
                for split_part, piece in pieces[0]:
                    if "perspective" in steps:
                        piece, codes = perspective_correct(piece)
                        warnings.extend({"source_index": source_index, "split_part": split_part, "code": code} for code in codes)
                    if uses_paddle:
                        piece, original_size = _limit_long_edge(piece, paddle_max_long_edge)
                        if original_size is not None:
                            warnings.append({
                                "source_index": source_index,
                                "split_part": split_part,
                                "code": "paddle_working_image_resized",
                                "original_size": list(original_size),
                                "working_size": list(piece.size),
                            })
                    name = f"s{source_index:04d}-{split_part}.png"
                    piece.save(pre_paddle / name)
                    metadata[name] = {
                        "source_index": source_index,
                        "source_path": source["original_path"],
                        "source_checksum": source["checksum"],
                        "split_part": split_part,
                        "qa_reference_size": piece.size,
                    }
            except Exception as exc:
                failures.append({"source_index": source_index, "source_path": source["original_path"], "stage": "geometry", "error": str(exc)})

        current = pre_paddle
        runner = paddle_runner or _run_paddle_stage
        paddle_environment = config.get("conda", {}).get("paddle_env", "digital-pdf-paddle")
        for mode in ("orientation", "dewarp"):
            if mode not in steps or not metadata:
                continue
            output_dir = temporary_root / mode
            output_dir.mkdir()
            report = runner(toolkit_root, current, output_dir, mode, paddle_environment)
            paddle_stages.append(_persist_paddle_stage(attempt_root, mode, report))
            completed_names = set(report.get("completed", []))
            for name in list(metadata):
                if name not in completed_names or not (output_dir / name).exists():
                    error = next((item.get("error") for item in report.get("failed", []) if item.get("name") in {name, "*"}), "Paddle preprocessing failed")
                    failures.append({**metadata[name], "stage": mode, "error": error})
                    metadata.pop(name)
            current = output_dir

        final_stage = temporary_root / "final"
        final_stage.mkdir()
        completed_values: list[dict[str, Any]] = []
        for name, value in list(metadata.items()):
            source_path = current / name
            try:
                with Image.open(source_path) as opened:
                    image = opened.convert("RGB")
                if "deskew" in steps:
                    image = deskew(image)
                if "lighting" in steps:
                    image = correct_lighting(image)
                if "denoise" in steps:
                    image = denoise(image)
                if "contrast" in steps:
                    image = enhance_contrast(image)
                if "crop" in steps:
                    image = crop_blank_border(image)
                if "binarization" in steps:
                    method = config.get("preprocessing", {}).get("binarization", "adaptive")
                    image = binarize(image, method)
                qa = {
                    "source_index": value["source_index"],
                    "source_path": value["source_path"],
                    "split_part": value["split_part"],
                    **_geometry_qa(tuple(value["qa_reference_size"]), image.size),
                }
                page_qa.append(qa)
                if qa["status"] == "failed":
                    failures.append({
                        "source_index": value["source_index"],
                        "source_path": value["source_path"],
                        "source_checksum": value["source_checksum"],
                        "split_part": value["split_part"],
                        "stage": "qa",
                        "error": f"image_geometry_qa_failed: {','.join(qa['violations'])}",
                    })
                    continue
                dpi = _a4_equivalent_dpi(image)
                if dpi < float(config.get("resolution", {}).get("low_dpi_warning", 150)):
                    warnings.append({**value, "code": "low_resolution", "a4_equivalent_dpi": dpi})
                final_path = final_stage / name
                image.save(final_path)
                completed_values.append({
                    **{key: item for key, item in value.items() if key != "qa_reference_size"},
                    "image_path": final_path, "dpi": dpi, "dpi_kind": "a4_equivalent_estimate",
                })
            except Exception as exc:
                failures.append({**value, "stage": "cleanup", "error": str(exc)})

        completed_values, order_warnings = _apply_order(completed_values, overrides)
        warnings.extend(order_warnings)
        output_root = attempt_root / "processed_pages"
        output_root.mkdir(parents=True, exist_ok=False)
        page_values: list[dict[str, Any]] = []
        for index, value in enumerate(completed_values, start=1):
            output_path = output_root / f"p{index:04d}.png"
            shutil.copyfile(value["image_path"], output_path)
            page_values.append({**value, "image_path": output_path})
        if debug:
            debug_root = attempt_root / "debug"
            shutil.copytree(pre_paddle, debug_root / "pre-paddle")
            if current != pre_paddle and current.exists():
                shutil.copytree(current, debug_root / current.name)

    result = {
        "schema_version": "0.2",
        "kind": "preprocessing_result",
        "input": {"kind": kind, "path": str(input_path.resolve()), "checksum": source_checksum, "files": source_files},
        "profile": profile,
        "steps": steps,
        "resolved_config": config.get("preprocessing", {}),
        "tool_versions": {
            "opencv": _opencv_version(),
            "paddle": config.get("tools", {}).get("paddle", {}).get("version"),
        },
        "paddle_stages": paddle_stages,
        "page_qa": page_qa,
        "output_pages": len(page_values),
        "warnings": warnings,
        "failures": failures,
    }
    write_json(attempt_root / "preprocessing.json", result)
    write_json(attempt_root / "overrides.snapshot.json", overrides)
    return {**result, "page_values": page_values}


def _opencv_version() -> str | None:
    try:
        import cv2
        return str(cv2.__version__)
    except ImportError:
        return None
