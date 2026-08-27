from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path


ATTEMPT_PATTERN = re.compile(r"^attempt-(\d{3})_")


def document_id(output_root: Path, requested: str | None = None) -> str:
    if requested:
        if not re.fullmatch(r"[A-Za-z0-9._-]+", requested):
            raise ValueError("document-id may contain only letters, numbers, dot, underscore, and hyphen")
        if (output_root / requested).exists():
            raise FileExistsError(f"Document already exists: {requested}")
        return requested
    stamp = datetime.now().astimezone().strftime("%m%d-%H%M")
    base = f"doc-{stamp}"
    candidate = base
    suffix = 2
    while (output_root / candidate).exists():
        candidate = f"{base}-{suffix:02d}"
        suffix += 1
    return candidate


def next_attempt_id(namespace_root: Path) -> str:
    highest = 0
    if namespace_root.exists():
        for child in namespace_root.iterdir():
            match = ATTEMPT_PATTERN.match(child.name) if child.is_dir() else None
            if match:
                highest = max(highest, int(match.group(1)))
    stamp = datetime.now().astimezone().strftime("%m%d-%H%M")
    return f"attempt-{highest + 1:03d}_{stamp}"
