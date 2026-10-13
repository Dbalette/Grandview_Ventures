"""Shared helpers: number formatting, a subprocess wrapper and atomic JSON files."""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from typing import Any, List, Optional, Tuple

_UNITS = ("B", "KB", "MB", "GB", "TB", "PB")


def human_bytes(n: float) -> str:
    """Decimal units, matching what macOS and drive makers print."""
    value = float(n)
    for unit in _UNITS[:-1]:
        if abs(value) < 1000:
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1000.0
    return f"{value:.1f} {_UNITS[-1]}"


def format_duration(seconds: Optional[float]) -> str:
    if seconds is None or seconds != seconds or seconds == float("inf"):
        return "--"
    total = int(seconds)
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def run(cmd: List[str], timeout: Optional[float] = None) -> Tuple[int, str, str]:
    """Run a command and return (returncode, stdout, stderr); never raises."""
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, errors="replace", timeout=timeout
        )
    except FileNotFoundError:
        return 127, "", f"{cmd[0]}: command not found"
    except subprocess.TimeoutExpired as exc:
        return 124, _text(exc.stdout), _text(exc.stderr) + "\ntimed out"
    return proc.returncode, proc.stdout, proc.stderr


def write_json(path: str, obj: Any) -> None:
    """Write JSON atomically so a crash never leaves a half-written file."""
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(obj, handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def read_json(path: str) -> Any:
    with open(path, "r") as handle:
        return json.load(handle)
