"""Command-line interface: drives, check, scan, image, rescue, verify, status, refresh-plan, doctor."""
from __future__ import annotations

import argparse
import glob
import os
import shlex
import shutil
import signal
import subprocess
import sys
import time
from typing import List, Optional, Tuple

from . import __version__
from .devices import Drive, Volume, detect_system, list_drives, resolve_target
from .health import Level, assess, collect_findings
from .imaging import Imager, RangeMap, open_image
from .plan import refresh_plan
from .progress import Progress, SlowWatcher, render_bar
from .rawio import open_reader
from .safety import (
    dest_on_source_drive, enough_space, full_disk_access_status, mounted_warning, permission_hint,
)
from .scan import MIB, ScanReport, run_scan
from .transfer import (
    LocalBackend, SshTarBackend, TransferError, TransferStats, build_plan, list_local, parse_destination,
)
from .util import format_duration, human_bytes, read_json, run, write_json
from .verify import compare

DEFAULT_WORKDIR = os.path.join("~", "driverescue-work")


# --- small helpers ------------------------------------------------------------

class StopFlag:
    """First Ctrl+C asks the job to stop cleanly; a second one quits immediately."""

    def __init__(self) -> None:
        self.stop = False
        self._previous = None

    def __call__(self) -> bool:
        return self.stop

    def install(self) -> None:
        def handler(signum, frame):
            if self.stop:
                raise KeyboardInterrupt
            self.stop = True
            print("\nStopping safely after the current block... (Ctrl+C again to quit at once)")

        self._previous = signal.signal(signal.SIGINT, handler)

    def restore(self) -> None:
        if self._previous is not None:
            signal.signal(signal.SIGINT, self._previous)
            self._previous = None


class StatusFile:
    """A small JSON file other terminals can read with `driverescue status`."""

    def __init__(self, workdir: str, job: str):
        self.path = os.path.join(workdir, f"status-{job}.json")
        self.job = job
        self.started = time.time()
        self._last = 0.0

    def write(self, done: float, total: float, speed: float, note: str = "",
              finished: bool = False, force: bool = False, **extra) -> None:
        now = time.time()
        if not force and not finished and now - self._last < 5.0:
            return
        self._last = now
        write_json(self.path, {
            "job": self.job, "pid": os.getpid(), "started": self.started, "updated": now,
            "done": done, "total": total, "speed": speed, "note": note, "finished": finished, **extra,
        })


def _workdir(args) -> str:
    path = os.path.abspath(os.path.expanduser(args.workdir))
    os.makedirs(path, exist_ok=True)
    return path


def _keep_awake(system: str) -> None:
    """Stop a Mac from sleeping mid-job (caffeinate exits when this process does)."""
    if system == "macos" and shutil.which("caffeinate"):
        try:
            subprocess.Popen(["caffeinate", "-i", "-w", str(os.getpid())])
        except OSError:
            pass


def _find_drive(target: str, system: str) -> Optional[Tuple[Drive, Optional[Volume]]]:
    found = resolve_target(target, list_drives(include_internal=True, system=system))
    if not found:
        print(f"Could not find a drive matching '{target}'. These are connected:")
        _print_drives(list_drives(include_internal=True, system=system))
    return found


def _print_drives(drives: List[Drive]) -> None:
    if not drives:
        print("No drives found. Check the cable, then run `driverescue doctor`.")
        return
    print(f"{'ID':<9}{'SIZE':<11}{'MODEL':<24}{'BUS':<8}VOLUMES")
    for d in drives:
        size = human_bytes(d.size) if d.size else "?"
        tag = " (internal)" if d.internal else ""
        vols = "; ".join(
            f"{v.name or v.identifier}" + (f" [{v.mount_point}]" if v.mount_point else " [not mounted]")
            for v in d.volumes
        ) or "-"
        print(f"{d.identifier:<9}{size:<11}{(d.model or '?')[:22]:<24}{d.bus or '?':<8}{vols}{tag}")


# --- drives / doctor -------------------------------------------------------------

