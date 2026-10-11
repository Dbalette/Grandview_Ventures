"""Small shared helpers: subprocess, sizes, timestamps, platform checks."""
from __future__ import annotations

import datetime as _dt
import os
import platform
import shutil
import subprocess
import sys
from typing import List, Optional, Sequence


class ToolError(RuntimeError):
    """A wrapped external tool failed."""


def is_macos() -> bool:
    return platform.system() == "Darwin"


def is_root() -> bool:
    return hasattr(os, "geteuid") and os.geteuid() == 0


def which(name: str) -> Optional[str]:
    """Find a binary on PATH, also checking the usual Homebrew prefixes."""
    found = shutil.which(name)
    if found:
        return found
    for prefix in ("/opt/homebrew/bin", "/usr/local/bin", "/opt/homebrew/sbin", "/usr/local/sbin", "/usr/sbin", "/sbin"):
        cand = os.path.join(prefix, name)
        if os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand
    return None


def run(cmd: Sequence[str], check: bool = True, input_bytes: Optional[bytes] = None,
        timeout: Optional[int] = None) -> subprocess.CompletedProcess:
    """Run a command, capturing output. Raises ToolError on non-zero exit when check=True."""
    try:
        proc = subprocess.run(list(cmd), input=input_bytes, capture_output=True, timeout=timeout)
    except FileNotFoundError as exc:
        raise ToolError(f"command not found: {cmd[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise ToolError(f"command timed out after {timeout}s: {' '.join(cmd)}") from exc
    if check and proc.returncode != 0:
        err = proc.stderr.decode(errors="replace").strip()
        out = proc.stdout.decode(errors="replace").strip()
        raise ToolError(f"{' '.join(cmd)} exited {proc.returncode}: {err or out}")
    return proc


def run_stream(cmd: Sequence[str]) -> int:
    """Run a command attached to the terminal (for long interactive tools like ddrescue)."""
    try:
        return subprocess.call(list(cmd))
    except FileNotFoundError as exc:
        raise ToolError(f"command not found: {cmd[0]}") from exc


def shell_join(cmd: Sequence[str]) -> str:
    out: List[str] = []
    for part in cmd:
        if any(ch in part for ch in " \t'\"$`\\"):
            out.append("'" + part.replace("'", "'\\''") + "'")
        else:
            out.append(part)
    return " ".join(out)


def human_size(num: Optional[float], binary: bool = True) -> str:
    if num is None:
        return "n/a"
    base = 1024.0 if binary else 1000.0
    units = ["B", "KiB", "MiB", "GiB", "TiB"] if binary else ["B", "KB", "MB", "GB", "TB"]
    val = float(num)
    for unit in units:
        if abs(val) < base or unit == units[-1]:
            return f"{val:.1f} {unit}" if unit != "B" else f"{int(val)} B"
        val /= base
    return f"{val:.1f} {units[-1]}"


def now_iso() -> str:
    return _dt.datetime.now().replace(microsecond=0).isoformat()


def eprint(*args: object) -> None:
    print(*args, file=sys.stderr, flush=True)


def align_down(value: int, block: int) -> int:
    return value - (value % block)


def align_up(value: int, block: int) -> int:
    rem = value % block
    return value if rem == 0 else value + (block - rem)
