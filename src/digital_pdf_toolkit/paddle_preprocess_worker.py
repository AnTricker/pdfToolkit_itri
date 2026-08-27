from __future__ import annotations

import argparse
import json
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--mode", choices=["orientation", "dewarp"], required=True)
    parser.add_argument("--report", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    import numpy as np
    from PIL import Image
    from paddleocr import DocPreprocessor

    args.output_dir.mkdir(parents=True, exist_ok=True)
    report = {"completed": [], "failed": []}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    _write_report(args.report, report)
    try:
        pipeline = DocPreprocessor(
            use_doc_orientation_classify=args.mode == "orientation",
            use_doc_unwarping=args.mode == "dewarp",
        )
    except Exception as exc:
        report["failed"].append({"name": "*", "error": str(exc)})
        _write_report(args.report, report)
        return 1
    for source in sorted(args.input_dir.glob("*.png")):
        output = args.output_dir / source.name
        try:
            results = pipeline.predict(
                input=str(source),
                use_doc_orientation_classify=args.mode == "orientation",
                use_doc_unwarping=args.mode == "dewarp",
            )
            result = next(iter(results))
            output_img = np.asarray(result["output_img"])
            if output_img.ndim != 3 or output_img.shape[2] != 3 or not output_img.size:
                raise ValueError(f"Paddle output_img must be a non-empty 3-channel array, got shape={output_img.shape}")
            if output_img.dtype != np.uint8:
                output_img = np.clip(output_img, 0, 255).astype(np.uint8)
            Image.fromarray(output_img[:, :, ::-1], mode="RGB").save(output, format="PNG")
            report["completed"].append(source.name)
        except Exception as exc:
            report["failed"].append({"name": source.name, "error": str(exc)})
        _write_report(args.report, report)
    return 0 if report["completed"] else 1


def _write_report(path: Path, report: dict) -> None:
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
