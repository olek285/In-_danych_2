"""Test-wide safety net: no test may open a network connection.

This matters in particular for the VAT White List API, whose daily quota
(100 search requests, IP blocked until midnight) must never be spent by tests.
"""

from __future__ import annotations

import socket

import pytest


class NetworkAccessInTests(RuntimeError):
    pass


@pytest.fixture(autouse=True)
def _block_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def guard(*args, **kwargs):
        raise NetworkAccessInTests("tests must not use the network - use fakes or saved samples")

    monkeypatch.setattr(socket.socket, "connect", guard)
    monkeypatch.setattr(socket, "create_connection", guard)
