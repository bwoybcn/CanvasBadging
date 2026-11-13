# SPDX-License-Identifier: AGPL-3.0-or-later
"""Bitstring Status List v1.0 encoding (W3C Recommendation, 15 May 2025).

``encodedList`` is the multibase base64url (no padding, prefix ``u``) encoding of the
GZIP-compressed bitstring. Index 0 is the left-most (most significant) bit of the first byte.
The minimum list length is 131,072 bits (16 KB), which gives group privacy.
"""

from __future__ import annotations

import base64
import gzip
import io
from collections.abc import Iterable

MIN_BITS = 131_072


def encode(set_indexes: Iterable[int], size: int = MIN_BITS) -> str:
    if size < MIN_BITS or size % 8:
        raise ValueError(f"status list size must be a multiple of 8 and at least {MIN_BITS}")
    bits = bytearray(size // 8)
    for i in set_indexes:
        if not 0 <= i < size:
            raise ValueError(f"status index {i} outside list of {size}")
        bits[i // 8] |= 0x80 >> (i % 8)
    compressed = gzip.compress(bytes(bits), compresslevel=9, mtime=0)
    return "u" + base64.urlsafe_b64encode(compressed).decode("ascii").rstrip("=")


def decode(encoded_list: str, *, max_bytes: int = 16 * 1024 * 1024) -> bytes:
    """Return the raw bitstring. Accepts multibase ``u`` (base64url) as the spec requires."""
    if not encoded_list.startswith("u"):
        raise ValueError("encodedList must be multibase base64url (prefix 'u')")
    body = encoded_list[1:]
    raw = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))
    d = gzip.GzipFile(fileobj=io.BytesIO(raw))
    out = d.read(max_bytes + 1)
    if len(out) > max_bytes:
        raise ValueError("status list is too large")
    return out


def is_set(bitstring: bytes, index: int) -> bool:
    if not 0 <= index < len(bitstring) * 8:
        raise IndexError(f"status index {index} outside list of {len(bitstring) * 8}")
    return bool(bitstring[index // 8] & (0x80 >> (index % 8)))