def cmd_drives(args) -> int:
    _print_drives(list_drives(include_internal=args.all))
    return 0


def cmd_doctor(args) -> int:
    system = detect_system()
    print(f"driverescue {__version__}  |  system: {system}  |  python {sys.version.split()[0]}")
    print(f"Running as: {'administrator (root)' if hasattr(os, 'geteuid') and os.geteuid() == 0 else 'normal user'}")
    tools = ["diskutil", "caffeinate"] if system == "macos" else ["lsblk", "e2fsck"]
    for tool in tools + ["smartctl", "ssh", "tar"]:
        print(f"  {tool:<11} {'found' if shutil.which(tool) else 'NOT found'}")
    if system == "macos":
        fda = full_disk_access_status(system)
        print(f"Full Disk Access for this terminal: {fda.upper()}")
        if fda == "off":
            print("  Needed only for raw reads (scan, image). Fix: System Settings > Privacy & Security >")
            print("  Full Disk Access > switch on your terminal app, then quit it (Cmd+Q) and reopen.")
            print("  The 'rescue' command (copy files from a mounted drive) does not need it.")
    workdir = _workdir(args)
    print(f"Work folder (logs, maps, reports): {workdir}")
    return 0


# --- check ---------------------------------------------------------------------

_EXIT = {Level.OK: 0, Level.WATCH: 1, Level.RESCUE_NOW: 2, Level.FAILING: 2}


def cmd_check(args) -> int:
    system = detect_system()
    found = _find_drive(args.target, system)
    if not found:
        return 1
    drive, volume = found
    print(f"Drive {drive.identifier}: {drive.model or '?'}  {human_bytes(drive.size) if drive.size else '?'}  {drive.bus}")
    for v in drive.volumes:
        print(f"  volume {v.name or v.identifier} ({v.identifier}) {'mounted at ' + v.mount_point if v.mount_point else 'not mounted'}")
    if not args.no_fsck:
        print("Running read-only checks (the file system check can take several minutes)...", flush=True)
    findings = collect_findings(drive, volume, system, do_fsck=not args.no_fsck)
    verdict = assess(findings)

    print("\nFindings")
    for f in findings:
        print(f"  [{f.level.name}] {f.summary}")
        if f.detail:
            print(f"      {f.detail}")
    print(f"\nVerdict: {verdict.headline}")
    print("What to do")
    for i, line in enumerate(verdict.advice, 1):
        print(f"  {i}. {line}")
    out = os.path.join(_workdir(args), f"check-{drive.identifier}.json")
    write_json(out, {"drive": drive.identifier, "model": drive.model, "verdict": verdict.to_dict(), "time": time.time()})
    print(f"\nSaved report: {out}")
    return _EXIT[verdict.level]


# --- scan / image (raw device access) ------------------------------------------------

def _raw_target(args, system: str) -> Optional[Tuple[str, int, Optional[Drive]]]:
    """Return (path to read, size in bytes, drive) or None after printing why not."""
    if os.path.isfile(args.target):
        return args.target, os.path.getsize(args.target), None
    found = _find_drive(args.target, system)
    if not found:
        return None
    drive = found[0]
    size = args.size or drive.size
    if not size:
        print("Could not work out the drive's size; pass --size BYTES.")
        return None
    if drive.mount_points and not args.allow_mounted:
        if args.unmount and system == "macos":
            rc, out, err = run(["diskutil", "unmountDisk", drive.identifier])
            print((out or err).strip())
            if rc != 0:
                print("Could not unmount. Find what holds it with: sudo lsof \"/Volumes/NAME\" | head")
                return None
        else:
            print("\n".join(mounted_warning(drive, system)))
            return None
    return drive.raw_node, int(size), drive


