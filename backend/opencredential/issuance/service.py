# SPDX-License-Identifier: AGPL-3.0-or-later
"""Idempotent, crash-safe issuance pipeline (ADR-0012, spec §6.6, §17, scenario 12).

Three steps, each safe to repeat:

1. **Prepare** (one transaction, decision row locked): create — or find — the single
   ``pending_signature`` credential row for the decision. Its id, ``validFrom``, recipient salt
   and hash, and status-list index are fixed here, so every later attempt signs the same content.
2. **Sign** (no transaction held): the signer adds the proof. A network failure here leaves the
   pending row for the next attempt.
3. **Commit** (one transaction, credential row locked): store ``signed_json`` and mark it issued
   with its status and audit event. If another attempt already committed, do nothing.

So: a retry after any failure reuses the same row; ``credentials.award_decision_id`` is unique
and a partial unique index allows only one live credential per learner and version; issued rows
are immutable (trigger). Duplicates and half-written records cannot arise.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from opencredential import audit
from opencredential.db.models import (
    AchievementVersion,
    AwardDecision,
    BadgeAsset,
    Credential,
    CredentialEvidence,
    CredentialStatus,
    Institution,
    Issuer,
    IssuerKey,
    StatusList,
    StatusListBit,
    User,
)
from opencredential.db.session import tenant_session
from opencredential.ids import uuid7
from opencredential.institutions.identity import base_url
from opencredential.institutions.keys import active_key
from opencredential.issuance import ob3
from opencredential.issuance.schema import validate_achievement_credential
from opencredential.logging import get_logger
from opencredential.settings import Settings
from opencredential.signer_client import SignerClient, SignerRejected
from opencredential.status import service as status_service

log = get_logger("issuance")

DEFAULT_BADGE_IMAGE = "/assets/default-badge.svg"


class IssuanceError(RuntimeError):
    """Permanent problem: retrying will not help until someone fixes the data."""


@dataclass(frozen=True)
class IssueResult:
    credential_id: uuid.UUID
    outcome: str  # issued | already_issued | duplicate
    status_list_id: uuid.UUID | None = None


#: Test hook for fault injection: called with a step name before each side effect.
FaultHook = Callable[[str], None]


def _noop(_: str) -> None:
    return None


def content_hash(doc: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def _versions_url(base: str, version: AchievementVersion) -> str:
    return f"{base}/achievements/{version.id}"


def _alignments(version: AchievementVersion) -> tuple[dict[str, str], ...]:
    out = []
    for skill in version.skills or []:
        name = skill.get("targetName") or skill.get("name")
        url = skill.get("targetUrl") or skill.get("url")
        if name and url:
            out.append(
                {
                    "targetName": str(name),
                    "targetUrl": str(url),
                    **{
                        k: str(skill[k])
                        for k in ("targetDescription", "targetFramework", "targetCode")
                        if skill.get(k)
                    },
                }
            )
    return tuple(out)


def unsigned_credential(db: Session, cred: Credential, settings: Settings) -> dict[str, Any]:
    """Rebuild the unsigned credential from the stored row. Deterministic for a given row."""
    institution = db.get(Institution, cred.institution_id)
    issuer = db.get(Issuer, cred.issuer_id)
    version = db.get(AchievementVersion, cred.version_id)
    sl = db.get(StatusList, cred.status_list_id) if cred.status_list_id else None
    assert institution and issuer and version and sl and cred.status_list_index is not None
    base = base_url(institution, settings)
    achievement_url = _versions_url(base, version)

    image_url, caption = base + DEFAULT_BADGE_IMAGE, f"Badge image for {version.title}"
    if version.asset_id:
        asset = db.get(BadgeAsset, version.asset_id)
        if asset is not None:
            ext = "svg" if asset.media_type == "image/svg+xml" else "png"
            image_url, caption = f"{base}/assets/public/{asset.sha256}.{ext}", asset.alt_text

    recipient_name = None
    if (institution.policy or {}).get("include_recipient_name_in_credential"):
        user = db.get(User, cred.user_id)
        recipient_name = user.display_name if user else None

    evidence = tuple(
        ob3.EvidenceItem(narrative=e.narrative, url=e.url, genre=e.kind.replace("_", " "))
        for e in db.scalars(
            select(CredentialEvidence)
            .where(
                CredentialEvidence.credential_id == cred.id,
                CredentialEvidence.include_in_credential.is_(True),
            )
            .order_by(CredentialEvidence.created_at)
        )
    )
    return ob3.build_credential(
        ob3.CredentialInputs(
            credential_id=cred.credential_uri,
            issuer=ob3.IssuerProfile(
                id=issuer.did,
                name=issuer.name,
                url=issuer.url or institution.website_url,
                email=issuer.email,
                description=issuer.description,
            ),
            achievement=ob3.AchievementInfo(
                id=achievement_url,
                name=version.title,
                description=version.description,
                criteria_narrative=version.criteria_narrative,
                criteria_id=f"{achievement_url}#criteria",
                achievement_type=version.achievement_type,
                image_url=image_url,
                image_caption=caption,
                tags=(version.category,) if version.category else (),
                alignments=_alignments(version),
            ),
            valid_from=cred.valid_from,
            valid_until=cred.valid_until,
            recipient_hash=cred.recipient_hash,
            recipient_salt=cred.recipient_salt,
            recipient_name=recipient_name,
            status=ob3.StatusEntry(
                list_url=status_service.list_url(institution, settings, sl),
                index=cred.status_list_index,
            ),
            evidence=evidence,
        )
    )


def _prepare(
    db: Session, decision_id: uuid.UUID, settings: Settings, now: datetime
) -> tuple[Credential | None, IssueResult | None]:
    decision = db.get(AwardDecision, decision_id, with_for_update=True)
    if decision is None:
        raise IssuanceError("no such award decision")
    existing = db.scalar(select(Credential).where(Credential.award_decision_id == decision.id))
    if existing is not None and existing.status == "issued":
        return None, IssueResult(existing.id, "already_issued", existing.status_list_id)
    if existing is not None and existing.status == "pending_signature":
        return existing, None
    if decision.status != "ready":
        raise IssuanceError(f"decision is {decision.status}, not ready for issuance")

    live = db.scalar(
        select(Credential).where(
            Credential.version_id == decision.version_id,
            Credential.user_id == decision.user_id,
            Credential.status != "failed",
            Credential.superseded_by_id.is_(None),
        )
    )
    cred_id = uuid7()
    if live is not None and decision.issuance_seq > 1:
        # Explicit reissue (decisions.reissue checked that the original is revoked): the old
        # credential stays immutable except for the supersession pointer.
        live.superseded_by_id = cred_id
        db.flush()
        live = None
    if live is not None:
        # Another decision (say a manual award) already produced this learner's credential.
        decision.status = "rejected"
        audit.record(
            db,
            action="award.duplicate",
            resource_type="award_decision",
            resource_id=decision.id,
            institution_id=decision.institution_id,
            actor_kind="system",
            data={"existing_credential_id": str(live.id)},
        )
        return None, IssueResult(live.id, "duplicate", live.status_list_id)

    issuer = db.get(Issuer, decision.issuer_id)
    version = db.get(AchievementVersion, decision.version_id)
    user = db.get(User, decision.user_id)
    institution = db.get(Institution, decision.institution_id)
    assert issuer and version and user and institution
    if issuer.status != "active" or issuer.approved_by is None:
        raise IssuanceError("the issuer identity has not been approved by the institution")
    if not version.frozen:
        raise IssuanceError("the achievement version is not published")
    if not user.email:
        raise IssuanceError("the learner has no email address to identify them in the credential")
    base_url(institution, settings)  # raises for unusable verification hosts in production

    sl, index = status_service.allocate(db, issuer)
    salt = ob3.new_salt()
    cred = Credential(
        id=cred_id,
        institution_id=decision.institution_id,
        award_decision_id=decision.id,
        issuer_id=issuer.id,
        version_id=version.id,
        user_id=user.id,
        credential_uri=f"urn:uuid:{cred_id}",
        status="pending_signature",
        valid_from=now.replace(microsecond=0),
        valid_until=(
            now.replace(microsecond=0) + timedelta(days=version.validity_days)
            if version.validity_days
            else None
        ),
        recipient_salt=salt,
        recipient_hash=ob3.email_identity_hash(user.email, salt),
        status_list_id=sl.id,
        status_list_index=index,
    )
    db.add(cred)
    db.flush()
    # Evidence chosen at decision time (W5: manual awards, spec §11.4). Only items marked
    # public go into the signed credential; the rest stay as private records.
    for item in getattr(decision, "evidence", None) or []:
        public = bool(item.get("public"))
        db.add(
            CredentialEvidence(
                institution_id=decision.institution_id,
                credential_id=cred.id,
                kind=item["kind"],
                narrative=item["narrative"],
                url=item.get("url"),
                include_in_credential=public,
                public=public,
            )
        )
    db.flush()
    bit = db.scalar(
        select(StatusListBit).where(
            StatusListBit.status_list_id == sl.id, StatusListBit.index == index
        )
    )
    assert bit is not None
    bit.credential_id = cred.id
    db.flush()
    return cred, None


def issue(
    institution_id: uuid.UUID,
    decision_id: uuid.UUID,
    *,
    signer: SignerClient,
    settings: Settings,
    now: datetime | None = None,
    fault: FaultHook = _noop,
) -> IssueResult:
    """Issue the credential for ``decision_id``. Safe to call any number of times."""
    now = now or datetime.now(UTC)

    # 1. prepare
    with tenant_session(institution_id) as db:
        cred, done = _prepare(db, decision_id, settings, now)
        if done is not None:
            return done
        assert cred is not None
        cred.attempts += 1
        unsigned = unsigned_credential(db, cred, settings)
        key: IssuerKey | None = active_key(db, cred.issuer_id)
        if key is None:
            raise IssuanceError("the issuer has no active signing key")
        cred_id, key_id, vm_id = cred.id, key.id, key.verification_method_id
    fault("after_prepare")

    problems = validate_achievement_credential(unsigned)
    if problems:
        _record_failure(institution_id, cred_id, "schema: " + "; ".join(problems[:5]))
        raise IssuanceError("credential failed Open Badges 3.0 schema validation: " + problems[0])

    # 2. sign (no transaction open)
    try:
        signed = signer.sign(
            issuer_key_id=key_id, verification_method_id=vm_id, document=unsigned, created=now
        )
    except SignerRejected as exc:
        _record_failure(institution_id, cred_id, f"{exc.code}: {exc}")
        raise IssuanceError(f"the signer refused this credential ({exc.code})") from exc
    except Exception as exc:
        _record_failure(institution_id, cred_id, type(exc).__name__)
        raise
    fault("after_sign")

    # 3. commit
    with tenant_session(institution_id) as db:
        cred = db.get(Credential, cred_id, with_for_update=True)
        assert cred is not None
        if cred.status == "issued":
            return IssueResult(cred.id, "already_issued", cred.status_list_id)
        cred.signed_json = signed
        cred.content_hash = content_hash(signed)
        cred.issuer_key_id = key_id
        cred.issued_at = now
        cred.status = "issued"
        cred.last_error = None
        db.add(
            CredentialStatus(
                institution_id=cred.institution_id, credential_id=cred.id, state="active"
            )
        )
        decision = db.get(AwardDecision, decision_id)
        assert decision is not None
        decision.status = "issued"
        audit.record(
            db,
            action="credential.issue",
            resource_type="credential",
            resource_id=cred.id,
            institution_id=cred.institution_id,
            actor_kind="system",
            data={
                "award_decision_id": str(decision_id),
                "issuer_key_id": str(key_id),
                "attempts": cred.attempts,
            },
        )
        fault("before_commit")
        result = IssueResult(cred.id, "issued", cred.status_list_id)
    log.info("credential_issued", credential_id=str(cred_id), outcome=result.outcome)
    return result


def _record_failure(institution_id: uuid.UUID, cred_id: uuid.UUID, error: str) -> None:
    try:
        with tenant_session(institution_id) as db:
            cred = db.get(Credential, cred_id, with_for_update=True)
            if cred is not None and cred.status == "pending_signature":
                cred.last_error = error[:500]
    except Exception:
        log.warning("record_failure_failed", credential_id=str(cred_id))


def pending(db: Session, older_than: timedelta = timedelta(minutes=10)) -> list[AwardDecision]:
    """Decisions whose credential is stuck in ``pending_signature`` (reconciliation, §17.2)."""
    cutoff = datetime.now(UTC) - older_than
    return list(
        db.scalars(
            select(AwardDecision)
            .join(Credential, Credential.award_decision_id == AwardDecision.id)
            .where(Credential.status == "pending_signature", Credential.updated_at < cutoff)
        )
    )
