#!/usr/bin/env python3
"""Run one PNG OCR analyze command and record Linux/AMD performance metadata.

Example:
    python png_analyze_metadata.py -- \
        ./scripts/linux/analyze.sh create doc-0824-0001 \
        --page-set attempt-001_0824-0001 --tools surya

The script is intentionally standalone: it uses only the Python standard library,
Linux /proc, and (when available) the ``amd-smi`` executable.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import platform
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SENSITIVE_FLAGS = ("token", "secret", "password", "api-key", "api_key", "authorization")
SAMPLE_FIELDS = (
    "elapsed_seconds",
    "timestamp_utc",
    "gpu_utilization_percent",
    "vram_used_gb",
    "gpu_temperature_c",
    "gpu_power_w",
    "process_cpu_percent",
    "process_rss_mib",
    "system_ram_used_mib",
    "system_ram_used_percent",
    "disk_read_mib",
    "disk_write_mib",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Wrap one Linux PNG analyze command and write AMD GPU/system metadata."
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=1.0,
        help="sampling interval in seconds (default: 1.0)",
    )
    parser.add_argument("command", nargs=argparse.REMAINDER, help="command after --")
    args = parser.parse_args()
    if args.command and args.command[0] == "--":
        args.command = args.command[1:]
    if not args.command:
        parser.error("provide the analyze command after --")
    if args.interval <= 0:
        parser.error("--interval must be greater than zero")
    return args


def command_option(command: list[str], name: str) -> str | None:
    for index, value in enumerate(command):
        if value == name and index + 1 < len(command):
            return command[index + 1]
        prefix = name + "="
        if value.startswith(prefix):
            return value[len(prefix) :]
    return None


def analyze_identity(command: list[str]) -> tuple[str, str]:
    tools_value = command_option(command, "--tools")
    if not tools_value:
        raise ValueError("the wrapped analyze command must include --tools")
    tools = [item.strip() for item in tools_value.split(",") if item.strip()]
    if len(tools) != 1:
        raise ValueError("exactly one OCR tool is allowed per metadata run")

    try:
        create_index = command.index("create")
        document_id = command[create_index + 1]
    except (ValueError, IndexError) as exc:
        raise ValueError("expected analyze command form: ... create <document-id> ...") from exc
    if document_id.startswith("-"):
        raise ValueError("could not determine document-id after 'create'")
    return document_id, tools[0]


def infer_toolkit_root(command: list[str]) -> Path:
    executable = Path(command[0]).expanduser()
    if not executable.is_absolute():
        executable = (Path.cwd() / executable).resolve()
    if executable.name in {"analyze.sh", "analyze.cmd"} and len(executable.parents) >= 3:
        return executable.parents[2]
    cwd = Path.cwd().resolve()
    if (cwd / "pyproject.toml").is_file():
        return cwd
    return executable.parent


def yaml_output_root(path: Path) -> str | None:
    """Read the simple project.output_root scalar without requiring PyYAML."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    in_project = False
    project_indent = 0
    for raw_line in lines:
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        if re.match(r"^\s*project\s*:\s*$", line):
            in_project = True
            project_indent = indent
            continue
        if in_project and indent <= project_indent:
            in_project = False
        if in_project:
            match = re.match(r"^\s*output_root\s*:\s*(.+?)\s*$", line)
            if match:
                return match.group(1).strip().strip("\"'")
    return None


def attempt_namespace(root: Path, command: list[str], document_id: str, tool: str) -> Path:
    output_value = yaml_output_root(root / "config" / "default.yml") or "output"
    config_value = command_option(command, "--config")
    if config_value:
        config_path = Path(config_value).expanduser()
        if not config_path.is_absolute():
            config_path = (Path.cwd() / config_path).resolve()
        output_value = yaml_output_root(config_path) or output_value
    output_root = Path(output_value).expanduser()
    if not output_root.is_absolute():
        output_root = root / output_root
    return output_root / document_id / "analyze" / tool


