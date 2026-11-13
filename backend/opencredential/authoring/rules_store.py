# SPDX-License-Identifier: AGPL-3.0-or-later
"""Persist ``rules/v1`` rule sets as ``award_rule_sets`` + ``award_rules`` rows and load them back.

Rule ids are the ``award_rules.id`` UUIDs, so explanations, manual approvals and Canvas
source-change flags all point at a stable row.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from opencredential.db.models import AwardRule, AwardRuleSet
from opencredential.ids import uuid7
from opencredential.rules.schema import SCHEMA_VERSION, Group, RuleSet, parse


def _params(rule: Any) -> dict[str, Any]:
    return rule.model_dump(mode="json", exclude={"id", "type", "rules"}, exclude_none=True)


def save(db: Session, institution_id: uuid.UUID, version_id: uuid.UUID, rs: RuleSet) -> RuleSet:
    """Replace the rule set of an (unfrozen) version. Returns the rule set with ids assigned."""
    existing = db.scalar(select(AwardRuleSet).where(AwardRuleSet.version_id == version_id))
    if existing is not None:
        db.execute(delete(AwardRule).where(AwardRule.rule_set_id == existing.id))
        db.delete(existing)
        db.flush()
    rule_set = AwardRuleSet(
        institution_id=institution_id,
        version_id=version_id,
        mode=rs.mode,
        schema_version=SCHEMA_VERSION,
    )
    db.add(rule_set)
    db.flush()

    def add(rule: Any, position: int, parent: uuid.UUID | None) -> uuid.UUID:
        params = _params(rule)
        if isinstance(rule, Group):
            params = {"mode": rule.mode}
        row = AwardRule(
            id=uuid7(),
            institution_id=institution_id,
            rule_set_id=rule_set.id,
            parent_rule_id=parent,
            position=position,
            type=rule.type,
            params=params,
        )
        db.add(row)
        db.flush()
        if isinstance(rule, Group):
            for i, child in enumerate(rule.rules):
                add(child, i, row.id)
        return row.id

    for pos, rule in enumerate(rs.rules):
        add(rule, pos, None)
    loaded = load(db, version_id)
    assert loaded is not None
    return loaded


def load(db: Session, version_id: uuid.UUID) -> RuleSet | None:
    rule_set = db.scalar(select(AwardRuleSet).where(AwardRuleSet.version_id == version_id))
    if rule_set is None:
        return None
    rows = db.scalars(
        select(AwardRule).where(AwardRule.rule_set_id == rule_set.id).order_by(AwardRule.position)
    ).all()
    children: dict[uuid.UUID | None, list[AwardRule]] = {}
    for r in rows:
        children.setdefault(r.parent_rule_id, []).append(r)

    def as_json(r: AwardRule) -> dict[str, Any]:
        d: dict[str, Any] = {"id": str(r.id), "type": r.type, **r.params}
        if r.type == "group":
            d["rules"] = [as_json(c) for c in children.get(r.id, [])]
        return d

    return parse({"mode": rule_set.mode, "rules": [as_json(r) for r in children.get(None, [])]})


def source_status(db: Session, version_id: uuid.UUID) -> dict[str, str]:
    rows = db.execute(
        select(AwardRule.id, AwardRule.source_status)
        .join(AwardRuleSet, AwardRuleSet.id == AwardRule.rule_set_id)
        .where(AwardRuleSet.version_id == version_id)
    ).all()
    return {str(i): s for i, s in rows}


def strip_ids(rs: RuleSet) -> dict[str, Any]:
    """The rule set as authoring JSON without ids (for copying into a new version)."""

    def clean(d: dict[str, Any]) -> dict[str, Any]:
        d = {k: v for k, v in d.items() if k != "id" and v is not None}
        if "rules" in d:
            d["rules"] = [clean(c) for c in d["rules"]]
        return d

    return clean(rs.model_dump(mode="json"))
