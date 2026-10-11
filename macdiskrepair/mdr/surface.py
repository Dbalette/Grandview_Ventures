"""Read-only surface scan of a raw device, producing a bad-block map.

The scan reads the device in large aligned chunks. When a chunk fails with an
I/O error it is bisected down to single device blocks so the bad map is exact.
The result is a JSON "badmap" file that `remap` and `report` consume.

A `reader` callable can be injected for tests: reader(offset, length) -> bytes
and must raise OSError on a bad block.
"""
from __future__ import annotations

import errno
import json
import os
import time
from dataclasses import dataclass, field, asdict
from typing import Callable, Dict, List, Optional, Tuple

from .util import align_down, align_up, now_iso

Reader = Callable[[int, int], bytes]
Range = Tuple[int, int]  # (offset_bytes, length_bytes)


@dataclass
class BadMap:
    device: str
    block_size: int
    total_bytes: int
    bad_ranges: List[List[int]] = field(default_factory=list)  # [[offset, length], ...]
    scanned_bytes: int = 0
    next_offset: int = 0
    started: str = ""
    finished: str = ""
    read_errors: int = 0
    slow_ranges: List[List[int]] = field(default_factory=list)  # chunks slower than threshold
    notes: List[str] = field(default_factory=list)

    @property
    def bad_bytes(self) -> int:
        return sum(l for _, l in self.bad_ranges)

    @property
    def bad_blocks(self) -> int:
        return self.bad_bytes // self.block_size if self.block_size else 0

    @property
    def complete(self) -> bool:
        return self.next_offset >= self.total_bytes and self.total_bytes > 0

    def to_dict(self) -> Dict:
        d = asdict(self)
        d["bad_bytes"] = self.bad_bytes
        d["bad_blocks"] = self.bad_blocks
        d["complete"] = self.complete
        return d

    def save(self, path: str) -> None:
        tmp = path + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(self.to_dict(), fh, indent=2)
        os.replace(tmp, path)

    @classmethod
    def load(cls, path: str) -> "BadMap":
        with open(path) as fh:
            d = json.load(fh)
        return cls(
            device=d["device"], block_size=int(d["block_size"]), total_bytes=int(d["total_bytes"]),
            bad_ranges=[[int(a), int(b)] for a, b in d.get("bad_ranges", [])],
            scanned_bytes=int(d.get("scanned_bytes", 0)), next_offset=int(d.get("next_offset", 0)),
            started=d.get("started", ""), finished=d.get("finished", ""), read_errors=int(d.get("read_errors", 0)),
            slow_ranges=[[int(a), int(b)] for a, b in d.get("slow_ranges", [])], notes=list(d.get("notes", [])),
        )


def merge_ranges(ranges: List[List[int]]) -> List[List[int]]:
    """Merge adjacent/overlapping [offset, length] ranges."""
    if not ranges:
        return []
    rs = sorted((int(a), int(b)) for a, b in ranges)
    out: List[List[int]] = [list(rs[0])]
    for off, ln in rs[1:]:
        last = out[-1]
        if off <= last[0] + last[1]:
            last[1] = max(last[0] + last[1], off + ln) - last[0]
        else:
            out.append([off, ln])
    return out


def device_reader(path: str) -> Tuple[Reader, Callable[[], None]]:
    """Open a raw device read-only and return (reader, closer)."""
    fd = os.open(path, os.O_RDONLY)

    def _read(offset: int, length: int) -> bytes:
        return os.pread(fd, length, offset)

    def _close() -> None:
        os.close(fd)

    return _read, _close


def _bisect(reader: Reader, offset: int, length: int, block_size: int, bad: List[List[int]]) -> int:
    """Recursively find failing blocks inside [offset, offset+length). Returns bytes confirmed bad."""
    if length <= block_size:
        try:
            reader(offset, length)
            return 0
        except OSError:
            bad.append([offset, length])
            return length
    half = align_down(length // 2, block_size) or block_size
    total = 0
    for off, ln in ((offset, half), (offset + half, length - half)):
        if ln <= 0:
            continue
        try:
            reader(off, ln)
        except OSError:
            total += _bisect(reader, off, ln, block_size, bad)
    return total


def scan(reader: Reader, badmap: BadMap, chunk_bytes: int = 1 << 20, end: Optional[int] = None,
         progress: Optional[Callable[[BadMap, float], None]] = None, checkpoint: Optional[Callable[[BadMap], None]] = None,
         checkpoint_every: int = 256, slow_threshold_s: float = 2.0) -> BadMap:
    """Scan from badmap.next_offset to `end` (default: total). Resumable via the badmap."""
    bs = badmap.block_size
    chunk = max(bs, align_down(chunk_bytes, bs))
    end = badmap.total_bytes if end is None else min(end, badmap.total_bytes)
    if not badmap.started:
        badmap.started = now_iso()
    offset = align_down(badmap.next_offset, bs)
    n = 0
    t_begin = time.time()
    while offset < end:
        length = min(chunk, end - offset)
        t0 = time.time()
        try:
            data = reader(offset, length)
            if len(data) < length:
                # Short read at a boundary we did not expect: treat remainder as unreadable.
                if len(data) == 0:
                    raise OSError(errno.EIO, "zero-length read")
                length_ok = align_down(len(data), bs)
                badmap.read_errors += 1
                badmap.bad_ranges.append([offset + length_ok, length - length_ok])
        except OSError:
            badmap.read_errors += 1
            _bisect(reader, offset, length, bs, badmap.bad_ranges)
        dt = time.time() - t0
        if dt > slow_threshold_s:
            badmap.slow_ranges.append([offset, length])
        offset += length
        badmap.next_offset = offset
        badmap.scanned_bytes += length
        n += 1
        if progress:
            elapsed = max(time.time() - t_begin, 1e-6)
            progress(badmap, badmap.scanned_bytes / elapsed)
        if checkpoint and n % checkpoint_every == 0:
            badmap.bad_ranges = merge_ranges(badmap.bad_ranges)
            checkpoint(badmap)
    badmap.bad_ranges = merge_ranges(badmap.bad_ranges)
    if badmap.complete:
        badmap.finished = now_iso()
    if checkpoint:
        checkpoint(badmap)
    return badmap


def verify_ranges(reader: Reader, ranges: List[List[int]], block_size: int) -> Tuple[List[List[int]], List[List[int]]]:
    """Re-read ranges block by block. Returns (now_readable, still_bad)."""
    good: List[List[int]] = []
    bad: List[List[int]] = []
    for off, ln in ranges:
        off = align_down(off, block_size)
        ln = align_up(ln, block_size)
        for b in range(off, off + ln, block_size):
            try:
                reader(b, block_size)
                good.append([b, block_size])
            except OSError:
                bad.append([b, block_size])
    return merge_ranges(good), merge_ranges(bad)
