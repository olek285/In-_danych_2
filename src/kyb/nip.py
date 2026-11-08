"""Polish tax identification number (NIP): normalisation, checksum, batching."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

WEIGHTS = (6, 5, 7, 2, 3, 4, 5, 6, 7)


def normalize_nip(value: str) -> str:
    """Strip separators and an optional 'PL' prefix: 'PL 526-025-09-95' -> '5260250995'."""
    text = value.strip().upper()
    if text.startswith("PL"):
        text = text[2:]
    return "".join(ch for ch in text if ch not in " -.")


def is_valid_nip(value: str | None) -> bool:
    """Checksum rule: sum(weight_i * digit_i) mod 11 must equal the 10th digit."""
    if not value:
        return False
    nip = normalize_nip(value)
    if len(nip) != 10 or not nip.isdigit() or nip == "0000000000":
        return False
    checksum = sum(w * int(d) for w, d in zip(WEIGHTS, nip)) % 11
    return checksum != 10 and checksum == int(nip[9])


def chunked(items: Sequence[str], size: int) -> list[list[str]]:
    if size < 1:
        raise ValueError("batch size must be positive")
    return [list(items[i : i + size]) for i in range(0, len(items), size)]


def nip_batches(nips: Iterable[str], size: int = 30) -> list[list[str]]:
    """Unique NIPs (first occurrence order) split into API-sized batches."""
    seen: set[str] = set()
    unique = []
    for raw in nips:
        nip = normalize_nip(raw)
        if nip not in seen:
            seen.add(nip)
            unique.append(nip)
    return chunked(unique, size)
