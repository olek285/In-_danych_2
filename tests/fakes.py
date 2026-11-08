"""Offline stand-ins for requests.Session used by the tests."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import requests


def make_response(
    status: int,
    body: bytes | str = b"",
    url: str = "https://example.test/x",
    headers: dict[str, str] | None = None,
) -> requests.Response:
    response = requests.Response()
    response.status_code = status
    response._content = body.encode("utf-8") if isinstance(body, str) else body
    response._content_consumed = True  # lets iter_content() replay _content
    response.url = url
    response.headers.update(headers or {"Content-Type": "application/json"})
    return response


class FakeSession:
    """Returns (or raises) the scripted outcomes in order and records calls."""

    def __init__(self, outcomes: Iterable[requests.Response | BaseException]) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[dict[str, Any]] = []
        self.headers: dict[str, str] = {}

    def get(self, url: str, params: Any = None, timeout: Any = None, stream: bool = False):
        self.calls.append({"url": url, "params": params, "stream": stream})
        if not self.outcomes:
            raise AssertionError(f"unexpected extra request to {url}")
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        if outcome.url == "https://example.test/x":
            outcome.url = url
        return outcome
