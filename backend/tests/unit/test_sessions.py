# SPDX-License-Identifier: AGPL-3.0-or-later
import uuid

import pytest

from opencredential.authz import sessions
from opencredential.settings import Settings

S = Settings(env="test")
USER, INST = uuid.uuid4(), uuid.uuid4()


def test_round_trip() -> None:
    token, expires = sessions.issue(S, user_id=USER, institution_id=INST, method="dev")
    claims = sessions.verify(S, token)
    assert (claims.user_id, claims.institution_id, claims.method) == (USER, INST, "dev")
    assert claims.expires_at == expires.replace(microsecond=0)


def test_rejects_other_key() -> None:
    token, _ = sessions.issue(S, user_id=USER, institution_id=INST, method="dev")
    other = Settings(env="test", secret_key="another-secret-key-of-sufficient-length-123")
    with pytest.raises(sessions.InvalidSession):
        sessions.verify(other, token)


def test_rejects_expired() -> None:
    expired = Settings(env="test")
    object.__setattr__(expired, "session_ttl_minutes", -1)
    token, _ = sessions.issue(expired, user_id=USER, institution_id=INST, method="dev")
    with pytest.raises(sessions.InvalidSession):
        sessions.verify(S, token)


@pytest.mark.parametrize("token", ["", "abc", "a.b.c", "eyJhbGciOiJub25lIn0.e30."])
def test_rejects_garbage_and_alg_none(token: str) -> None:
    with pytest.raises(sessions.InvalidSession):
        sessions.verify(S, token)
