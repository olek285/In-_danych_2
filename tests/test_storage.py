from __future__ import annotations

import json
from datetime import date

import pytest

from kyb.storage import BronzeStore, atomic_open, atomic_write_text, make_envelope


def test_envelope_has_required_fields():
    env = make_envelope("krs_current", "0000000001", "https://x/1", 200, '{"a": 1}')
    assert list(env)[:6] == ["source", "key", "url", "http_status", "ingested_at", "payload"]
    assert env["ingested_at"].endswith("+00:00")


def test_write_part_uses_ingest_date_partition_and_never_overwrites(tmp_path):
    store = BronzeStore(tmp_path)
    day = date(2026, 11, 8)
    env = make_envelope("krs_current", "k1", "u", 200, "{}")
    p1 = store.write_part("krs_current", [env], ingest_date=day)
    p2 = store.write_part("krs_current", [env], ingest_date=day)
    assert p1.parent == tmp_path / "krs_current" / "ingest_date=2026-11-08"
    assert p1 != p2  # a second run adds a new part file instead of rewriting the first
    assert json.loads(p1.read_text(encoding="utf-8").splitlines()[0])["key"] == "k1"


def test_write_part_rejects_incomplete_envelope(tmp_path):
    with pytest.raises(ValueError, match="misses fields"):
        BronzeStore(tmp_path).write_part("s", [{"source": "s", "key": "k"}])


def test_write_part_skips_empty_batches(tmp_path):
    assert BronzeStore(tmp_path).write_part("s", []) is None
    assert not (tmp_path / "s").exists()


def test_latest_by_key_prefers_newest_and_filters_statuses(tmp_path):
    store = BronzeStore(tmp_path)
    day = date(2026, 11, 8)
    old = make_envelope("s", "k", "u", 200, "old", ingested_at="2026-11-08T08:00:00+00:00")
    new = make_envelope("s", "k", "u", 200, "new", ingested_at="2026-11-08T09:00:00+00:00")
    failed = make_envelope("s", "k2", "u", 500, "x")
    store.write_part("s", [new, failed], ingest_date=day)
    store.write_part("s", [old], ingest_date=day)
    latest = store.latest_by_key("s", day)
    assert latest["k"]["payload"] == "new"
    assert "k2" not in latest


def test_atomic_open_leaves_old_content_on_failure(tmp_path):
    target = tmp_path / "state.json"
    atomic_write_text(target, "old")
    with pytest.raises(RuntimeError):
        with atomic_open(target, "w", encoding="utf-8") as fh:
            fh.write("half-writ")
            raise RuntimeError("crash in the middle")
    assert target.read_text(encoding="utf-8") == "old"
    assert [p.name for p in tmp_path.iterdir()] == ["state.json"]
