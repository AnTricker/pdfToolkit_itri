from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def toolkit_root() -> Path:
    return Path(__file__).resolve().parents[2]


def csv_values(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _subcommand(parent: argparse.ArgumentParser, name: str, help_text: str) -> argparse.ArgumentParser:
    return parent.add_subparsers(dest=f"{name}_action", required=True).add_parser(name, help=help_text)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="digital-pdf-toolkit")
    modes = parser.add_subparsers(dest="command", required=True)

    pages = modes.add_parser("pages", help="Map one PNG folder into an external page set")
    pages_create = _subcommand(pages, "create", "Create a raw PNG page set")
    pages_create.add_argument("input", type=Path)

    extract = modes.add_parser("extract", help="Create a Digital PDF page set")
    extract_create = _subcommand(extract, "create", "Extract one Digital PDF")
    extract_create.add_argument("input", type=Path)
    extract_create.add_argument("--document-id")
    extract_create.add_argument("--config", type=Path)

    preprocess = modes.add_parser("preprocess", help="Create, retry, or report scanned-page preprocessing")
    preprocess_actions = preprocess.add_subparsers(dest="preprocess_action", required=True)
    preprocess_create = preprocess_actions.add_parser("create")
    preprocess_create.add_argument("input", type=Path)
    preprocess_create.add_argument("--profile", choices=["full", "geometry-only", "cleanup-only", "custom"], default="full")
    preprocess_create.add_argument("--document-id")
    preprocess_create.add_argument("--overrides", type=Path)
    preprocess_create.add_argument("--config", type=Path)
    preprocess_create.add_argument("--debug", action="store_true")
    preprocess_retry = preprocess_actions.add_parser("retry")
    preprocess_retry.add_argument("document_id")
    preprocess_retry.add_argument("--from", dest="parent_attempt", required=True)
    preprocess_retry.add_argument("--overrides", type=Path)
    preprocess_retry.add_argument("--config", type=Path)
    preprocess_retry.add_argument("--debug", action="store_true")
    preprocess_report_parser = preprocess_actions.add_parser("report")
    preprocess_report_parser.add_argument("document_id")
    preprocess_report_parser.add_argument("--attempt", required=True)

    resolution = modes.add_parser("resolution", help="Optimize or report page-set resolution")
    resolution_actions = resolution.add_subparsers(dest="resolution_action", required=True)
    optimize = resolution_actions.add_parser("optimize")
    optimize.add_argument("document_id")
    optimize.add_argument("--page-set", required=True)
    optimize.add_argument("--target-dpi", type=int)
    resolution_report_parser = resolution_actions.add_parser("report")
    resolution_report_parser.add_argument("document_id")
    resolution_report_parser.add_argument("--attempt", required=True)

    analyze = modes.add_parser("analyze", help="Run OCR tools against an explicit page set")
    analyze_create = _subcommand(analyze, "create", "Create Paddle, Surya, or MinerU attempts")
    analyze_create.add_argument("document_id")
    analyze_create.add_argument("--page-set", required=True)
    analyze_create.add_argument("--tools", required=True)
    analyze_create.add_argument("--config", type=Path)

    finalize = modes.add_parser("finalize", help="Build a handoff from an explicit analyze attempt")
    finalize_create = _subcommand(finalize, "create", "Create a document handoff")
    finalize_create.add_argument("document_id")
    finalize_create.add_argument("--tool", required=True, choices=["paddle", "surya", "mineru"])
    finalize_create.add_argument("--attempt", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    from .workflow import (
        create_analysis, create_extract, create_finalize, create_pages, create_preprocess,
        create_resolution, preprocess_report, resolution_report, retry_preprocess,
    )
    root = toolkit_root()
    try:
        if args.command == "pages":
            document_root, page_set, result = create_pages(root, args.input)
            print(f"Document: {document_root.name}\nPage set: {page_set}")
            print(f"Output pages: {len(result['page_values'])}\nFailed: {len(result['failures'])}")
        elif args.command == "extract":
            document_root, page_set = create_extract(root, args.input, args.document_id, args.config)
            print(f"Document: {document_root.name}\nPage set: {page_set}")
        elif args.command == "preprocess" and args.preprocess_action == "create":
            document_root, page_set, result = create_preprocess(
                root, args.input, args.profile, args.document_id, args.config,
                args.overrides, args.debug,
            )
            print(f"Document: {document_root.name}\nPage set: {page_set}")
            print(f"Output pages: {result['output_pages']}\nWarnings: {len(result['warnings'])}\nFailed: {len(result['failures'])}")
            _print_dpi_summary(result)
        elif args.command == "preprocess" and args.preprocess_action == "retry":
            document_root, page_set, result = retry_preprocess(
                root, args.document_id, args.parent_attempt, args.overrides, args.config, args.debug
            )
            print(f"Document: {document_root.name}\nPage set: {page_set}")
            print(f"Output pages: {result['output_pages']}\nWarnings: {len(result['warnings'])}\nFailed: {len(result['failures'])}")
            _print_dpi_summary(result)
        elif args.command == "preprocess":
            print(json.dumps(preprocess_report(root, args.document_id, args.attempt), ensure_ascii=False, indent=2))
        elif args.command == "resolution" and args.resolution_action == "optimize":
            _, page_set, result = create_resolution(root, args.document_id, args.page_set, args.target_dpi)
            print(f"Page set: {page_set}\nOutput pages: {len(result['page_values'])}\nFailed: {len(result['failures'])}")
        elif args.command == "resolution":
            print(json.dumps(resolution_report(root, args.document_id, args.attempt), ensure_ascii=False, indent=2))
        elif args.command == "analyze":
            tools = csv_values(args.tools)
            unknown = set(tools) - {"paddle", "surya", "mineru"}
            if unknown:
                raise ValueError(f"Unknown tools: {sorted(unknown)}")
            _, attempts = create_analysis(root, args.document_id, args.page_set, tools, args.config)
            for attempt in attempts:
                print(f"{attempt['id']}: {attempt['state']} ({attempt['input_page_set']})")
            if any(attempt["state"] != "completed" for attempt in attempts):
                return 1
        else:
            path = create_finalize(root, args.document_id, args.tool, args.attempt)
            print(f"Payload: {path}")
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


def _print_dpi_summary(result: dict) -> None:
    values = [float(page["dpi"]) for page in result.get("page_values", []) if page.get("dpi") is not None]
    if not values:
        return
    print(f"A4-equivalent DPI estimate: {min(values):.1f}–{max(values):.1f}")
    if min(values) < 300:
        print("Recommendation: optional resolution optimize")


if __name__ == "__main__":
    raise SystemExit(main())
