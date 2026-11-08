from __future__ import annotations

import json
from datetime import date

from fakes import FakeSession, make_response

from kyb.http import HttpClient
from kyb.ingestion.vat import SOURCE, ingest_vat, nip_from_extract, nips_from_krs_bronze
from kyb.quota import DailyQuota
from kyb.storage import BronzeStore, make_envelope

AS_OF = date(2026, 11, 8)
BASE = "https://wl-api.example/api/search/nips"
NIPS = ["5252674798", "7740001454"]
ANSWER = json.dumps({"result": {"subjects": [{"nip": "5252674798", "statusVat": "Czynny",
                                             "representatives": [{"companyName": None, "firstName": "JAN",
                                                                  "lastName": "NOWAK", "pesel": None, "nip": None}]}]}})


def setup(tmp_path, outcomes, limit=100, margin=0):
    session = FakeSession(outcomes)
    client = HttpClient(session=session, sleep=lambda s: None)
    quota = DailyQuota(tmp_path / "state" / "vat.json", limit=limit, safety_margin=margin, today=lambda: AS_OF)
    return BronzeStore(tmp_path / "bronze"), client, session, quota


def test_one_request_per_30_nips_and_quota_counted(tmp_path):
    store, client, session, quota = setup(tmp_path, [make_response(200, ANSWER)])
    report = ingest_vat(NIPS, client=client, store=store, quota=quota, base_url=BASE, query_date=AS_OF)
    assert report.ok and dict(report.statuses) == {200: 1}
    assert session.calls[0]["url"] == f"{BASE}/5252674798,7740001454"
    assert session.calls[0]["params"] == {"date": "2026-11-08"}
    assert quota.used == 1
    stored = list(store.iter_envelopes(SOURCE))
    assert stored[0]["query_date"] == "2026-11-08"
    assert "NOWAK" not in stored[0]["payload"]


def test_dry_run_sends_nothing_and_spends_no_quota(tmp_path):
    store, client, session, quota = setup(tmp_path, [])
    report = ingest_vat(NIPS * 20, client=client, store=store, quota=quota, base_url=BASE, dry_run=True)
    assert session.calls == [] and quota.used == 0
    assert "2 NIP(s) to query" in report.notes[0] and "1 request(s)" in report.notes[0]


def test_answers_from_bronze_are_not_requested_again(tmp_path):
    store, client, session, quota = setup(tmp_path, [make_response(200, ANSWER)])
    ingest_vat(NIPS, client=client, store=store, quota=quota, base_url=BASE, query_date=AS_OF)
    report = ingest_vat(NIPS, client=client, store=store, quota=quota, base_url=BASE, query_date=AS_OF)
    assert report.cached == 2 and len(session.calls) == 1 and quota.used == 1


def test_retries_count_against_quota_and_429_is_not_retried(tmp_path):
    store, client, session, quota = setup(tmp_path, [make_response(503), make_response(200, ANSWER)])
    ingest_vat(NIPS, client=client, store=store, quota=quota, base_url=BASE, query_date=AS_OF)
    assert quota.used == 2  # the failed attempt also hit the server

    store, client, session, quota = setup(tmp_path / "b", [make_response(429)])
    report = ingest_vat(NIPS, client=client, store=store, quota=quota, base_url=BASE, query_date=AS_OF)
    assert len(session.calls) == 1 and not report.ok


def test_stops_before_exceeding_quota(tmp_path):
    nips = [f"{i:010d}" for i in range(90)]  # 3 batches, only 2 allowed
    store, client, session, quota = setup(tmp_path, [make_response(200, ANSWER)] * 2, limit=4, margin=2)
    report = ingest_vat(nips, client=client, store=store, quota=quota, base_url=BASE, query_date=AS_OF)
    assert len(session.calls) == 2 and quota.used == 2
    assert "daily quota reached" in next(iter(report.failed.values()))


def test_nips_come_from_krs_bronze_and_bad_ones_are_skipped(tmp_path):
    store = BronzeStore(tmp_path)

    def extract(nip):
        return json.dumps({"odpis": {"dane": {"dzial1": {"danePodmiotu": {"identyfikatory": {"nip": nip}}}}}})

    store.write_part("krs_current", [
        make_envelope("krs_current", "0000000001", "u", 200, extract("5252674798")),
        make_envelope("krs_current", "0000000002", "u", 200, extract("5252674799")),
        make_envelope("krs_current", "0000000003", "u", 200, json.dumps({"odpis": {}})),
        make_envelope("krs_current", "0009999999", "u", 404, "{}"),
    ])
    valid, problems = nips_from_krs_bronze(store)
    assert valid == ["5252674798"]
    assert any("fails checksum" in p for p in problems) and any("no NIP" in p for p in problems)


def test_nip_from_extract_tolerates_missing_sections():
    assert nip_from_extract({}) is None
    assert nip_from_extract({"odpis": {"dane": None}}) is None


# Body shape observed live on 2026-11-08 (HTTP 200, text/html) - not an API answer.
WAF_PAGE = ('<html style="height:100%"><head><META NAME="ROBOTS" CONTENT="NOINDEX, NOFOLLOW"></head>'
            '<body><iframe id="main-iframe" src="/_Incapsula_Resource?x=1">Request unsuccessful. '
            'Incapsula incident ID: 0-0</iframe></body></html>')


def test_waf_page_with_200_is_a_failure_and_never_cached(tmp_path):
    store, client, session, quota = setup(
        tmp_path, [make_response(200, WAF_PAGE, headers={"Content-Type": "text/html"}), make_response(200, ANSWER)]
    )
    report = ingest_vat(NIPS, client=client, store=store, quota=quota, base_url=BASE, query_date=AS_OF)
    assert not report.ok and "HTML/WAF" in next(iter(report.failed.values()))
    assert list(store.iter_envelopes(SOURCE)) == []
    assert quota.used == 1  # the request was sent, so it still counts
    report = ingest_vat(NIPS, client=client, store=store, quota=quota, base_url=BASE, query_date=AS_OF)
    assert report.ok and report.cached == 0  # nothing was treated as already fetched


def test_invalid_answers_already_in_bronze_do_not_count_as_cache(tmp_path):
    store, client, session, quota = setup(tmp_path, [make_response(200, ANSWER)])
    store.write_part(SOURCE, [make_envelope(SOURCE, ",".join(NIPS), "u", 200, WAF_PAGE, query_date="2026-11-08")])
    report = ingest_vat(NIPS, client=client, store=store, quota=quota, base_url=BASE, query_date=AS_OF)
    assert report.cached == 0 and len(session.calls) == 1
