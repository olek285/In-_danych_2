"""Personal-data minimisation applied *before* anything is written to bronze.

The course rules forbid personal data unless effectively anonymised, so raw
payloads are stored with person-identifying values replaced by ``[REDACTED]``.
The JSON structure (keys, list lengths, roles) is kept, because it is what the
parsers need; nothing else in the payload is changed.

What the live APIs return (verified 2026-11-08, see docs/source_structures.md):
* KRS API masks names and PESEL (first character + asterisks) but returns a
  full ``identyfikator.dataUrodzenia`` for some persons (e.g. holders of
  commercial power of attorney without PESEL). All of it is redacted here.
* VAT White List returns representatives / clerks / partners with names.
"""

from __future__ import annotations

import json
from typing import Any

REDACTED = "[REDACTED]"

# Every person object in the KRS extract (board, supervisory board, proxies,
# liquidators, shareholders who are natural persons) uses these keys.
KRS_PERSON_KEYS = frozenset({"imiona", "nazwisko", "pesel", "dataUrodzenia"})

# VAT White List: lists of people attached to a taxpayer record.
VAT_PERSON_LISTS = frozenset({"representatives", "authorizedClerks", "partners"})
VAT_PERSON_FIELDS = frozenset({"firstName", "lastName", "pesel"})


def _mask(value: Any) -> tuple[Any, int]:
    """Replace every non-empty leaf with REDACTED, keeping the shape."""
    if isinstance(value, dict):
        out, count = {}, 0
        for key, item in value.items():
            out[key], n = _mask(item)
            count += n
        return out, count
    if isinstance(value, list):
        masked = [_mask(item) for item in value]
        return [m for m, _ in masked], sum(n for _, n in masked)
    if value is None or value == "":
        return value, 0
    return REDACTED, 1


def redact_keys(obj: Any, keys: frozenset[str]) -> tuple[Any, int]:
    """Copy of ``obj`` with all values stored under ``keys`` masked (any depth)."""
    if isinstance(obj, dict):
        out, count = {}, 0
        for key, value in obj.items():
            if key in keys:
                out[key], n = _mask(value)
            else:
                out[key], n = redact_keys(value, keys)
            count += n
        return out, count
    if isinstance(obj, list):
        items = [redact_keys(item, keys) for item in obj]
        return [m for m, _ in items], sum(n for _, n in items)
    return obj, 0


def redact_vat_people(obj: Any) -> tuple[Any, int]:
    """Mask names/PESEL of people listed under a VAT subject.

    A listed entry may also be a company (``companyName`` set); then its NIP is
    company data and stays. A natural person's NIP is masked as well.
    """
    if isinstance(obj, dict):
        out, count = {}, 0
        for key, value in obj.items():
            if key in VAT_PERSON_LISTS and isinstance(value, list):
                entries = []
                for entry in value:
                    if not isinstance(entry, dict):
                        masked, n = _mask(entry)
                    else:
                        fields = set(VAT_PERSON_FIELDS)
                        if not entry.get("companyName"):
                            fields.add("nip")
                        masked, n = redact_keys(entry, frozenset(fields))
                    entries.append(masked)
                    count += n
                out[key] = entries
            else:
                out[key], n = redact_vat_people(value)
                count += n
        return out, count
    if isinstance(obj, list):
        items = [redact_vat_people(item) for item in obj]
        return [m for m, _ in items], sum(n for _, n in items)
    return obj, 0


def _detect_indent(text: str) -> int | None:
    """Indent width of pretty-printed JSON (None for compact JSON)."""
    lines = text.lstrip().splitlines()
    if len(lines) < 2:
        return None
    second = lines[1]
    width = len(second) - len(second.lstrip(" "))
    return width or None


def _redact_json_text(text: str, redactor) -> tuple[str, int]:
    try:
        data = json.loads(text)
    except ValueError:
        return text, 0  # not JSON (e.g. an HTML error page): nothing structured to mask
    redacted, count = redactor(data)
    if count == 0:
        return text, 0  # keep the exact original text when there is nothing to mask
    # re-serialise in the source's own layout, so only the masked values differ
    indent = _detect_indent(text)
    if indent:
        return json.dumps(redacted, ensure_ascii=False, indent=indent), count
    return json.dumps(redacted, ensure_ascii=False, separators=(",", ":")), count


def redact_krs_payload(text: str) -> tuple[str, int]:
    return _redact_json_text(text, lambda data: redact_keys(data, KRS_PERSON_KEYS))


def redact_vat_payload(text: str) -> tuple[str, int]:
    return _redact_json_text(text, redact_vat_people)
