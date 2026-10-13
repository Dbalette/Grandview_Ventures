"""Guards that keep rescue work from making things worse."""
from __future__ import annotations

import errno
import os
import shutil
import sys
from typing import List, Optional, Tuple

from .devices import Drive


def dest_on_source_drive(dest_path: str, drive: Drive) -> Optional[str]:
    """An error message if the destination lives on the drive being rescued."""
    folder = os.path.realpath(os.path.dirname(os.path.abspath(dest_path)) or ".")
    for mount in drive.mount_points:
        root = os.path.realpath(mount)
        if folder == root or folder.startswith(root.rstrip(os.sep) + os.sep):
            return (
                f"The destination ({dest_path}) is on the drive you are rescuing ({mount}). "
                "Writing there would overwrite the data you are trying to save. Choose another drive."
            )
    return None


def free_space(dest_path: str) -> int:
    folder = os.path.dirname(os.path.abspath(dest_path)) or "."
    return shutil.disk_usage(folder).free


def enough_space(dest_path: str, needed: int) -> Tuple[bool, int]:
    free = free_space(dest_path)
    return free >= needed, free


def unmount_command(drive: Drive, system: str) -> str:
    if system == "macos":
        return f"diskutil unmountDisk {drive.identifier}"
    return " && ".join(f"sudo umount {m!r}" for m in drive.mount_points) or "sudo umount <mount point>"


def full_disk_access_status(system: str) -> str:
    """macOS only: 'on', 'off' or 'unknown'. Raw drive access needs it for your terminal app."""
    if system != "macos":
        return "not applicable"
    probe = os.path.expanduser("~/Library/Mail")
    try:
        os.listdir(probe)
        return "on"
    except PermissionError:
        return "off"
    except OSError:
        return "unknown"


def permission_hint(exc: OSError, system: str, command: str) -> str:
    code = getattr(exc, "errno", None)
    if system == "macos" and code == errno.EPERM:
        return (
            "macOS refused raw access to the drive (Operation not permitted). "
            "This is the Full Disk Access privacy gate, not a fault in the drive.\n"
            "  1. System Settings > Privacy & Security > Full Disk Access: switch on your terminal app\n"
            "  2. Quit the terminal completely (Cmd+Q) and reopen it\n"
            "  3. Check it worked:  ls ~/Library/Mail | head -3   (it should list names)\n"
            "  If it still fails, connect the drive to a Linux computer and run the same command there.\n"
            "  (Copying files from the mounted drive with 'rescue' does not need this permission.)"
        )
    if code == errno.EACCES:
        return (
            "Permission denied: reading a whole drive needs administrator rights. Run it with sudo:\n"
            f"  sudo \"{sys.executable}\" -m driverescue {command}"
        )
    return f"Could not open the drive: {exc}"


def mounted_warning(drive: Drive, system: str) -> List[str]:
    if not drive.mount_points:
        return []
    return [
        "These volumes are still mounted: " + ", ".join(drive.mount_points),
        "Unmounting first stops the computer from writing to the drive while you read it:",
        f"  {unmount_command(drive, system)}",
        "Or add --allow-mounted to read it anyway.",
    ]
