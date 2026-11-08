"""Watchlist of companies to screen: config/watchlist.csv (column ``krs``)."""

from __future__ import annotations

import csv
from collections.abc import Iterable
from pathlib import Path


def normalize_krs(value: str) -> str:
    """KRS numbers are 10 digits; leading zeros are often dropped in spreadsheets."""
    digits = value.strip()
    if not digits.isdigit() or len(digits) > 10:
        raise ValueError(f"invalid KRS number: {value!r}")
    return digits.zfill(10)


def unique(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    return [v for v in values if not (v in seen or seen.add(v))]


def read_watchlist(path: Path) -> list[str]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames or "krs" not in reader.fieldnames:
            raise ValueError(f"{path}: missing 'krs' column (found {reader.fieldnames})")
        numbers = []
        for line_no, row in enumerate(reader, start=2):
            raw = (row.get("krs") or "").strip()
            if not raw or raw.startswith("#"):
                continue
            try:
                numbers.append(normalize_krs(raw))
            except ValueError as exc:
                raise ValueError(f"{path}:{line_no}: {exc}") from exc
    return unique(numbers)
