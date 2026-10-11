"""Force the SSD controller to retire unreadable blocks by overwriting them.

An SSD cannot "fix" a block that fails to read: the data is gone. What it CAN
do is retire the physical flash page and point the logical block (LBA) at a
fresh page. Firmware does that on WRITE, not on read. So after the data has
been rescued to an image, we write zeros over exactly the bad LBAs, then read
them back. A block that reads clean afterwards has been remapped; one that
still fails means the drive is out of spare area and is at end of life.

This module is destructive to the bad ranges only, and only runs after
safety checks and an explicit typed confirmation in the CLI.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field, asdict
from typing import Callable, Dict, List, Optional, Tuple

from .surface import BadMap, Reader, merge_ranges, verify_ranges
from .util import align_down, align_up, now_iso

Writer = Callable[[int, bytes], int]


@dataclass
class RemapResult:
    device: str
    block_size: int
    attempted_blocks: int = 0
    write_failed_blocks: int = 0
    readable_after: int = 0
    still_bad: int = 0
    still_bad_ranges: List[List[int]] = field(default_factory=list)
    write_failed_ranges: List[List[int]] = field(default_factory=list)
    started: str = ""
    finished: str = ""

    @property
    def success_ratio(self) -> float:
        return self.readable_after / self.attempted_blocks if self.attempted_blocks else 0.0

    def to_dict(self) -> Dict:
        d = asdict(self)
        d["success_ratio"] = round(self.success_ratio, 4)
        return d


def device_rw(path: str) -> Tuple[Reader, Writer, Callable[[], None]]:
    fd = os.open(path, os.O_RDWR)

    def _read(offset: int, length: int) -> bytes:
        return os.pread(fd, length, offset)

    def _write(offset: int, data: bytes) -> int:
        return os.pwrite(fd, data, offset)

    def _close() -> None:
        try:
            os.fsync(fd)
        except OSError:
            pass
        os.close(fd)

    return _read, _write, _close


def zero_fill(reader: Reader, writer: Writer, badmap: BadMap, pad_blocks: int = 0) -> RemapResult:
    """Overwrite each bad block (plus optional neighbours) with zeros, then verify by reading back."""
    bs = badmap.block_size
    res = RemapResult(device=badmap.device, block_size=bs, started=now_iso())
    zeros = bytes(bs)
    targets: List[List[int]] = []
    for off, ln in badmap.bad_ranges:
        start = max(0, align_down(off, bs) - pad_blocks * bs)
        end = min(badmap.total_bytes, align_up(off + ln, bs) + pad_blocks * bs)
        targets.append([start, end - start])
    targets = merge_ranges(targets)
    for off, ln in targets:
        for b in range(off, off + ln, bs):
            res.attempted_blocks += 1
            try:
                n = writer(b, zeros)
                if n != bs:
                    raise OSError("short write")
            except OSError:
                res.write_failed_blocks += 1
                res.write_failed_ranges.append([b, bs])
    good, bad = verify_ranges(reader, targets, bs)
    res.readable_after = sum(l for _, l in good) // bs
    res.still_bad = sum(l for _, l in bad) // bs
    res.still_bad_ranges = bad
    res.write_failed_ranges = merge_ranges(res.write_failed_ranges)
    res.finished = now_iso()
    return res
