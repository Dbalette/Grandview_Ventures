"""Low-level reads that survive short reads and report errors as OSError."""
from __future__ import annotations

import errno
import os
from typing import Callable, Tuple

ReadAt = Callable[[int, int], bytes]


def pread_full(fd: int, length: int, offset: int) -> bytes:
    """Read up to `length` bytes at `offset`; shorter only at end of file."""
    chunks = []
    got = 0
    while got < length:
        piece = os.pread(fd, length - got, offset + got)
        if not piece:
            break
        chunks.append(piece)
        got += len(piece)
    return chunks[0] if len(chunks) == 1 else b"".join(chunks)


def open_reader(path: str) -> Tuple[ReadAt, Callable[[], None]]:
    """Open `path` read-only and return (read_at, close)."""
    fd = os.open(path, os.O_RDONLY)

    def read_at(offset: int, length: int) -> bytes:
        data = pread_full(fd, length, offset)
        if len(data) < length:
            raise OSError(errno.EIO, "short read (end of device or unreadable tail)")
        return data

    def close() -> None:
        os.close(fd)

    return read_at, close


def pwrite_full(fd: int, data: bytes, offset: int) -> None:
    view = memoryview(data)
    done = 0
    while done < len(view):
        done += os.pwrite(fd, view[done:], offset + done)