def cmd_scan(args) -> int:
    system = detect_system()
    target = _raw_target(args, system)
    if not target:
        return 2
    path, size, drive = target
    workdir = _workdir(args)
    report_path = os.path.join(workdir, f"scan-{os.path.basename(path)}.json")
    report = None
    if args.resume and os.path.exists(report_path):
        report = ScanReport.from_dict(read_json(report_path))
        print(f"Resuming from {human_bytes(report.next_offset)}")
    try:
        read_at, close = open_reader(path)
    except OSError as exc:
        print(permission_hint(exc, system, f"scan {args.target}"))
        return 1
    _keep_awake(system)
    stop = StopFlag()
    stop.install()
    prog = Progress(size)
    status = StatusFile(workdir, "scan")
    last_save = [time.monotonic()]

    def on_progress(offset: int, total: int, rep: ScanReport) -> None:
        note = f"bad:{len(rep.bad_ranges)} slow:{len(rep.slow_chunks)}"
        prog.update(offset, note)
        status.write(offset, total, prog.rate.rate(), note)
        if time.monotonic() - last_save[0] > 10:
            write_json(report_path, rep.to_dict())
            last_save[0] = time.monotonic()

    print(f"Scanning {path} ({human_bytes(size)}) read-only. Ctrl+C stops safely; --resume continues.")
    try:
        rep = run_scan(read_at, size, chunk=args.chunk_mb * MIB, progress=on_progress,
                       report=report, should_stop=stop)
    except OSError as exc:
        prog.finish()
        print(permission_hint(exc, system, f"scan {args.target}"))
        return 1
    finally:
        close()
        stop.restore()
    prog.finish()
    write_json(report_path, rep.to_dict())
    status.write(rep.next_offset, size, 0.0, "done" if rep.complete else "stopped", finished=rep.complete, force=True)
    print("\n".join(rep.summary_lines()))
    print(f"Saved report: {report_path}")
    if not rep.complete:
        print("Stopped early. Run the same command with --resume to continue.")
        return 130
    return 2 if rep.bad_ranges else 0


def cmd_image(args) -> int:
    system = detect_system()
    target = _raw_target(args, system)
    if not target:
        return 2
    path, size, drive = target
    dest = os.path.abspath(args.dest)
    map_path = os.path.abspath(args.map or dest + ".map.json")
    if drive:
        problem = dest_on_source_drive(dest, drive)
        if problem:
            print(problem)
            return 2
    resume = os.path.exists(dest) and os.path.exists(map_path)
    if os.path.exists(dest) and not resume:
        print(f"{dest} already exists and there is no map file to resume from. Choose another name.")
        return 2
    if not resume:
        enough, free = enough_space(dest, size)
        if not enough:
            print(f"Not enough free space for the image: need {human_bytes(size)}, have {human_bytes(free)}.")
            return 2
    try:
        read_at, close = open_reader(path)
    except OSError as exc:
        print(permission_hint(exc, system, f"image {args.target} {args.dest}"))
        return 1
    try:
        rmap = RangeMap.load(map_path, size) if resume else RangeMap(size)
        dest_fd = open_image(dest, size, resume)
    except (OSError, ValueError) as exc:
        close()
        print(f"Cannot prepare the image file: {exc}")
        return 2
    _keep_awake(system)
    stop = StopFlag()
    stop.install()
    prog = Progress(size)
    status = StatusFile(_workdir(args), "image")
    last = [0.0]

    def on_progress(phase: str, imager: Imager) -> None:
        now = time.monotonic()
        if now - last[0] < 0.5:
            return
        last[0] = now
        done = size - imager.rmap.total("?") - imager.rmap.total("s")
        note = f"{phase}; bad {human_bytes(imager.rmap.total('-'))}"
        prog.update(done, note)
        status.write(done, size, prog.rate.rate(), note)

    print(f"{'Resuming' if resume else 'Imaging'} {path} -> {dest}\nMap file: {map_path}")
    imager = Imager(read_at, dest_fd, rmap, chunk=args.chunk_mb * MIB, retries=args.retries,
                    progress=on_progress, map_path=map_path, should_stop=stop)
    try:
        result = imager.run()
    finally:
        close()
        os.close(dest_fd)
        stop.restore()
    prog.finish()
    status.write(size - result.untried, size, 0.0, "done" if result.complete else "stopped",
                 finished=result.complete, force=True)
    print(f"Recovered {human_bytes(result.finished)} of {human_bytes(size)} "
          f"({result.recovered_fraction * 100:.3f}%). Unreadable: {human_bytes(result.bad)}.")
    if result.interrupted:
        print("Stopped early. Run the same command again to resume.")
        return 130
    print("Open the image read-only to browse it:")
    if system == "macos":
        print(f"  hdiutil attach -readonly -imagekey diskimage-class=CRawDiskImage {shlex.quote(dest)}")
    else:
        print(f"  sudo losetup -r -f --show -P {shlex.quote(dest)}   # then mount the partition read-only")
    return 2 if result.bad else 0


