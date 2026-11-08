from __future__ import annotations

import json
from datetime import date

import pytest

from kyb.quota import DailyQuota, QuotaExceededError


class Clock:
    def __init__(self, day: date) -> None:
        self.day = day

    def __call__(self) -> date:
        return self.day


def test_counter_is_persisted_on_disk(tmp_path):
    path = tmp_path / "state" / "vat_quota.json"
    clock = Clock(date(2026, 11, 8))
    DailyQuota(path, limit=100, today=clock).consume(1, note="batch 1")
    DailyQuota(path, limit=100, today=clock).consume(2)  # a new process sees the same counter
    state = json.loads(path.read_text(encoding="utf-8"))
    assert state["date"] == "2026-11-08" and state["used"] == 3
    assert [e["requests"] for e in state["events"]] == [1, 2]


def test_limit_with_safety_margin_blocks_before_sending(tmp_path):
    quota = DailyQuota(tmp_path / "q.json", limit=5, safety_margin=2, today=Clock(date(2026, 11, 8)))
    quota.consume(3)
    with pytest.raises(QuotaExceededError, match="3 used, 3 allowed"):
        quota.consume(1)
    assert quota.used == 3  # the refused request was not counted
    assert quota.remaining == 0


def test_counter_resets_on_a_new_day(tmp_path):
    clock = Clock(date(2026, 11, 8))
    quota = DailyQuota(tmp_path / "q.json", limit=2, today=clock)
    quota.consume(2)
    clock.day = date(2026, 11, 9)
    assert quota.used == 0
    quota.consume(1)
    assert quota.used == 1


def test_margin_must_leave_room():
    with pytest.raises(ValueError):
        DailyQuota(__import__("pathlib").Path("x.json"), limit=5, safety_margin=5)
