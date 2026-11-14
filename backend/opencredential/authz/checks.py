# SPDX-License-Identifier: AGPL-3.0-or-later
"""Role checks for W4's privileged actions, now backed by the W7 policy (ADR-0013).

* Revocation: roles listed in the institution policy ``revokers``, each within its own scope
  (:func:`opencredential.authz.policy.can_revoke`). Institution administrators always can.
* Key management: ``inst_admin`` at institution scope only.
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from opencredential.api.errors import ApiError
from opencredential.authz import policy
from opencredential.db.models import (
    AchievementDefinition,
    AchievementVersion,
    Course,
    Credential,
    Issuer,
)


def credential_definition(db: Session, cred: Credential) -> AchievementDefinition | None:
    version = db.get(AchievementVersion, cred.version_id)
    return db.get(AchievementDefinition, version.definition_id) if version else None


def credential_course(db: Session, cred: Credential) -> Course | None:
    definition = credential_definition(db, cred)
    if definition is None or definition.course_id is None:
        return None
    return db.get(Course, definition.course_id)


def may_revoke(db: Session, user_id: uuid.UUID, cred: Credential) -> bool:
    issuer = db.get(Issuer, cred.issuer_id)
    if issuer is None:
        return False
    actor = policy.load_actor(db, user_id, cred.institution_id)
    rules = policy.institution_policy(db, cred.institution_id)
    return policy.can_revoke(
        db, actor, issuer, credential_course(db, cred), rules, credential_definition(db, cred)
    )


def require_revoker(db: Session, user_id: uuid.UUID, cred: Credential) -> None:
    if not may_revoke(db, user_id, cred):
        raise ApiError(403, "FORBIDDEN", "You are not allowed to revoke this badge")


def require_key_manager(db: Session, user_id: uuid.UUID) -> None:
    actor = policy.load_actor(db, user_id, uuid.UUID(int=0))
    if not actor.is_inst_admin:
        raise ApiError(403, "FORBIDDEN", "Only institutional administrators can manage keys")
