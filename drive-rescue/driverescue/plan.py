"""The 'wipe it or toss it?' plan, printed for you to run yourself.

Nothing here erases anything. Wiping is the one irreversible step, so the tool
prints the exact commands and leaves the decision (and the typing) to you.
"""
from __future__ import annotations


def refresh_plan(drive_id: str, system: str) -> str:
    if system == "macos":
        erase = f"diskutil eraseDisk APFS Refreshed {drive_id}"
        health = f"smartctl -a -d sat /dev/{drive_id}"
    else:
        erase = f"sudo blkdiscard /dev/{drive_id}      # SSD full erase (or: sudo wipefs -a /dev/{drive_id} for a plain reformat)"
        health = f"sudo smartctl -a -d sat /dev/{drive_id}"
    return f"""\
REFRESH PLAN for {drive_id}  (read this fully; nothing below is run for you)

0. STOP unless your files are safe.
   Run `driverescue verify` and confirm the copy is complete. Erasing is permanent.

1. Read the drive's own health report (macOS needs: brew install smartmontools):
     {health}
   Look for: reallocated / pending / uncorrectable sectors (flash is wearing out),
   CRC errors (a bad cable or adapter, not the drive), wear level or "percentage used".

2. Rule out the connection: repeat any failing check with a different cable and port.

3. Erase it completely (DESTROYS EVERYTHING on {drive_id}; double-check the name with `driverescue drives`):
     {erase}
   A wipe fixes a damaged file index. It does not repair worn-out flash.

4. Fill and re-read it, to see whether the flash still holds data reliably:
   - with f3 (also exposes fake capacity):   f3write /Volumes/Refreshed && f3read /Volumes/Refreshed
   - then a full read-only pass:             driverescue scan {drive_id}

5. Decide:
   - Everything passes -> use it for things you can afford to lose (scratch space, a second copy of a backup).
   - Any new error, a failing health report, or errors that come back -> replace it.
     A drive that has thrown read errors should never hold the only copy of anything.
"""
