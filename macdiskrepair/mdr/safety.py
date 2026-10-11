"""Guard rails. Every destructive path must pass `check_target` first.

Rules:
  * target must be a WHOLE disk (disk4, not disk4s2) for rescue/scan/remap
  * target must be EXTERNAL (never the internal/boot disk)
  * target must not be the disk the running system lives on
  * for writes, target must be unmounted
  * for writes, the operator must type the identifier back
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from . import diskutil


class SafetyError(RuntimeError):
    pass


@dataclass
class TargetCheck:
    identifier: str
    ok: bool
    reasons: List[str] = field(default_factory=list)
    info: Optional[diskutil.DiskInfo] = None


def evaluate(info: diskutil.DiskInfo, boot_disk: str, mounted_children: List[str], require_unmounted: bool,
             allow_internal: bool = False) -> TargetCheck:
    reasons: List[str] = []
    if not info.whole:
        reasons.append(f"{info.identifier} is a partition/volume, not a whole disk (parent: {info.parent_whole or '?'})")
    if info.internal and not allow_internal:
        reasons.append(f"{info.identifier} is an INTERNAL disk; this tool only operates on external disks")
    if boot_disk and info.identifier == boot_disk:
        reasons.append(f"{info.identifier} holds the running macOS system")
    if require_unmounted and mounted_children:
        reasons.append(f"volumes still mounted: {', '.join(mounted_children)} (run: diskutil unmountDisk {info.identifier})")
    if not info.writable and require_unmounted:
        reasons.append(f"{info.identifier} is read-only media")
    return TargetCheck(identifier=info.identifier, ok=not reasons, reasons=reasons, info=info)


def check_target(ident: str, require_unmounted: bool, allow_internal: bool = False) -> TargetCheck:
    info = diskutil.info(ident)
    boot = diskutil.boot_whole_disk()
    mounted: List[str] = []
    if require_unmounted:
        for child in diskutil.list_children(info.identifier):
            try:
                ci = diskutil.info(child)
            except Exception:  # noqa: BLE001 - a vanished child is not a mount
                continue
            if ci.mount_point:
                mounted.append(f"{child} at {ci.mount_point}")
    return evaluate(info, boot, mounted, require_unmounted, allow_internal)


def confirm_typed(expected: str, prompt: str, input_fn=input) -> bool:
    """Ask the operator to type the identifier back. Returns True only on exact match."""
    try:
        answer = input_fn(f"{prompt}\nType '{expected}' to continue, anything else to abort: ")
    except (EOFError, KeyboardInterrupt):
        return False
    return answer.strip() == expected
