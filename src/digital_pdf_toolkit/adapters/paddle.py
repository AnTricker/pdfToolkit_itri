from __future__ import annotations

from pathlib import Path
import re
from typing import Any, Iterable

from digital_pdf_toolkit.coordinates import RegionCoordinates, normalize_bbox

from .base import AnalysisRegion, AnalysisRunReader
from .helpers import box_from, json_files, walk
from digital_pdf_toolkit.io import read_json


class PaddleRunReader(AnalysisRunReader):
    tool_name = "paddle"

    def __init__(self, result_root: Path):
        super().__init__(result_root)
        files = json_files(result_root)
        if not files:
            raise FileNotFoundError(f"No Paddle JSON result under {result_root}")
        self.documents = [(path, read_json(path)) for path in files]
        self._regions = list(self._parse())

    def _parse(self) -> Iterable[AnalysisRegion]:
        sequence = 0
        for path, document in self.documents:
            page_match = re.search(r"p(\d{4})", path.stem)
            inferred_page = int(page_match.group(1)) - 1 if page_match else 0
            raw_page = document.get("page_index") if isinstance(document, dict) else None
            default_page = inferred_page if raw_page is None else int(raw_page)
            for value in walk(document):
                if not isinstance(value, dict):
                    continue
                label = value.get("label") or value.get("type") or value.get("cls_name")
                bbox = box_from(value.get("coordinate") or value.get("bbox") or value.get("box"))
                if label is None or bbox is None:
                    continue
                sequence += 1
                page_index = int(value.get("page_index", default_page) or 0)
                text = value.get("text") or value.get("rec_text") or value.get("rec_formula")
                yield AnalysisRegion(
                    id=f"paddle-p{page_index}-r{sequence}",
                    page_index=page_index,
                    type=str(label).lower(),
                    coordinates=RegionCoordinates(normalize_bbox(bbox), "image_px", 1.0, 1.0),
                    text=str(text) if text is not None else None,
                    polygon=value.get("polygon") or value.get("rec_polys"),
                    provenance={"tool": "paddle", "raw_file": str(path)},
                )

    def with_page_dimensions(self, widths: dict[int, tuple[float, float]]) -> "PaddleRunReader":
        replaced = []
        for region in self._regions:
            source_width, source_height = widths.get(region.page_index, (1.0, 1.0))
            replaced.append(AnalysisRegion(
                **{
                    **region.__dict__,
                    "coordinates": RegionCoordinates(region.coordinates.bbox, "image_px", source_width, source_height),
                }
            ))
        self._regions = replaced
        return self

    def pages(self) -> list[int]:
        return sorted({region.page_index for region in self._regions})

    def regions(self, page_index: int | None = None) -> Iterable[AnalysisRegion]:
        return [region for region in self._regions if page_index is None or region.page_index == page_index]
