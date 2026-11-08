"""Daily request quota persisted on disk (data/state/<name>.json).

The VAT White List allows 100 ``search`` requests per day; exceeding it blocks
the IP address until midnight. The counter is incremented *before* each request
is sent (retries included), so a crash can only over-count, never under-count.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

from kyb.config import local_today
from kyb.storage import atomic_write_json, utc_now_iso


class QuotaExceededError(RuntimeError):
    """Raised instead of sending a request that would exceed the daily limit."""


class DailyQuota:
    def __init__(
        self,
        path: Path,
        limit: int,
        safety_margin: int = 0,
        today: Callable[[], date] = local_today,
    ) -> None:
        if safety_margin >= limit:
            raise ValueError("safety margin must be smaller than the limit")
        self.path = path
        self.limit = limit
        self.safety_margin = safety_margin
        self.today = today

    @property
    def allowed(self) -> int:
        """Requests we allow ourselves per day (hard limit minus safety margin)."""
        return self.limit - self.safety_margin

    def _load(self) -> dict[str, Any]:
        today = self.today().isoformat()
        if self.path.is_file():
            state = json.loads(self.path.read_text(encoding="utf-8"))
            if state.get("date") == today:
                return state
        return {"date": today, "used": 0, "limit": self.limit, "events": []}

    @property
    def used(self) -> int:
        return int(self._load()["used"])

    @property
    def remaining(self) -> int:
        return max(self.allowed - self.used, 0)

    def consume(self, requests: int = 1, note: str = "") -> int:
        """Record ``requests`` about to be sent; returns the new daily total."""
        state = self._load()
        if state["used"] + requests > self.allowed:
            raise QuotaExceededError(
                f"daily quota reached: {state['used']} used, {self.allowed} allowed "
                f"(API limit {self.limit}, safety margin {self.safety_margin}); try again tomorrow"
            )
        state["used"] += requests
        state["limit"] = self.limit
        state["events"].append({"at": utc_now_iso(), "requests": requests, "note": note})
        atomic_write_json(self.path, state)
        return state["used"]

    def status(self) -> str:
        return (
            f"{self.today().isoformat()}: used {self.used} of {self.allowed} allowed requests "
            f"(API limit {self.limit}, safety margin {self.safety_margin}); remaining {self.remaining}"
        )
