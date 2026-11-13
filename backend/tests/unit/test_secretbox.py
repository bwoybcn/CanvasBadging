# SPDX-License-Identifier: AGPL-3.0-or-later
from __future__ import annotations

import pytest

from opencredential import secretbox
from opencredential.settings import Settings


def test_round_trip_and_context_binding() -> None:
    s = Settings()
    sealed = secretbox.seal(s, "canvas-access-token", "canvas_token:1:a")
    assert b"canvas-access-token" not in sealed
    assert secretbox.open_(s, sealed, "canvas_token:1:a") == "canvas-access-token"
    with pytest.raises(secretbox.SecretBoxError):
        secretbox.open_(s, sealed, "canvas_token:2:a")  # copied to another row
    other = Settings(token_encryption_key="x" * 40)
    with pytest.raises(secretbox.SecretBoxError):
        secretbox.open_(other, sealed, "canvas_token:1:a")
    with pytest.raises(secretbox.SecretBoxError):
        secretbox.open_(s, b"garbage", "canvas_token:1:a")