# --- rescue / verify -----------------------------------------------------------------

def _plan_from(args):
    priority = [p.strip() for p in args.priority.split(",") if p.strip()] if args.priority is not None else None
    return build_plan(args.source, priority=priority, skip_replaceable=args.skip_replaceable,
                      skip_os=args.skip_os, excludes=args.exclude or [])


def _print_plan(plan, source: str) -> None:
    folders = sum(1 for e in plan.entries if e.kind == "dir")
    print(f"Plan for {source}: {len(plan.files):,} files in {folders:,} folders, "
          f"{human_bytes(plan.total_bytes)}; {plan.skipped:,} items skipped by filters.")
    if plan.errors:
        print(f"{len(plan.errors)} folder(s)/item(s) could not be listed (first few):")
        for line in plan.errors[:5]:
            print(f"  {line}")


def _backend_for(args):
    kind, host, path = parse_destination(args.dest)
    if kind == "ssh":
        return SshTarBackend(host, path, shlex.split(args.ssh_cmd))
    return LocalBackend(path)


def cmd_rescue(args) -> int:
    system = detect_system()
    if not os.path.isdir(args.source):
        print(f"Source folder not found: {args.source}")
        return 2
    plan = _plan_from(args)
    _print_plan(plan, args.source)
    if args.dry_run:
        by_top = {}
        for e in plan.entries:
            top = e.rel.split("/")[0]
            by_top[top] = by_top.get(top, 0) + e.size
        print("Biggest top-level folders:")
        for name, size in sorted(by_top.items(), key=lambda kv: -kv[1])[:12]:
            print(f"  {human_bytes(size):>10}  {name}")
        return 0
    backend = _backend_for(args)
    try:
        backend.prepare()
    except (TransferError, OSError) as exc:
        print(exc)
        return 2
    if isinstance(backend, LocalBackend):
        present = list_local(backend.dest_root)  # a re-run only needs room for what is still missing
        needed = sum(e.size for e in plan.files if present.get(e.rel) != e.size)
        enough, free = enough_space(os.path.join(backend.dest_root, "x"), needed)
        if not enough:
            print(f"Not enough free space at the destination: need {human_bytes(needed)}, "
                  f"have {human_bytes(free)}.")
            return 2

    workdir = _workdir(args)
    _keep_awake(system)
    stats = TransferStats(plan.total_bytes, len(plan.files))
    prog = Progress(plan.total_bytes)
    watcher = SlowWatcher(threshold_bps=args.slow_mbps * 1e6)
    status = StatusFile(workdir, "rescue")
    last = [0.0]

    def say(message: str) -> None:
        if prog.tty:
            sys.stdout.write("\n")
        print(message, flush=True)

    def tick() -> None:
        now = time.monotonic()
        if now - last[0] < 0.5:
            return
        last[0] = now
        note = f"{stats.files_done:,}/{stats.total_files:,} files  {stats.current[-34:]}"
        prog.update(stats.bytes_done, note)
        status.write(stats.bytes_done, stats.total_bytes, prog.rate.rate(), note,
                     errors=len(stats.errors), damaged_files=len(stats.damaged))
        if watcher.check(stats.bytes_done):
            say(
                f"Speed has been under {args.slow_mbps:g} MB/s for a while. Likely causes: a weak area of the "
                "drive (run `driverescue scan` on it), a long run of small files, a slow link (Wi-Fi instead of a "
                "cable) or a slow destination. The copy is still safe and keeps going."
            )

    print(f"Copying to {backend.description} (priority folders first). Ctrl+C is safe: re-run to resume.")
    interrupted = True
    try:
        backend.run(plan.entries, stats, tick)
        interrupted = False
    except TransferError as exc:
        prog.finish()
        print(exc)
    except KeyboardInterrupt:
        prog.finish()
        print("Interrupted. Run the same command again to resume where it stopped.")
        raise
    finally:
        _write_rescue_logs(workdir, stats)
        status.write(stats.bytes_done, stats.total_bytes, 0.0, "done" if not interrupted else "stopped",
                     finished=not interrupted, force=True,
                     errors=len(stats.errors), damaged_files=len(stats.damaged))
    prog.finish()
    if interrupted:
        return 1
    elapsed = time.monotonic() - stats.started
    print(f"Done in {format_duration(elapsed)}: {stats.files_done:,} files, {human_bytes(stats.bytes_done)} "
          f"({stats.files_skipped:,} already there).")
    if stats.errors:
        print(f"{len(stats.errors)} file(s) could not be opened and were skipped (see {workdir}/rescue-errors.log).")
    if stats.damaged:
        print(f"{len(stats.damaged)} file(s) copied with unreadable parts zero-filled (see {workdir}/rescue-damaged.json).")
    print("Next: driverescue verify (same source and destination) to confirm nothing is missing.")
    return 3 if (stats.errors or stats.damaged) else 0


