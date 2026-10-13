"""Turn drive-check output (fsck, SMART) into findings and a plain-language verdict."""
from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Dict, List, Optional

from .devices import Drive, Runner, Volume
from .util import run


class Level(IntEnum):
    OK = 0
    WATCH = 1
    RESCUE_NOW = 2
    FAILING = 3


@dataclass
class Finding:
    code: str
    level: Level
    summary: str
    detail: str = ""


@dataclass
class Verdict:
    level: Level
    headline: str
    findings: List[Finding] = field(default_factory=list)
    advice: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "level": self.level.name,
            "headline": self.headline,
            "findings": [
                {"code": f.code, "level": f.level.name, "summary": f.summary, "detail": f.detail}
                for f in self.findings
            ],
            "advice": self.advice,
        }


# (code, level, regex, summary) -- matched against fsck / diskutil verify output
_TEXT_RULES = [
    (
        "IO_ERROR",
        Level.RESCUE_NOW,
        r"input/output error|i/o error|error reading block|unrecovered read error",
        "The drive failed to read some data (an I/O error).",
    ),
    (
        "CHECKSUM_INVALID",
        Level.RESCUE_NOW,
        r"invalid o_cksum|checksum (?:mismatch|error|failed)|bad checksum",
        "Stored data does not match its checksum, so it has been damaged.",
    ),
    (
        "FS_CORRUPT",
        Level.RESCUE_NOW,
        r"found to be corrupt|cannot be repaired|needs to be repaired"
        r"|unexpected inconsistency|tree is invalid|invalid b-tree",
        "The file system structure (its index of files and folders) is damaged.",
    ),
    (
        "LIVE_CHECK_UNAVAILABLE",
        Level.WATCH,
        r"could not freeze volume",
        "The check could not run on a volume that is in use, so it proves nothing yet.",
    ),
    (
        "UNMOUNT_BLOCKED",
        Level.WATCH,
        r"could not be unmounted|dissented",
        "Something on this computer is holding the drive open.",
    ),
    (
        "VERIFY_INCOMPLETE",
        Level.WATCH,
        r"could not be verified completely",
        "The check could not finish.",
    ),
    (
        "FS_OK",
        Level.OK,
        r"appears to be (?:ok|fine)|file system is clean|is clean",
        "The file system check found no problems.",
    ),
]


def parse_fsck_output(text: str) -> List[Finding]:
    findings: List[Finding] = []
    lines = text.splitlines()
    for code, level, pattern, summary in _TEXT_RULES:
        regex = re.compile(pattern, re.IGNORECASE)
        for line in lines:
            if regex.search(line):
                findings.append(Finding(code, level, summary, line.strip()))
                break
    return findings


_ATA_FIELDS = {
    5: "reallocated",
    187: "reported_uncorrect",
    197: "pending",
    198: "offline_uncorrectable",
    199: "crc_errors",
}


def _smart_unavailable(reason: str) -> List[Finding]:
    return [Finding("SMART_UNAVAILABLE", Level.OK, "SMART health data is not available.", reason)]


def parse_smart_json(data: Optional[Dict[str, Any]]) -> List[Finding]:
    """Findings from `smartctl -j -a` output."""
    if not data or not any(
        key in data for key in ("smart_status", "ata_smart_attributes", "nvme_smart_health_information_log")
    ):
        return _smart_unavailable("This drive or adapter does not pass SMART data through.")

    findings: List[Finding] = []
    status = data.get("smart_status")
    if isinstance(status, dict) and status.get("passed") is False:
        findings.append(
            Finding("SMART_FAILED", Level.FAILING, "The drive reports that its own health test failed.")
        )

    table = (data.get("ata_smart_attributes") or {}).get("table") or []
    raw: Dict[str, int] = {}
    for row in table:
        name = _ATA_FIELDS.get(row.get("id"))
        if name:
            value = (row.get("raw") or {}).get("value")
            if isinstance(value, int):
                raw[name] = value
    bad_media = [n for n in ("pending", "offline_uncorrectable", "reported_uncorrect") if raw.get(n, 0) > 0]
    if bad_media:
        detail = ", ".join(f"{n}={raw[n]}" for n in bad_media)
        findings.append(
            Finding("SMART_MEDIA_ERRORS", Level.RESCUE_NOW, "The drive has sectors it cannot read reliably.", detail)
        )
    if raw.get("reallocated", 0) > 0:
        level = Level.RESCUE_NOW if raw["reallocated"] >= 50 else Level.WATCH
        findings.append(
            Finding(
                "SMART_REALLOCATED",
                level,
                "The drive has already retired some damaged sectors.",
                f"reallocated={raw['reallocated']}",
            )
        )
    if raw.get("crc_errors", 0) > 0:
        findings.append(
            Finding(
                "SMART_CABLE_ERRORS",
                Level.WATCH,
                "Data was corrupted in transit, which points at the cable or adapter.",
                f"crc_errors={raw['crc_errors']}",
            )
        )

    nvme = data.get("nvme_smart_health_information_log")
    if isinstance(nvme, dict):
        if nvme.get("critical_warning", 0):
            findings.append(
                Finding("SMART_FAILED", Level.FAILING, "The drive raised a critical health warning.")
            )
        if nvme.get("media_errors", 0) > 0:
            findings.append(
                Finding(
                    "SMART_MEDIA_ERRORS",
                    Level.RESCUE_NOW,
                    "The drive has logged media errors.",
                    f"media_errors={nvme['media_errors']}",
                )
            )
        used = nvme.get("percentage_used", 0)
        if used >= 100:
            findings.append(Finding("SMART_WORN_OUT", Level.RESCUE_NOW, "The drive has used up its rated lifetime."))
        elif used >= 90:
            findings.append(Finding("SMART_WORN_OUT", Level.WATCH, "The drive is close to its rated lifetime."))

    if not findings:
        findings.append(Finding("SMART_OK", Level.OK, "The drive's own health data looks clean."))
    return findings


