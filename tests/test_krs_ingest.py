from __future__ import annotations

import json
from datetime import date

import pytest
from fakes import FakeSession, make_response

from kyb.http import HttpClient
from kyb.ingestion.krs import ingest_krs
from kyb.storage import BronzeStore
from kyb.watchlist import normalize_krs, read_watchlist

DAY = date(2026, 11, 8)
BASE = "https://api-krs.example/api/krs"
ODPIS = json.dumps({"odpis": {"dane": {"dzial2": {"sklad": [{"imiona": {"imie": "J***"}}]}}}}, indent=2)
NOT_FOUND = '{"title": "Not Found", "status": 404}'


def run(store, outcomes, numbers, **kwargs):
    session = FakeSession(outcomes)
    client = HttpClient(session=session, sleep=lambda s: None)
    report = ingest_krs(numbers, client=client, store=store, base_url=BASE, ingest_date=DAY,
                        min_interval_s=0, **kwargs)
    return report, session


def test_stores_200_and_404_and_reports_400(tmp_path):
    store = BronzeStore(tmp_path)
    report, session = run(
        store,
        [make_response(200, ODPIS), make_response(404, NOT_FOUND), make_response(400, '{"title":"Bad Request"}')],
        ["0000000001", "0009999999", "0000000000"],
    )
    assert session.calls[0]["url"] == f"{BASE}/OdpisAktualny/0000000001"
    assert session.calls[0]["params"] == {"rejestr": "P", "format": "json"}
    assert dict(report.statuses) == {200: 1, 404: 1}
    assert list(report.failed) == ["0000000000"]
    assert not report.ok
    stored = store.latest_by_key("krs_current", DAY)
    assert set(stored) == {"0000000001", "0009999999"}
    assert stored["0009999999"]["http_status"] == 404
    assert "J***" not in stored["0000000001"]["payload"]  # redacted before writing
    assert stored["0000000001"]["redacted_values"] == 1


def test_second_run_same_day_uses_bronze_instead_of_api(tmp_path):
    store = BronzeStore(tmp_path)
    run(store, [make_response(200, ODPIS)], ["0000000001"])
    report, session = run(store, [], ["0000000001"])  # FakeSession fails on any request
    assert report.cached == 1 and session.calls == []
    report, session = run(store, [make_response(200, ODPIS)], ["0000000001"], force=True)
    assert len(session.calls) == 1


def test_results_are_kept_when_run_is_interrupted(tmp_path):
    store = BronzeStore(tmp_path)
    with pytest.raises(KeyboardInterrupt):
        run(store, [make_response(200, ODPIS), KeyboardInterrupt()], ["0000000001", "0000000002"])
    assert set(store.latest_by_key("krs_current", DAY)) == {"0000000001"}


def test_full_extract_endpoint_goes_to_separate_source(tmp_path):
    store = BronzeStore(tmp_path)
    report, session = run(store, [make_response(200, ODPIS)], ["0000000001"], endpoint="OdpisPelny")
    assert report.source == "krs_full"
    assert session.calls[0]["url"].endswith("/OdpisPelny/0000000001")


def test_normalize_krs_pads_and_validates():
    assert normalize_krs(" 28860 ") == "0000028860"
    for bad in ("", "12a", "12345678901"):
        with pytest.raises(ValueError):
            normalize_krs(bad)


def test_read_watchlist_dedupes_and_skips_blank_lines(tmp_path):
    path = tmp_path / "watchlist.csv"
    path.write_text("krs,note\n28860,a\n\n0000028860,dup\n126258,b\n", encoding="utf-8")
    assert read_watchlist(path) == ["0000028860", "0000126258"]
    path.write_text("number\n1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing 'krs' column"):
        read_watchlist(path)


def test_200_without_extract_is_rejected(tmp_path):
    store = BronzeStore(tmp_path)
    report, _ = run(store, [make_response(200, "<html>blocked</html>", headers={"Content-Type": "text/html"}),
                            make_response(200, '{"unexpected": true}')], ["0000000001", "0000000002"])
    assert set(report.failed) == {"0000000001", "0000000002"}
    assert store.latest_by_key("krs_current", DAY) == {}
