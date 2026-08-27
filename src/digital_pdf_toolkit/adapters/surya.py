from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import re
from typing import Any, Iterable

from digital_pdf_toolkit.coordinates import RegionCoordinates, normalize_bbox

from .base import AnalysisRegion, AnalysisRunReader
from .helpers import box_from, load_first


class SuryaRunReader(AnalysisRunReader):
    tool_name = "surya"

    def __init__(self, result_root: Path):
        super().__init__(result_root)
        self.path, self.document = load_first(result_root, ["results.json"])
        self._regions = list(self._parse())

    def _page_values(self) -> Iterable[tuple[str, int, dict[str, Any]]]:
        if isinstance(self.document, dict):
            fallback = 0
            for key, value in self.document.items():
                raw_page_key = str(key)
                match = re.search(r"p(\d{4})", raw_page_key)
                inferred = int(match.group(1)) - 1 if match else fallback
                if isinstance(value, list):
                    for offset, page in enumerate(value):
                        if isinstance(page, dict):
                            yield raw_page_key, inferred + offset, page
                            fallback += 1
        elif isinstance(self.document, list):
            yield from (
                (str(index), index, page)
                for index, page in enumerate(self.document)
                if isinstance(page, dict)
            )

    def _parse(self) -> Iterable[AnalysisRegion]:
        sequence = 0
        for raw_page_key, inferred_page, page in self._page_values():
            page_index = inferred_page
            image_bbox = box_from(page.get("image_bbox")) or [0.0, 0.0, 1.0, 1.0]
            source_width = image_bbox[2] - image_bbox[0]
            source_height = image_bbox[3] - image_bbox[1]
            for box in page.get("bboxes", page.get("blocks", [])):
                if not isinstance(box, dict):
                    continue
                bbox = box_from(box.get("bbox") or box.get("polygon"))
                if bbox is None:
                    continue
                sequence += 1
                yield AnalysisRegion(
                    id=f"surya-p{page_index}-r{sequence}",
                    page_index=page_index,
                    type=str(box.get("label", "unknown")).lower(),
                    coordinates=RegionCoordinates(
                        normalize_bbox(bbox), "image_px", source_width, source_height
                    ),
                    text=box.get("text") or box.get("html"),
                    polygon=box.get("polygon"),
                    provenance={
                        "tool": "surya",
                        "raw_file": str(self.path),
                        "raw_page_key": raw_page_key,
                    },
                )

    def with_page_mapping(self, mapping: dict[str, int]) -> "SuryaRunReader":
        self._regions = [
            replace(
                region,
                page_index=mapping.get(
                    str(region.provenance.get("raw_page_key", "")),
                    region.page_index,
                ),
            )
            for region in self._regions
        ]
        return self

    def pages(self) -> list[int]:
        return sorted({region.page_index for region in self._regions})

    def regions(self, page_index: int | None = None) -> Iterable[AnalysisRegion]:
        return [region for region in self._regions if page_index is None or region.page_index == page_index]
