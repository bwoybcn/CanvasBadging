# SPDX-License-Identifier: AGPL-3.0-or-later
"""Verification checks and outcomes (spec §16.1, §16.2).

Checks: structure (incl. the official JSON Schema), issuer identification, proof verification
method, signature, validity period, revocation status and the integrity of the signed
achievement. Outcomes, in order of precedence:

* **Invalid** — structure or cryptography failed (the credential is not what it claims).
* **Unable to verify** — the signature could not be checked because something was unreachable.
* **Revoked** — the issuer's signed status list says so.
* **Expired** — authentic, but past ``validUntil``.
* **Unable to verify** — authentic and in date, but the status list was unreachable or stale.
* **Verified** — every required check passed.

Infrastructure failure is never reported as fraud. Whether to *trust* the issuer is a separate,
human decision; the result reports whether the issuer is one this service knows, but that does
not change the outcome.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from opencredential.issuance.ob3 import OB_CONTEXTS, VC_V2_CONTEXT
from opencredential.issuance.schema import validate_achievement_credential
from opencredential.signer_client import SignerClient, SignerError
from opencredential.status import bitstring
from opencredential.verification.sources import Sources, Unavailable

CLOCK_SKEW = timedelta(minutes=5)

EXPLANATION = (
    "Verification confirms that this credential was signed by the issuer named in it, has not "
    "been altered since, is within its validity period and has not been revoked by the issuer. "
    "It does not confirm the identity of the person presenting it (ask them to prove control of "
    "the email address it was issued to), and it does not tell you whether to trust the issuing "
    "organisation: that is your decision."
)


class Outcome(StrEnum):
    verified = "verified"
    revoked = "revoked"
    expired = "expired"
    invalid = "invalid"
    unable_to_verify = "unable_to_verify"


LABELS = {
    Outcome.verified: "Verified",
    Outcome.revoked: "Revoked",
    Outcome.expired: "Expired",
    Outcome.invalid: "Invalid",
    Outcome.unable_to_verify: "Unable to verify",
}


class CheckStatus(StrEnum):
    passed = "pass"
    failed = "fail"
    unavailable = "unavailable"
    skipped = "skipped"


@dataclass
class Check:
    name: str
    status: CheckStatus
    detail: str

    @property
    def ok(self) -> bool:
        return self.status == CheckStatus.passed


@dataclass
class VerificationResult:
    result: Outcome
    label: str
    checks: list[Check]
    issuer: dict[str, Any] | None = None
    achievement: dict[str, Any] | None = None
    credential_id: str | None = None
    valid_from: str | None = None
    valid_until: str | None = None
    issuer_trust: dict[str, Any] = field(default_factory=dict)
    explanation: str = EXPLANATION
    checked_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["checks"] = [{**asdict(c), "ok": c.ok} for c in self.checks]
        return d


def _parse_dt(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _types(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    return [v for v in value if isinstance(v, str)] if isinstance(value, list) else []


def _issuer_id(doc: dict[str, Any]) -> str | None:
    issuer = doc.get("issuer")
    if isinstance(issuer, str):
        return issuer
    if isinstance(issuer, dict) and isinstance(issuer.get("id"), str):
        return str(issuer["id"])
    return None


def check_structure(doc: Any) -> Check:
    if not isinstance(doc, dict):
        return Check("structure", CheckStatus.failed, "The credential is not a JSON object.")
    problems: list[str] = []
    ctx = doc.get("@context")
    if not isinstance(ctx, list) or not ctx or ctx[0] != VC_V2_CONTEXT:
        problems.append("the first @context must be the VC Data Model 2.0 context")
    elif not any(c in OB_CONTEXTS for c in ctx if isinstance(c, str)):
        problems.append("the Open Badges 3.0 context is missing")
    types = _types(doc.get("type"))
    if "VerifiableCredential" not in types or not (
        {"OpenBadgeCredential", "AchievementCredential"} & set(types)
    ):
        problems.append("type must include VerifiableCredential and OpenBadgeCredential")
    if not problems:
        problems += validate_achievement_credential(doc)
    if problems:
        return Check("structure", CheckStatus.failed, "; ".join(problems[:5]))
    return Check(
        "structure", CheckStatus.passed, "Valid Open Badges 3.0 credential (official JSON Schema)."
    )


def _status_entries(doc: dict[str, Any]) -> list[dict[str, Any]]:
    cs = doc.get("credentialStatus")
    entries = cs if isinstance(cs, list) else [cs] if isinstance(cs, dict) else []
    return [
        e
        for e in entries
        if isinstance(e, dict)
        and e.get("type") == "BitstringStatusListEntry"
        and e.get("statusPurpose") == "revocation"
    ]


class Verifier:
    def __init__(self, signer: SignerClient, sources: Sources):
        self.signer = signer
        self.sources = sources

    def _resolve(self, did: str, cache: dict[str, dict[str, Any]]) -> None:
        if did.startswith("did:web:") and did not in cache:
            cache[did] = self.sources.did_document(did)

    def verify(self, doc: Any, *, now: datetime | None = None) -> VerificationResult:
        now = now or datetime.now(UTC)
        checks: list[Check] = []
        structure = check_structure(doc)
        checks.append(structure)
        if not structure.ok:
            return self._finish(Outcome.invalid, checks, doc, now)
        assert isinstance(doc, dict)

        # issuer + verification method
        issuer_id = _issuer_id(doc)
        proof = doc.get("proof")
        vm = proof.get("verificationMethod") if isinstance(proof, dict) else None
        if not issuer_id or not issuer_id.startswith(("did:key:", "did:web:")):
            checks.append(
                Check(
                    "issuer",
                    CheckStatus.failed,
                    "The issuer must be identified by a did:key or did:web identifier.",
                )
            )
            return self._finish(Outcome.invalid, checks, doc, now)
        if not isinstance(vm, str) or vm.split("#")[0] != issuer_id or "#" not in vm:
            checks.append(
                Check(
                    "issuer",
                    CheckStatus.failed,
                    "The proof's key does not belong to the issuer named in the credential.",
                )
            )
            return self._finish(Outcome.invalid, checks, doc, now)
        checks.append(Check("issuer", CheckStatus.passed, f"Issuer identified as {issuer_id}."))

        did_docs: dict[str, dict[str, Any]] = {}
        try:
            self._resolve(issuer_id, did_docs)
        except Unavailable as exc:
            checks.append(Check("verification_method", CheckStatus.unavailable, str(exc)))
            checks.append(Check("signature", CheckStatus.skipped, "Issuer keys unavailable."))
            return self._finish(Outcome.unable_to_verify, checks, doc, now)
        checks.append(
            Check(
                "verification_method",
                CheckStatus.passed,
                f"Signing key {vm} resolved from the issuer's DID.",
            )
        )

        # signature (and assertionMethod authorisation)
        try:
            pc = self.signer.verify(doc, did_docs)
        except SignerError as exc:
            checks.append(
                Check("signature", CheckStatus.unavailable, f"Signature service unavailable: {exc}")
            )
            return self._finish(Outcome.unable_to_verify, checks, doc, now)
        if pc.unresolvable:
            msg = "; ".join(e.get("message", "") for e in pc.errors[:3])
            checks.append(Check("signature", CheckStatus.unavailable, msg))
            return self._finish(Outcome.unable_to_verify, checks, doc, now)
        if not pc.verified:
            msg = "; ".join(e.get("message", "") for e in pc.errors[:3]) or "signature mismatch"
            checks.append(Check("signature", CheckStatus.failed, msg))
            checks.append(
                Check(
                    "achievement_integrity",
                    CheckStatus.failed,
                    "The signed content (including the achievement) does not match the proof.",
                )
            )
            return self._finish(Outcome.invalid, checks, doc, now)
        checks.append(
            Check("signature", CheckStatus.passed, "eddsa-rdfc-2022 Data Integrity proof is valid.")
        )
        checks.append(
            Check(
                "achievement_integrity",
                CheckStatus.passed,
                "The achievement, criteria and recipient data are covered by the signature.",
            )
        )

        # validity period
        valid_from, valid_until = _parse_dt(doc.get("validFrom")), _parse_dt(doc.get("validUntil"))
        expired = False
        if valid_from and valid_from > now + CLOCK_SKEW:
            checks.append(
                Check("validity", CheckStatus.failed, f"Not valid until {doc.get('validFrom')}.")
            )
            return self._finish(Outcome.invalid, checks, doc, now)
        if valid_until and valid_until < now - CLOCK_SKEW:
            expired = True
            checks.append(
                Check("validity", CheckStatus.failed, f"Expired {doc.get('validUntil')}.")
            )
        else:
            checks.append(Check("validity", CheckStatus.passed, "Within its validity period."))

        # revocation status
        status_check, revoked = self._check_status(doc, issuer_id, now)
        checks.append(status_check)
        if revoked:
            return self._finish(Outcome.revoked, checks, doc, now)
        if expired:
            return self._finish(Outcome.expired, checks, doc, now)
        if status_check.status == CheckStatus.unavailable:
            return self._finish(Outcome.unable_to_verify, checks, doc, now)
        return self._finish(Outcome.verified, checks, doc, now)

    def _check_status(
        self, doc: dict[str, Any], issuer_id: str, now: datetime
    ) -> tuple[Check, bool]:
        entries = _status_entries(doc)
        if not entries:
            return Check(
                "status", CheckStatus.skipped, "The issuer gave no revocation list."
            ), False
        for entry in entries:
            url = entry.get("statusListCredential")
            try:
                index = int(str(entry.get("statusListIndex")))
            except ValueError:
                return Check(
                    "status", CheckStatus.failed, "statusListIndex is not a number."
                ), False
            if not isinstance(url, str):
                return Check("status", CheckStatus.failed, "statusListCredential missing."), False
            try:
                list_vc = self.sources.status_list(url)
                problem = self._check_list(list_vc, url, issuer_id, now)
                if problem:
                    return Check("status", CheckStatus.unavailable, problem), False
                subject = list_vc.get("credentialSubject") or {}
                if subject.get("statusPurpose") != "revocation":
                    return Check("status", CheckStatus.unavailable, "Wrong list purpose."), False
                bits = bitstring.decode(str(subject.get("encodedList", "")))
                if bitstring.is_set(bits, index):
                    return (
                        Check("status", CheckStatus.failed, "The issuer has revoked it."),
                        True,
                    )
            except (Unavailable, SignerError) as exc:
                return Check("status", CheckStatus.unavailable, str(exc)), False
            except (ValueError, IndexError, OSError) as exc:
                return Check(
                    "status", CheckStatus.unavailable, f"Unreadable status list: {exc}"
                ), False
        return Check(
            "status", CheckStatus.passed, "Not revoked (signed status list checked)."
        ), False

    def _check_list(
        self, list_vc: dict[str, Any], url: str, issuer_id: str, now: datetime
    ) -> str | None:
        """Return why the status list can't be relied on, or ``None`` if it can."""
        if list_vc.get("id") != url:
            return "The status list does not match its URL."
        if "BitstringStatusListCredential" not in _types(list_vc.get("type")):
            return "Not a BitstringStatusListCredential."
        if _issuer_id(list_vc) != issuer_id:
            return "The status list was not issued by the credential's issuer."
        until = _parse_dt(list_vc.get("validUntil"))
        if until and until < now - CLOCK_SKEW:
            return "The status list has expired; the issuer has not renewed it."
        did_docs: dict[str, dict[str, Any]] = {}
        self._resolve(issuer_id, did_docs)
        pc = self.signer.verify(list_vc, did_docs)
        if not pc.verified:
            return "The status list's signature could not be verified."
        return None

    def _finish(
        self, outcome: Outcome, checks: list[Check], doc: Any, now: datetime
    ) -> VerificationResult:
        issuer: dict[str, Any] | None = None
        achievement: dict[str, Any] | None = None
        trust: dict[str, Any] = {"known_issuer": False}
        if isinstance(doc, dict):
            raw_issuer = doc.get("issuer")
            if isinstance(raw_issuer, dict):
                issuer = {k: raw_issuer.get(k) for k in ("id", "name", "url") if k in raw_issuer}
            elif isinstance(raw_issuer, str):
                issuer = {"id": raw_issuer}
            subject = doc.get("credentialSubject")
            if isinstance(subject, dict) and isinstance(subject.get("achievement"), dict):
                a = subject["achievement"]
                criteria = a.get("criteria") if isinstance(a.get("criteria"), dict) else {}
                achievement = {
                    "id": a.get("id"),
                    "name": a.get("name"),
                    "description": a.get("description"),
                    "criteria": criteria.get("narrative") if criteria else None,
                }
            iid = _issuer_id(doc)
            if iid:
                try:
                    known = self.sources.known_issuer(iid)
                except Exception:
                    known = None
                trust = {
                    "known_issuer": bool(known and known.get("approved")),
                    "detail": (
                        f"{known['name']} is an issuer registered with this service."
                        if known
                        else "This issuer is not registered with this service. "
                        "Decide for yourself whether to trust it."
                    ),
                }
        return VerificationResult(
            result=outcome,
            label=LABELS[outcome],
            checks=checks,
            issuer=issuer,
            achievement=achievement,
            credential_id=doc.get("id") if isinstance(doc, dict) else None,
            valid_from=doc.get("validFrom") if isinstance(doc, dict) else None,
            valid_until=doc.get("validUntil") if isinstance(doc, dict) else None,
            issuer_trust=trust,
            checked_at=now.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        )
