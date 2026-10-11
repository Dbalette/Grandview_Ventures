"""SMART health via smartmontools (`smartctl -j`), with graceful degradation.

On macOS, SMART over USB 3.x bridges is usually NOT available: the kernel has
no SCSI pass-through for USB storage, so smartctl can only talk to internal
SATA/NVMe, Thunderbolt and USB4 devices. We try several device types and
report honestly when nothing answers.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

from .util import ToolError, run, which

# Device types to try, in order. "" means let smartctl guess.
DEVICE_TYPES = ["", "sat", "sat,12", "nvme", "sntjmicron", "sntasmedia", "sntrealtek", "scsi"]

# ATA attribute ids that matter for a failing SSD.
ATA_REALLOCATED = 5
ATA_REPORTED_UNCORRECT = 187
ATA_PENDING = 197
ATA_OFFLINE_UNCORRECT = 198
ATA_CRC = 199
ATA_WEAR_IDS = (177, 173, 231, 233, 202, 169)  # vendor wear/life indicators
ATA_RUNTIME_BAD_BLOCK = 183
ATA_ERASE_FAIL = 182
ATA_PROGRAM_FAIL = 181


@dataclass
class SmartSummary:
    available: bool = False
    reason: str = ""
    device_type_used: str = ""
    model: str = ""
    serial: str = ""
    firmware: str = ""
    protocol: str = ""
    capacity_bytes: Optional[int] = None
    overall_passed: Optional[bool] = None
    power_on_hours: Optional[int] = None
    power_cycles: Optional[int] = None
    temperature_c: Optional[int] = None
    reallocated: Optional[int] = None
    pending: Optional[int] = None
    offline_uncorrectable: Optional[int] = None
    reported_uncorrectable: Optional[int] = None
    crc_errors: Optional[int] = None
    program_fail: Optional[int] = None
    erase_fail: Optional[int] = None
    runtime_bad_blocks: Optional[int] = None
    wear_pct_used: Optional[int] = None  # 0..100, higher is more worn
    nvme_critical_warning: Optional[int] = None
    nvme_media_errors: Optional[int] = None
    nvme_available_spare: Optional[int] = None
    nvme_percentage_used: Optional[int] = None
    nvme_unsafe_shutdowns: Optional[int] = None
    attributes: List[Dict[str, Any]] = field(default_factory=list)
    error_log_count: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def smartctl_path() -> Optional[str]:
    return which("smartctl")


def read(device_node: str) -> SmartSummary:
    """Try smartctl with several device types. Never raises; returns a summary."""
    binary = smartctl_path()
    if not binary:
        return SmartSummary(available=False, reason="smartctl not installed (brew install smartmontools)")
    last_err = ""
    for dtype in DEVICE_TYPES:
        cmd = [binary, "-j", "-a"]
        if dtype:
            cmd += ["-d", dtype]
        cmd.append(device_node)
        try:
            proc = run(cmd, check=False, timeout=120)
        except ToolError as exc:
            last_err = str(exc)
            continue
        try:
            data = json.loads(proc.stdout.decode(errors="replace") or "{}")
        except json.JSONDecodeError:
            last_err = proc.stderr.decode(errors="replace")[:200]
            continue
        # smartctl exit status bit 1 (value 2) = device open failed; bit 0 = cmdline error.
        if proc.returncode & 0b11 and not data.get("ata_smart_attributes") and not data.get("nvme_smart_health_information_log"):
            msgs = [m.get("string", "") for m in data.get("smartctl", {}).get("messages", [])]
            last_err = "; ".join(m for m in msgs if m) or last_err
            continue
        summary = parse(data)
        if summary.available:
            summary.device_type_used = dtype or "auto"
            return summary
        last_err = summary.reason or last_err
    reason = (last_err or "no SMART response").strip()
    if "VALID ARGUMENTS ARE" in reason or "Not a device of type" in reason:
        reason = reason.split(";")[0].strip()
    if len(reason) > 160:
        reason = reason[:157] + "..."
    reason += f" [tried -d {', '.join(t or 'auto' for t in DEVICE_TYPES)}]"
    reason += " (macOS does not pass SMART through USB enclosures; Thunderbolt/USB4 or a direct SATA attach would)"
    return SmartSummary(available=False, reason=reason)


def _attr_raw(table: List[Dict[str, Any]], attr_id: int) -> Optional[int]:
    for row in table:
        if row.get("id") == attr_id:
            raw = row.get("raw", {})
            val = raw.get("value")
            if isinstance(val, int):
                # Some vendors pack several counters; keep the low 32 bits for counts.
                return val & 0xFFFFFFFF if attr_id in (ATA_REALLOCATED, ATA_PENDING, ATA_OFFLINE_UNCORRECT) else val
            try:
                return int(str(raw.get("string", "")).split()[0])
            except (ValueError, IndexError):
                return None
    return None


def _attr_norm(table: List[Dict[str, Any]], attr_id: int) -> Optional[int]:
    for row in table:
        if row.get("id") == attr_id:
            v = row.get("value")
            return int(v) if isinstance(v, int) else None
    return None


def parse(data: Dict[str, Any]) -> SmartSummary:
    """Parse `smartctl -j -a` output into a SmartSummary."""
    s = SmartSummary()
    s.model = data.get("model_name", "") or data.get("scsi_model_name", "")
    s.serial = data.get("serial_number", "")
    s.firmware = data.get("firmware_version", "")
    s.protocol = (data.get("device", {}) or {}).get("protocol", "")
    s.capacity_bytes = (data.get("user_capacity", {}) or {}).get("bytes")
    status = data.get("smart_status")
    if isinstance(status, dict) and "passed" in status:
        s.overall_passed = bool(status["passed"])
    s.power_on_hours = (data.get("power_on_time", {}) or {}).get("hours")
    s.power_cycles = data.get("power_cycle_count")
    s.temperature_c = (data.get("temperature", {}) or {}).get("current")
    s.error_log_count = ((data.get("ata_smart_error_log", {}) or {}).get("summary", {}) or {}).get("count")

    table = (data.get("ata_smart_attributes", {}) or {}).get("table") or []
    nvme = data.get("nvme_smart_health_information_log") or {}

    if table:
        s.available = True
        s.attributes = [
            {"id": r.get("id"), "name": r.get("name"), "value": r.get("value"), "worst": r.get("worst"),
             "thresh": r.get("thresh"), "raw": (r.get("raw", {}) or {}).get("string"),
             "failing_now": (r.get("when_failed") == "now")}
            for r in table
        ]
        s.reallocated = _attr_raw(table, ATA_REALLOCATED)
        s.pending = _attr_raw(table, ATA_PENDING)
        s.offline_uncorrectable = _attr_raw(table, ATA_OFFLINE_UNCORRECT)
        s.reported_uncorrectable = _attr_raw(table, ATA_REPORTED_UNCORRECT)
        s.crc_errors = _attr_raw(table, ATA_CRC)
        s.program_fail = _attr_raw(table, ATA_PROGRAM_FAIL)
        s.erase_fail = _attr_raw(table, ATA_ERASE_FAIL)
        s.runtime_bad_blocks = _attr_raw(table, ATA_RUNTIME_BAD_BLOCK)
        for wid in ATA_WEAR_IDS:
            norm = _attr_norm(table, wid)
            if norm is not None:
                # Normalized wear attributes count DOWN from 100 (new) toward threshold.
                s.wear_pct_used = max(0, min(100, 100 - norm))
                break
    elif nvme:
        s.available = True
        s.nvme_critical_warning = nvme.get("critical_warning")
        s.nvme_media_errors = nvme.get("media_errors")
        s.nvme_available_spare = nvme.get("available_spare")
        s.nvme_percentage_used = nvme.get("percentage_used")
        s.nvme_unsafe_shutdowns = nvme.get("unsafe_shutdowns")
        s.wear_pct_used = nvme.get("percentage_used")
        if s.power_on_hours is None:
            s.power_on_hours = nvme.get("power_on_hours")
        if s.temperature_c is None:
            s.temperature_c = nvme.get("temperature")
    else:
        s.available = False
        msgs = [m.get("string", "") for m in (data.get("smartctl", {}) or {}).get("messages", [])]
        s.reason = "; ".join(m for m in msgs if m) or "no SMART attribute table in smartctl output"
    return s


def findings(s: SmartSummary) -> List[Dict[str, str]]:
    """Turn a summary into severity-tagged findings: critical / warning / info."""
    out: List[Dict[str, str]] = []
    if not s.available:
        out.append({"severity": "info", "text": f"SMART not readable: {s.reason}"})
        return out
    if s.overall_passed is False:
        out.append({"severity": "critical", "text": "SMART overall self-assessment: FAILED. The firmware itself predicts failure."})
    if s.reallocated:
        sev = "critical" if s.reallocated >= 50 else "warning"
        out.append({"severity": sev, "text": f"Reallocated sectors/blocks: {s.reallocated}. The controller has already retired flash."})
    if s.pending:
        out.append({"severity": "critical", "text": f"Current pending sectors: {s.pending}. Unreadable blocks awaiting remap. Expect read errors."})
    if s.offline_uncorrectable:
        out.append({"severity": "critical", "text": f"Offline uncorrectable: {s.offline_uncorrectable}."})
    if s.reported_uncorrectable:
        out.append({"severity": "warning", "text": f"Reported uncorrectable errors: {s.reported_uncorrectable}."})
    if s.program_fail or s.erase_fail:
        out.append({"severity": "warning", "text": f"NAND program/erase failures: {s.program_fail or 0}/{s.erase_fail or 0}. Flash cells are wearing out."})
    if s.crc_errors:
        out.append({"severity": "info", "text": f"UDMA CRC errors: {s.crc_errors}. Usually cable/enclosure, not the flash."})
    if s.wear_pct_used is not None:
        if s.wear_pct_used >= 90:
            out.append({"severity": "critical", "text": f"Wear indicator: {s.wear_pct_used}% of rated life consumed."})
        elif s.wear_pct_used >= 70:
            out.append({"severity": "warning", "text": f"Wear indicator: {s.wear_pct_used}% of rated life consumed."})
        else:
            out.append({"severity": "info", "text": f"Wear indicator: {s.wear_pct_used}% of rated life consumed."})
    if s.nvme_critical_warning:
        out.append({"severity": "critical", "text": f"NVMe critical warning bitmask: 0x{s.nvme_critical_warning:02x}."})
    if s.nvme_media_errors:
        out.append({"severity": "critical", "text": f"NVMe media errors: {s.nvme_media_errors}."})
    if s.nvme_available_spare is not None and s.nvme_available_spare < 10:
        out.append({"severity": "critical", "text": f"NVMe available spare: {s.nvme_available_spare}%. Spare blocks nearly exhausted."})
    if s.power_on_hours is not None:
        out.append({"severity": "info", "text": f"Power-on hours: {s.power_on_hours} (~{s.power_on_hours / 8760:.1f} years powered)."})
    if s.temperature_c is not None:
        sev = "warning" if s.temperature_c >= 65 else "info"
        out.append({"severity": sev, "text": f"Temperature: {s.temperature_c} C."})
    return out
