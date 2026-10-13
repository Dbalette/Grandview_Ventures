"""ddrescue-style imaging: copy what reads fast first, then work gently on the rest.

Pass 1 copies big chunks forward and skips ahead when reads keep failing.
Pass 2 splits every failed chunk down to small blocks to save what is readable.
Pass 3 retries the blocks that are still unreadable.
A map file records progress, so an interrupted image can be resumed.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

from .rawio import ReadAt, pwrite_full
from .util import read_json, write_json

MIB = 1024 * 1024
NONTRIED = "?"
FINISHED = "+"
SUSPECT = "s"
BAD = "-"


class RangeMap:
    """Sorted, non-overlapping [start, end, status] ranges covering the whole device."""

    def __init__(self, size: int, ranges: Optional[List[List]] = None):
        self.size = size
        self.ranges: List[List] = ranges if ranges is not None else [[0, size, NONTRIED]]

    def mark(self, start: int, end: int, status: str) -> None:
        if end <= start:
            return
        rebuilt: List[List] = []
        for s, e, st in self.ranges:
            if e <= start or s >= end:
                rebuilt.append([s, e, st])
                continue
            if s < start:
                rebuilt.append([s, start, st])
            if e > end:
                rebuilt.append([end, e, st])
        rebuilt.append([start, end, status])
        rebuilt.sort(key=lambda r: r[0])
        merged: List[List] = []
        for r in rebuilt:
            if merged and merged[-1][2] == r[2] and merged[-1][1] == r[0]:
                merged[-1][1] = r[1]
            else:
                merged.append(r)
        self.ranges = merged

    def spans(self, status: str) -> List[Tuple[int, int]]:
        return [(s, e) for s, e, st in self.ranges if st == status]

    def total(self, status: str) -> int:
        return sum(e - s for s, e in self.spans(status))

    def save(self, path: str) -> None:
        write_json(path, {"version": 1, "size": self.size, "ranges": self.ranges})

    @classmethod
    def load(cls, path: str, size: int) -> "RangeMap":
        data = read_json(path)
        if data.get("size") != size:
            raise ValueError(
                f"Map file {path} is for a {data.get('size')}-byte drive, not {size} bytes. "
                "Use a different map file or start a new image."
            )
        return cls(size, data["ranges"])


@dataclass
class ImageResult:
    size: int
    finished: int
    bad: int
    untried: int
    interrupted: bool = False

    @property
    def complete(self) -> bool:
        return self.untried == 0 and not self.interrupted

    @property
    def recovered_fraction(self) -> float:
        return self.finished / self.size if self.size else 1.0


def open_image(path: str, size: int, resume: bool) -> int:
    """Open (or create, sparse) the image file; never overwrites an existing image by accident."""
    if resume:
        if not os.path.exists(path):
            raise FileNotFoundError(f"Cannot resume: {path} does not exist")
        return os.open(path, os.O_RDWR)
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
    os.ftruncate(fd, size)
    return fd


class Imager:
    def __init__(
        self,
        read_at: ReadAt,
        dest_fd: int,
        rmap: RangeMap,
        chunk: int = 4 * MIB,
        min_block: int = 4096,
        retries: int = 1,
        skip_chunks: int = 8,
        fail_streak: int = 3,
        progress: Optional[Callable[[str, "Imager"], None]] = None,
        map_path: Optional[str] = None,
        should_stop: Optional[Callable[[], bool]] = None,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.read_at = read_at
        self.dest_fd = dest_fd
        self.rmap = rmap
        self.chunk = chunk
        self.min_block = min_block
        self.retries = retries
        self.skip_chunks = skip_chunks
        self.fail_streak = fail_streak
        self.progress = progress
        self.map_path = map_path
        self.should_stop = should_stop
        self.clock = clock
        self._last_save = clock()
        self.interrupted = False

    # -- bookkeeping --------------------------------------------------------
    def _stop(self) -> bool:
        if self.should_stop and self.should_stop():
            self.interrupted = True
        return self.interrupted

    def _save(self, force: bool = False) -> None:
        if not self.map_path:
            return
        now = self.clock()
        if force or now - self._last_save >= 5.0:
            self.rmap.save(self.map_path)
            self._last_save = now

    def _report(self, phase: str) -> None:
        if self.progress:
            self.progress(phase, self)

    def _copy(self, offset: int, length: int) -> bool:
        try:
            data = self.read_at(offset, length)
        except OSError:
            return False
        if len(data) < length:
            return False
        pwrite_full(self.dest_fd, data, offset)
        self.rmap.mark(offset, offset + length, FINISHED)
        return True

    # -- passes -------------------------------------------------------------
    def _forward(self) -> None:
        fails = 0
        for start, end in self.rmap.spans(NONTRIED):
            pos = start
            while pos < end:
                if self._stop():
                    return
                if fails >= self.fail_streak:
                    skip_end = min(end, pos + self.skip_chunks * self.chunk)
                    self.rmap.mark(pos, skip_end, SUSPECT)
                    pos, fails = skip_end, 0
                    continue
                length = min(self.chunk, end - pos)
                if self._copy(pos, length):
                    fails = 0
                else:
                    fails += 1
                    self.rmap.mark(pos, pos + length, SUSPECT)
                pos += length
                self._save()
                self._report("copying")

    def _split(self) -> None:
        for start, end in self.rmap.spans(SUSPECT):
            stack = [(start, end)]
            while stack:
                if self._stop():
                    return
                a, b = stack.pop()
                length = b - a
                if length > self.chunk:
                    pos = a
                    pieces = []
                    while pos < b:
                        pieces.append((pos, min(pos + self.chunk, b)))
                        pos += self.chunk
                    stack.extend(reversed(pieces))
                    continue
                if self._copy(a, length):
                    pass
                elif length <= self.min_block:
                    self.rmap.mark(a, b, BAD)
                else:
                    half = max(self.min_block, (length // 2) // self.min_block * self.min_block)
                    if half >= length:
                        self.rmap.mark(a, b, BAD)
                    else:
                        stack.append((a + half, b))
                        stack.append((a, a + half))
                self._save()
                self._report("splitting failed areas")

    def _retry(self) -> None:
        for _ in range(self.retries):
            spans = self.rmap.spans(BAD)
            if not spans:
                return
            for start, end in spans:
                pos = start
                while pos < end:
                    if self._stop():
                        return
                    self._copy(pos, min(self.min_block, end - pos))
                    pos += self.min_block
                    self._report("retrying unreadable blocks")
            self._save()

    # -- driver -------------------------------------------------------------
    def run(self) -> ImageResult:
        for step in (self._forward, self._split, self._retry):
            if self._stop():
                break
            step()
            self._save(force=True)
        try:
            os.fsync(self.dest_fd)
        except OSError:
            pass
        self._save(force=True)
        return ImageResult(
            size=self.rmap.size,
            finished=self.rmap.total(FINISHED),
            bad=self.rmap.total(BAD),
            untried=self.rmap.total(NONTRIED) + self.rmap.total(SUSPECT),
            interrupted=self.interrupted,
        )
