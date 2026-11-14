# SPDX-License-Identifier: AGPL-3.0-or-later
"""Retry policies of jobs whose failure would leave a security promise unkept."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from opencredential.jobs import tasks
from opencredential.signer_client import SignerRejected, SignerUnavailable


def test_signer_key_lifecycle_retries_while_the_signer_is_down() -> None:
    """Destroying a compromised key must survive a signer outage (review 14 Nov 2026, item 5)."""
    strategy = tasks.signer_key_lifecycle.retry_strategy
    assert strategy is not None
    job: Any = SimpleNamespace(attempts=1)
    assert strategy.get_retry_decision(exception=SignerUnavailable("down"), job=job) is not None
    refused = SignerRejected(409, "KEY_STATE", "already destroyed")
    assert strategy.get_retry_decision(exception=refused, job=job) is None
