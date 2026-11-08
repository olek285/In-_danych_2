from __future__ import annotations

import pytest
import requests

from conftest import NetworkAccessInTests


def test_real_network_requests_are_blocked_in_tests():
    # wl-api.mf.gov.pl has a hard daily quota; tests must never reach it
    with pytest.raises((NetworkAccessInTests, requests.ConnectionError)):
        requests.get("https://wl-api.mf.gov.pl/api/search/nips/5260250995?date=2026-01-01", timeout=5)
