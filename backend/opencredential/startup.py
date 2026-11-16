# SPDX-License-Identifier: AGPL-3.0-or-later
"""Checks made before the api serves or the worker takes jobs (ADR-0005)."""

from __future__ import annotations

from sqlalchemy import text

from opencredential.db.session import app_engine
from opencredential.settings import Settings


class StartupRefused(RuntimeError):
    pass


def check_production_safety(settings: Settings) -> None:
    """Refuse to run in production while a signing key is a development key.

    Two questions, both answered by the database so that neither depends on the signer being
    up: is an active key *marked* as a development key, and is an active key *protected* by the
    committed development key-wrapping key? The second catches a signer that once ran without
    its own ``SIGNER_KEK``: its keys look like production keys, but anyone who can read the
    database and the repository could unwrap them.
    """
    if not settings.is_production:
        return
    with app_engine().connect() as conn:
        if conn.execute(text("select app.dev_keys_active()")).scalar():
            raise StartupRefused(
                "A development signing key is active. Retire it before running in production."
            )
        if conn.execute(text("select app.dev_wrapped_keys_active()")).scalar():
            raise StartupRefused(
                "An active signing key is protected with the committed development key-wrapping "
                "key: the signer created it without its own SIGNER_KEK. Give the signer a "
                "SIGNER_KEK, create a new key for the issuer, then retire and destroy this one."
            )
