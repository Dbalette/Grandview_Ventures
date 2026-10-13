"""File-level rescue: plan what to copy, then copy it with exact progress.

Unreadable parts of a file are zero-filled and logged instead of aborting the
whole copy, so one bad sector costs you one block, not the file or the job.
Two destinations are supported: a local folder (including a mounted network
share) and another computer over SSH, streamed as tar so nothing has to be
installed on either side.
"""
from __future__ import annotations

import fnmatch
import os
import re
import shlex
import subprocess
import tarfile
import tempfile
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterator, List, Optional, Sequence, Tuple

from .rawio import pread_full

BLOCK = 1024 * 1024
SMALL = 4096

# Never worth copying: the OS regenerates these.
ALWAYS_SKIP_NAMES = {
    ".Spotlight-V100", ".fseventsd", ".Trashes", ".DocumentRevisions-V100",
    ".TemporaryItems", ".MobileBackups", ".PKInstallSandboxManager", "lost+found",
}
# --skip-replaceable: caches, trash and installers you can download again.
REPLACEABLE_PATTERNS = [
    "Library/Caches", "*/Library/Caches", ".Trash", "*/.Trash",
    "node_modules", "*/node_modules", "*.dmg", "*.pkg",
]
# --skip-os: top-level folders of a whole macOS volume that a reinstall recreates.
OS_TOP_LEVEL = {
    "System", "usr", "bin", "sbin", "private", "Library", "Applications",
    "cores", "dev", "Volumes", "Network", "home", "net", "opt",
}
DEFAULT_PRIORITY = [
    pat
    for name in ("Desktop", "Documents", "Pictures", "Movies", "Music", "Dropbox")
    for pat in (name, f"Users/*/{name}")
]


class TransferError(Exception):
    pass


@dataclass
class Entry:
    path: str
    rel: str
    kind: str            # "file" | "dir" | "symlink"
    size: int = 0
    mtime: float = 0.0
    mode: int = 0o644


@dataclass
class Plan:
    entries: List[Entry] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    skipped: int = 0

    @property
    def files(self) -> List[Entry]:
        return [e for e in self.entries if e.kind == "file"]

    @property
    def total_bytes(self) -> int:
        return sum(e.size for e in self.entries)


def _compile(patterns: Sequence[str]) -> List["re.Pattern[str]"]:
    return [re.compile(fnmatch.translate(p.lower())) for p in patterns]


def build_plan(
    root: str,
    priority: Optional[Sequence[str]] = None,
    skip_replaceable: bool = False,
    skip_os: bool = False,
    excludes: Sequence[str] = (),
) -> Plan:
    """Walk `root` (metadata only) and decide what to copy and in which order."""
    root = os.path.abspath(root)
    plan = Plan()
    exclude_res = _compile(list(excludes) + (REPLACEABLE_PATTERNS if skip_replaceable else []))
    priority_pats = list(DEFAULT_PRIORITY if priority is None else priority)
    priority_res = [(re.compile(fnmatch.translate(p.lower())), re.compile(fnmatch.translate(p.lower() + "/*")))
                    for p in priority_pats]

    stack = [""]
    while stack:
        rel_dir = stack.pop()
        abs_dir = os.path.join(root, rel_dir) if rel_dir else root
        try:
            with os.scandir(abs_dir) as it:
                children = sorted(it, key=lambda e: e.name)
        except OSError as exc:
            plan.errors.append(f"{rel_dir or '.'}: {exc.strerror or exc}")
            continue
        for ent in children:
            rel = f"{rel_dir}/{ent.name}" if rel_dir else ent.name
            lowered = rel.lower()
            if (
                ent.name in ALWAYS_SKIP_NAMES
                or (skip_os and not rel_dir and ent.name in OS_TOP_LEVEL)
                or any(r.match(lowered) for r in exclude_res)
            ):
                plan.skipped += 1
                continue
            try:
                if ent.is_symlink():
                    plan.entries.append(Entry(ent.path, rel, "symlink"))
                elif ent.is_dir(follow_symlinks=False):
                    st = ent.stat(follow_symlinks=False)
                    plan.entries.append(Entry(ent.path, rel, "dir", 0, st.st_mtime, st.st_mode & 0o777))
                    stack.append(rel)
                elif ent.is_file(follow_symlinks=False):
                    st = ent.stat(follow_symlinks=False)
                    plan.entries.append(Entry(ent.path, rel, "file", st.st_size, st.st_mtime, st.st_mode & 0o777))
            except OSError as exc:
                plan.errors.append(f"{rel}: {exc.strerror or exc}")

    def key(entry: Entry) -> Tuple[int, str]:
        lowered = entry.rel.lower()
        for index, (exact, inside) in enumerate(priority_res):
            if exact.match(lowered) or inside.match(lowered):
                return index, entry.rel
        return len(priority_res), entry.rel

    plan.entries.sort(key=key)
    return plan


# --- reading with salvage --------------------------------------------------