def _write_rescue_logs(workdir: str, stats: TransferStats) -> None:
    with open(os.path.join(workdir, "rescue-errors.log"), "w") as handle:
        for rel, reason in stats.errors:
            handle.write(f"{rel}\t{reason}\n")
    damaged_path = os.path.join(workdir, "rescue-damaged.json")
    merged = {}
    if os.path.exists(damaged_path):
        try:
            merged = read_json(damaged_path)
        except ValueError:
            merged = {}
    merged.update(stats.damaged)
    write_json(damaged_path, merged)


def cmd_verify(args) -> int:
    if not os.path.isdir(args.source):
        print(f"Source folder not found: {args.source}")
        return 2
    plan = _plan_from(args)
    _print_plan(plan, args.source)
    backend = _backend_for(args)
    if isinstance(backend, SshTarBackend):
        dest_sizes = backend.existing()
        if not dest_sizes:
            print("Nothing found at the destination (or the remote 'find -printf' is unavailable).")
    else:
        dest_sizes = list_local(backend.dest_root)
    damaged_path = os.path.join(_workdir(args), "rescue-damaged.json")
    damaged = set(read_json(damaged_path)) if os.path.exists(damaged_path) else set()
    report = compare(plan.entries, dest_sizes, damaged)
    print("\n".join(report.summary_lines()))
    return 0 if report.ok else 2


# --- status / refresh-plan ------------------------------------------------------------

def _status_line(data: dict) -> str:
    done, total = data.get("done", 0), data.get("total", 0) or 1
    age = time.time() - data.get("updated", 0)
    line = (f"{data.get('job', '?'):<7} {render_bar(done / total)} {done / total * 100:5.1f}% "
            f"{human_bytes(done)}/{human_bytes(total)} {human_bytes(data.get('speed', 0))}/s  {data.get('note', '')}")
    if data.get("finished"):
        return line + "  [finished]"
    if age > 120:
        return line + f"  [no update for {format_duration(age)}: the job may have stopped]"
    return line


def cmd_status(args) -> int:
    workdir = _workdir(args)
    while True:
        files = sorted(glob.glob(os.path.join(workdir, "status-*.json")))
        if not files:
            print("No jobs have run yet.")
            return 0
        for path in files:
            try:
                print(_status_line(read_json(path)))
            except (OSError, ValueError):
                pass
        if not args.watch:
            return 0
        time.sleep(5)
        print()


