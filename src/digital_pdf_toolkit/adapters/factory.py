from __future__ import annotations

from pathlib import Path

from .base import AnalysisRunReader
from .mineru import MinerURunReader
from .paddle import PaddleRunReader
from .surya import SuryaRunReader


READERS = {
    "paddle": PaddleRunReader,
    "mineru": MinerURunReader,
    "surya": SuryaRunReader,
}


def create_reader(tool: str, result_root: Path) -> AnalysisRunReader:
    try:
        return READERS[tool](result_root)
    except KeyError as exc:
        raise ValueError(f"Unknown tool: {tool}") from exc

