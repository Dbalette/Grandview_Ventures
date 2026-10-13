"""Compare a rescued copy against the source (sizes and presence, no heavy re-reads)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Set

from .transfer import Entry


@dataclass
class VerifyReport:
    matched: int = 0
    missing: List[str] = field(default_factory=list)
    size_mismatch: List[str] = field(default_factory=list)
    known_damaged: List[str] = field(default_factory=list)
    bytes_checked: int = 0

    @property
    def ok(self) -> bool:
        return not self.missing and not self.size_mismatch

    def summary_lines(self, limit: int = 15) -> List[str]:
        lines = [
            f"Matched: {self.matched:,} files ({self.bytes_checked:,} bytes)",
            f"Missing from the copy: {len(self.missing):,}",
            f"Different size: {len(self.size_mismatch):,}",
            f"Copied with unreadable parts (zero-filled): {len(self.known_damaged):,}",
        ]
        for title, names in (("Missing", self.missing), ("Different size", self.size_mismatch),
                             ("Damaged", self.known_damaged)):
            if names:
                lines.append(f"{title} (first {min(limit, len(names))}):")
                lines.extend(f"  {n}" for n in names[:limit])
        lines.append("RESULT: " + ("copy matches the source." if self.ok else "copy is INCOMPLETE - run rescue again."))
        return lines


def compare(
    source_entries: Iterable[Entry],
    dest_sizes: Dict[str, int],
    damaged: Optional[Set[str]] = None,
) -> VerifyReport:
    report = VerifyReport()
    damaged = damaged or set()
    for entry in source_entries:
        if entry.kind != "file":
            continue
        got = dest_sizes.get(entry.rel)
        if got is None:
            report.missing.append(entry.rel)
        elif got != entry.size:
            report.size_mismatch.append(entry.rel)
        else:
            report.matched += 1
            report.bytes_checked += entry.size
            if entry.rel in damaged:
                report.known_damaged.append(entry.rel)
    return report
