# SPDX-License-Identifier: AGPL-3.0-or-later
"""Status list allocation, revocation and publishing (ADR-0006, spec §7.6).

* Each issuer has revocation lists of 131,072 entries. A credential gets a *random* unused index
  (no ordering leak); a new list is opened when the current one is 90% allocated.
* Revocation never deletes anything: it records state, reason, actor and an event, and the list
  is re-signed so previously downloaded copies are recognised as revoked.
* A published list is a ``BitstringStatusListCredential`` signed by the issuer's active key, with
  ``validUntil`` 30 days ahead; it is republished daily and after every revocation.
"""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from opencredential import audit
from opencredential.db.models import (
    Credential,
    CredentialStatus,
    CredentialStatusEvent,
    Institution,
    Issuer,
    StatusList,
    StatusListBit,
)
from opencredential.ids import uuid7
from opencredential.institutions.identity import base_url
from opencredential.institutions.keys import active_key
from opencredential.issuance.ob3 import VC_V2_CONTEXT, iso
from opencredential.settings import Settings
from opencredential.signer_client import SignerClient
from opencredential.status import bitstring

LIST_SIZE = bitstring.MIN_BITS
FILL_LIMIT = int(LIST_SIZE * 0.9)
LIST_VALIDITY = timedelta(days=30)
REPUBLISH_EVERY = timedelta(days=1)
TTL_MS = 300_000

#: Reason codes for revocation (free text goes in ``reason_text``, which is never public).
REASON_CODES = (
    "issued_in_error",
    "academic_misconduct",
    "requirements_not_met",
    "superseded",
    "key_compromise",
    "learner_request",
    "other",
)


class StatusError(RuntimeError):
    pass


def list_url(institution: Institution, settings: Settings, status_list: StatusList) -> str:
    return base_url(institution, settings) + status_list.url_path


def allocate(db: Session, issuer: Issuer) -> tuple[StatusList, int]:
    """Reserve a random unused index on the issuer's current revocation list."""
    candidates = db.scalars(
        select(StatusList)
        .where(StatusList.issuer_id == issuer.id, StatusList.purpose == "revocation")
        .order_by(StatusList.created_at)
        .with_for_update()
    ).all()
    for sl in candidates:
        used = set(
            db.scalars(select(StatusListBit.index).where(StatusListBit.status_list_id == sl.id))
        )
        if len(used) < min(FILL_LIMIT, sl.size):
            break
    else:
        list_id = uuid7()
        sl = StatusList(
            id=list_id,
            institution_id=issuer.institution_id,
            issuer_id=issuer.id,
            purpose="revocation",
            url_path=f"/status/{issuer.slug}/{list_id}",
            size=LIST_SIZE,
        )
        db.add(sl)
        db.flush()
        used = set()
    while True:
        index = secrets.randbelow(sl.size)
        if index not in used:
            break
    db.add(StatusListBit(institution_id=issuer.institution_id, status_list_id=sl.id, index=index))
    db.flush()
    return sl, index


def revoked_indexes(db: Session, status_list_id: uuid.UUID) -> list[int]:
    rows = db.scalars(
        select(Credential.status_list_index)
        .join(CredentialStatus, CredentialStatus.credential_id == Credential.id)
        .where(Credential.status_list_id == status_list_id, CredentialStatus.state == "revoked")
    )
    return [i for i in rows if i is not None]


def build_list_credential(
    *, url: str, issuer_did: str, encoded: str, now: datetime
) -> dict[str, Any]:
    return {
        "@context": [VC_V2_CONTEXT],
        "id": url,
        "type": ["VerifiableCredential", "BitstringStatusListCredential"],
        "issuer": issuer_did,
        "validFrom": iso(now),
        "validUntil": iso(now + LIST_VALIDITY),
        "credentialSubject": {
            "id": f"{url}#list",
            "type": "BitstringStatusList",
            "statusPurpose": "revocation",
            "encodedList": encoded,
            "ttl": TTL_MS,
        },
    }


