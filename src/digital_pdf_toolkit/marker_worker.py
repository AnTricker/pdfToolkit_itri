from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, NamedTuple


class MarkerRuntime(NamedTuple):
    PdfConverter: type
    JSONRenderer: type
    MarkdownRenderer: type
    create_model_dict: Any
    save_output: Any


def _load_runtime() -> MarkerRuntime:
    try:
        from marker.converters.pdf import PdfConverter
        from marker.models import create_model_dict
        from marker.output import save_output
        from marker.renderers.json import JSONRenderer
        from marker.renderers.markdown import MarkdownRenderer
    except ImportError as exc:  # pragma: no cover - marker environment only
        raise RuntimeError("Marker conversion requires marker-pdf>=2,<3") from exc
    return MarkerRuntime(PdfConverter, JSONRenderer, MarkdownRenderer, create_model_dict, save_output)


def collect_block_provenance(document: Any) -> dict[str, Any]:
    blocks = []
    candidates = [*getattr(document, "pages", []), *document.contained_blocks()]
    for block in candidates:
        method = getattr(block, "text_extraction_method", None)
        source_kind = "ocr" if method == "surya" else method
        blocks.append(
            {
                "block_id": str(block.id),
                "block_type": str(block.block_type),
                "page_id": block.page_id,
                "text_extraction_method": method,
                "source_kind": source_kind,
            }
        )
    blocks.sort(key=lambda item: (item["page_id"], item["block_id"]))
    return {"schema_version": 1, "blocks": blocks}


def convert_pdf(
    input_pdf: Path,
    output_dir: Path,
    runtime: MarkerRuntime | None = None,
    *,
    mode: str = "balanced",
    inference_backend: str = "llamacpp",
) -> None:
    input_pdf = input_pdf.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    if not input_pdf.is_file() or input_pdf.suffix.lower() != ".pdf":
        raise ValueError(f"Marker requires one PDF file: {input_pdf}")
    output_dir.mkdir(parents=True, exist_ok=True)

    os.environ["SURYA_INFERENCE_BACKEND"] = inference_backend
    runtime = runtime or _load_runtime()
    converter = runtime.PdfConverter(artifact_dict=runtime.create_model_dict(), config={"mode": mode})
    document = converter.build_document(str(input_pdf))

    json_renderer = converter.resolve_dependencies(runtime.JSONRenderer)
    markdown_renderer = converter.resolve_dependencies(runtime.MarkdownRenderer)
    runtime.save_output(json_renderer(document), str(output_dir), "result")
    runtime.save_output(markdown_renderer(document), str(output_dir), "result")

    provenance = collect_block_provenance(document)
    (output_dir / "block_provenance.json").write_text(
        json.dumps(provenance, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="marker-worker")
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--mode", default="balanced", choices=("balanced", "fast"))
    parser.add_argument("--inference-backend", default="llamacpp", choices=("llamacpp", "vllm"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        convert_pdf(args.input, args.output, mode=args.mode, inference_backend=args.inference_backend)
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
