# SPDX-License-Identifier: AGPL-3.0-or-later
"""Development seed: demo institution, dev issuer + key, Academic Skills Passport, learners.

Runs as the owner role. Refuses to run in production. Idempotent: if the demo institution
exists it does nothing. ``reset=True`` rebuilds the whole database first (dev only).

What it does *not* do: issue credentials. Issuance is real signing (W4); the seed only
provides the inputs (published badges, LMS snapshots, eligibility results) for it.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from opencredential import audit
from opencredential.db import models as m
from opencredential.db.session import owner_session
from opencredential.paths import EXAMPLES_DIR
from opencredential.seed.expected import evaluate_demo
from opencredential.settings import Settings, get_settings
from opencredential.signer_client import SignerClient

PASSPORT = EXAMPLES_DIR / "academic-skills-passport" / "passport.json"


class SeedRefused(RuntimeError):
    pass


@dataclass
class SeedResult:
    institution_id: uuid.UUID
    created: bool
    counts: dict[str, int] = field(default_factory=dict)


def load_passport(path: Path = PASSPORT) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def run(
    *,
    reset: bool = False,
    settings: Settings | None = None,
    signer: SignerClient | None = None,
    path: Path = PASSPORT,
) -> SeedResult:
    settings = settings or get_settings()
    if settings.is_production:
        raise SeedRefused("The development seed never runs with OC_ENV=production.")
    data = load_passport(path)
    slug = data["institution"]["slug"]

    if reset:
        from opencredential.db.migrate import reset_database

        reset_database()
    with owner_session() as db:
        existing = db.scalar(select(m.Institution).where(m.Institution.slug == slug))
        if existing:
            return SeedResult(institution_id=existing.id, created=False)

    own_signer = signer is None
    signer = signer or SignerClient(settings)
    try:
        key_id = uuid.uuid4()
        key = signer.create_key(key_id, dev=True)
    finally:
        if own_signer:
            signer.close()

    with owner_session() as db:
        result = _build(db, data, key)
    return result


def _build(db: Session, data: dict[str, Any], key: Any) -> SeedResult:
    now = datetime.now(UTC)
    inst_d = data["institution"]
    inst = m.Institution(
        slug=inst_d["slug"],
        name=inst_d["name"],
        description=inst_d["description"],
        website_url=inst_d["website_url"],
        categories=inst_d["categories"],
        is_demo=True,
        branding={"primary_colour": "#1f4e79"},
    )
    db.add(inst)
    db.flush()
    iid = inst.id

    canvas = m.CanvasIntegration(
        institution_id=iid,
        status="pending",
        **{k: v for k, v in data["canvas"].items() if not k.startswith("$")},
    )
    org = m.OrgUnit(institution_id=iid, **data["org_unit"])
    db.add_all([canvas, org])
    db.flush()

    course = m.Course(
        institution_id=iid,
        canvas_integration_id=canvas.id,
        org_unit_id=org.id,
        status="active",
        activated_at=now,
        **data["course"],
    )
    db.add(course)
    db.flush()

    people: dict[str, m.User] = {}
    for person in [*data["staff"], *data["students"]]:
        u = m.User(
            institution_id=iid,
            given_name=person["given_name"],
            family_name=person["family_name"],
            display_name=f"{person['given_name']} {person['family_name']}",
            email=f"{person['key']}@demo-university.example",
            email_verified_by="dev_seed",
        )
        db.add(u)
        people[person["key"]] = u
    db.flush()

    for person in data["staff"]:
        role = person["role"]
        scope = {"inst_admin": ("institution", iid), "dept_admin": ("org_unit", org.id)}.get(
            role, ("course", course.id)
        )
        db.add(
            m.Membership(
                institution_id=iid,
                user_id=people[person["key"]].id,
                scope_type=scope[0],
                scope_id=scope[1],
                role=role,
                source="dev_seed",
            )
        )
        if role == "inst_admin":  # admins can view the demo course too
            course.activated_by = people[person["key"]].id
    for person in data["students"]:
        # The demo LMS adapter (integrations.fake.passport_adapter) knows learners by seed key.
        db.add(
            m.ExternalIdentity(
                institution_id=iid,
                user_id=people[person["key"]].id,
                canvas_integration_id=canvas.id,
                kind="canvas_user_id",
                value=person["key"],
            )
        )
        db.add(
            m.Membership(
                institution_id=iid,
                user_id=people[person["key"]].id,
                scope_type="course",
                scope_id=course.id,
                role="student",
                source="dev_seed",
            )
        )

    admin = people["admin"]
    issuer = m.Issuer(
        institution_id=iid,
        org_unit_id=org.id,
        did=key.did,
        status="active",
        approved_by=admin.id,
        approved_at=now,
        **data["issuer"],
    )
    db.add(issuer)
    db.flush()
    db.add(
        m.IssuerKey(
            id=key.issuer_key_id,
            institution_id=iid,
            issuer_id=issuer.id,
            verification_method_id=key.verification_method_id,
            public_key_multibase=key.public_key_multibase,
            state="active",
            activated_at=now,
            is_dev=True,
        )
    )
    db.add(
        m.IssuerDelegation(
            institution_id=iid,
            issuer_id=issuer.id,
            scope_type="course",
            scope_id=course.id,
            granted_by=admin.id,
        )
    )

    # LMS snapshot (as if synced from Canvas)
    fetched = now - timedelta(minutes=5)
    canvas_ids = {mod["key"]: str(1000 + i) for i, mod in enumerate(data["modules"])}
    canvas_ids |= {a["key"]: str(5000 + i) for i, a in enumerate(data["assignments"])}
    for mod in data["modules"]:
        db.add(
            m.LmsModule(
                institution_id=iid,
                course_id=course.id,
                canvas_module_id=canvas_ids[mod["key"]],
                name=mod["name"],
                requirement_type=mod["requirement_type"],
                has_requirements=True,
                workflow_state="active",
                fetched_at=fetched,
            )
        )
    points = {a["key"]: a["points_possible"] for a in data["assignments"]}
    for a in data["assignments"]:
        db.add(
            m.LmsAssignment(
                institution_id=iid,
                course_id=course.id,
                canvas_assignment_id=canvas_ids[a["key"]],
                name=a["name"],
                points_possible=a["points_possible"],
                fetched_at=fetched,
            )
        )
    for s in data["students"]:
        uid = people[s["key"]].id
        for mod in data["modules"]:
            done = mod["key"] in s["completed"]
            db.add(
                m.LmsModuleProgress(
                    institution_id=iid,
                    course_id=course.id,
                    user_id=uid,
                    canvas_module_id=canvas_ids[mod["key"]],
                    state="completed" if done else "started",
                    completed_at=fetched - timedelta(days=3) if done else None,
                    fetched_at=fetched,
                )
            )
        for akey, sub in s["submissions"].items():
            excused = sub.get("excused", False)
            posted = sub.get("posted", True) and not excused
            graded = sub.get("score") is not None or excused
            db.add(
                m.LmsSubmission(
                    institution_id=iid,
                    course_id=course.id,
                    user_id=uid,
                    canvas_assignment_id=canvas_ids[akey],
                    workflow_state="graded" if graded else "submitted",
                    submitted_at=None if excused else fetched - timedelta(days=4),
                    score=sub.get("score"),
                    excused=excused,
                    posted_at=fetched - timedelta(days=1) if posted and graded else None,
                    fetched_at=fetched,
                )
            )
    db.add(
        m.SyncRun(
            institution_id=iid,
            course_id=course.id,
            kind="dev_seed",
            started_at=fetched,
            finished_at=fetched,
            status="ok",
        )
    )

    # Badges: definitions + published, frozen versions + rule sets
    versions: dict[str, tuple[m.AchievementVersion, dict[str, Any]]] = {}
    for b in data["badges"]:
        definition = m.AchievementDefinition(
            institution_id=iid,
            issuer_id=issuer.id,
            course_id=course.id,
            owner_user_id=people["lecturer"].id,
            state="published",
            award_policy=b["award_policy"],
        )
        db.add(definition)
        db.flush()
        content = {k: b[k] for k in sorted(b) if k not in ("key", "award_policy", "rules")}
        version = m.AchievementVersion(
            institution_id=iid,
            definition_id=definition.id,
            version_no=1,
            title=b["title"],
            short_description=b["short_description"],
            description=b["short_description"],
            learning_outcomes=b["learning_outcomes"],
            criteria_narrative=b["criteria_narrative"],
            category=b["category"],
            achievement_type=b["achievement_type"],
            demonstration_kind=b["demonstration_kind"],
            content_hash=hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest(),
            published_at=now,
            published_by=people["reviewer"].id,
        )
        db.add(version)
        db.flush()
        definition.current_version_id = version.id
        rule_set = m.AwardRuleSet(
            institution_id=iid, version_id=version.id, mode=b["rules"]["mode"]
        )
        db.add(rule_set)
        db.flush()
        for pos, rule in enumerate(b["rules"]["rules"]):
            db.add(
                m.AwardRule(
                    institution_id=iid,
                    rule_set_id=rule_set.id,
                    position=pos,
                    type=rule["type"],
                    params=_canvas_params(rule, canvas_ids),
                )
            )
        db.add(
            m.DefinitionReview(
                institution_id=iid,
                definition_id=definition.id,
                version_id=version.id,
                reviewer_id=people["reviewer"].id,
                decision="approve",
                checklist={
                    k: True
                    for k in (
                        "clarity",
                        "level",
                        "evidence",
                        "alignment",
                        "accessibility",
                        "terminology",
                    )
                },
                comment="Approved for demonstration.",
            )
        )
        versions[b["key"]] = (version, b)
    db.flush()
    # Freeze only after rule sets exist (frozen rows are immutable).
    for version, _ in versions.values():
        version.frozen = True

    # Eligibility results for the synthetic learners
    evaluations = 0
    for s in data["students"]:
        for version, badge in versions.values():
            outcome, detail = evaluate_demo(badge["rules"], s, points)
            db.add(
                m.EligibilityEvaluation(
                    institution_id=iid,
                    version_id=version.id,
                    user_id=people[s["key"]].id,
                    outcome=outcome,
                    detail=detail,
                    inputs_hash=hashlib.sha256(
                        json.dumps([badge["rules"], s], sort_keys=True).encode()
                    ).hexdigest(),
                    triggered_by="dev_seed",
                    evaluated_at=fetched,
                )
            )
            evaluations += 1

    audit.record(
        db,
        action="institution.dev_seed",
        resource_type="institution",
        resource_id=iid,
        institution_id=iid,
        actor_kind="system",
        data={"badges": len(versions), "students": len(data["students"])},
    )
    db.flush()
    return SeedResult(
        institution_id=iid,
        created=True,
        counts={
            "badges": len(versions),
            "students": len(data["students"]),
            "staff": len(data["staff"]),
            "evaluations": evaluations,
        },
    )


def _canvas_params(rule: dict[str, Any], canvas_ids: dict[str, str]) -> dict[str, Any]:
    """Translate seed keys (``m-awf``) into the Canvas ids the rules/v1 schema uses."""
    params = {k: v for k, v in rule.items() if k not in ("type", "module", "modules", "assignment")}
    if "module" in rule:
        params["module_id"] = canvas_ids[rule["module"]]
    if "modules" in rule:
        params["module_ids"] = [canvas_ids[k] for k in rule["modules"]]
    if "assignment" in rule:
        params["assignment_id"] = canvas_ids[rule["assignment"]]
    return params