def read_salvaging(
    fd: int, size: int, damaged: List[List[int]], block: int = BLOCK, small: int = SMALL
) -> Iterator[bytes]:
    """Yield exactly `size` bytes; unreadable blocks come back as zeros and are logged."""
    def note(offset: int, length: int) -> None:
        if damaged and damaged[-1][0] + damaged[-1][1] == offset:
            damaged[-1][1] += length
        else:
            damaged.append([offset, length])

    offset = 0
    while offset < size:
        want = min(block, size - offset)
        try:
            data = pread_full(fd, want, offset)
        except OSError:
            pieces = []
            for sub in range(offset, offset + want, small):
                sub_len = min(small, offset + want - sub)
                try:
                    part = pread_full(fd, sub_len, sub)
                except OSError:
                    part = b""
                if len(part) < sub_len:
                    note(sub + len(part), sub_len - len(part))
                    part += b"\0" * (sub_len - len(part))
                pieces.append(part)
            data = b"".join(pieces)
        else:
            if len(data) < want:
                note(offset + len(data), want - len(data))
                data += b"\0" * (want - len(data))
        yield data
        offset += want


class SalvageReader:
    """File-like wrapper that always returns exactly the bytes requested (tar needs that)."""

    def __init__(self, fd: int, size: int, damaged: List[List[int]], on_bytes: Callable[[int], None]):
        self._gen = read_salvaging(fd, size, damaged)
        self._view = memoryview(b"")
        self._pos = 0
        self._on_bytes = on_bytes

    def read(self, n: int = -1) -> bytes:
        if n is None or n < 0:
            n = 1 << 62
        out = []
        need = n
        while need > 0:
            if self._pos >= len(self._view):
                try:
                    self._view = memoryview(next(self._gen))
                except StopIteration:
                    break
                self._pos = 0
            take = min(need, len(self._view) - self._pos)
            out.append(bytes(self._view[self._pos:self._pos + take]))
            self._pos += take
            need -= take
        data = b"".join(out)
        self._on_bytes(len(data))
        return data


# --- stats -----------------------------------------------------------------

class TransferStats:
    def __init__(self, total_bytes: int, total_files: int, clock: Callable[[], float] = time.monotonic):
        self.total_bytes = total_bytes
        self.total_files = total_files
        self.bytes_done = 0
        self.files_done = 0
        self.files_skipped = 0
        self.current = ""
        self.errors: List[Tuple[str, str]] = []
        self.damaged: Dict[str, List[List[int]]] = {}
        self.started = clock()

    def add_bytes(self, n: int) -> None:
        self.bytes_done += n


Tick = Callable[[], None]


def _err_text(exc: OSError) -> str:
    return exc.strerror or str(exc)


# --- local destination -------------------------------------------------------

class LocalBackend:
    def __init__(self, dest_root: str):
        self.dest_root = os.path.abspath(dest_root)
        self.description = self.dest_root

    def prepare(self) -> None:
        os.makedirs(self.dest_root, exist_ok=True)

    def run(self, entries: List[Entry], stats: TransferStats, tick: Tick) -> None:
        for entry in entries:
            stats.current = entry.rel
            dest = os.path.join(self.dest_root, *entry.rel.split("/"))
            try:
                if entry.kind == "dir":
                    os.makedirs(dest, exist_ok=True)
                elif entry.kind == "symlink":
                    if not os.path.lexists(dest):
                        os.makedirs(os.path.dirname(dest), exist_ok=True)
                        os.symlink(os.readlink(entry.path), dest)
                else:
                    self._copy_file(entry, dest, stats, tick)
            except OSError as exc:
                stats.errors.append((entry.rel, _err_text(exc)))
            tick()

    def _copy_file(self, entry: Entry, dest: str, stats: TransferStats, tick: Tick) -> None:
        if os.path.isfile(dest) and os.path.getsize(dest) == entry.size:
            stats.add_bytes(entry.size)
            stats.files_skipped += 1
            stats.files_done += 1
            return
        fd = os.open(entry.path, os.O_RDONLY)  # OSError here = file unreadable, caller logs it
        try:
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            damaged: List[List[int]] = []
            partial = dest + ".partial"
            with open(partial, "wb") as out:
                for block in read_salvaging(fd, entry.size, damaged):
                    out.write(block)
                    stats.add_bytes(len(block))
                    tick()
            os.replace(partial, dest)
            os.utime(dest, (entry.mtime, entry.mtime))
            os.chmod(dest, entry.mode | 0o600)
            if damaged:
                stats.damaged[entry.rel] = damaged
            stats.files_done += 1
        finally:
            os.close(fd)


# --- SSH destination (tar stream) ----------------------------------------------

_SSH_DEST = re.compile(r"^(?P<host>[\w.-]+@[\w.-]+):(?P<path>.*)$")


def parse_destination(dest: str) -> Tuple[str, str, str]:
    """('ssh', 'user@host', 'path') for user@host:path, otherwise ('local', '', path)."""
    match = _SSH_DEST.match(dest)
    if match:
        return "ssh", match.group("host"), match.group("path")
    return "local", "", dest