def attempt_directories(namespace: Path) -> set[Path]:
    try:
        return {path.resolve() for path in namespace.iterdir() if path.is_dir()}
    except OSError:
        return set()


def find_new_attempt(namespace: Path, before: set[Path]) -> Path | None:
    created = list(attempt_directories(namespace) - before)
    if not created:
        return None
    return max(created, key=lambda path: path.stat().st_mtime_ns)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def numeric(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        match = re.search(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)", value.replace(",", ""))
        if match:
            return float(match.group(0))
    return None


def flatten_json(value: Any, prefix: str = "") -> Iterable[tuple[str, Any]]:
    if isinstance(value, dict):
        for key, child in value.items():
            child_prefix = f"{prefix}.{key}" if prefix else str(key)
            yield from flatten_json(child, child_prefix)
    elif isinstance(value, list):
        # Multi-GPU attribution is intentionally out of scope; use the first record.
        if value:
            yield from flatten_json(value[0], prefix)
    else:
        yield prefix.lower().replace(" ", "_"), value


def pick_metric(flat: list[tuple[str, Any]], groups: tuple[tuple[str, ...], ...]) -> tuple[float | None, str]:
    for required in groups:
        for key, value in flat:
            if all(part in key for part in required):
                number = numeric(value)
                if number is not None:
                    return number, key
    return None, ""


def named_quantity(value: Any, names: tuple[str, ...]) -> tuple[float | None, str | None]:
    """Find an amd-smi ``{"value": ..., "unit": ...}`` field by exact name."""
    normalized_names = {name.lower().replace(" ", "_") for name in names}
    if isinstance(value, list):
        # Multi-GPU attribution is intentionally out of scope; use GPU 0/first record.
        return named_quantity(value[0], names) if value else (None, None)
    if not isinstance(value, dict):
        return None, None
    for key, child in value.items():
        normalized_key = str(key).lower().replace(" ", "_")
        if normalized_key in normalized_names and isinstance(child, dict):
            number = numeric(child.get("value"))
            if number is not None:
                unit = child.get("unit")
                return number, str(unit) if unit is not None else None
    for child in value.values():
        number, unit = named_quantity(child, names)
        if number is not None:
            return number, unit
    return None, None


def memory_to_gb(value: float | None, unit: str | None) -> float | None:
    if value is None:
        return None
    normalized = (unit or "MB").strip().lower()
    if normalized in {"gb", "gib"}:
        return value
    if normalized in {"mb", "mib"}:
        return value / 1024
    if normalized in {"kb", "kib"}:
        return value / (1024 * 1024)
    if normalized in {"b", "byte", "bytes"}:
        return value / (1024 * 1024 * 1024)
    return value


class AmdSmiSampler:
    def __init__(self) -> None:
        self.executable = shutil.which("amd-smi")
        self.command: list[str] | None = None
        self.warning: str | None = None

    def _run(self, command: list[str]) -> dict[str, Any] | list[Any] | None:
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            self.warning = f"amd-smi failed: {exc}"
            return None
        if result.returncode != 0:
            self.warning = f"amd-smi returned {result.returncode}: {result.stderr.strip()}"
            return None
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            self.warning = f"amd-smi returned invalid JSON: {exc}"
            return None

    def sample(self) -> dict[str, float | None]:
        empty = {
            "gpu_utilization_percent": None,
            "vram_used_gb": None,
            "gpu_temperature_c": None,
            "gpu_power_w": None,
        }
        if not self.executable:
            self.warning = "amd-smi was not found in PATH; GPU metrics are null"
            return empty
        if self.command is None:
            probes = [
                [self.executable, "monitor", "-g", "0", "--json"],
                [self.executable, "metric", "-g", "0", "-u", "-m", "-p", "-t", "--json"],
            ]
            payload = None
            for probe in probes:
                payload = self._run(probe)
                if payload is not None:
                    self.command = probe
                    break
            if payload is None:
                return empty
        else:
            payload = self._run(self.command)
            if payload is None:
                return empty

        flat = list(flatten_json(payload))
        utilization, _ = named_quantity(payload, ("gfx", "gfx_utilization"))
        if utilization is None:
            utilization, _ = pick_metric(
                flat,
                (("gfx", "util"), ("gfx", "activity"), ("gpu", "util"), ("gpu", "activity")),
            )
        vram, vram_unit = named_quantity(payload, ("vram_used", "used_vram"))
        if vram is None:
            vram, _ = pick_metric(flat, (("vram", "used"), ("used", "vram")))
        vram = memory_to_gb(vram, vram_unit)
        temperature, _ = named_quantity(
            payload,
            ("hotspot_temperature", "gpu_temperature", "edge_temperature"),
        )
        if temperature is None:
            temperature, _ = pick_metric(
                flat,
                (("gpu", "temp"), ("edge", "temp"), ("temperature", "edge"), ("temperature",)),
            )
        power, _ = named_quantity(payload, ("power_usage", "socket_power", "average_socket_power"))
        if power is None:
            power, _ = pick_metric(
                flat,
                (("power", "current"), ("power", "average"), ("power", "usage"), ("power",)),
            )
        return {
            "gpu_utilization_percent": utilization,
            "vram_used_gb": vram,
            "gpu_temperature_c": temperature,
            "gpu_power_w": power,
        }


def proc_stat(pid: int) -> tuple[int, int, int] | None:
    try:
        text = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
        close = text.rfind(")")
        fields = text[close + 2 :].split()
        ppid = int(fields[1])
        cpu_ticks = int(fields[11]) + int(fields[12])
        rss_pages = int(fields[21])
        return ppid, cpu_ticks, rss_pages
    except (OSError, ValueError, IndexError):
        return None


def process_tree(root_pid: int) -> dict[int, tuple[int, int]]:
    records: dict[int, tuple[int, int, int]] = {}
    try:
        entries = os.scandir("/proc")
    except OSError:
        return {}
    with entries:
        for entry in entries:
            if not entry.name.isdigit():
                continue
            pid = int(entry.name)
            stat = proc_stat(pid)
            if stat is not None:
                records[pid] = stat
    selected = {root_pid}
    changed = True
    while changed:
        changed = False
        for pid, (ppid, _, _) in records.items():
            if ppid in selected and pid not in selected:
                selected.add(pid)
                changed = True
    return {pid: (records[pid][1], records[pid][2]) for pid in selected if pid in records}


def process_io(pid: int) -> tuple[int, int]:
    read_bytes = 0
    write_bytes = 0
    try:
        for line in Path(f"/proc/{pid}/io").read_text(encoding="utf-8").splitlines():
            key, _, raw_value = line.partition(":")
            if key == "read_bytes":
                read_bytes = int(raw_value.strip())
            elif key == "write_bytes":
                write_bytes = int(raw_value.strip())
    except (OSError, ValueError):
        pass
    return read_bytes, write_bytes


def system_memory() -> tuple[float | None, float | None]:
    values: dict[str, int] = {}
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            key, _, raw_value = line.partition(":")
            match = re.search(r"\d+", raw_value)
            if match:
                values[key] = int(match.group(0)) * 1024
    except OSError:
        return None, None
    total = values.get("MemTotal")
    available = values.get("MemAvailable")
    if not total or available is None:
        return None, None
    used = total - available
    return used / (1024 * 1024), used / total * 100


class ProcSampler:
    def __init__(self, pid: int) -> None:
        self.pid = pid
        self.clock_ticks = os.sysconf("SC_CLK_TCK")
        self.page_size = os.sysconf("SC_PAGE_SIZE")
        self.last_at = time.monotonic()
        self.last_cpu: dict[int, int] = {}
        self.last_io: dict[int, tuple[int, int]] = {}
        self.disk_read_bytes = 0
        self.disk_write_bytes = 0

    def sample(self) -> dict[str, float | None]:
        now = time.monotonic()
        elapsed = max(now - self.last_at, 1e-9)
        tree = process_tree(self.pid)
        cpu_delta = 0
        rss_pages = 0
        for pid, (cpu_ticks, pages) in tree.items():
            previous_cpu = self.last_cpu.get(pid, cpu_ticks)
            cpu_delta += max(0, cpu_ticks - previous_cpu)
            self.last_cpu[pid] = cpu_ticks
            rss_pages += pages

            current_io = process_io(pid)
            previous_io = self.last_io.get(pid, current_io)
            self.disk_read_bytes += max(0, current_io[0] - previous_io[0])
            self.disk_write_bytes += max(0, current_io[1] - previous_io[1])
            self.last_io[pid] = current_io
        self.last_at = now
        system_used, system_percent = system_memory()
        return {
            "process_cpu_percent": cpu_delta / self.clock_ticks / elapsed * 100,
            "process_rss_mib": rss_pages * self.page_size / (1024 * 1024),
            "system_ram_used_mib": system_used,
            "system_ram_used_percent": system_percent,
            "disk_read_mib": self.disk_read_bytes / (1024 * 1024),
            "disk_write_mib": self.disk_write_bytes / (1024 * 1024),
        }


def redact_command(command: list[str]) -> list[str]:
    redacted: list[str] = []
    hide_next = False
    for value in command:
        if hide_next:
            redacted.append("***")
            hide_next = False
            continue
        lowered = value.lower()
        if any(term in lowered for term in SENSITIVE_FLAGS):
            if "=" in value:
                redacted.append(value.split("=", 1)[0] + "=***")
            else:
                redacted.append(value)
                hide_next = True
        else:
            redacted.append(value)
    return redacted


def count_attempt_pngs(attempt_root: Path | None) -> int | None:
    if attempt_root is None:
        return None
    try:
        command_data = json.loads((attempt_root / "command.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    for raw_value in command_data.get("native_command", []):
        candidate = Path(str(raw_value)).expanduser()
        if candidate.is_dir():
            try:
                count = sum(1 for path in candidate.iterdir() if path.is_file() and path.suffix.lower() == ".png")
            except OSError:
                continue
            if count:
                return count
    return None


def metric_summary(samples: list[dict[str, Any]], field: str) -> dict[str, float | None]:
    values = [float(sample[field]) for sample in samples if sample.get(field) is not None]
    if not values:
        return {"average": None, "peak": None}
    return {"average": sum(values) / len(values), "peak": max(values)}


def rounded(value: Any, digits: int = 3) -> Any:
    if isinstance(value, float):
        return round(value, digits)
    if isinstance(value, dict):
        return {key: rounded(child, digits) for key, child in value.items()}
    if isinstance(value, list):
        return [rounded(child, digits) for child in value]
    return value


def write_results(output_dir: Path, summary: dict[str, Any], samples: list[dict[str, Any]]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = output_dir / "summary.json"
    samples_path = output_dir / "samples.csv"
    summary_path.write_text(
        json.dumps(rounded(summary), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    with samples_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SAMPLE_FIELDS)
        writer.writeheader()
        for sample in samples:
            writer.writerow(rounded({field: sample.get(field) for field in SAMPLE_FIELDS}))
    print(f"Metadata summary: {summary_path}", file=sys.stderr)
    print(f"Metadata samples: {samples_path}", file=sys.stderr)


def main() -> int:
    args = parse_args()
    if sys.platform != "linux":
        print("ERROR: this standalone metadata logger supports Linux only", file=sys.stderr)
        return 2
    try:
        document_id, tool = analyze_identity(args.command)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    toolkit_root = infer_toolkit_root(args.command)
    namespace = attempt_namespace(toolkit_root, args.command, document_id, tool)
    attempts_before = attempt_directories(namespace)
    started_wall = utc_now()
    started = time.monotonic()
    samples: list[dict[str, Any]] = []
    warnings: list[str] = []
    interrupted = False

    try:
        process = subprocess.Popen(args.command, start_new_session=True)
    except OSError as exc:
        print(f"ERROR: could not start analyze command: {exc}", file=sys.stderr)
        return 127

    proc_sampler = ProcSampler(process.pid)
    gpu_sampler = AmdSmiSampler()
    next_sample = started
    try:
        while process.poll() is None:
            now = time.monotonic()
            if now < next_sample:
                time.sleep(min(next_sample - now, 0.1))
                continue
            sample = {
                "elapsed_seconds": now - started,
                "timestamp_utc": utc_now(),
                **gpu_sampler.sample(),
                **proc_sampler.sample(),
            }
            samples.append(sample)
            next_sample += args.interval
            if next_sample <= time.monotonic():
                next_sample = time.monotonic() + args.interval
    except KeyboardInterrupt:
        interrupted = True
        warnings.append("metadata wrapper received KeyboardInterrupt")
        try:
            os.killpg(process.pid, signal.SIGINT)
            process.wait(timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except OSError:
                pass
    finally:
        exit_code = process.wait()

    finished = time.monotonic()
    total_seconds = finished - started
    finished_wall = utc_now()
    if gpu_sampler.warning:
        warnings.append(gpu_sampler.warning)
    attempt_root = find_new_attempt(namespace, attempts_before)
    image_count = count_attempt_pngs(attempt_root)
    if attempt_root is not None:
        output_dir = attempt_root / "metadata"
    else:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        output_dir = Path.cwd() / "metadata_logs" / f"{tool}_{stamp}"
        warnings.append(f"new attempt was not found under {namespace}; used fallback output directory")

    final_read = samples[-1].get("disk_read_mib") if samples else None
    final_write = samples[-1].get("disk_write_mib") if samples else None
    summary = {
        "schema_version": 1,
        "run": {
            "document_id": document_id,
            "tool": tool,
            "attempt_path": str(attempt_root) if attempt_root else None,
            "command": redact_command(args.command),
            "hostname": socket.gethostname(),
            "platform": platform.platform(),
            "python": platform.python_version(),
            "started_at_utc": started_wall,
            "finished_at_utc": finished_wall,
            "exit_code": exit_code,
            "interrupted": interrupted,
        },
        "sampling": {
            "interval_seconds": args.interval,
            "sample_count": len(samples),
            "gpu_source": "amd-smi (GPU 0)",
        },
        "workload": {
            "png_count": image_count,
            "total_seconds": total_seconds,
            "seconds_per_image": total_seconds / image_count if image_count else None,
            "images_per_second": image_count / total_seconds if image_count and total_seconds else None,
        },
        "metrics": {
            "gpu_utilization_percent": metric_summary(samples, "gpu_utilization_percent"),
            "vram_used_gb": metric_summary(samples, "vram_used_gb"),
            "gpu_temperature_c": metric_summary(samples, "gpu_temperature_c"),
            "gpu_power_w": metric_summary(samples, "gpu_power_w"),
            "process_cpu_percent": metric_summary(samples, "process_cpu_percent"),
            "process_rss_mib": metric_summary(samples, "process_rss_mib"),
            "system_ram_used_mib": metric_summary(samples, "system_ram_used_mib"),
            "system_ram_used_percent": metric_summary(samples, "system_ram_used_percent"),
            "disk_io_mib": {"read": final_read, "write": final_write},
        },
        "notes": {
            "process_cpu_percent": "100% equals one fully utilized logical CPU core",
            "process_rss_mib": "sum of RSS for the wrapper process and current descendants",
            "averages": "arithmetic mean of successful samples",
        },
        "warnings": warnings,
    }
    try:
        write_results(output_dir, summary, samples)
    except OSError as exc:
        print(f"ERROR: could not write metadata: {exc}", file=sys.stderr)
        return exit_code if exit_code != 0 else 1
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
