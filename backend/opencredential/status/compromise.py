# SPDX-License-Identifier: AGPL-3.0-or-later
"""Key-compromise response (spec §15.5, docs/security/key-compromise.md, steps 2-6).

Runs in one transaction: replacement key activated, compromised key revoked and removed from the
DID document, its private material destroyed, every credential it signed revoked with reason
``key_compromise``, and every status list of the issuer re-signed with the replacement key.
Notifying holders and reissuing are separate, deliberate steps (see the runbook).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from opencredential.db.models import IssuerKey, StatusList
from opencredential.institutions import keys as key_service
from opencredential.settings import Settings
from opencredential.signer_client import SignerClient
from opencredential.status import service as status_service


@dataclass
class CompromiseResponse:
    revoked_key_id: uuid.UUID
    replacement_key_id: uuid.UUID | None
    credentials_revoked: int
    status_lists_republished: int
    affected_credential_ids: list[uuid.UUID]


def respond_to_compromise(
    db: Session,
    key: IssuerKey,
    signer: SignerClient,
    settings: Settings,
    *,
    reason: str,
    actor_user_id: uuid.UUID,
) -> CompromiseResponse:
    result = key_service.handle_compromise(
        db, key, signer, reason=reason, actor_user_id=actor_user_id
    )
    lists: set[uuid.UUID] = set()
    for cid in result.affected_credential_ids:
        r = status_service.revoke(
            db,
            cid,
            reason_code="key_compromise",
            reason_text=reason,
            actor_user_id=actor_user_id,
        )
        if r.status_list_id:
            lists.add(r.status_list_id)
    # Every list of this issuer was signed by some key; re-sign them all with the new key.
    lists |= set(db.scalars(select(StatusList.id).where(StatusList.issuer_id == key.issuer_id)))
    republished = 0
    if result.replacement_key_id is not None:
        for list_id in lists:
            status_service.publish(db, list_id, signer, settings)
            republished += 1
    return CompromiseResponse(
        revoked_key_id=result.revoked_key_id,
        replacement_key_id=result.replacement_key_id,
        credentials_revoked=len(result.affected_credential_ids),
        status_lists_republished=republished,
        affected_credential_ids=result.affected_credential_ids,
    )