def remote_path(path: str) -> str:
    """Quote a remote path but still let ~ mean the remote home folder."""
    if path == "~":
        return '"$HOME"'
    if path.startswith("~/"):
        return '"$HOME"/' + shlex.quote(path[2:])
    return shlex.quote(path or ".")


class SshTarBackend:
    def __init__(self, host: str, path: str, ssh_cmd: Sequence[str] = ("ssh",)):
        self.host = host
        self.path = path
        self.ssh = list(ssh_cmd)
        self.description = f"{host}:{path}"

    def _remote(self, command: str) -> List[str]:
        return self.ssh + [self.host, command]

    def prepare(self) -> None:
        proc = subprocess.run(
            self._remote(f"mkdir -p {remote_path(self.path)}"), capture_output=True, text=True
        )
        if proc.returncode != 0:
            raise TransferError(
                f"Cannot reach {self.host} or create {self.path}: {proc.stderr.strip() or 'ssh failed'}"
            )

    def existing(self) -> Dict[str, int]:
        """Files already on the remote side (name -> size), so a re-run resumes."""
        command = f"cd {remote_path(self.path)} 2>/dev/null && find . -type f -printf '%P\\t%s\\n'"
        proc = subprocess.run(self._remote(command), capture_output=True, text=True, errors="replace")
        found: Dict[str, int] = {}
        if proc.returncode != 0:
            return found
        for line in proc.stdout.splitlines():
            name, _, size = line.rpartition("\t")
            if name and size.isdigit():
                found[name] = int(size)
        return found

    def run(self, entries: List[Entry], stats: TransferStats, tick: Tick) -> None:
        existing = self.existing()
        command = f"tar -xpf - -C {remote_path(self.path)}"
        errfile = tempfile.TemporaryFile()
        proc = subprocess.Popen(
            self._remote(command), stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=errfile
        )
        tar = tarfile.open(fileobj=proc.stdin, mode="w|", format=tarfile.GNU_FORMAT)

        def on_bytes(n: int) -> None:
            stats.add_bytes(n)
            tick()

        try:
            try:
                for entry in entries:
                    stats.current = entry.rel
                    self._send(tar, entry, existing, stats, on_bytes)
                    tick()
                tar.close()
                proc.stdin.close()
            except (BrokenPipeError, ValueError) as exc:
                self._abandon(tar, proc)
                raise TransferError(
                    f"The connection to {self.host} was lost ({exc}). Run the same command again to resume."
                )
            except BaseException:
                self._abandon(tar, proc)
                raise
            finally:
                code = proc.wait()
            if code != 0:
                errfile.seek(0)
                message = errfile.read().decode("utf-8", errors="replace").strip()
                raise TransferError(f"The remote tar failed (exit {code}): {message or 'no message'}")
        finally:
            errfile.close()

    @staticmethod
    def _abandon(tar, proc) -> None:
        """Stop a broken transfer quietly (tar and the pipe would otherwise complain on cleanup)."""
        proc.kill()
        for closer in (tar.fileobj.close, proc.stdin.close):
            try:
                closer()
            except (OSError, ValueError):
                pass

    @staticmethod
    def _send(tar, entry: Entry, existing: Dict[str, int], stats: TransferStats, on_bytes) -> None:
        info = tarfile.TarInfo(entry.rel)
        info.mtime = entry.mtime
        info.uid = info.gid = 0
        info.uname = info.gname = ""
        if entry.kind == "dir":
            info.type = tarfile.DIRTYPE
            info.mode = entry.mode | 0o700
            tar.addfile(info)
            return
        if entry.kind == "symlink":
            try:
                info.linkname = os.readlink(entry.path)
            except OSError as exc:
                stats.errors.append((entry.rel, _err_text(exc)))
                return
            info.type = tarfile.SYMTYPE
            info.mode = 0o777
            tar.addfile(info)
            return
        if existing.get(entry.rel) == entry.size:
            stats.add_bytes(entry.size)
            stats.files_skipped += 1
            stats.files_done += 1
            return
        try:
            fd = os.open(entry.path, os.O_RDONLY)
        except OSError as exc:
            stats.errors.append((entry.rel, _err_text(exc)))
            return
        try:
            damaged: List[List[int]] = []
            info.type = tarfile.REGTYPE
            info.size = entry.size
            info.mode = entry.mode | 0o600
            tar.addfile(info, SalvageReader(fd, entry.size, damaged, on_bytes))
            if damaged:
                stats.damaged[entry.rel] = damaged
            stats.files_done += 1
        finally:
            os.close(fd)


# --- listings for verification -------------------------------------------------

def list_local(root: str) -> Dict[str, int]:
    sizes: Dict[str, int] = {}
    root = os.path.abspath(root)
    for base, _dirs, files in os.walk(root):
        for name in files:
            full = os.path.join(base, name)
            if name.endswith(".partial"):
                continue
            try:
                sizes[os.path.relpath(full, root).replace(os.sep, "/")] = os.path.getsize(full)
            except OSError:
                pass
    return sizes
