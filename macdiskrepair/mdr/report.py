"""Grade a disk and render the Markdown/JSON report."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .util import human_size, now_iso

GRADE_TEXT = {
    "A": "Healthy. No defects found.",
    "B": "Serviceable. Minor wear or isolated, remapped defects. Keep backups current.",
    "C": "Degraded. Unreadable blocks present but the controller still has spare capacity. Use only for non-critical data after remap.",
    "D": "Failing. Many unreadable blocks, or remap did not clear them. Retire the drive after rescuing data.",
    "F": "Dead or dying. SMART failed, or large unreadable regions. Do not write new data; image it and recycle it.",
}


@dataclass
class Assessment:
    grade: str
    score: int  # 0..100
    reasons: List[str] = field(default_factory=list)
    recommendation: str = ""
    provisional: bool = False  # True when neither SMART nor a complete surface scan backs the grade

    @property
    def label(self) -> str:
        return f"{self.grade} (provisional)" if self.provisional else self.grade


def grade(smart: Optional[Dict[str, Any]], badmap: Optional[Dict[str, Any]], fs: Optional[Dict[str, Any]],
          remap: Optional[Dict[str, Any]] = None) -> Assessment:
    score = 100
    reasons: List[str] = []

    if smart and smart.get("available"):
        if smart.get("overall_passed") is False:
            score -= 60
            reasons.append("SMART overall status FAILED")
        for key, label, per, cap in (
            ("pending", "pending sectors", 5, 30),
            ("offline_uncorrectable", "offline uncorrectable", 5, 30),
            ("reallocated", "reallocated blocks", 1, 25),
            ("reported_uncorrectable", "reported uncorrectable errors", 1, 10),
            ("nvme_media_errors", "NVMe media errors", 5, 30),
        ):
            v = smart.get(key) or 0
            if v:
                pen = min(cap, v * per)
                score -= pen
                reasons.append(f"{v} {label} (-{pen})")
        wear = smart.get("wear_pct_used")
        if wear is not None:
            if wear >= 90:
                score -= 30; reasons.append(f"wear {wear}% (-30)")
            elif wear >= 70:
                score -= 15; reasons.append(f"wear {wear}% (-15)")
        if smart.get("nvme_critical_warning"):
            score -= 25; reasons.append("NVMe critical warning (-25)")
    else:
        reasons.append("SMART unavailable; grade rests on the surface scan and filesystem checks")

    if badmap:
        bad_blocks = int(badmap.get("bad_blocks", 0))
        total = int(badmap.get("total_bytes", 0)) or 1
        bad_bytes = int(badmap.get("bad_bytes", 0))
        ppm = bad_bytes * 1_000_000 / total
        if bad_blocks == 0:
            reasons.append("surface scan: 0 unreadable blocks")
        else:
            if ppm > 1000:      # > 0.1 % of the disk
                pen = 50
            elif ppm > 100:
                pen = 35
            elif ppm > 10:
                pen = 20
            else:
                pen = 10
            score -= pen
            reasons.append(f"surface scan: {bad_blocks} unreadable blocks, {human_size(bad_bytes)} ({ppm:.1f} ppm) (-{pen})")
        if not badmap.get("complete", True):
            reasons.append("surface scan incomplete; grade is provisional")
        if badmap.get("slow_ranges"):
            n = len(badmap["slow_ranges"])
            pen = min(10, n)
            score -= pen
            reasons.append(f"{n} slow regions (retries inside the controller) (-{pen})")

    if remap:
        attempted = int(remap.get("attempted_blocks", 0))
        still = int(remap.get("still_bad", 0))
        if attempted:
            if still == 0:
                score += 10
                reasons.append(f"remap cleared all {attempted} blocks (+10)")
            else:
                ratio = still / attempted
                pen = 20 if ratio < 0.10 else 40
                score -= pen
                reasons.append(f"remap left {still}/{attempted} blocks unreadable ({ratio:.0%}): spare area exhausted (-{pen})")

    if fs:
        if fs.get("partition_map_ok") is False:
            score -= 10
            reasons.append("partition map errors (-10)")
        for v in fs.get("volumes", []):
            if not v.get("ok"):
                score -= 5
                reasons.append(f"filesystem {v.get('identifier')} ({v.get('filesystem')}) failed {v.get('action')} (-5)")

    score = max(0, min(100, score))
    if smart and smart.get("available") and smart.get("overall_passed") is False:
        g = "F"
    elif score >= 90:
        g = "A"
    elif score >= 75:
        g = "B"
    elif score >= 55:
        g = "C"
    elif score >= 30:
        g = "D"
    else:
        g = "F"
    rec = GRADE_TEXT[g]
    has_smart = bool(smart and smart.get("available"))
    has_scan = bool(badmap and badmap.get("complete"))
    provisional = not (has_smart or has_scan)
    if provisional:
        reasons.append("PROVISIONAL: no SMART and no complete surface scan yet; verify only checks metadata, not every sector")
        rec = "Not yet rated. Filesystem metadata is consistent, but the sectors have not been read. Run the surface scan."
    return Assessment(grade=g, score=score, reasons=reasons, recommendation=rec, provisional=provisional)


def render_markdown(title: str, disk: Dict[str, Any], smart: Optional[Dict[str, Any]], smart_findings: List[Dict[str, str]],
                    badmap: Optional[Dict[str, Any]], fs: Optional[Dict[str, Any]], remap: Optional[Dict[str, Any]],
                    rescue: Optional[Dict[str, Any]], assessment: Assessment) -> str:
    L: List[str] = []
    L.append(f"# {title}")
    L.append("")
    L.append(f"Generated {now_iso()} by Mac Disk Repair.")
    L.append("")
    L.append(f"## Verdict: grade {assessment.label} (score {assessment.score}/100)")
    L.append("")
    L.append(assessment.recommendation)
    L.append("")
    for r in assessment.reasons:
        L.append(f"- {r}")
    L.append("")
    L.append("## Disk")
    L.append("")
    L.append("| Field | Value |")
    L.append("|---|---|")
    for k in ("identifier", "media_name", "protocol", "size", "block_size", "solid_state", "internal", "smart_status", "content"):
        v = disk.get(k)
        if k == "size":
            v = f"{human_size(v)} ({v} bytes)"
        L.append(f"| {k} | {v} |")
    L.append("")
    L.append("## SMART")
    L.append("")
    if smart and smart.get("available"):
        L.append(f"Model {smart.get('model')}, serial {smart.get('serial')}, firmware {smart.get('firmware')}, via `-d {smart.get('device_type_used') or 'auto'}`.")
        L.append("")
        for f in smart_findings:
            L.append(f"- **{f['severity']}**: {f['text']}")
    else:
        L.append(f"Not available: {(smart or {}).get('reason', 'not collected')}")
    L.append("")
    L.append("## Surface scan")
    L.append("")
    if badmap:
        L.append("| Metric | Value |")
        L.append("|---|---|")
        L.append(f"| scanned | {human_size(badmap.get('scanned_bytes'))} of {human_size(badmap.get('total_bytes'))} |")
        L.append(f"| complete | {badmap.get('complete')} |")
        L.append(f"| unreadable blocks | {badmap.get('bad_blocks')} |")
        L.append(f"| unreadable bytes | {human_size(badmap.get('bad_bytes'))} |")
        L.append(f"| bad ranges | {len(badmap.get('bad_ranges', []))} |")
        L.append(f"| slow regions | {len(badmap.get('slow_ranges', []))} |")
        L.append("")
        rngs = badmap.get("bad_ranges", [])[:50]
        if rngs:
            L.append("First bad ranges (byte offset, length, LBA):")
            L.append("")
            bs = int(badmap.get("block_size") or 512)
            for off, ln in rngs:
                L.append(f"- {off} +{ln} (LBA {off // bs}, {ln // bs} blocks)")
            if len(badmap.get("bad_ranges", [])) > 50:
                L.append(f"- ... {len(badmap['bad_ranges']) - 50} more")
    else:
        L.append("Not run.")
    L.append("")
    L.append("## Rescue image")
    L.append("")
    if rescue:
        for k, v in rescue.items():
            L.append(f"- {k}: {v}")
    else:
        L.append("Not run.")
    L.append("")
    L.append("## Block remap")
    L.append("")
    if remap:
        L.append(f"- attempted: {remap.get('attempted_blocks')} blocks")
        L.append(f"- readable after: {remap.get('readable_after')}")
        L.append(f"- still bad: {remap.get('still_bad')}")
        L.append(f"- write failures: {remap.get('write_failed_blocks')}")
    else:
        L.append("Not run.")
    L.append("")
    L.append("## Filesystem")
    L.append("")
    if fs:
        L.append(f"- partition map ok: {fs.get('partition_map_ok')}")
        for v in fs.get("volumes", []):
            L.append(f"- {v.get('identifier')} {v.get('volume_name')!r} ({v.get('filesystem')}): {v.get('action')} {'OK' if v.get('ok') else 'FAILED'}")
            if v.get("manual_command"):
                L.append(f"  - manual: `{v['manual_command']}`")
    else:
        L.append("Not run.")
    L.append("")
    return "\n".join(L)


def to_json(obj: Any) -> str:
    return json.dumps(obj, indent=2, default=str)
