# SPDX-License-Identifier: AGPL-3.0-or-later
"""Bitstring Status List encoding (W3C BSL v1.0 §4)."""

from __future__ import annotations

import base64
import gzip

import pytest
from hypothesis import given
from hypothesis import strategies as st

from opencredential.status import bitstring


def test_empty_list_is_16kb_of_zeros() -> None:
    enc = bitstring.encode([])
    assert enc.startswith("u")
    raw = bitstring.decode(enc)
    assert len(raw) == 16384 and not any(raw)


def test_index_zero_is_the_leftmost_bit() -> None:
    raw = bitstring.decode(bitstring.encode([0, 9]))
    assert raw[0] == 0b1000_0000 and raw[1] == 0b0100_0000


def test_encoding_is_plain_gzip_base64url_without_padding() -> None:
    enc = bitstring.encode([5])
    assert "=" not in enc and "+" not in enc and "/" not in enc
    body = enc[1:]
    data = gzip.decompress(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    assert data[0] == 0b0000_0100


def test_rejects_small_lists_and_bad_indexes() -> None:
    with pytest.raises(ValueError):
        bitstring.encode([], size=1024)
    with pytest.raises(ValueError):
        bitstring.encode([bitstring.MIN_BITS])
    with pytest.raises(ValueError):
        bitstring.decode("zabc")


@given(st.sets(st.integers(min_value=0, max_value=bitstring.MIN_BITS - 1), max_size=50))
def test_round_trip(indexes: set[int]) -> None:
    raw = bitstring.decode(bitstring.encode(indexes))
    for i in list(indexes)[:10]:
        assert bitstring.is_set(raw, i)
    assert sum(bin(b).count("1") for b in raw) == len(indexes)