def publish(
    db: Session,
    status_list_id: uuid.UUID,
    signer: SignerClient,
    settings: Settings,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Re-sign and store the list. Call inside the tenant's transaction."""
    now = now or datetime.now(UTC)
    sl = db.get(StatusList, status_list_id, with_for_update=True)
    if sl is None:
        raise StatusError("no such status list")
    issuer = db.get(Issuer, sl.issuer_id)
    institution = db.get(Institution, sl.institution_id)
    assert issuer is not None and institution is not None
    key = active_key(db, issuer.id)
    if key is None:
        raise StatusError(f"issuer {issuer.slug} has no active key to sign its status list")
    url = list_url(institution, settings, sl)
    doc = build_list_credential(
        url=url,
        issuer_did=issuer.did,
        encoded=bitstring.encode(revoked_indexes(db, sl.id), sl.size),
        now=now,
    )
    signed = signer.sign(
        issuer_key_id=key.id,
        verification_method_id=key.verification_method_id,
        document=doc,
        created=now,
    )
    sl.published_credential = signed
    sl.published_at = now
    sl.published_valid_until = now + LIST_VALIDITY
    sl.published_key_id = key.id
    sl.next_publish_due = now + REPUBLISH_EVERY
    db.flush()
    return signed


@dataclass
class Revocation:
    credential_id: uuid.UUID
    status_list_id: uuid.UUID | None
    changed: bool


def revoke(
    db: Session,
    credential_id: uuid.UUID,
    *,
    reason_code: str,
    reason_text: str | None = None,
    actor_user_id: uuid.UUID | None,
    request_id: str | None = None,
    now: datetime | None = None,
) -> Revocation:
    """Record a revocation. Authorisation is the caller's job; a reason is mandatory.

    Idempotent: revoking a revoked credential changes nothing. The caller republishes the list
    (``publish``) or enqueues ``publish_status_list``.
    """
    if reason_code not in REASON_CODES:
        raise StatusError(f"reason_code must be one of {', '.join(REASON_CODES)}")
    now = now or datetime.now(UTC)
    cred = db.get(Credential, credential_id)
    if cred is None or cred.status != "issued":
        raise StatusError("only an issued credential can be revoked")
    status = db.scalar(
        select(CredentialStatus).where(CredentialStatus.credential_id == cred.id).with_for_update()
    )
    if status is None:
        status = CredentialStatus(
            institution_id=cred.institution_id, credential_id=cred.id, state="active"
        )
        db.add(status)
    if status.state == "revoked":
        return Revocation(cred.id, cred.status_list_id, changed=False)
    previous = status.state
    status.state = "revoked"
    status.reason_code = reason_code
    status.reason_text = reason_text
    status.changed_by = actor_user_id
    status.changed_at = now
    db.add(
        CredentialStatusEvent(
            institution_id=cred.institution_id,
            credential_id=cred.id,
            from_state=previous,
            to_state="revoked",
            reason=reason_code,
            actor_id=actor_user_id,
            at=now,
        )
    )
    audit.record(
        db,
        action="credential.revoke",
        resource_type="credential",
        resource_id=cred.id,
        institution_id=cred.institution_id,
        actor_user_id=actor_user_id,
        actor_kind="user" if actor_user_id else "system",
        request_id=request_id,
        data={"reason_code": reason_code},
    )
    db.flush()
    return Revocation(cred.id, cred.status_list_id, changed=True)


def lists_due(db: Session, now: datetime | None = None) -> list[uuid.UUID]:
    now = now or datetime.now(UTC)
    return list(
        db.scalars(
            select(StatusList.id).where(
                (StatusList.published_at.is_(None)) | (StatusList.next_publish_due <= now)
            )
        )
    )


def allocated_count(db: Session, status_list_id: uuid.UUID) -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(StatusListBit)
            .where(StatusListBit.status_list_id == status_list_id)
        )
        or 0
    )
