"""GNU ddrescue orchestration: build the multi-pass command sequence and parse mapfiles.

Pass plan (from the ddrescue manual's recommended workflow):
  1. Fast copy, skip the hard parts:   ddrescue -n  -b BS  SRC IMG MAP
  2. Retry the hard parts 3 times:      ddrescue -r3 -b BS  SRC IMG MAP
  3. Optional reverse retry:            ddrescue -R -r1 -b BS SRC IMG MAP
The mapfile makes every pass resumable; never delete it while the rescue is unfinished.

Mapfile status characters: '?' non-tried, '*' non-trimmed, '/' non-scraped,
'-' bad sector, '+' finished.
"""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .surface import BadMap, merge_ranges
from .util import which

STATUS_NAMES = {"?": "non-tried", "*": "non-trimmed", "/": "non-scraped", "-": "bad-sector", "+": "finished"}


def ddrescue_path() -> Optional[str]:
    return which("ddrescue")


def pass_commands(source_raw: str, image: str, mapfile: str, block_size: int, passes: List[int],
                  binary: str = "ddrescue") -> List[List[str]]:
    cmds: List[List[str]] = []
    base = [binary, "-b", str(block_size)]
    for p in passes:
        if p == 1:
            cmds.append(base + ["-n", source_raw, image, mapfile])
        elif p == 2:
            cmds.append(base + ["-r3", source_raw, image, mapfile])
        elif p == 3:
            cmds.append(base + ["-R", "-r1", source_raw, image, mapfile])
        else:
            raise ValueError(f"unknown pass {p}")
    return cmds


@dataclass
class MapStats:
    current_pos: int = 0
    current_status: str = ""
    totals: Dict[str, int] = field(default_factory=dict)  # status char -> bytes
    bad_ranges: List[List[int]] = field(default_factory=list)
    untried_ranges: List[List[int]] = field(default_factory=list)

    @property
    def rescued(self) -> int:
        return self.totals.get("+", 0)

    @property
    def bad(self) -> int:
        return self.totals.get("-", 0)

    @property
    def total(self) -> int:
        return sum(self.totals.values())

    @property
    def finished(self) -> bool:
        return self.total > 0 and all(k in ("+", "-") for k in self.totals if self.totals[k] > 0)

    def pct_rescued(self) -> float:
        return 100.0 * self.rescued / self.total if self.total else 0.0


def parse_mapfile(text: str) -> MapStats:
    stats = MapStats()
    seen_header = False
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        if not seen_header:
            # "current_pos current_status [current_pass]"
            stats.current_pos = int(parts[0], 0)
            stats.current_status = parts[1] if len(parts) > 1 else ""
            seen_header = True
            continue
        if len(parts) < 3:
            continue
        pos, size, status = int(parts[0], 0), int(parts[1], 0), parts[2]
        stats.totals[status] = stats.totals.get(status, 0) + size
        if status == "-":
            stats.bad_ranges.append([pos, size])
        elif status in ("?", "*", "/"):
            stats.untried_ranges.append([pos, size])
    stats.bad_ranges = merge_ranges(stats.bad_ranges)
    stats.untried_ranges = merge_ranges(stats.untried_ranges)
    return stats


def badmap_from_mapfile(text: str, device: str, block_size: int, total_bytes: int) -> BadMap:
    stats = parse_mapfile(text)
    bm = BadMap(device=device, block_size=block_size, total_bytes=total_bytes)
    bm.bad_ranges = stats.bad_ranges
    bm.scanned_bytes = stats.rescued + stats.bad
    bm.next_offset = total_bytes if stats.finished else stats.current_pos
    bm.notes.append("derived from ddrescue mapfile")
    return bm


def free_space(path: str) -> int:
    probe = path
    while not os.path.exists(probe):
        parent = os.path.dirname(probe) or "/"
        if parent == probe:
            break
        probe = parent
    return shutil.disk_usage(probe).free


def space_check(image_path: str, source_bytes: int, margin: float = 0.02) -> Dict[str, object]:
    free = free_space(image_path)
    need = int(source_bytes * (1 + margin))
    return {"free": free, "need": need, "ok": free >= need}
