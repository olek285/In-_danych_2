"""Bronze layer storage: envelopes, ingest_date partitions, atomic writes.

Bronze is append-only. Every run writes new part files and never rewrites
files that already exist, so earlier observations stay auditable.
"""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from collections.abc import Iterable, Iterator
from contextlib import contextmanager, suppress
from datetime import date, datetime, timezone
from pathlib import Path
from typing import IO, Any

from kyb.config import local_today

ENVELOPE_FIELDS = ("source", "key", "url", "http_status", "ingested_at", "payload")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def atomic_open(path: Path, mode: str = "wb", encoding: str | None = None) -> Iterator[IO[Any]]:
    """Write to a temp file in the target directory, then rename it into place.

    Readers never see a half-written file: either the old content (or no file)
    or the complete new content. On error the temp file is removed.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, mode, encoding=encoding, newline="" if "b" not in mode else None) as fh:
            yield fh
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        with suppress(FileNotFoundError):
            os.unlink(tmp_name)
        raise


def atomic_write_text(path: Path, text: str) -> None:
    with atomic_open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def atomic_write_json(path: Path, obj: Any) -> None:
    atomic_write_text(path, json.dumps(obj, ensure_ascii=False, indent=2) + "\n")


def make_envelope(
    source: str,
    key: str,
    url: str,
    http_status: int,
    payload: str,
    *,
    ingested_at: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """Bronze record: request metadata plus the response body kept as text."""
    envelope: dict[str, Any] = {
        "source": source,
        "key": key,
        "url": url,
        "http_status": http_status,
        "ingested_at": ingested_at or utc_now_iso(),
        "payload": payload,
    }
    envelope.update(extra)
    return envelope


class BronzeStore:
    """data/bronze/<source>/ingest_date=YYYY-MM-DD/part-*.jsonl"""

    def __init__(self, root: Path) -> None:
        self.root = root

    def partition_dir(self, source: str, ingest_date: date | None = None) -> Path:
        day = ingest_date or local_today()
        return self.root / source / f"ingest_date={day.isoformat()}"

    def write_part(
        self, source: str, envelopes: Iterable[dict[str, Any]], ingest_date: date | None = None
    ) -> Path | None:
        """Write envelopes to a new, uniquely named JSONL part file."""
        rows = list(envelopes)
        if not rows:
            return None
        for row in rows:
            missing = [f for f in ENVELOPE_FIELDS if f not in row]
            if missing:
                raise ValueError(f"envelope for key {row.get('key')!r} misses fields {missing}")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = self.partition_dir(source, ingest_date) / f"part-{stamp}-{uuid.uuid4().hex[:8]}.jsonl"
        if path.exists():  # practically impossible with uuid, but bronze must never be overwritten
            raise FileExistsError(path)
        body = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
        atomic_write_text(path, body)
        return path

    def partitions(self, source: str) -> list[Path]:
        base = self.root / source
        if not base.is_dir():
            return []
        return sorted(p for p in base.iterdir() if p.is_dir() and p.name.startswith("ingest_date="))

    def iter_envelopes(self, source: str, ingest_date: date | None = None) -> Iterator[dict[str, Any]]:
        """Envelopes in chronological file order (one day or the whole history)."""
        dirs = [self.partition_dir(source, ingest_date)] if ingest_date else self.partitions(source)
        for part_dir in dirs:
            if not part_dir.is_dir():
                continue
            for part in sorted(part_dir.glob("part-*.jsonl")):
                with part.open(encoding="utf-8") as fh:
                    for line in fh:
                        if line.strip():
                            yield json.loads(line)

    def latest_by_key(
        self,
        source: str,
        ingest_date: date | None = None,
        statuses: Iterable[int] = (200, 404),
    ) -> dict[str, dict[str, Any]]:
        """Most recent envelope per key, limited to the given HTTP statuses."""
        allowed = set(statuses)
        latest: dict[str, dict[str, Any]] = {}
        for env in self.iter_envelopes(source, ingest_date):
            if env["http_status"] in allowed:
                previous = latest.get(env["key"])
                if previous is None or env["ingested_at"] >= previous["ingested_at"]:
                    latest[env["key"]] = env
        return latest
