"""VAT White List (Ministry of Finance) taxpayer status -> bronze.

Endpoint (no API key): GET {base}/{nip1,nip2,...}?date=YYYY-MM-DD, at most
30 NIPs per request and 100 ``search`` requests per day; above that the IP is
blocked until midnight. Therefore:
* NIPs come from KRS extracts already in bronze (no extra KRS calls);
* NIPs with an invalid checksum are never sent;
* NIPs already answered for the same ``date`` are served from bronze;
* every attempt is counted on disk *before* it is sent (DailyQuota);
* only server errors are retried, once; 429 is not retried at all.
"""

from __future__ import annotations

import json
import logging
from datetime import date
from typing import Any

from kyb.config import local_today
from kyb.http import HttpClient, HttpError, InvalidPayloadError, ensure_json, parse_json_payload
from kyb.ingestion.report import IngestReport
from kyb.nip import is_valid_nip, nip_batches, normalize_nip
from kyb.pii import redact_vat_payload
from kyb.quota import DailyQuota, QuotaExceededError
from kyb.storage import BronzeStore, make_envelope

log = logging.getLogger(__name__)

SOURCE = "vat_whitelist"
VAT_RETRY_STATUSES = frozenset({500, 502, 503, 504})

# verified on live KRS extracts (see docs/source_structures.md)
KRS_NIP_PATH = ("odpis", "dane", "dzial1", "danePodmiotu", "identyfikatory", "nip")


def nip_from_extract(extract: dict[str, Any]) -> str | None:
    node: Any = extract
    for key in KRS_NIP_PATH:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node if isinstance(node, str) and node.strip() else None


def nips_from_krs_bronze(store: BronzeStore, krs_source: str = "krs_current") -> tuple[list[str], list[str]]:
    """Valid NIPs from the latest stored KRS extract of each company.

    Returns (valid_nips, problems) where problems describe skipped companies.
    """
    valid: list[str] = []
    problems: list[str] = []
    for krs, envelope in sorted(store.latest_by_key(krs_source, statuses=(200,)).items()):
        nip = nip_from_extract(json.loads(envelope["payload"]))
        if nip is None:
            problems.append(f"KRS {krs}: no NIP in extract")
        elif not is_valid_nip(nip):
            problems.append(f"KRS {krs}: NIP {nip!r} fails checksum - not sent")
        else:
            valid.append(normalize_nip(nip))
    return valid, problems


def is_valid_answer(envelope: dict[str, Any]) -> bool:
    """True for a real API answer (JSON with ``result``), False e.g. for a WAF page."""
    if envelope["http_status"] != 200:
        return False
    try:
        parse_json_payload(envelope["payload"], required_keys=("result",))
    except InvalidPayloadError:
        return False
    return True


def nips_already_fetched(store: BronzeStore, query_date: date) -> set[str]:
    done: set[str] = set()
    for envelope in store.iter_envelopes(SOURCE):
        if envelope.get("query_date") == query_date.isoformat() and is_valid_answer(envelope):
            done.update(envelope["key"].split(","))
    return done


def ingest_vat(
    nips: list[str],
    *,
    client: HttpClient,
    store: BronzeStore,
    quota: DailyQuota,
    base_url: str,
    batch_size: int = 30,
    max_retries: int = 1,
    query_date: date | None = None,
    force: bool = False,
    dry_run: bool = False,
) -> IngestReport:
    day = local_today()
    as_of = query_date or day
    cached = set() if force else nips_already_fetched(store, as_of)
    unique = list(dict.fromkeys(normalize_nip(n) for n in nips))
    todo = [n for n in unique if n not in cached]
    batches = nip_batches(todo, batch_size)
    report = IngestReport(source=SOURCE, requested=len(unique), cached=len(unique) - len(todo))
    report.notes.append(
        f"{len(todo)} NIP(s) to query for date={as_of.isoformat()} -> {len(batches)} request(s); "
        f"quota today: {quota.used} used, {quota.remaining} remaining of {quota.allowed}"
    )
    if dry_run:
        report.notes.append("dry run: no request sent")
        return report

    for index, batch in enumerate(batches, start=1):
        key = ",".join(batch)
        url = f"{base_url.rstrip('/')}/{key}"
        note = f"search/nips batch {index}/{len(batches)} ({len(batch)} NIPs)"
        try:
            result = client.get(
                url,
                params={"date": as_of.isoformat()},
                business_statuses={200},
                retry_statuses=VAT_RETRY_STATUSES,
                max_retries=max_retries,
                before_attempt=lambda: quota.consume(1, note=note),
            )
            ensure_json(result, required_keys=("result",))
        except QuotaExceededError as exc:
            log.error("VAT: %s", exc)
            report.failed[key] = str(exc)
            break  # every further request would be refused as well
        except HttpError as exc:
            log.error("VAT batch %d: %s", index, exc)
            report.failed[key] = str(exc)
            continue
        payload, redacted = redact_vat_payload(result.text)
        envelope = make_envelope(
            SOURCE, key, result.url, result.status, payload,
            query_date=as_of.isoformat(), content_type=result.content_type, redacted_values=redacted,
        )
        # one part file per request: a quota-limited answer must never be lost
        report.written.append(store.write_part(SOURCE, [envelope], day))
        report.statuses[result.status] += 1
    report.notes.append(f"quota after run: {quota.status()}")
    return report
