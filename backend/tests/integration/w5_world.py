# SPDX-License-Identifier: AGPL-3.0-or-later
"""A small synthetic tenant for W5 tests: one course, staff, students, an issuer and a fake LMS."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select, text

from opencredential.authz import sessions
from opencredential.db import models as m
from opencredential.db.session import owner_session, tenant_session
from opencredential.integrations.fake import FakeLmsAdapter
from opencredential.jobs import tasks
from opencredential.settings import get_settings

COURSE_REF = "course-101"
CHECKLIST = {
    k: True
    for k in (
        "clarity",
        "level",
        "evidence",
        "alignment",
        "accessibility",
        "consistency",
        "terminology",
    )
}


@dataclass
class World:
    iid: uuid.UUID
    course_id: uuid.UUID
    issuer_id: uuid.UUID
    users: dict[str, uuid.UUID]
    lms: FakeLmsAdapter
    client: TestClient
    tokens: dict[str, str] = field(default_factory=dict)

    def h(self, who: str) -> dict[str, str]:
        if who not in self.tokens:
            token, _ = sessions.issue(
                get_settings(), user_id=self.users[who], institution_id=self.iid, method="dev"
            )
            self.tokens[who] = token
        return {"authorization": f"Bearer {self.tokens[who]}"}

    def get(self, who: str, path: str, **kw: Any) -> Any:
        return self.client.get(path, headers=self.h(who), **kw)

    def post(self, who: str, path: str, json: Any = None, **kw: Any) -> Any:
        return self.client.post(path, headers=self.h(who), json=json, **kw)

    def patch(self, who: str, path: str, json: Any = None) -> Any:
        return self.client.patch(path, headers=self.h(who), json=json)

    def put(self, who: str, path: str, json: Any = None) -> Any:
        return self.client.put(path, headers=self.h(who), json=json)

    # -- background work, run inline (what the worker would do) ---------------------------
    def sync(self, kind: str = "scheduled") -> dict[str, Any]:
        return tasks.sync_course_task(str(self.iid), str(self.course_id), kind=kind)

    def evaluate(self) -> dict[str, int]:
        return tasks.evaluate_course_task(str(self.iid), str(self.course_id))

    def sync_and_evaluate(self) -> dict[str, int]:
        self.sync()
        return self.evaluate()

    def jobs(self, task: str) -> list[dict[str, Any]]:
        with owner_session() as db:
            rows = db.execute(
                text(
                    "SELECT id, status, args FROM jobs.procrastinate_jobs WHERE task_name = :t"
                    " AND args->>'institution_id' = :iid ORDER BY id"
                ),
                {"t": task, "iid": str(self.iid)},
            ).mappings()
            return [dict(r) for r in rows]

    def db(self) -> Any:
        return tenant_session(self.iid)

    def decisions(self) -> list[m.AwardDecision]:
        with self.db() as db:
            return list(db.scalars(select(m.AwardDecision).order_by(m.AwardDecision.decided_at)))

    def evaluations(self, user: str) -> list[m.EligibilityEvaluation]:
        with self.db() as db:
            return list(
                db.scalars(
                    select(m.EligibilityEvaluation)
                    .where(m.EligibilityEvaluation.user_id == self.users[user])
                    .order_by(m.EligibilityEvaluation.evaluated_at)
                )
            )

    # -- authoring shortcuts --------------------------------------------------------------
    def artwork(self, who: str = "lecturer") -> str:
        r = self.post(
            who,
            "/api/v1/assets/from-template",
            {
                "template": "shield",
                "primary_colour": "#1f4e79",
                "secondary_colour": "#f2c14e",
                "label": "Writing",
                "alt_text": "Blue shield with a tick and the word Writing",
            },
        )
        assert r.status_code == 201, r.text
        return str(r.json()["id"])

    def draft(self, rules: dict[str, Any], **fields: Any) -> dict[str, Any]:
        body = {
            "issuer_id": str(self.issuer_id),
            "course_id": str(self.course_id),
            "fields": {
                "title": "Academic Writing Foundations",
                "short_description": "Plans and writes a short academic text.",
                "learning_outcomes": ["Structure an academic argument"],
                "criteria_narrative": "Complete the writing module.",
                "category": "Completion",
                "demonstration_kind": "completing",
                "asset_id": self.artwork(),
                **fields,
            },
            "rules": rules,
        }
        r = self.post("lecturer", "/api/v1/achievements", body)
        assert r.status_code == 201, r.text
        return r.json()

    def publish(self, rules: dict[str, Any], **fields: Any) -> dict[str, Any]:
        d = self.draft(rules, **fields)
        did = d["id"]
        r = self.post("lecturer", f"/api/v1/achievements/{did}/submit")
        assert r.status_code == 200, r.text
        r = self.post("reviewer", f"/api/v1/achievements/{did}/approve", {"checklist": CHECKLIST})
        assert r.status_code == 200, r.text
        r = self.post("lecturer", f"/api/v1/achievements/{did}/publish")
        assert r.status_code == 200, r.text
        return r.json()


def build_world(client: TestClient, *, policy: dict[str, Any] | None = None) -> World:
    suffix = uuid.uuid4().hex[:8]
    users: dict[str, uuid.UUID] = {}
    with owner_session() as db:
        inst = m.Institution(
            slug=f"w5-{suffix}",
            name="W5 Test University",
            is_demo=True,
            policy={
                "definitions_require_approval": True,
                "self_approval_allowed": False,
                "approver_roles": ["dept_admin", "inst_admin"],
                "score_rules_default_policy": "lecturer_confirmed",
                "score_rules_force_confirmation": False,
                "manual_awards_require_second_approval": False,
                "max_snapshot_age_minutes": 120,
                **(policy or {}),
            },
            categories=["Academic Skills"],
        )
        db.add(inst)
        db.flush()
        iid = inst.id
        canvas = m.CanvasIntegration(
            institution_id=iid,
            name="Fake Canvas",
            base_url="https://canvas.example",
            lti_issuer=f"https://canvas.example/{suffix}",
            lti_client_id=f"client-{suffix}",
            status="active",
        )
        org = m.OrgUnit(institution_id=iid, name="Library", kind="department")
        db.add_all([canvas, org])
        db.flush()
        course = m.Course(
            institution_id=iid,
            canvas_integration_id=canvas.id,
            canvas_course_id=COURSE_REF,
            title="Study Skills 101",
            org_unit_id=org.id,
            status="active",
        )
        db.add(course)
        db.flush()
        for key in ("lecturer", "reviewer", "admin", "outsider", "s1", "s2", "s3"):
            u = m.User(institution_id=iid, display_name=key.title(), family_name=key)
            db.add(u)
            db.flush()
            users[key] = u.id
        grants = [
            ("lecturer", "course", course.id, "lecturer"),
            ("reviewer", "org_unit", org.id, "dept_admin"),
            ("admin", "institution", iid, "inst_admin"),
        ]
        for s in ("s1", "s2", "s3"):
            grants.append((s, "course", course.id, "student"))
            db.add(
                m.ExternalIdentity(
                    institution_id=iid,
                    user_id=users[s],
                    canvas_integration_id=canvas.id,
                    kind="canvas_user_id",
                    value=f"lms-{s}",
                )
            )
        for who, st, sid, role in grants:
            db.add(
                m.Membership(
                    institution_id=iid,
                    user_id=users[who],
                    scope_type=st,
                    scope_id=sid,
                    role=role,
                    source="dev_seed",
                )
            )
        issuer = m.Issuer(
            institution_id=iid,
            org_unit_id=org.id,
            slug="skills",
            name="Skills Centre (TEST)",
            did=f"did:key:z6Mktest{suffix}",
            status="active",
        )
        db.add(issuer)
        db.flush()
        db.add(
            m.IssuerDelegation(
                institution_id=iid, issuer_id=issuer.id, scope_type="course", scope_id=course.id
            )
        )
        course_id, issuer_id = course.id, issuer.id

    lms = FakeLmsAdapter()
    lms.add_module(COURSE_REF, "m1", "Writing Foundations")
    lms.add_module(COURSE_REF, "m2", "Referencing")
    lms.add_module(COURSE_REF, "m-noreq", "Welcome", has_requirements=False)
    lms.add_assignment(COURSE_REF, "a1", "Short essay", points_possible=20.0)
    return World(iid, course_id, issuer_id, users, lms, client)
