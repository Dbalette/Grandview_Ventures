"""Read-only surface scan: read every byte once, time it, record what fails."""
from __future__ import annotations

import errno
import statistics
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Deque, Dict, List, Optional

from .rawio import ReadAt

MIB = 1024 * 1024
BUCKETS = 60
_RANK = {"?": 0, "#": 1, "~": 2, "X": 3}


@dataclass
class ScanReport:
    size: int
    chunk: int
    next_offset: int = 0
    bytes_read: int = 0
    elapsed: float = 0.0
    complete: bool = False
    bad_ranges: List[List[int]] = field(default_factory=list)       # [start, end)
    slow_chunks: List[List[float]] = field(default_factory=list)    # [offset, seconds]
    bucket_state: List[str] = field(default_factory=lambda: ["?"] * BUCKETS)
    bucket_min_mbps: List[Optional[float]] = field(default_factory=lambda: [None] * BUCKETS)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ScanReport":
        return cls(**data)

    @property
    def bad_bytes(self) -> int:
        return sum(end - start for start, end in self.bad_ranges)

    def heatmap(self) -> str:
        """One character per slice of the drive: # fine, ~ slow, X unreadable, ? not read yet."""
        return "".join(self.bucket_state)

    def summary_lines(self) -> List[str]:
        lines = [
            f"Read {self.bytes_read:,} of {self.size:,} bytes in {self.elapsed:,.0f}s",
            f"Unreadable: {len(self.bad_ranges)} region(s), {self.bad_bytes:,} bytes",
            f"Slow chunks: {len(self.slow_chunks)}",
            "Map (start -> end of drive): " + self.heatmap(),
            "  # fine   ~ slow   X unreadable   ? not read",
        ]
        if self.bad_ranges:
            lines.append("First unreadable regions (byte offsets):")
            for start, end in self.bad_ranges[:10]:
                lines.append(f"  {start:,} - {end:,}")
        return lines


def merge_ranges(ranges: List[List[int]]) -> List[List[int]]:
    merged: List[List[int]] = []
    for start, end in sorted(ranges):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return merged


def _buckets(offset: int, length: int, size: int) -> range:
    """The map slices (0..BUCKETS-1) that the byte range [offset, offset+length) touches."""
    first = min(BUCKETS - 1, offset * BUCKETS // size)
    last = min(BUCKETS - 1, (offset + max(length, 1) - 1) * BUCKETS // size)
    return range(first, last + 1)


def _raise_state(rep: ScanReport, bucket: int, state: str) -> None:
    if _RANK[state] > _RANK[rep.bucket_state[bucket]]:
        rep.bucket_state[bucket] = state


def _readable(read_at: ReadAt, offset: int, length: int) -> bool:
    try:
        return len(read_at(offset, length)) >= length
    except OSError:
        return False


def localize_bad(read_at: ReadAt, offset: int, length: int, min_block: int) -> List[List[int]]:
    """Bisect a failing range down to `min_block` pieces; returns the unreadable parts."""
    if _readable(read_at, offset, length):
        return []
    if length <= min_block:
        return [[offset, offset + length]]
    half = max(min_block, (length // 2) // min_block * min_block)
    if half >= length:
        return [[offset, offset + length]]
    return merge_ranges(
        localize_bad(read_at, offset, half, min_block)
        + localize_bad(read_at, offset + half, length - half, min_block)
    )


def run_scan(
    read_at: ReadAt,
    size: int,
    chunk: int = 8 * MIB,
    min_block: int = 64 * 1024,
    slow_factor: float = 5.0,
    slow_floor: float = 1.0,
    progress: Optional[Callable[[int, int, ScanReport], None]] = None,
    report: Optional[ScanReport] = None,
    should_stop: Optional[Callable[[], bool]] = None,
    clock: Callable[[], float] = time.monotonic,
) -> ScanReport:
    rep = report or ScanReport(size=size, chunk=chunk)
    recent: Deque[float] = deque(maxlen=200)
    started = clock()
    base_elapsed = rep.elapsed
    offset = rep.next_offset

    while offset < size:
        if should_stop and should_stop():
            break
        length = min(chunk, size - offset)
        t0 = clock()
        try:
            data = read_at(offset, length)
            ok = len(data) >= length
        except OSError as exc:
            ok = False
            if exc.errno in (errno.EPERM, errno.EACCES) and rep.bytes_read == 0 and not rep.bad_ranges:
                raise  # not a drive fault: a permission problem; let the caller explain it
        dt = clock() - t0

        state = "#"
        mbps: Optional[float] = None
        bad_here: List[List[int]] = []
        if ok:
            rep.bytes_read += length
            if len(recent) >= 10:
                median = statistics.median(recent)
                if dt > max(slow_floor, slow_factor * median):
                    rep.slow_chunks.append([offset, round(dt, 3)])
                    state = "~"
            recent.append(dt)
            mbps = length / dt / 1e6 if dt > 0 else None
        else:
            bad_here = localize_bad(read_at, offset, length, min_block)
            rep.bad_ranges = merge_ranges(rep.bad_ranges + bad_here)
            rep.bytes_read += length - sum(end - start for start, end in bad_here)

        for bucket in _buckets(offset, length, size):
            _raise_state(rep, bucket, state)
            if mbps is not None:
                current = rep.bucket_min_mbps[bucket]
                rep.bucket_min_mbps[bucket] = mbps if current is None else min(current, mbps)
        for start, end in bad_here:
            for bucket in _buckets(start, end - start, size):
                _raise_state(rep, bucket, "X")

        offset += length
        rep.next_offset = offset
        rep.elapsed = base_elapsed + (clock() - started)
        if progress:
            progress(offset, size, rep)

    rep.complete = offset >= size
    return rep
