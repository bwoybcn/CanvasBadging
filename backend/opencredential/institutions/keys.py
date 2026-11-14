# SPDX-License-Identifier: AGPL-3.0-or-later
"""Issuer signing-key lifecycle: create, activate, rotate, retire, compromise (ADR-0005).

The private half never leaves the signer. This module records the public half and the key's
state, and tells the signer when a key must stop signing (retire) or be erased (destroy).

Retire and destroy cannot be undone in the signer, so they only happen once the database change
that calls for them has committed: straight after the commit, and through a job queued in the
same transaction in case the signer is unreachable at that moment. A rollback therefore never
leaves the signer refusing a key the database still calls active.

States: ``pending → active → retired → (revoked)``; exactly one active key per issuer.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import event, select
from sqlalchemy.orm import Session, SessionTransaction

from opencredential import audit
from opencredential.db.models import Credential, Issuer, IssuerKey
from opencredential.institutions.identity import verification_method_id
from opencredential.jobs import enqueue
from opencredential.logging import get_logger
from opencredential.signer_client import SignerClient

log = get_logger("keys")

#: Job that tells the signer to retire or destroy a key (idempotent; see module docstring).
SIGNER_KEY_LIFECYCLE = "oc:signer_key_lifecycle"
_AFTER_COMMIT = "oc_signer_after_commit"

#: Retired private keys are erased after this long (no further signing need, ADR-0005).
RETIRED_KEY_DESTROY_AFTER = timedelta(days=30)


class KeyLifecycleError(RuntimeError):
    pass


@event.listens_for(Session, "after_commit")
def _run_signer_actions(session: Session) -> None:
    if session.get_nested_transaction() is not None:
        return  # a savepoint was released; the real transaction is still open
    for client, act, kid in session.info.pop(_AFTER_COMMIT, []):
        try:
            apply_in_signer(client, act, kid)
        except Exception as exc:  # the job queued in the same transaction retries
            log.warning(
                "signer_key_action_deferred",
                issuer_key_id=str(kid),
                action=act,
                error=type(exc).__name__,
            )


@event.listens_for(Session, "after_transaction_end")
def _drop_signer_actions(session: Session, transaction: SessionTransaction) -> None:
    if transaction.parent is None:
        # After a commit the list is already empty; after a rollback it goes with it.
        session.info.pop(_AFTER_COMMIT, None)


def apply_in_signer(signer: SignerClient, action: str, key_id: uuid.UUID) -> None:
    if action == "retire":
        signer.retire_key(key_id)
    elif action == "destroy":
        signer.destroy_key(key_id)
    else:
        raise ValueError(f"unknown signer key action {action!r}")


def _signer_after_commit(db: Session, signer: SignerClient, action: str, key: IssuerKey) -> None:
    """Retire or destroy ``key`` in the signer once, and only if, this transaction commits."""
    enqueue.defer(
        db,
        SIGNER_KEY_LIFECYCLE,
        queue="maintenance",
        institution_id=key.institution_id,
        args={"key_id": str(key.id), "action": action},
        subject_type="issuer_key",
        subject_id=key.id,
        queueing_lock=f"signer_key:{action}:{key.id}",
    )
    pending: list[tuple[SignerClient, str, uuid.UUID]] = db.info.setdefault(_AFTER_COMMIT, [])
    pending.append((signer, action, key.id))


def active_key(db: Session, issuer_id: uuid.UUID) -> IssuerKey | None:
    return db.scalar(
        select(IssuerKey).where(IssuerKey.issuer_id == issuer_id, IssuerKey.state == "active")
    )


def create_key(
    db: Session, issuer: Issuer, signer: SignerClient, *, dev: bool = False
) -> IssuerKey:
    """Generate a key in the signer and record it as ``pending``."""
    if issuer.did.startswith("did:key:") and active_key(db, issuer.id):
        raise KeyLifecycleError(
            "did:key issuers cannot rotate: the DID *is* the key. Create a did:web issuer for "
            "production use (ADR-0004)."
        )
    key_id = uuid.uuid4()
    generated = signer.create_key(key_id, dev=dev)
    key = IssuerKey(
        id=key_id,
        institution_id=issuer.institution_id,
        issuer_id=issuer.id,
        verification_method_id=verification_method_id(
            issuer, key_id, generated.verification_method_id
        ),
        public_key_multibase=generated.public_key_multibase,
        state="pending",
        is_dev=dev,
    )
    db.add(key)
    db.flush()
    return key


def activate(
    db: Session,
    key: IssuerKey,
    signer: SignerClient,
    *,
    actor_user_id: uuid.UUID | None = None,
    now: datetime | None = None,
) -> IssuerKey | None:
    """Make ``key`` the issuer's signing key; the previous active key is retired (and stays
    published so its credentials keep verifying). Returns the retired key, if any."""
    now = now or datetime.now(UTC)
    if key.state != "pending":
        raise KeyLifecycleError(f"only a pending key can be activated (this one is {key.state})")
    previous = db.scalar(
        select(IssuerKey)
        .where(IssuerKey.issuer_id == key.issuer_id, IssuerKey.state == "active")
        .with_for_update()
    )
    if previous is not None:
        previous.state = "retired"
        previous.retired_at = now
        db.flush()  # free the one-active-key slot before activating the new key
    key.state = "active"
    key.activated_at = now
    db.flush()
    if previous is not None:
        _signer_after_commit(db, signer, "retire", previous)
    audit.record(
        db,
        action="issuer_key.activate",
        resource_type="issuer_key",
        resource_id=key.id,
        institution_id=key.institution_id,
        actor_user_id=actor_user_id,
        actor_kind="user" if actor_user_id else "system",
        data={"retired_key_id": str(previous.id) if previous else None},
    )
    return previous


def rotate(
    db: Session,
    issuer: Issuer,
    signer: SignerClient,
    *,
    actor_user_id: uuid.UUID | None = None,
) -> IssuerKey:
    """Routine rotation: new active key, old key retired but still published."""
    key = create_key(db, issuer, signer)
    activate(db, key, signer, actor_user_id=actor_user_id)
    return key


@dataclass
class CompromiseResult:
    revoked_key_id: uuid.UUID
    replacement_key_id: uuid.UUID | None
    affected_credential_ids: list[uuid.UUID]


def handle_compromise(
    db: Session,
    key: IssuerKey,
    signer: SignerClient,
    *,
    reason: str,
    actor_user_id: uuid.UUID,
    now: datetime | None = None,
) -> CompromiseResult:
    """Key-compromise response, steps 2-5 of docs/security/key-compromise.md.

    1. A replacement key is activated first (did:web issuers), so status lists can be re-signed.
    2. The compromised key is marked ``revoked`` and removed from the DID document: everything it
       signed now fails signature verification at any verifier that re-resolves the DID.
    3. Its private material is destroyed in the signer.
    4. The credentials it signed are returned so the caller can revoke them in the status list
       (reason ``key_compromise``), notify holders and offer reissue.
    """
    now = now or datetime.now(UTC)
    if key.state == "revoked":
        raise KeyLifecycleError("key is already revoked")
    issuer = db.get(Issuer, key.issuer_id)
    assert issuer is not None
    replacement: IssuerKey | None = None
    if key.state == "active" and issuer.did.startswith("did:web:"):
        replacement = create_key(db, issuer, signer)
        activate(db, replacement, signer, actor_user_id=actor_user_id, now=now)
    key.state = "revoked"
    key.revoked_at = now
    key.revocation_reason = reason
    db.flush()
    _signer_after_commit(db, signer, "destroy", key)
    affected = list(
        db.scalars(
            select(Credential.id).where(
                Credential.issuer_key_id == key.id, Credential.status == "issued"
            )
        )
    )
    audit.record(
        db,
        action="issuer_key.compromised",
        resource_type="issuer_key",
        resource_id=key.id,
        institution_id=key.institution_id,
        actor_user_id=actor_user_id,
        data={
            "affected_credentials": len(affected),
            "replacement_key_id": str(replacement.id) if replacement else None,
        },
    )
    return CompromiseResult(
        revoked_key_id=key.id,
        replacement_key_id=replacement.id if replacement else None,
        affected_credential_ids=affected,
    )


def keys_due_for_destruction(db: Session, now: datetime | None = None) -> list[IssuerKey]:
    """Retired keys past the grace period whose private material has not been erased yet."""
    cutoff = (now or datetime.now(UTC)) - RETIRED_KEY_DESTROY_AFTER
    return list(
        db.scalars(
            select(IssuerKey).where(
                IssuerKey.state == "retired",
                IssuerKey.retired_at < cutoff,
                IssuerKey.destroyed_at.is_(None),
            )
        )
    )


def mark_destroyed(
    db: Session, key_id: uuid.UUID, *, reason: str, now: datetime | None = None
) -> bool:
    """Record that the signer erased ``key_id``'s private material. Idempotent.

    Call only after the signer confirmed the destruction. Returns ``True`` the first time.
    """
    key = db.get(IssuerKey, key_id)
    if key is None or key.destroyed_at is not None:
        return False
    key.destroyed_at = now or datetime.now(UTC)
    audit.record(
        db,
        action="issuer_key.destroyed",
        resource_type="issuer_key",
        resource_id=key.id,
        institution_id=key.institution_id,
        actor_kind="system",
        data={"reason": reason, "state": key.state},
    )
    return True
