"""Find drives and their volumes on macOS (diskutil) and Linux (lsblk)."""
from __future__ import annotations

import json
import os
import platform
import plistlib
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from .util import run

Runner = Callable[[List[str]], Tuple[int, str, str]]


@dataclass
class Volume:
    identifier: str
    name: str = ""
    mount_point: Optional[str] = None
    fs: Optional[str] = None
    size: Optional[int] = None


@dataclass
class Drive:
    identifier: str
    node: str
    model: str = ""
    size: Optional[int] = None
    bus: str = ""
    internal: Optional[bool] = None
    smart_status: str = ""
    volumes: List[Volume] = field(default_factory=list)

    @property
    def raw_node(self) -> str:
        """The raw device (/dev/rdiskN on macOS) is what you read for speed."""
        if self.node.startswith("/dev/disk"):
            return "/dev/r" + self.node[len("/dev/"):]
        return self.node

    @property
    def mount_points(self) -> List[str]:
        return [v.mount_point for v in self.volumes if v.mount_point]


def detect_system() -> str:
    name = platform.system()
    return {"Darwin": "macos", "Linux": "linux"}.get(name, name.lower())


# --- macOS ---------------------------------------------------------------

def _plist(runner: Runner, cmd: List[str]) -> Optional[Dict[str, Any]]:
    rc, out, _ = runner(cmd)
    if rc != 0 or not out.strip():
        return None
    try:
        return plistlib.loads(out.encode("utf-8"))
    except Exception:
        return None


def _apfs_volumes(runner: Runner, partition_id: str) -> List[Volume]:
    info = _plist(runner, ["diskutil", "info", "-plist", partition_id]) or {}
    container = info.get("APFSContainerReference")
    if not container:
        return []
    listing = _plist(runner, ["diskutil", "list", "-plist", container]) or {}
    volumes: List[Volume] = []
    for entry in listing.get("AllDisksAndPartitions", []):
        for vol in entry.get("APFSVolumes", []):
            volumes.append(
                Volume(
                    identifier=vol.get("DeviceIdentifier", ""),
                    name=vol.get("VolumeName", ""),
                    mount_point=vol.get("MountPoint") or None,
                    fs="apfs",
                    size=vol.get("Size"),
                )
            )
    return volumes


def macos_drives(runner: Runner = run, include_internal: bool = False) -> List[Drive]:
    filters = ["physical"] if include_internal else ["external", "physical"]
    data = _plist(runner, ["diskutil", "list", "-plist"] + filters)
    if not data:
        return []
    drives: List[Drive] = []
    for entry in data.get("AllDisksAndPartitions", []):
        ident = entry.get("DeviceIdentifier")
        if not ident:
            continue
        info = _plist(runner, ["diskutil", "info", "-plist", ident]) or {}
        drive = Drive(
            identifier=ident,
            node=info.get("DeviceNode") or f"/dev/{ident}",
            model=str(info.get("MediaName", "")).strip(),
            size=entry.get("Size") or info.get("TotalSize") or info.get("Size"),
            bus=str(info.get("BusProtocol", "")),
            internal=info.get("Internal"),
            smart_status=str(info.get("SMARTStatus", "")),
        )
        for part in entry.get("Partitions", []):
            content = part.get("Content", "")
            if content == "Apple_APFS":
                drive.volumes.extend(_apfs_volumes(runner, part.get("DeviceIdentifier", "")))
            elif content != "EFI" and (part.get("VolumeName") or part.get("MountPoint")):
                drive.volumes.append(
                    Volume(
                        identifier=part.get("DeviceIdentifier", ""),
                        name=part.get("VolumeName", ""),
                        mount_point=part.get("MountPoint") or None,
                        fs=content,
                        size=part.get("Size"),
                    )
                )
        drives.append(drive)
    return drives


# --- Linux ---------------------------------------------------------------

_LSBLK_COLUMNS = "NAME,PATH,SIZE,MODEL,TRAN,RM,TYPE,FSTYPE,LABEL,MOUNTPOINT"


def _mount_of(dev: Dict[str, Any]) -> Optional[str]:
    points = dev.get("mountpoints")
    if isinstance(points, list):
        for point in points:
            if point:
                return point
    return dev.get("mountpoint") or None


def _linux_volumes(dev: Dict[str, Any]) -> List[Volume]:
    volumes: List[Volume] = []
    if dev.get("fstype"):
        volumes.append(
            Volume(
                identifier=dev.get("name", ""),
                name=dev.get("label") or "",
                mount_point=_mount_of(dev),
                fs=dev.get("fstype"),
                size=_int(dev.get("size")),
            )
        )
    for child in dev.get("children") or []:
        volumes.extend(_linux_volumes(child))
    return volumes


def _int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def linux_drives(runner: Runner = run, include_internal: bool = False) -> List[Drive]:
    rc, out, _ = runner(["lsblk", "-J", "-b", "-o", _LSBLK_COLUMNS + ",MOUNTPOINTS"])
    if rc != 0:
        rc, out, _ = runner(["lsblk", "-J", "-b", "-o", _LSBLK_COLUMNS])
    if rc != 0 or not out.strip():
        return []
    try:
        devices = json.loads(out).get("blockdevices", [])
    except ValueError:
        return []
    drives: List[Drive] = []
    for dev in devices:
        if dev.get("type") != "disk":
            continue
        transport = (dev.get("tran") or "").lower()
        removable = dev.get("rm") in (True, 1, "1")
        external = transport == "usb" or removable
        if not external and not include_internal:
            continue
        drives.append(
            Drive(
                identifier=dev.get("name", ""),
                node=dev.get("path") or "/dev/" + dev.get("name", ""),
                model=(dev.get("model") or "").strip(),
                size=_int(dev.get("size")),
                bus=transport.upper(),
                internal=not external,
                volumes=_linux_volumes(dev),
            )
        )
    return drives


# --- shared --------------------------------------------------------------

def list_drives(
    include_internal: bool = False,
    runner: Runner = run,
    system: Optional[str] = None,
) -> List[Drive]:
    system = system or detect_system()
    if system == "macos":
        return macos_drives(runner, include_internal)
    if system == "linux":
        return linux_drives(runner, include_internal)
    return []


_MAC_PART = re.compile(r"^(disk\d+)s\d+$")
_LINUX_PART = re.compile(r"^((?:sd|vd|hd)[a-z]+|nvme\d+n\d+|mmcblk\d+)p?\d+$")


def resolve_target(
    target: str, drives: List[Drive]
) -> Optional[Tuple[Drive, Optional[Volume]]]:
    """Map 'disk5', '/dev/rdisk5', 'sdb1' or a mount path to (drive, volume)."""
    text = target.strip()
    base = os.path.basename(text.rstrip("/"))
    if base.startswith("rdisk"):
        base = base[1:]
    real = os.path.realpath(text) if os.path.exists(text) else text

    for drive in drives:
        if base == drive.identifier or text == drive.node:
            return drive, None
        for vol in drive.volumes:
            if base == vol.identifier:
                return drive, vol
            if vol.mount_point and real == os.path.realpath(vol.mount_point):
                return drive, vol

    match = _MAC_PART.match(base)
    parent = match.group(1) if match else None
    match = _LINUX_PART.match(base)
    parent = parent or (match.group(1) if match else None)
    if parent:
        for drive in drives:
            if drive.identifier == parent:
                return drive, None
    return None