def cmd_refresh_plan(args) -> int:
    print(refresh_plan(args.drive, detect_system()))
    return 0


# --- parser ----------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--workdir", default=DEFAULT_WORKDIR, help="where logs, maps and reports are kept")

    parser = argparse.ArgumentParser(
        prog="driverescue",
        description="Rescue data from old or failing drives. Read-only first: it never writes to the drive it is rescuing.",
    )
    parser.add_argument("--version", action="version", version=f"driverescue {__version__}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("drives", parents=[common], help="list connected drives")
    p.add_argument("--all", action="store_true", help="include internal drives")
    p.set_defaults(func=cmd_drives)

    p = sub.add_parser("doctor", parents=[common], help="check this computer is ready (tools, permissions)")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("check", parents=[common], help="read-only health check with a plain-language verdict")
    p.add_argument("target", help="drive id (disk5, sdb), device path or mount path")
    p.add_argument("--no-fsck", action="store_true", help="skip the file system check, SMART only")
    p.set_defaults(func=cmd_check)

    for name, helptext in (("scan", "read-only surface scan: finds unreadable and slow areas"),
                           ("image", "make an exact, resumable image of a whole drive")):
        p = sub.add_parser(name, parents=[common], help=helptext)
        p.add_argument("target", help="drive id (disk5, sdb), device path, or an image file")
        if name == "image":
            p.add_argument("dest", help="image file to create (on a different drive)")
            p.add_argument("--map", help="map file (default: <image>.map.json)")
            p.add_argument("--retries", type=int, default=1, help="extra tries for unreadable blocks")
        else:
            p.add_argument("--resume", action="store_true", help="continue a stopped scan")
        p.add_argument("--chunk-mb", type=int, default=8 if name == "scan" else 4, help="read size in MiB")
        p.add_argument("--size", type=int, help="drive size in bytes if it cannot be detected")
        p.add_argument("--unmount", action="store_true", help="unmount the drive's volumes first (macOS)")
        p.add_argument("--allow-mounted", action="store_true", help="read even though volumes are mounted")
        p.set_defaults(func=cmd_scan if name == "scan" else cmd_image)

    for name, helptext in (("rescue", "copy files off a mounted drive, priority folders first"),
                           ("verify", "check a rescued copy against the source")):
        p = sub.add_parser(name, parents=[common], help=helptext)
        p.add_argument("source", help="folder to copy from, e.g. \"/Volumes/EL Capitan/Users\"")
        p.add_argument("dest", help="local folder, or user@host:path to send over SSH")
        p.add_argument("--priority", help="comma list of folders to copy first (patterns allowed); default: Desktop, Documents, Pictures, Movies, Music, Dropbox")
        p.add_argument("--skip-replaceable", action="store_true", help="skip caches, trash, installers (.dmg/.pkg), node_modules")
        p.add_argument("--skip-os", action="store_true", help="skip macOS system folders when copying a whole volume")
        p.add_argument("--exclude", action="append", help="skip paths matching this pattern (repeatable)")
        p.add_argument("--ssh-cmd", default="ssh", help="ssh command for user@host destinations")
        if name == "rescue":
            p.add_argument("--dry-run", action="store_true", help="only show what would be copied and how big it is")
            p.add_argument("--slow-mbps", type=float, default=5.0, help="warn if speed stays below this (MB/s)")
            p.set_defaults(func=cmd_rescue)
        else:
            p.set_defaults(func=cmd_verify)

    p = sub.add_parser("status", parents=[common], help="show progress of a running job (use from a second terminal)")
    p.add_argument("--watch", action="store_true", help="keep refreshing every 5 seconds")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("refresh-plan", parents=[common], help="print the wipe-or-replace plan (runs nothing)")
    p.add_argument("--drive", default="diskN", help="drive id to put in the printed commands")
    p.set_defaults(func=cmd_refresh_plan)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\nInterrupted.")
        return 130
