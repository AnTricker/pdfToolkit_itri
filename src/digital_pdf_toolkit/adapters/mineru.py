from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from digital_pdf_toolkit.coordinates import RegionCoordinates, normalize_bbox

from .base import AnalysisRegion, AnalysisRunReader
from .helpers import box_from, load_first


class MinerURunReader(AnalysisRunReader):
    tool_name = "mineru"

    def __init__(self, result_root: Path):
        super().__init__(result_root)
        self.path, self.document = load_first(
            result_root,
            ["*_content_list_v2.json", "*_content_list.json", "*_middle.json"],
        )
        self._regions = list(self._parse())

    def _blocks(self) -> Iterable[tuple[int, dict[str, Any]]]:
        value = self.document
        if isinstance(value, list):
            for page_index, page in enumerate(value):
                if isinstance(page, list):
                    for block in page:
                        if isinstance(block, dict):
                            yield int(block.get("page_idx", page_index)), block
                elif isinstance(page, dict):
                    yield int(page.get("page_idx", page_index)), page
        elif isinstance(value, dict) and isinstance(value.get("pdf_info"), list):
            for page_index, page in enumerate(value["pdf_info"]):
                for key in ("preproc_blocks", "discarded_blocks", "blocks"):
                    for block in page.get(key, []):
                        if isinstance(block, dict):
                            yield page_index, block

    def _parse(self) -> Iterable[AnalysisRegion]:
        for sequence, (page_index, block) in enumerate(self._blocks(), start=1):
            bbox = box_from(block.get("bbox"))
            if bbox is None:
                continue
            maximum = max(abs(value) for value in bbox)
            if self.path.name.endswith("content_list_v2.json") or self.path.name.endswith("content_list.json"):
                space = "normalized_1" if maximum <= 1.5 else "normalized_1000"
            else:
                space = "image_px"
            text = block.get("content")
            if isinstance(text, dict):
                text = text.get("text") or text.get("content")
            yield AnalysisRegion(
                id=f"mineru-p{page_index}-r{sequence}",
                page_index=page_index,
                type=str(block.get("type", "unknown")).lower(),
                coordinates=RegionCoordinates(normalize_bbox(bbox), space, 1.0, 1.0),
                text=str(text) if text is not None else None,
                provenance={"tool": "mineru", "raw_file": str(self.path)},
            )

    def with_page_dimensions(self, widths: dict[int, tuple[float, float]]) -> "MinerURunReader":
        replaced = []
        for region in self._regions:
            if region.coordinates.space != "image_px":
                replaced.append(region)
                continue
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
