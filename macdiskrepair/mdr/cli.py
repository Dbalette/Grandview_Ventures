#!/usr/bin/env python3
"""Mac Disk Repair command-line interface.

    mdr doctor                      check that the tools are installed
    mdr detect                      list external physical disks
    sudo mdr health diskN           SMART + diskutil verify (read-only), graded
    sudo mdr scan diskN             read-only surface scan -> badmap.json (resumable)
    sudo mdr rescue diskN --to IMG  ddrescue multi-pass image (dry-run unless --execute)
    sudo mdr repair diskN|--image   verify, then repair filesystems (dry-run unless --execute)
    sudo mdr remap diskN            zero-fill bad blocks so the SSD retires them (needs image + --execute)
    sudo mdr revive diskN --workdir DIR   the whole sequence in the right order
    mdr report --workdir DIR        build the Markdown + JSON report

Read-only commands never write to the disk. Destructive commands dry-run by
default, print exactly what they would do, and require --execute plus a typed
confirmation.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mdr import __version__, diskutil, fsrepair, remap as remap_mod, rescue, report, safety, smart, surface  # noqa: E402
from mdr.util import ToolError, eprint, human_size, is_macos, is_root, run_stream, shell_join, which  # noqa: E402


# ---------------------------------------------------------------- helpers ---

def die(msg: str, code: int = 2) -> "NoReturn":  # type: ignore[name-defined]
    eprint(f"error: {msg}")
    sys.exit(code)


def need_macos() -> None:
    if not is_macos():
        die("this command drives macOS diskutil/hdiutil and must run on the Mac the disk is plugged into")


def need_root(what: str) -> None:
    if not is_root():
        die(f"{what} needs raw device access: re-run with sudo")


def workdir_paths(workdir: str, ident: str) -> Dict[str, str]:
    os.makedirs(workdir, exist_ok=True)
    return {
        "disk": os.path.join(workdir, f"{ident}.disk.json"),
        "smart": os.path.join(workdir, f"{ident}.smart.json"),
        "badmap": os.path.join(workdir, f"{ident}.badmap.json"),
        "image": os.path.join(workdir, f"{ident}.img"),
        "mapfile": os.path.join(workdir, f"{ident}.ddrescue.map"),
        "fs_before": os.path.join(workdir, f"{ident}.fs-verify.json"),
        "fs_after": os.path.join(workdir, f"{ident}.fs-repair.json"),
        "remap": os.path.join(workdir, f"{ident}.remap.json"),
        "rescue": os.path.join(workdir, f"{ident}.rescue.json"),
        "report_md": os.path.join(workdir, f"{ident}.report.md"),
        "report_json": os.path.join(workdir, f"{ident}.report.json"),
    }


def save_json(path: str, obj: Any) -> None:
    with open(path, "w") as fh:
        json.dump(obj, fh, indent=2, default=str)


def load_json(path: str) -> Optional[Dict[str, Any]]:
    if not os.path.exists(path):
        return None
    with open(path) as fh:
        return json.load(fh)


def print_table(rows: List[List[str]], header: List[str]) -> None:
    widths = [len(h) for h in header]
    for r in rows:
        for i, c in enumerate(r):
            widths[i] = max(widths[i], len(c))
    fmt = "  ".join("{:<" + str(w) + "}" for w in widths)
    print(fmt.format(*header))
    print(fmt.format(*["-" * w for w in widths]))
    for r in rows:
        print(fmt.format(*r))


def progress_printer(total: int):
    last = [0.0]

    def _p(bm: surface.BadMap, rate: float) -> None:
        now = time.time()
        if now - last[0] < 1.0 and bm.next_offset < total:
            return
        last[0] = now
        pct = 100.0 * bm.next_offset / total if total else 0
        remaining = (total - bm.next_offset) / rate if rate > 0 else 0
        eprint(f"\r  {pct:6.2f}%  {human_size(bm.next_offset)}  {human_size(rate)}/s  bad blocks: {bm.bad_blocks}  ETA {remaining/60:6.1f} min   ", )

    return _p


# --------------------------------------------------------------- commands ---

def cmd_doctor(args: argparse.Namespace) -> int:
    rows = []
    tools = [
        ("diskutil", "/usr/sbin/diskutil", "macOS built-in"),
        ("hdiutil", "/usr/bin/hdiutil", "macOS built-in"),
        ("fsck_apfs", "/sbin/fsck_apfs", "macOS built-in"),
        ("fsck_hfs", "/sbin/fsck_hfs", "macOS built-in"),
        ("smartctl", None, "brew install smartmontools"),
        ("ddrescue", None, "brew install ddrescue"),
        ("testdisk", None, "brew install testdisk"),
        ("photorec", None, "brew install testdisk"),
        ("f3probe", None, "brew install f3"),
        ("pv", None, "brew install pv"),
        ("sgdisk", None, "brew install gptfdisk"),
    ]
    missing = 0
    for name, fixed, how in tools:
        path = fixed if fixed and os.path.exists(fixed) else which(name)
        ok = bool(path)
        if not ok:
            missing += 1
        rows.append([name, "ok" if ok else "MISSING", path or how])
    print_table(rows, ["tool", "status", "path / install"])
    print()
    print(f"platform: {'macOS' if is_macos() else 'not macOS (only tests and parsing work here)'}; root: {is_root()}; mdr {__version__}")
    if missing:
        print(f"{missing} tool(s) missing. Run: brew bundle --file=Brewfile")
    return 0 if missing == 0 else 1


def cmd_detect(args: argparse.Namespace) -> int:
    need_macos()
    idents = diskutil.list_whole_disks(external_only=not args.all)
    boot = diskutil.boot_whole_disk()
    rows = []
    for ident in idents:
        try:
            di = diskutil.info(ident)
        except ToolError as exc:
            rows.append([ident, "?", "?", "?", "?", "?", f"error: {exc}"])
            continue
        flags = []
        if di.internal:
            flags.append("internal")
        if ident == boot:
            flags.append("BOOT")
        if di.solid_state:
            flags.append("ssd")
        rows.append([ident, di.media_name[:28], human_size(di.size, binary=False), di.protocol, di.smart_status or "n/a",
                     ",".join(flags) or "external", di.content])
    if not rows:
        print("No external physical disks found. Is the SSD powered and plugged in? Try: diskutil list")
        return 1
    print_table(rows, ["disk", "media", "size", "bus", "SMART(diskutil)", "flags", "content"])
    print()
    print("Pick the external disk, e.g.:  sudo mdr health disk4")
    return 0


def collect_disk_and_smart(ident: str) -> Tuple[diskutil.DiskInfo, smart.SmartSummary]:
    di = diskutil.info(ident)
    sm = smart.read(di.device_node)
    return di, sm


def cmd_health(args: argparse.Namespace) -> int:
    need_macos()
    ident = diskutil.normalize_identifier(args.disk)
    check = safety.check_target(ident, require_unmounted=False, allow_internal=args.allow_internal)
    if not check.ok:
        die("; ".join(check.reasons))
    di, sm = collect_disk_and_smart(ident)
    fs = None
    if not args.no_verify:
        eprint("Running read-only diskutil verify (this may take a few minutes)...")
        fs = fsrepair.check_disk(ident, repair=False).to_dict()
    badmap = None
    if args.workdir:
        paths = workdir_paths(args.workdir, ident)
        save_json(paths["disk"], di.to_dict())
        save_json(paths["smart"], sm.to_dict())
        if fs:
            save_json(paths["fs_before"], fs)
        badmap = load_json(paths["badmap"])
    assessment = report.grade(sm.to_dict(), badmap, fs)
    if args.json:
        print(report.to_json({"disk": di.to_dict(), "smart": sm.to_dict(), "smart_findings": smart.findings(sm),
                              "fs": fs, "assessment": assessment.__dict__}))
        return 0
    print(f"Disk {di.identifier}: {di.media_name}  {human_size(di.size, binary=False)}  {di.protocol}  block {di.block_size}B  "
          f"{'SSD' if di.solid_state else 'HDD/unknown'}  {'external' if di.is_external else 'INTERNAL'}")
    print(f"diskutil SMART status: {di.smart_status or 'n/a'}")
    print()
    print("SMART (smartctl):")
    for f in smart.findings(sm):
        print(f"  [{f['severity']:8}] {f['text']}")
    if fs:
        print()
        print(f"Partition map verify: {'OK' if fs['partition_map_ok'] else 'ERRORS'}")
        for v in fs["volumes"]:
            print(f"  {v['identifier']:10} {v['filesystem']:8} {v['volume_name']!r:24} verify: {'OK' if v['ok'] else 'ERRORS'}")
    print()
    print(f"Grade {assessment.label} (score {assessment.score}/100): {assessment.recommendation}")
    for r in assessment.reasons:
        print(f"  - {r}")
    if not badmap:
        print()
        print(f"Next: a surface scan finds the exact unreadable blocks:  sudo mdr scan {ident} --workdir {args.workdir or '~/mdr-work'}")
    return 0


def cmd_scan(args: argparse.Namespace) -> int:
    need_macos()
    need_root("surface scan")
    ident = diskutil.normalize_identifier(args.disk)
    check = safety.check_target(ident, require_unmounted=True, allow_internal=args.allow_internal)
    if not check.ok and not args.allow_mounted:
        die("; ".join(check.reasons) + "\n(unmounting avoids the OS writing while we read; --allow-mounted overrides)")
    di = check.info or diskutil.info(ident)
    paths = workdir_paths(args.workdir, ident)
    save_json(paths["disk"], di.to_dict())
    if os.path.exists(paths["badmap"]) and not args.restart:
        bm = surface.BadMap.load(paths["badmap"])
        eprint(f"Resuming scan at {human_size(bm.next_offset)} ({bm.bad_blocks} bad blocks so far)")
    else:
        bm = surface.BadMap(device=di.raw_node, block_size=di.block_size, total_bytes=di.size)
    reader, closer = surface.device_reader(di.raw_node)
    try:
        eprint(f"Scanning {di.raw_node} ({human_size(di.size, binary=False)}) read-only, {args.chunk_mib} MiB chunks. Ctrl-C to pause; rerun to resume.")
        surface.scan(reader, bm, chunk_bytes=args.chunk_mib << 20, progress=progress_printer(di.size),
                     checkpoint=lambda b: b.save(paths["badmap"]))
    except KeyboardInterrupt:
        bm.save(paths["badmap"])
        eprint("\nPaused. Progress saved; rerun the same command to resume.")
        return 130
    finally:
        closer()
    bm.save(paths["badmap"])
    eprint("")
    print(f"Scan complete: {bm.bad_blocks} unreadable blocks ({human_size(bm.bad_bytes)}) in {len(bm.bad_ranges)} ranges; "
          f"{len(bm.slow_ranges)} slow regions. Saved {paths['badmap']}")
    return 0 if bm.bad_blocks == 0 else 3


def cmd_rescue(args: argparse.Namespace) -> int:
    need_macos()
    ident = diskutil.normalize_identifier(args.disk)
    binary = rescue.ddrescue_path()
    if not binary:
        die("ddrescue not found: brew install ddrescue")
    check = safety.check_target(ident, require_unmounted=True, allow_internal=args.allow_internal)
    if not check.ok:
        die("; ".join(check.reasons))
    di = check.info or diskutil.info(ident)
    image = os.path.abspath(args.to)
    mapfile = args.mapfile or image + ".map"
    space = rescue.space_check(image, di.size)
    passes = [int(p) for p in args.passes.split(",") if p]
    cmds = rescue.pass_commands(di.raw_node, image, mapfile, di.block_size, passes, binary)
    print(f"Source : {di.raw_node}  {human_size(di.size, binary=False)}  block {di.block_size}B")
    print(f"Image  : {image}")
    print(f"Mapfile: {mapfile}  (keep it; it makes every pass resumable)")
    print(f"Space  : need {human_size(space['need'])}, free {human_size(space['free'])}  -> {'OK' if space['ok'] else 'NOT ENOUGH'}")
    print()
    print("Pass plan:")
    for c in cmds:
        print("  sudo " + shell_join(c))
    if not space["ok"]:
        die("not enough free space at the image destination")
    if not args.execute:
        print("\nDry run. Add --execute to run the passes.")
        return 0
    need_root("ddrescue on a raw device")
    rc = 0
    for c in cmds:
        eprint(f"\n==> {shell_join(c)}")
        rc = run_stream(c)
        if rc != 0:
            eprint(f"ddrescue exited {rc}; stopping. Rerun the same command to resume from the mapfile.")
            break
    stats = None
    if os.path.exists(mapfile):
        with open(mapfile) as fh:
            stats = rescue.parse_mapfile(fh.read())
        print(f"\nRescued {human_size(stats.rescued)} ({stats.pct_rescued():.4f}%), bad {human_size(stats.bad)}, finished={stats.finished}")
        if args.workdir:
            paths = workdir_paths(args.workdir, ident)
            save_json(paths["rescue"], {"image": image, "mapfile": mapfile, "rescued_bytes": stats.rescued, "bad_bytes": stats.bad,
                                        "pct_rescued": round(stats.pct_rescued(), 6), "finished": stats.finished,
                                        "bad_ranges": len(stats.bad_ranges)})
            if not os.path.exists(paths["badmap"]) or args.update_badmap:
                rescue.badmap_from_mapfile(open(mapfile).read(), di.raw_node, di.block_size, di.size).save(paths["badmap"])
                print(f"Bad-block map written from mapfile: {paths['badmap']}")
    return rc


def cmd_repair(args: argparse.Namespace) -> int:
    need_macos()
    attached: List[str] = []
    try:
        if args.image:
            image = os.path.abspath(args.image)
            if not os.path.exists(image):
                die(f"image not found: {image}")
            eprint(f"Attaching image {'read-only' if not args.execute else 'read-write'} without mounting...")
            attached = diskutil.attach_image(image, readonly=not args.execute)
            if not attached:
                die("hdiutil attached nothing")
            whole = attached[0]
            print(f"Image attached as {whole} (children: {', '.join(attached[1:]) or 'none'})")
            allow_internal = True  # image-backed devices are not external; safety whitelists them here
        else:
            whole = diskutil.normalize_identifier(args.disk)
            allow_internal = args.allow_internal
        check = safety.check_target(whole, require_unmounted=False, allow_internal=allow_internal)
        if not check.ok and not args.image:
            die("; ".join(check.reasons))
        eprint("Verifying (read-only)...")
        before = fsrepair.check_disk(whole, repair=False)
        _print_fs(before)
        if args.workdir:
            paths = workdir_paths(args.workdir, whole if not args.image else os.path.basename(image).split(".")[0])
            save_json(paths["fs_before"], before.to_dict())
        if before.all_ok:
            print("\nNothing to repair.")
            return 0
        if not args.execute:
            print("\nDry run. Repair would run:")
            print(f"  sudo diskutil repairDisk {whole}")
            for v in before.volumes:
                if not v.ok:
                    print(f"  sudo diskutil repairVolume {v.identifier}    # or: {v.manual_command}")
            print("Add --execute to repair. Repair the IMAGE first (--image), the original only after the data is safe.")
            return 1
        need_root("filesystem repair")
        target_name = whole
        if not args.image and not safety.confirm_typed(target_name, f"About to REPAIR filesystems on {target_name}. Repairs rewrite metadata and cannot be undone."):
            die("aborted by operator")
        after = fsrepair.check_disk(whole, repair=True)
        _print_fs(after)
        if args.workdir:
            save_json(paths["fs_after"], after.to_dict())
        return 0 if after.all_ok else 4
    finally:
        for ident in attached[:1]:
            try:
                diskutil.detach(ident)
            except ToolError as exc:
                eprint(f"warning: could not detach {ident}: {exc}")


def _print_fs(rep: fsrepair.FsReport) -> None:
    print(f"Partition map ({rep.whole_disk}): {'OK' if rep.partition_map_ok else 'ERRORS'}")
    for v in rep.volumes:
        print(f"  {v.identifier:10} {v.filesystem:8} {v.volume_name!r:24} {v.action}: {'OK' if v.ok else 'ERRORS'}")
        if not v.ok:
            tail = "\n".join(v.output.strip().splitlines()[-6:])
            for line in tail.splitlines():
                print(f"      {line}")


def cmd_remap(args: argparse.Namespace) -> int:
    need_macos()
    ident = diskutil.normalize_identifier(args.disk)
    paths = workdir_paths(args.workdir, ident)
    badmap_path = args.badmap or paths["badmap"]
    if not os.path.exists(badmap_path):
        die(f"no bad-block map at {badmap_path}; run `mdr scan` or `mdr rescue` first")
    bm = surface.BadMap.load(badmap_path)
    check = safety.check_target(ident, require_unmounted=True, allow_internal=args.allow_internal)
    if not check.ok:
        die("; ".join(check.reasons))
    di = check.info or diskutil.info(ident)
    if bm.device != di.raw_node:
        die(f"bad map is for {bm.device}, target is {di.raw_node}; identifiers change between plug-ins, rescan or pass --badmap")
    if bm.total_bytes != di.size or bm.block_size != di.block_size:
        die("bad map geometry does not match the disk; rescan")
    if not bm.bad_ranges:
        print("Bad-block map is empty; nothing to remap.")
        return 0
    image = args.image or paths["image"]
    have_image = os.path.exists(image) and os.path.getsize(image) >= bm.total_bytes
    print(f"Target : {di.raw_node}  {di.media_name}")
    print(f"Bad map: {len(bm.bad_ranges)} ranges, {bm.bad_blocks} blocks, {human_size(bm.bad_bytes)}")
    print(f"Image  : {image}  -> {'present, full size' if have_image else 'MISSING or short'}")
    print(f"Action : write {bm.block_size}-byte zero blocks over each bad block (+{args.pad} neighbour blocks each side), then re-read")
    if not have_image and not args.no_image_i_accept_data_loss:
        die("no full-size rescue image found. Image the disk first (mdr rescue) or pass --no-image-i-accept-data-loss")
    if not args.execute:
        print("\nDry run. Add --execute to write.")
        return 0
    need_root("raw device writes")
    if not safety.confirm_typed(ident, f"About to OVERWRITE {bm.bad_blocks} unreadable blocks on {ident} with zeros. Data in those blocks is already unreadable and will be gone for good."):
        die("aborted by operator")
    reader, writer, closer = remap_mod.device_rw(di.raw_node)
    try:
        res = remap_mod.zero_fill(reader, writer, bm, pad_blocks=args.pad)
    finally:
        closer()
    save_json(paths["remap"], res.to_dict())
    print(f"\nRemap: attempted {res.attempted_blocks}, readable after {res.readable_after}, still bad {res.still_bad}, write failures {res.write_failed_blocks}")
    if res.still_bad == 0:
        print("All formerly unreadable blocks now read clean: the controller retired the bad flash.")
        print(f"Next: repair the filesystem on the original:  sudo mdr repair {ident} --workdir {args.workdir} --execute")
    else:
        print("Some blocks still fail after a write: the drive has no spare area left. Retire it after copying what you need from the image.")
    return 0 if res.still_bad == 0 else 5


def cmd_revive(args: argparse.Namespace) -> int:
    """Run the full sequence, pausing at each destructive step."""
    need_macos()
    ident = diskutil.normalize_identifier(args.disk)
    paths = workdir_paths(args.workdir, ident)
    print("Mac Disk Repair: revive sequence")
    print("  1. health (read-only)     2. rescue image (reads only)   3. repair the IMAGE copy")
    print("  4. remap bad blocks       5. repair the ORIGINAL          6. report")
    print()
    rc = cmd_health(argparse.Namespace(disk=ident, allow_internal=args.allow_internal, no_verify=False, workdir=args.workdir, json=False))
    if rc:
        return rc
    print("\n--- step 2: rescue image ---")
    rc = cmd_rescue(argparse.Namespace(disk=ident, to=paths["image"], mapfile=paths["mapfile"], passes="1,2", execute=args.execute,
                                       workdir=args.workdir, allow_internal=args.allow_internal, update_badmap=True))
    if rc and args.execute:
        return rc
    print("\n--- step 3: repair the image copy ---")
    rc = cmd_repair(argparse.Namespace(disk=None, image=paths["image"], execute=args.execute, workdir=args.workdir, allow_internal=True)) \
        if os.path.exists(paths["image"]) else 0
    print("\n--- step 4: remap bad blocks on the original ---")
    if os.path.exists(paths["badmap"]):
        rc = cmd_remap(argparse.Namespace(disk=ident, workdir=args.workdir, badmap=None, image=paths["image"], pad=1, execute=args.execute,
                                          allow_internal=args.allow_internal, no_image_i_accept_data_loss=False))
    else:
        print("(no bad map yet; dry-run skips)")
    print("\n--- step 5: repair the original ---")
    cmd_repair(argparse.Namespace(disk=ident, image=None, execute=args.execute, workdir=args.workdir, allow_internal=args.allow_internal))
    if args.execute:
        # Re-read SMART so the report grades the drive AFTER remap, not the snapshot from step 1.
        try:
            _, sm_after = collect_disk_and_smart(ident)
            if sm_after.available:
                save_json(paths["smart"], sm_after.to_dict())
                print("SMART re-read after remap and saved for the report.")
        except ToolError as exc:
            eprint(f"warning: SMART re-read failed: {exc}")
    print("\n--- step 6: report ---")
    return cmd_report(argparse.Namespace(workdir=args.workdir, disk=ident, title=None))


def cmd_report(args: argparse.Namespace) -> int:
    ident = args.disk
    if not ident:
        cands = sorted({f.split(".")[0] for f in os.listdir(args.workdir) if f.endswith(".disk.json")})
        if len(cands) != 1:
            die(f"pass --disk; found {cands or 'no disks'} in {args.workdir}")
        ident = cands[0]
    paths = workdir_paths(args.workdir, ident)
    disk = load_json(paths["disk"]) or {"identifier": ident}
    sm = load_json(paths["smart"])
    badmap = load_json(paths["badmap"])
    fs = load_json(paths["fs_after"]) or load_json(paths["fs_before"])
    rm = load_json(paths["remap"])
    rs = load_json(paths["rescue"])
    sm_findings = smart.findings(smart.SmartSummary(**{k: v for k, v in sm.items() if k in smart.SmartSummary.__dataclass_fields__})) if sm else []
    assessment = report.grade(sm, badmap, fs, rm)
    title = args.title or f"Mac Disk Repair report: {disk.get('media_name') or ident} ({ident})"
    md = report.render_markdown(title, disk, sm, sm_findings, badmap, fs, rm, rs, assessment)
    with open(paths["report_md"], "w") as fh:
        fh.write(md)
    save_json(paths["report_json"], {"disk": disk, "smart": sm, "badmap": badmap, "fs": fs, "remap": rm, "rescue": rs,
                                     "assessment": assessment.__dict__})
    print(md)
    print(f"\nWritten: {paths['report_md']} and {paths['report_json']}")
    return 0


# ------------------------------------------------------------------ parser ---

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mdr", description="Mac Disk Repair: assess, image, repair and remap a failing external disk.")
    p.add_argument("--version", action="version", version=f"mdr {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("doctor", help="check installed tools").set_defaults(fn=cmd_doctor)

    s = sub.add_parser("detect", help="list external physical disks")
    s.add_argument("--all", action="store_true", help="include internal disks")
    s.set_defaults(fn=cmd_detect)

    s = sub.add_parser("health", help="SMART + read-only verify, graded")
    s.add_argument("disk")
    s.add_argument("--workdir", help="save results here for the report")
    s.add_argument("--no-verify", action="store_true", help="skip diskutil verify")
    s.add_argument("--json", action="store_true")
    s.add_argument("--allow-internal", action="store_true", help=argparse.SUPPRESS)
    s.set_defaults(fn=cmd_health)

    s = sub.add_parser("scan", help="read-only surface scan to a bad-block map (resumable)")
    s.add_argument("disk")
    s.add_argument("--workdir", required=True)
    s.add_argument("--chunk-mib", type=int, default=4)
    s.add_argument("--restart", action="store_true", help="discard a previous partial scan")
    s.add_argument("--allow-mounted", action="store_true")
    s.add_argument("--allow-internal", action="store_true", help=argparse.SUPPRESS)
    s.set_defaults(fn=cmd_scan)

    s = sub.add_parser("rescue", help="ddrescue multi-pass image of the disk")
    s.add_argument("disk")
    s.add_argument("--to", required=True, help="image file path on a HEALTHY disk with enough free space")
    s.add_argument("--mapfile")
    s.add_argument("--passes", default="1,2", help="comma list: 1=fast no-scrape, 2=retry x3, 3=reverse retry")
    s.add_argument("--workdir")
    s.add_argument("--update-badmap", action="store_true")
    s.add_argument("--execute", action="store_true")
    s.add_argument("--allow-internal", action="store_true", help=argparse.SUPPRESS)
    s.set_defaults(fn=cmd_rescue)

    s = sub.add_parser("repair", help="verify then repair filesystems (disk or image)")
    s.add_argument("disk", nargs="?")
    s.add_argument("--image", help="repair a rescue image instead of a disk")
    s.add_argument("--workdir")
    s.add_argument("--execute", action="store_true")
    s.add_argument("--allow-internal", action="store_true", help=argparse.SUPPRESS)
    s.set_defaults(fn=cmd_repair)

    s = sub.add_parser("remap", help="zero-fill unreadable blocks so the SSD retires them")
    s.add_argument("disk")
    s.add_argument("--workdir", required=True)
    s.add_argument("--badmap")
    s.add_argument("--image")
    s.add_argument("--pad", type=int, default=1, help="also rewrite N neighbour blocks on each side")
    s.add_argument("--execute", action="store_true")
    s.add_argument("--no-image-i-accept-data-loss", action="store_true")
    s.add_argument("--allow-internal", action="store_true", help=argparse.SUPPRESS)
    s.set_defaults(fn=cmd_remap)

    s = sub.add_parser("revive", help="full sequence: health, rescue, repair image, remap, repair original, report")
    s.add_argument("disk")
    s.add_argument("--workdir", required=True)
    s.add_argument("--execute", action="store_true")
    s.add_argument("--allow-internal", action="store_true", help=argparse.SUPPRESS)
    s.set_defaults(fn=cmd_revive)

    s = sub.add_parser("report", help="render the Markdown/JSON report from a workdir")
    s.add_argument("--workdir", required=True)
    s.add_argument("--disk")
    s.add_argument("--title")
    s.set_defaults(fn=cmd_report)
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.fn(args) or 0)
    except ToolError as exc:
        eprint(f"error: {exc}")
        return 1
    except ValueError as exc:
        eprint(f"error: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
