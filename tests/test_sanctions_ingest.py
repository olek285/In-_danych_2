"""OpenSanctions ingestion on a fictional CSV shaped like targets.simple.csv."""

from __future__ import annotations

import hashlib
import json
from datetime import date

from fakes import FakeSession, make_response

from kyb.http import HttpClient
from kyb.ingestion.sanctions import SOURCE, ingest_sanctions, stored_versions

DAY = date(2026, 11, 8)
BASE = "https://data.example/datasets/latest"
HEADER = '"id","schema","name","aliases","birth_date","countries","dataset"\n'
COMPANY = '"NK-1","Company","ACME TRADING, LTD","ACME","","ru","Test list"\n'
PERSON = '"NK-2","Person","Jan Fikcyjny","","1970-01-01","pl","Test list"\n'
ORG = '"NK-3","Organization","Shadow\nHoldings","","","ir","Test list"\n'  # multi-line cell
VESSEL = '"NK-4","Vessel","MV FICTION","","","pa","Test list"\n'
CSV_BODY = (HEADER + COMPANY + PERSON + ORG + VESSEL).encode("utf-8")


def index_json(version="20261108-abc", checksum=None):
    return json.dumps({
        "name": "test_list",
        "version": version,
        "target_count": 4,
        "resources": [{
            "name": "targets.simple.csv",
            "url": f"https://data.example/artifacts/test_list/{version}/targets.simple.csv",
            "checksum": checksum or hashlib.sha1(CSV_BODY).hexdigest(),
            "size": len(CSV_BODY),
        }],
    })


def run(tmp_path, outcomes, **kwargs):
    session = FakeSession(outcomes)
    client = HttpClient(session=session, sleep=lambda s: None, max_retries=1)
    report = ingest_sanctions(["test_list"], client=client, bronze_root=tmp_path, base_url=BASE,
                              ingest_date=DAY, **kwargs)
    return report, session


def csv_response():
    return make_response(200, CSV_BODY, headers={"Content-Type": "text/csv", "Content-Length": str(len(CSV_BODY))})


def test_only_entity_rows_are_stored_byte_for_byte(tmp_path):
    report, session = run(tmp_path, [make_response(200, index_json()), csv_response()])
    assert report.ok, report.failed
    stored = tmp_path / SOURCE / "ingest_date=2026-11-08" / "test_list" / "20261108-abc" / "targets.simple.csv"
    assert stored.read_bytes() == (HEADER + COMPANY + ORG).encode("utf-8")
    assert b"Fikcyjny" not in stored.read_bytes() and b"1970-01-01" not in stored.read_bytes()
    assert session.calls[1]["url"].startswith("https://data.example/artifacts/test_list/20261108-abc/")


def test_metadata_describes_original_and_stored_subset(tmp_path):
    run(tmp_path, [make_response(200, index_json()), csv_response()])
    meta = json.loads(stored_versions(tmp_path, "test_list")[0].read_text(encoding="utf-8"))
    assert meta["source"] == "opensanctions" and meta["key"] == "test_list" and meta["http_status"] == 200
    assert meta["dataset_version"] == "20261108-abc"
    assert meta["original"]["rows"] == 4
    assert meta["original"]["sha1"] == meta["original"]["sha1_published"] == hashlib.sha1(CSV_BODY).hexdigest()
    assert meta["original"]["schema_counts"] == {"Company": 1, "Person": 1, "Organization": 1, "Vessel": 1}
    assert meta["stored"]["rows"] == 2 and meta["stored"]["dropped_rows"] == 2
    assert meta["columns"][:3] == ["id", "schema", "name"]
    assert json.loads(meta["payload"])["version"] == "20261108-abc"  # raw index.json kept


def test_known_version_is_not_downloaded_again(tmp_path):
    run(tmp_path, [make_response(200, index_json()), csv_response()])
    report, session = run(tmp_path, [make_response(200, index_json())])  # only index.json requested
    assert report.cached == 1 and len(session.calls) == 1
    report, session = run(tmp_path, [make_response(200, index_json("20261109-new")), csv_response()])
    assert len(stored_versions(tmp_path, "test_list")) == 2  # a new version is a new snapshot


def test_checksum_mismatch_fails_without_leaving_files(tmp_path):
    report, _ = run(tmp_path, [make_response(200, index_json(checksum="0" * 40)), csv_response(), csv_response()])
    assert not report.ok and "differs from published" in report.failed["test_list"]
    assert stored_versions(tmp_path, "test_list") == []
    assert not any(p.is_file() for p in tmp_path.rglob("*"))


def test_unknown_dataset_is_reported(tmp_path):
    report, _ = run(tmp_path, [make_response(404, '{"detail": "Not found"}')])
    assert "HTTP 404" in report.failed["test_list"]


def test_waf_or_html_index_is_rejected(tmp_path):
    report, _ = run(tmp_path, [make_response(200, "<html>blocked</html>", headers={"Content-Type": "text/html"})])
    assert "expected JSON" in report.failed["test_list"]
