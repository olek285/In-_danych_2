from __future__ import annotations

import pytest
import requests
from fakes import FakeSession, make_response

from kyb.http import HttpClient, SourceUnavailableError, UnexpectedStatusError


def client_with(outcomes, **kwargs):
    sleeps: list[float] = []
    session = FakeSession(outcomes)
    client = HttpClient(session=session, sleep=sleeps.append, **kwargs)
    return client, session, sleeps


def test_returns_200_without_retry():
    client, session, sleeps = client_with([make_response(200, '{"ok": true}')])
    result = client.get("https://example.test/a")
    assert result.status == 200
    assert result.text == '{"ok": true}'
    assert result.attempts == 1
    assert sleeps == []


def test_404_is_a_business_result_not_an_error():
    client, session, sleeps = client_with([make_response(404, '{"status": 404}')])
    result = client.get("https://example.test/missing")
    assert result.status == 404
    assert len(session.calls) == 1  # no retry for a definitive answer
    assert sleeps == []


def test_retries_5xx_with_exponential_backoff_then_succeeds():
    client, session, sleeps = client_with(
        [make_response(503), make_response(502), make_response(500), make_response(200, "{}")]
    )
    result = client.get("https://example.test/a")
    assert result.status == 200
    assert result.attempts == 4
    assert sleeps == [2, 4, 8]


def test_retries_network_errors():
    client, session, sleeps = client_with(
        [requests.ConnectionError("reset"), requests.Timeout("slow"), make_response(200, "{}")]
    )
    assert client.get("https://example.test/a").status == 200
    assert sleeps == [2, 4]


def test_network_error_after_last_retry_raises():
    client, session, sleeps = client_with([requests.ConnectionError("down")] * 5)
    with pytest.raises(SourceUnavailableError, match="5 attempt"):
        client.get("https://example.test/a")
    assert sleeps == [2, 4, 8, 16]


def test_persistent_5xx_raises_source_unavailable():
    client, session, sleeps = client_with([make_response(503)] * 3, max_retries=2)
    with pytest.raises(SourceUnavailableError, match="HTTP 503"):
        client.get("https://example.test/a")
    assert len(session.calls) == 3


def test_400_raises_immediately_without_retry():
    client, session, sleeps = client_with([make_response(400, '{"title": "Bad Request"}')])
    with pytest.raises(UnexpectedStatusError) as excinfo:
        client.get("https://example.test/a")
    assert excinfo.value.status == 400
    assert "Bad Request" in str(excinfo.value)
    assert len(session.calls) == 1


def test_retry_after_header_is_respected_and_capped():
    client, session, sleeps = client_with(
        [make_response(429, headers={"Retry-After": "30"}), make_response(429, headers={"Retry-After": "999"}),
         make_response(200, "{}")],
        max_backoff=60,
    )
    client.get("https://example.test/a")
    assert sleeps == [30, 60]


def test_custom_statuses_per_call():
    # e.g. the VAT API: 429 means "blocked until midnight", retrying is pointless
    client, session, sleeps = client_with([make_response(429)])
    with pytest.raises(UnexpectedStatusError):
        client.get("https://example.test/a", retry_statuses={502, 503, 504})


def test_before_attempt_runs_for_every_sent_request():
    counter: list[int] = []
    client, session, sleeps = client_with([make_response(503), make_response(200, "{}")])
    client.get("https://example.test/a", before_attempt=lambda: counter.append(1))
    assert len(counter) == 2


def test_before_attempt_can_veto_the_request():
    class QuotaHit(Exception):
        pass

    def veto():
        raise QuotaHit()

    client, session, sleeps = client_with([make_response(200, "{}")])
    with pytest.raises(QuotaHit):
        client.get("https://example.test/a", before_attempt=veto)
    assert session.calls == []  # nothing was sent


def test_json_without_charset_is_decoded_as_utf8():
    body = '{"nazwa": "SPÓŁKA ŻÓŁTA"}'.encode("utf-8")
    client, *_ = client_with([make_response(200, body, headers={"Content-Type": "application/json"})])
    assert "SPÓŁKA ŻÓŁTA" in client.get("https://example.test/a").text


def test_download_writes_file_atomically_with_checksum(tmp_path):
    import hashlib

    data = b"id,schema,name\n1,Company,ACME\n"
    client, session, sleeps = client_with(
        [make_response(503), make_response(200, data, headers={"Content-Length": str(len(data))})]
    )
    dest = tmp_path / "out" / "file.csv"
    result = client.download("https://example.test/file.csv", dest)
    assert dest.read_bytes() == data
    assert result.size_bytes == len(data)
    assert result.sha256 == hashlib.sha256(data).hexdigest()
    assert sleeps == [2]
    assert list(dest.parent.iterdir()) == [dest]  # no temp files left behind


def test_download_detects_truncated_transfer(tmp_path):
    data = b"partial"
    client, session, sleeps = client_with(
        [make_response(200, data, headers={"Content-Length": "100"})] * 2, max_retries=1
    )
    dest = tmp_path / "file.csv"
    with pytest.raises(SourceUnavailableError, match="got 7 of 100"):
        client.download("https://example.test/file.csv", dest)
    assert not dest.exists()
    assert list(tmp_path.iterdir()) == []


def test_parse_json_payload_names_the_problem():
    from kyb.http import InvalidPayloadError, parse_json_payload

    assert parse_json_payload('{"result": 1}', ["result"]) == {"result": 1}
    with pytest.raises(InvalidPayloadError, match="HTML/WAF"):
        parse_json_payload("<html>Request unsuccessful</html>")
    with pytest.raises(InvalidPayloadError, match="misses expected key"):
        parse_json_payload('{"other": 1}', ["result"])


def test_client_sends_json_accept_header_and_project_user_agent():
    client, session, _ = client_with([], user_agent="kyb-test/1.0")
    assert session.headers["User-Agent"] == "kyb-test/1.0"
    assert session.headers["Accept"].startswith("application/json")
