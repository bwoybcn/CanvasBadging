# SPDX-License-Identifier: AGPL-3.0-or-later
"""Badges that went live without a colleague's review (migration 0009).

Areas can make review optional or switch it off. If an area later makes review stricter, nothing
is unpublished; instead admins can list the live badges nobody else checked and review them.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from opencredential.authoring import service as authoring
from opencredential.authz import policy as authz
from opencredential.db.models import (
    AchievementDefinition,
    AchievementVersion,
    DefinitionReview,
    OrgUnit,
    User,
)


def published_without_review(db: Session, actor: authz.Actor) -> list[dict[str, Any]]:
    """Live badges in the actor's administrative scope whose live version was not reviewed."""
    authz.require_admin(actor)
    scope = authz.admin_org_units(db, actor)
    # Every approval of each live version, newest first. Only the newest counts: a badge a
    # colleague reviewed after an automatic approval is not "published without review". Live
    # means it has a current version and is not archived, even while a new draft is in progress.
    rows = db.execute(
        select(AchievementDefinition, AchievementVersion, DefinitionReview)
        .join(AchievementVersion, AchievementVersion.id == AchievementDefinition.current_version_id)
        .join(
            DefinitionReview,
            (DefinitionReview.version_id == AchievementVersion.id)
            & (DefinitionReview.decision == "approve"),
        )
        .where(AchievementDefinition.state != "archived")
        .order_by(DefinitionReview.created_at.desc())
    ).all()
    out: list[dict[str, Any]] = []
    seen: set[Any] = set()
    for d, v, review in rows:
        if d.id in seen:
            continue
        seen.add(d.id)
        if not review.without_review:
            continue
        area = authz.definition_area(db, d)
        if scope is not None and (area is None or area not in scope):
            continue
        unit = db.get(OrgUnit, area) if area else None
        author = db.get(User, d.owner_user_id)
        now = authoring.review_requirement(db, d, v)
        out.append(
            {
                "id": str(d.id),
                "title": v.title,
                "version_no": v.version_no,
                "area": unit.name if unit else None,
                "author": author.display_name if author else None,
                "approved_at": review.created_at.isoformat(),
                "reason": review.comment,
                "review_now": now["mode"],
            }
        )
    return out
