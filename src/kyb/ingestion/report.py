"""Summary of one ingestion run, printed at the end and used for the exit code."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class IngestReport:
    source: str
    requested: int = 0
    statuses: Counter = field(default_factory=Counter)
    cached: int = 0
    failed: dict[str, str] = field(default_factory=dict)
    written: list[Path] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failed

    def summary(self) -> str:
        statuses = ", ".join(f"HTTP {code}: {n}" for code, n in sorted(self.statuses.items())) or "none"
        lines = [
            f"[{self.source}] requested={self.requested} fetched=({statuses}) "
            f"from_cache={self.cached} failed={len(self.failed)}"
        ]
        lines += [f"  written: {path}" for path in self.written]
        lines += [f"  FAILED {key}: {error}" for key, error in self.failed.items()]
        lines += [f"  note: {note}" for note in self.notes]
        return "\n".join(lines)
