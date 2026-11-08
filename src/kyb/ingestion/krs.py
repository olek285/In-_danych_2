"""KRS (National Court Register) extracts -> bronze.

Endpoint (no API key): GET {base}/OdpisAktualny/{krs}?rejestr=P&format=json
Observed on the live API: 200 with the extract, 404 for a well-formed number
that is not in the register (stored in bronze as a business result) and 400
for a malformed number (raised as an error).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterable
from datetime import date

from kyb.config import local_today
from kyb.http import HttpClient, HttpError, ensure_json
from kyb.ingestion.report import IngestReport
from kyb.pii import redact_krs_payload
from kyb.storage import BronzeStore, make_envelope

log = logging.getLogger(__name__)

SOURCE_BY_ENDPOINT = {"OdpisAktualny": "krs_current", "OdpisPelny": "krs_full"}


def ingest_krs(
    krs_numbers: Iterable[str],
    *,
    client: HttpClient,
    store: BronzeStore,
    base_url: str,
    endpoint: str = "OdpisAktualny",
    register: str = "P",
    force: bool = False,
    min_interval_s: float = 1.0,
    ingest_date: date | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> IngestReport:
    """Fetch extracts for the given KRS numbers and append them to bronze.

    Idempotent within a day: numbers already answered (200/404) in today's
    partition are skipped unless ``force`` is set.
    """
    source = SOURCE_BY_ENDPOINT[endpoint]
    day = ingest_date or local_today()
    numbers = list(krs_numbers)
    report = IngestReport(source=source, requested=len(numbers))
    cached = set() if force else set(store.latest_by_key(source, day))
    envelopes = []
    sent = 0
    try:
        for krs in numbers:
            if krs in cached:
                report.cached += 1
                continue
            if sent and min_interval_s:
                sleep(min_interval_s)  # be polite to a public, keyless service
            sent += 1
            url = f"{base_url.rstrip('/')}/{endpoint}/{krs}"
            try:
                result = client.get(url, params={"rejestr": register, "format": "json"})
                # a 200 must be an extract; a 404 must still be the API's own JSON error
                ensure_json(result, required_keys=("odpis",) if result.status == 200 else ())
            except HttpError as exc:
                log.error("KRS %s: %s", krs, exc)
                report.failed[krs] = str(exc)
                continue
            payload, redacted = redact_krs_payload(result.text)
            envelopes.append(
                make_envelope(source, krs, result.url, result.status, payload, redacted_values=redacted)
            )
            report.statuses[result.status] += 1
            if result.status == 404:
                log.warning("KRS %s not found in register %s (stored as HTTP 404)", krs, register)
    finally:
        # keep whatever was fetched even if the run is interrupted
        path = store.write_part(source, envelopes, day)
        if path:
            report.written.append(path)
    return report
