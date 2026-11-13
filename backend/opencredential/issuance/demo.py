# SPDX-License-Identifier: AGPL-3.0-or-later
"""Development: turn the seeded eligibility results into real, signed credentials.

Every demo learner whose evaluation is ``met`` for an *automatic* badge gets an award decision
and a credential issued through the normal pipeline (the same code path production uses, with
the real signer). Status lists are published straight away. Running it twice issues nothing new.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import select

from opencredential.db.models import (
    AchievementDefinition,
    AchievementVersion,
    Credential,
    EligibilityEvaluation,
    Institution,
)
from opencredential.db.session import tenant_session
from opencredential.issuance import decisions
from opencredential.issuance.service import issue
from opencredential.settings import Settings, get_settings
from opencredential.signer_client import SignerClient
from opencredential.status.service import publish

DEMO_SLUG = "demo-university"


class DemoRefused(RuntimeError):
    pass


def issue_demo_credentials(
    *,
    out_dir: Path | None = None,
    settings: Settings | None = None,
    signer: SignerClient | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    if settings.is_production:
        raise DemoRefused("issue-demo never runs with OC_ENV=production")
    with tenant_session(None) as db:
        inst = db.scalar(select(Institution).where(Institution.slug == DEMO_SLUG))
        if inst is None or not inst.is_demo:
            raise DemoRefused("seed the demo institution first (oc seed)")
        iid = inst.id

    with tenant_session(iid) as db:
        rows = (
            db.execute(
                select(EligibilityEvaluation)
                .join(AchievementVersion, AchievementVersion.id == EligibilityEvaluation.version_id)
                .join(
                    AchievementDefinition,
                    AchievementDefinition.id == AchievementVersion.definition_id,
                )
                .where(
                    EligibilityEvaluation.outcome == "met",
                    AchievementDefinition.award_policy == "automatic",
                )
                .order_by(EligibilityEvaluation.evaluated_at, EligibilityEvaluation.id)
            )
            .scalars()
            .all()
        )
        decision_ids = []
        for ev in rows:
            d, _ = decisions.decide(
                db,
                institution_id=iid,
                user_id=ev.user_id,
                version_id=ev.version_id,
                kind="automatic",
                evaluation_id=ev.id,
            )
            decision_ids.append(d.id)

    own_signer = signer is None
    signer = signer or SignerClient(settings)
    outcomes: dict[str, int] = {}
    lists = set()
    try:
        for did in decision_ids:
            r = issue(iid, did, signer=signer, settings=settings)
            outcomes[r.outcome] = outcomes.get(r.outcome, 0) + 1
            if r.status_list_id:
                lists.add(r.status_list_id)
        with tenant_session(iid) as db:
            for list_id in lists:
                publish(db, list_id, signer, settings)
    finally:
        if own_signer:
            signer.close()

    written = []
    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
        with tenant_session(iid) as db:
            for cred in db.scalars(select(Credential).where(Credential.status == "issued")):
                path = out_dir / f"{cred.id}.json"
                path.write_text(json.dumps(cred.signed_json, indent=2) + "\n", encoding="utf-8")
                written.append(str(path))
    return {"institution_id": iid, "decisions": len(decision_ids), **outcomes, "files": written}
