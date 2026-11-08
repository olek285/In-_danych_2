"""OpenSanctions bulk lists -> bronze (entities only).

For each dataset (e.g. ``us_ofac_sdn``) the small ``index.json`` gives the
current version and a versioned, immutable artifact URL of
``targets.simple.csv`` with its size and SHA-1. Verified on 2026-11-08:
CSV with a header, LF line endings, no BOM, no multi-line cells and a
``schema`` column (Person, Company, Organization, LegalEntity, Vessel, ...).

Privacy by design: the file is filtered *while it streams in*. Only rows whose
``schema`` is in ``keep_schemas`` (legal entities) are written - unchanged,
byte for byte - so records of natural persons never reach the disk. The SHA-1
of the complete original is still verified against index.json and recorded,
which keeps the stored subset auditable against the public artifact.

Layout: bronze/opensanctions/ingest_date=D/<dataset>/<version>/
        targets.simple.csv + _metadata.json (written last = completeness marker)
"""

from __future__ import annotations

import csv
import hashlib
import io
import logging
from collections import Counter
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from kyb.config import local_today
from kyb.http import HttpClient, HttpError, InvalidPayloadError, ensure_json
from kyb.ingestion.report import IngestReport
from kyb.storage import atomic_open, atomic_write_json, make_envelope

log = logging.getLogger(__name__)

SOURCE = "opensanctions"
DEFAULT_KEEP_SCHEMAS = frozenset({"Company", "Organization", "LegalEntity", "PublicBody"})
METADATA_FILE = "_metadata.json"


class _ChunkReader(io.RawIOBase):
    """Read-only file object over an iterator of byte chunks."""

    def __init__(self, chunks: Iterable[bytes]) -> None:
        self._chunks = iter(chunks)
        self._buffer = b""

    def readable(self) -> bool:
        return True

    def readinto(self, target) -> int:  # type: ignore[override]
        while not self._buffer:
            try:
                self._buffer = next(self._chunks)
            except StopIteration:
                return 0
        n = min(len(target), len(self._buffer))
        target[:n] = self._buffer[:n]
        self._buffer = self._buffer[n:]
        return n


class _RecordingLines:
    """Line iterator for csv.reader that remembers the raw text of each record."""

    def __init__(self, lines: Iterator[str]) -> None:
        self._lines = lines
        self.raw: list[str] = []

    def __iter__(self) -> _RecordingLines:
        return self

    def __next__(self) -> str:
        line = next(self._lines)
        self.raw.append(line)
        return line

    def pop_record(self) -> str:
        text = "".join(self.raw)
        self.raw.clear()
        return text


@dataclass
class FilterStats:
    columns: list[str] = field(default_factory=list)
    rows_total: int = 0
    rows_kept: int = 0
    schema_counts: Counter = field(default_factory=Counter)
    kept_size_bytes: int = 0
    kept_sha256: str = ""


def filter_entity_rows(chunks: Iterable[bytes], dest: Path, keep_schemas: frozenset[str]) -> FilterStats:
    """Write the header and the rows whose schema is kept, exactly as received."""
    stats = FilterStats()
    digest = hashlib.sha256()
    text = io.TextIOWrapper(io.BufferedReader(_ChunkReader(chunks)), encoding="utf-8", newline="")
    lines = _RecordingLines(iter(text))
    reader = csv.reader(lines)
    with atomic_open(dest, "w", encoding="utf-8") as out:

        def write(record: str) -> None:
            out.write(record)
            encoded = record.encode("utf-8")
            digest.update(encoded)
            stats.kept_size_bytes += len(encoded)

        try:
            stats.columns = next(reader)
        except StopIteration:
            raise InvalidPayloadError(f"{dest.name}: empty CSV") from None
        if "schema" not in stats.columns:
            raise InvalidPayloadError(f"{dest.name}: no 'schema' column in {stats.columns}")
        schema_idx = stats.columns.index("schema")
        write(lines.pop_record())
        for row in reader:
            record = lines.pop_record()
            stats.rows_total += 1
            schema = row[schema_idx] if len(row) > schema_idx else ""
            stats.schema_counts[schema] += 1
            if schema in keep_schemas:
                stats.rows_kept += 1
                write(record)
    stats.kept_sha256 = digest.hexdigest()
    return stats


def stored_versions(bronze_root: Path, dataset: str) -> list[Path]:
    return sorted((bronze_root / SOURCE).glob(f"ingest_date=*/{dataset}/*/{METADATA_FILE}"))


def find_resource(index: dict[str, Any], name: str) -> dict[str, Any]:
    for resource in index.get("resources", []):
        if resource.get("name") == name:
            return resource
    raise InvalidPayloadError(f"dataset {index.get('name')!r} has no resource {name!r}")


def ingest_sanctions(
    datasets: Iterable[str],
    *,
    client: HttpClient,
    bronze_root: Path,
    base_url: str,
    file_name: str = "targets.simple.csv",
    keep_schemas: frozenset[str] = DEFAULT_KEEP_SCHEMAS,
    force: bool = False,
    ingest_date: date | None = None,
) -> IngestReport:
    day = ingest_date or local_today()
    names = list(datasets)
    report = IngestReport(source=SOURCE, requested=len(names))
    for dataset in names:
        index_url = f"{base_url.rstrip('/')}/{dataset}/index.json"
        try:
            index_result = client.get(index_url, business_statuses={200})
            index = ensure_json(index_result, required_keys=("version", "resources"))
            version = index["version"]
            resource = find_resource(index, file_name)
            already = [p for p in stored_versions(bronze_root, dataset) if p.parent.name == version]
            if already and not force:
                log.info("%s version %s already in bronze (%s) - skipped", dataset, version, already[0].parent)
                report.cached += 1
                continue
            target_dir = bronze_root / SOURCE / f"ingest_date={day.isoformat()}" / dataset / version
            result = client.stream(
                resource["url"],
                lambda chunks: filter_entity_rows(chunks, target_dir / file_name, keep_schemas),
                expected_sha1=resource.get("checksum"),
            )
        except HttpError as exc:
            log.error("OpenSanctions %s: %s", dataset, exc)
            report.failed[dataset] = str(exc)
            continue

        stats: FilterStats = result.value
        if index.get("target_count") is not None and index["target_count"] != stats.rows_total:
            report.notes.append(f"{dataset}: {stats.rows_total} rows but index.json says target_count={index['target_count']}")
        metadata = make_envelope(
            SOURCE, dataset, result.url, result.status, index_result.text,
            index_url=index_result.url,
            dataset_version=version,
            file=file_name,
            columns=stats.columns,
            original={
                "size_bytes": result.size_bytes,
                "sha1": result.sha1,
                "sha1_published": resource.get("checksum"),
                "sha256": result.sha256,
                "rows": stats.rows_total,
                "schema_counts": dict(stats.schema_counts.most_common()),
            },
            stored={
                "size_bytes": stats.kept_size_bytes,
                "sha256": stats.kept_sha256,
                "rows": stats.rows_kept,
                "kept_schemas": sorted(keep_schemas),
                "dropped_rows": stats.rows_total - stats.rows_kept,
            },
        )
        atomic_write_json(target_dir / METADATA_FILE, metadata)  # last step: marks the version complete
        report.statuses[result.status] += 1
        report.written.append(target_dir / file_name)
        report.notes.append(
            f"{dataset} {version}: kept {stats.rows_kept} of {stats.rows_total} rows "
            f"({', '.join(f'{k}={v}' for k, v in stats.schema_counts.most_common())})"
        )
    return report
