from __future__ import annotations

import queue
import subprocess
import threading
import time
from pathlib import Path
from typing import TextIO

from .events import EventLogger


def _pump(stream: TextIO, destination: TextIO, label: str, messages: queue.Queue[tuple[str, str | None]]) -> None:
    try:
        for line in iter(stream.readline, ""):
            destination.write(line)
            destination.flush()
            messages.put((label, line.rstrip()))
    finally:
        messages.put((label, None))


def run_process(
    command: list[str],
    cwd: Path,
    stdout_path: Path,
    stderr_path: Path,
    logger: EventLogger,
    tool: str,
    attempt: str,
    heartbeat_seconds: int,
) -> tuple[int, float]:
    started = time.monotonic()
    logger.emit("analyze", "START", "process started", tool=tool, attempt=attempt)
    messages: queue.Queue[tuple[str, str | None]] = queue.Queue()
    with stdout_path.open("w", encoding="utf-8") as stdout_file, stderr_path.open(
        "w", encoding="utf-8"
    ) as stderr_file:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        assert process.stdout is not None and process.stderr is not None
        threads = [
            threading.Thread(target=_pump, args=(process.stdout, stdout_file, "stdout", messages), daemon=True),
            threading.Thread(target=_pump, args=(process.stderr, stderr_file, "stderr", messages), daemon=True),
        ]
        for thread in threads:
            thread.start()
        completed_streams = 0
        last_heartbeat = time.monotonic()
        while completed_streams < 2 or process.poll() is None:
            try:
                label, line = messages.get(timeout=0.25)
                if line is None:
                    completed_streams += 1
                elif line and ("page" in line.lower() or "progress" in line.lower()):
                    logger.emit("analyze", "RUN", line, tool=tool, attempt=attempt)
            except queue.Empty:
                pass
            if time.monotonic() - last_heartbeat >= heartbeat_seconds and process.poll() is None:
                elapsed = round(time.monotonic() - started)
                logger.emit("analyze", "RUN", f"elapsed={elapsed}s, process active", tool=tool, attempt=attempt)
                last_heartbeat = time.monotonic()
        for thread in threads:
            thread.join(timeout=1)
        exit_code = process.wait()
    return exit_code, time.monotonic() - started