def parse_diskutil_smart(status: str) -> List[Finding]:
    text = (status or "").strip().lower()
    if text == "verified":
        return [Finding("SMART_OK", Level.OK, "macOS reports the drive's health as Verified.")]
    if text == "failing":
        return [Finding("SMART_FAILED", Level.FAILING, "macOS reports that this drive is failing.")]
    return []


_HEADLINES = {
    Level.OK: "No problems found.",
    Level.WATCH: "Inconclusive, or minor warning signs.",
    Level.RESCUE_NOW: "Damage found. Copy your files off before trying any repair.",
    Level.FAILING: "The drive reports that it is failing. Copy your files off now.",
}

_ADVICE = {
    Level.OK: [
        "Nothing wrong was detected, but drives can fail without warning: keep a second copy of anything important.",
    ],
    Level.WATCH: [
        "Run the check again with the drive unmounted so it can finish (see the notes above).",
        "Keep a second copy of anything important while you investigate.",
    ],
    Level.RESCUE_NOW: [
        "Do NOT run First Aid, fsck repair or a reformat yet: repairs write to the drive.",
        "Open the drive read-only, then copy your irreplaceable folders first: driverescue rescue",
        "Then make a full image if you can: driverescue image",
        "Only after the copy is verified (driverescue verify) decide whether to wipe or replace the drive: driverescue refresh-plan",
    ],
}
_ADVICE[Level.FAILING] = _ADVICE[Level.RESCUE_NOW]


def assess(findings: List[Finding]) -> Verdict:
    codes = {f.code for f in findings}
    level = max((f.level for f in findings), default=Level.OK)
    advice = list(_ADVICE[level])

    if codes & {"LIVE_CHECK_UNAVAILABLE", "UNMOUNT_BLOCKED"}:
        advice.insert(
            0,
            "Something is holding the drive open (often Spotlight, 'mds'). Find it with: "
            "sudo lsof \"/Volumes/NAME\" | head   then unmount, e.g. diskutil unmountDisk disk5",
        )
    if "SMART_CABLE_ERRORS" in codes:
        advice.append("Try a different cable and USB port before blaming the drive itself.")
    if "IO_ERROR" in codes and not codes & {"SMART_OK", "SMART_MEDIA_ERRORS", "SMART_FAILED", "SMART_REALLOCATED"}:
        advice.append(
            "An I/O error can come from a bad cable or adapter as well as failing flash: "
            "try another cable and port, and read the drive's SMART data on a Linux computer (smartctl -a -d sat)."
        )
    if "SMART_UNAVAILABLE" in codes and "SMART_OK" not in codes:
        advice.append(
            "SMART data could not be read here. Install smartmontools (macOS: brew install smartmontools) "
            "or connect the drive to a Linux computer for a full health report."
        )
    return Verdict(level, _HEADLINES[level], findings, advice)


# --- gathering ------------------------------------------------------------

def read_smart(node: str, runner: Runner = run) -> List[Finding]:
    if not shutil.which("smartctl"):
        return _smart_unavailable("smartctl is not installed.")
    for extra in ([], ["-d", "sat"]):
        rc, out, _ = runner(["smartctl", "-j", "-a"] + extra + [node])
        try:
            data = json.loads(out)
        except ValueError:
            continue
        findings = parse_smart_json(data)
        if not any(f.code == "SMART_UNAVAILABLE" for f in findings):
            return findings
    return _smart_unavailable("smartctl could not read this drive through its adapter.")


def check_volume(volume: Volume, system: str, runner: Runner = run) -> List[Finding]:
    """Read-only file system check of one volume."""
    if system == "macos":
        rc, out, err = runner(["diskutil", "verifyVolume", volume.identifier])
        findings = parse_fsck_output(out + "\n" + err)
        if not findings:
            findings.append(
                Finding("FS_UNKNOWN", Level.WATCH, f"No clear result from the check of {volume.name or volume.identifier}.", (out + err).strip()[-300:])
            )
        return findings
    if system == "linux" and (volume.fs or "").startswith("ext") and not volume.mount_point:
        rc, out, err = runner(["e2fsck", "-fn", "/dev/" + volume.identifier])
        return parse_fsck_output(out + "\n" + err) or [
            Finding("FS_UNKNOWN", Level.WATCH, "No clear result from e2fsck.", (out + err).strip()[-300:])
        ]
    return [
        Finding(
            "FS_NOT_CHECKED",
            Level.OK,
            f"{volume.name or volume.identifier}: file system check not supported or volume is mounted.",
        )
    ]


def collect_findings(
    drive: Drive,
    volume: Optional[Volume],
    system: str,
    runner: Runner = run,
    do_fsck: bool = True,
) -> List[Finding]:
    findings: List[Finding] = []
    findings += parse_diskutil_smart(drive.smart_status)
    findings += read_smart(drive.node, runner)
    if do_fsck:
        for vol in [volume] if volume else drive.volumes:
            findings += check_volume(vol, system, runner)
    return findings
