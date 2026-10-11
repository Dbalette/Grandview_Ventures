"""Filesystem verify/repair through diskutil, on the live disk or on an image copy.

Why diskutil and not fsck_* directly: diskutil picks the right checker per
volume format (fsck_apfs, fsck_hfs, fsck_exfat, fsck_msdos), handles
unmount/remount, and works on APFS containers. The equivalent manual commands
are recorded in the result so the operator can rerun them by hand:
    sudo fsck_apfs -n -S /dev/diskNs2      # read-only, skip snapshots
    sudo fsck_apfs -y /dev/diskNs2         # repair
    sudo fsck_hfs -fy /dev/diskNs2
    sudo fsck_exfat -y /dev/diskNs2
    sudo fsck_msdos -y /dev/diskNs2
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional

from . import diskutil

MANUAL_FSCK = {
    "apfs": ("fsck_apfs -n -S", "fsck_apfs -y"),
    "hfs": ("fsck_hfs -fn", "fsck_hfs -fy"),
    "exfat": ("fsck_exfat -n", "fsck_exfat -y"),
    "msdos": ("fsck_msdos -n", "fsck_msdos -y"),
    "fat32": ("fsck_msdos -n", "fsck_msdos -y"),
    "ntfs": ("(no native checker; use ntfsfix from ntfs-3g on Linux, or chkdsk on Windows)", ""),
}


@dataclass
class VolumeResult:
    identifier: str
    filesystem: str
    volume_name: str
    action: str  # verify | repair
    ok: bool
    output: str = ""
    manual_command: str = ""

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class FsReport:
    whole_disk: str
    partition_map_ok: Optional[bool] = None
    partition_map_output: str = ""
    volumes: List[VolumeResult] = field(default_factory=list)

    @property
    def all_ok(self) -> bool:
        return bool(self.partition_map_ok) and all(v.ok for v in self.volumes)

    def to_dict(self) -> Dict:
        return {"whole_disk": self.whole_disk, "partition_map_ok": self.partition_map_ok,
                "partition_map_output": self.partition_map_output, "volumes": [v.to_dict() for v in self.volumes],
                "all_ok": self.all_ok}


def manual_command(fs: str, repair: bool, node: str) -> str:
    key = (fs or "").lower()
    for k, (verify, fix) in MANUAL_FSCK.items():
        if key.startswith(k):
            cmd = fix if repair else verify
            return f"sudo {cmd} {node}" if cmd and not cmd.startswith("(") else cmd
    return ""


def checkable_volumes(whole: str) -> List[diskutil.DiskInfo]:
    """Volumes under a whole disk that have a filesystem worth checking."""
    out: List[diskutil.DiskInfo] = []
    for child in diskutil.list_children(whole):
        try:
            ci = diskutil.info(child)
        except Exception:  # noqa: BLE001
            continue
        fs = (ci.filesystem or "").lower()
        content = (ci.content or "").lower()
        if fs and fs not in ("", "none") and "efi" not in content and "efi" not in (ci.volume_name or "").lower():
            out.append(ci)
    return out


def check_disk(whole: str, repair: bool) -> FsReport:
    """Verify (or repair) the partition map and each checkable volume."""
    rep = FsReport(whole_disk=whole)
    r = diskutil.repair_disk(whole) if repair else diskutil.verify_disk(whole)
    rep.partition_map_ok, rep.partition_map_output = r.ok, r.output
    for vol in checkable_volumes(whole):
        vr = diskutil.repair_volume(vol.identifier) if repair else diskutil.verify_volume(vol.identifier)
        rep.volumes.append(VolumeResult(
            identifier=vol.identifier, filesystem=vol.filesystem, volume_name=vol.volume_name,
            action="repair" if repair else "verify", ok=vr.ok, output=vr.output,
            manual_command=manual_command(vol.filesystem, repair, vol.device_node)))
    return rep
