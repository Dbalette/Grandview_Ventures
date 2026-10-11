"""Wrappers around macOS `diskutil` and `hdiutil` with plist parsing.

Nothing here is destructive except the functions whose names say so
(repair_*, unmount_*, erase is intentionally not implemented here).
"""
from __future__ import annotations

import plistlib
import re
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

from .util import ToolError, run

IDENT_RE = re.compile(r"^disk\d+(s\d+)*$")


def normalize_identifier(ident: str) -> str:
    """Accept 'disk4', '/dev/disk4', '/dev/rdisk4' and return 'disk4'."""
    ident = ident.strip()
    if ident.startswith("/dev/"):
        ident = ident[5:]
    if ident.startswith("rdisk"):
        ident = "disk" + ident[5:]
    if not IDENT_RE.match(ident):
        raise ValueError(f"not a disk identifier: {ident!r} (expected like disk4 or disk4s2)")
    return ident


@dataclass
class DiskInfo:
    identifier: str
    device_node: str
    raw_node: str
    media_name: str = ""
    size: int = 0
    block_size: int = 512
    internal: bool = True
    removable: bool = False
    protocol: str = ""
    solid_state: Optional[bool] = None
    smart_status: str = ""
    whole: bool = False
    parent_whole: str = ""
    content: str = ""
    filesystem: str = ""
    volume_name: str = ""
    mount_point: str = ""
    writable: bool = True
    apfs_container: str = ""
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def is_external(self) -> bool:
        return not self.internal

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d.pop("raw", None)
        return d


def parse_info_plist(data: bytes) -> DiskInfo:
    p = plistlib.loads(data)
    ident = p.get("DeviceIdentifier", "")
    return DiskInfo(
        identifier=ident,
        device_node=p.get("DeviceNode", f"/dev/{ident}"),
        raw_node=f"/dev/r{ident}",
        media_name=p.get("MediaName", "") or p.get("IORegistryEntryName", ""),
        size=int(p.get("TotalSize", p.get("Size", 0)) or 0),
        block_size=int(p.get("DeviceBlockSize", 512) or 512),
        internal=bool(p.get("Internal", True)),
        removable=bool(p.get("RemovableMedia", p.get("Removable", False))),
        protocol=p.get("BusProtocol", "") or "",
        solid_state=p.get("SolidState"),
        smart_status=p.get("SMARTStatus", "") or "",
        whole=bool(p.get("WholeDisk", False)),
        parent_whole=p.get("ParentWholeDisk", "") or "",
        content=p.get("Content", "") or "",
        filesystem=p.get("FilesystemType", "") or p.get("FilesystemName", "") or "",
        volume_name=p.get("VolumeName", "") or "",
        mount_point=p.get("MountPoint", "") or "",
        writable=bool(p.get("WritableMedia", True)),
        apfs_container=p.get("APFSContainerReference", "") or "",
        raw=p,
    )


def info(ident: str) -> DiskInfo:
    ident = normalize_identifier(ident)
    proc = run(["diskutil", "info", "-plist", ident])
    return parse_info_plist(proc.stdout)


def parse_list_plist(data: bytes) -> List[Dict[str, Any]]:
    """Return the AllDisksAndPartitions array from `diskutil list -plist`."""
    p = plistlib.loads(data)
    return list(p.get("AllDisksAndPartitions", []))


def list_whole_disks(external_only: bool = True) -> List[str]:
    cmd = ["diskutil", "list", "-plist"]
    if external_only:
        cmd += ["external", "physical"]
    else:
        cmd += ["physical"]
    proc = run(cmd)
    return [d["DeviceIdentifier"] for d in parse_list_plist(proc.stdout) if "DeviceIdentifier" in d]


def child_identifiers(list_entry: Dict[str, Any]) -> List[str]:
    """Partitions and APFS volumes listed under a whole-disk entry."""
    out: List[str] = []
    for part in list_entry.get("Partitions", []):
        if "DeviceIdentifier" in part:
            out.append(part["DeviceIdentifier"])
    for vol in list_entry.get("APFSVolumes", []):
        if "DeviceIdentifier" in vol:
            out.append(vol["DeviceIdentifier"])
    return out


def list_children(ident: str) -> List[str]:
    ident = normalize_identifier(ident)
    proc = run(["diskutil", "list", "-plist", ident])
    out: List[str] = []
    for entry in parse_list_plist(proc.stdout):
        out.extend(child_identifiers(entry))
    return out


def boot_whole_disk() -> str:
    """Identifier of the whole disk holding the running system, e.g. 'disk0'."""
    try:
        proc = run(["diskutil", "info", "-plist", "/"])
        p = plistlib.loads(proc.stdout)
    except ToolError:
        return ""
    # APFS system volumes report their physical store via APFSPhysicalStores.
    stores = p.get("APFSPhysicalStores") or []
    for store in stores:
        dev = store.get("DeviceIdentifier", "")
        m = re.match(r"(disk\d+)", dev)
        if m:
            return m.group(1)
    parent = p.get("ParentWholeDisk", "")
    return parent or ""


def unmount_disk(ident: str, force: bool = False) -> None:
    cmd = ["diskutil", "unmountDisk"]
    if force:
        cmd.append("force")
    cmd.append(normalize_identifier(ident))
    run(cmd)


def mount_disk(ident: str) -> None:
    run(["diskutil", "mountDisk", normalize_identifier(ident)])


def verify_disk(ident: str) -> subprocess_result:
    return _verb("verifyDisk", ident)


def repair_disk(ident: str) -> subprocess_result:
    return _verb("repairDisk", ident)


def verify_volume(ident: str) -> subprocess_result:
    return _verb("verifyVolume", ident)


def repair_volume(ident: str) -> subprocess_result:
    return _verb("repairVolume", ident)


class subprocess_result:  # simple record so callers don't import subprocess
    def __init__(self, ok: bool, output: str, returncode: int):
        self.ok = ok
        self.output = output
        self.returncode = returncode


def _verb(verb: str, ident: str) -> subprocess_result:
    proc = run(["diskutil", verb, normalize_identifier(ident)], check=False)
    out = (proc.stdout + proc.stderr).decode(errors="replace")
    return subprocess_result(proc.returncode == 0, out, proc.returncode)


# ---- hdiutil (disk images) --------------------------------------------------

def attach_image(path: str, readonly: bool = True, raw: bool = True) -> List[str]:
    """Attach a disk image without mounting; return the device identifiers created."""
    cmd = ["hdiutil", "attach", "-nomount", "-noverify", "-noautofsck"]
    if readonly:
        cmd.append("-readonly")
    if raw:
        cmd += ["-imagekey", "diskimage-class=CRawDiskImage"]
    cmd.append(path)
    proc = run(cmd, check=False)
    if proc.returncode != 0 and raw:
        # Fall back to letting hdiutil sniff the format.
        cmd = [c for c in cmd if c not in ("-imagekey", "diskimage-class=CRawDiskImage")]
        proc = run(cmd)
    elif proc.returncode != 0:
        raise ToolError(proc.stderr.decode(errors="replace"))
    return parse_attach_output(proc.stdout.decode(errors="replace"))


def parse_attach_output(text: str) -> List[str]:
    idents: List[str] = []
    for line in text.splitlines():
        m = re.match(r"\s*/dev/(disk\d+(?:s\d+)*)", line)
        if m:
            idents.append(m.group(1))
    return idents


def detach(ident: str, force: bool = False) -> None:
    cmd = ["hdiutil", "detach"]
    if force:
        cmd.append("-force")
    cmd.append(f"/dev/{normalize_identifier(ident)}")
    run(cmd)
