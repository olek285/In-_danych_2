from __future__ import annotations

import pytest

from kyb.nip import chunked, is_valid_nip, nip_batches, normalize_nip


@pytest.mark.parametrize(
    "nip",
    ["5252674798", "7740001454", "1234563218", "PL 525-267-47-98", "pl5252674798"],
)
def test_valid_checksums(nip):
    assert is_valid_nip(nip)


@pytest.mark.parametrize(
    "nip",
    [
        "5252674799",  # wrong check digit
        "1234567890",  # checksum 10 is never valid
        "0000000000",  # KRS uses zeros as a placeholder for foreign entities
        "525267479",  # too short
        "52526747981",  # too long
        "52526747AB",
        "",
        None,
    ],
)
def test_invalid_nips(nip):
    assert not is_valid_nip(nip)


def test_normalize_strips_prefix_and_separators():
    assert normalize_nip(" PL 525-267-47.98 ") == "5252674798"


def test_batches_of_30_with_remainder():
    nips = [f"{i:010d}" for i in range(65)]
    batches = nip_batches(nips, 30)
    assert [len(b) for b in batches] == [30, 30, 5]
    assert batches[0][0] == "0000000000" and batches[-1][-1] == "0000000064"


def test_batches_dedupe_after_normalisation():
    assert nip_batches(["5252674798", "PL 525-267-47-98", "7740001454"], 30) == [["5252674798", "7740001454"]]


def test_exactly_30_is_one_request_and_empty_is_none():
    assert len(nip_batches([f"{i:010d}" for i in range(30)], 30)) == 1
    assert nip_batches([], 30) == []


def test_chunk_size_must_be_positive():
    with pytest.raises(ValueError):
        chunked(["a"], 0)
