# SPDX-License-Identifier: AGPL-3.0-or-later
"""The verifier fails closed on revocation (finding 2 of the external review, 14 Nov 2026).

A credential must never show as Verified when its revocation status could not be checked:
malformed or missing status details, unsupported status methods and unreadable lists all give
"Unable to verify". The signature check is faked here so the credential's status entry can be
altered freely; the real signer is exercised by the W4 integration tests.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from opencredential.issuance import ob3
from opencredential.signer_client import ProofCheck
from opencredential.status import bitstring
from opencredential.verification.service import CheckStatus, Outcome, Verifier
from opencredential.verification.sources import Unavailable

ISSUER = "did:key:z6MkExampleIssuer"
LIST_URL = "https://u.example/status/c/l"
NOW = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)


class AcceptAllSigner:
    def verify(self, credential: dict[str, Any], did_documents: Any = None) -> ProofCheck:
        return ProofCheck(verified=True, verification_method=None, unresolvable=False, errors=[])


class Lists:
    def __init__(self, lists: dict[str, Any] | None = None):
        self.lists = lists or {}

    def did_document(self, did: str) -> dict[str, Any]:
        raise AssertionError("did:key needs no resolution")

    def status_list(self, url: str) -> dict[str, Any]:
        if url not in self.lists:
            raise Unavailable("not found")
        value = self.lists[url]
        if isinstance(value, Exception):
            raise value
        return value

    def known_issuer(self, did: str) -> dict[str, Any] | None:
        return None


def _list(
    revoked: frozenset[int] | set[int] = frozenset(),
    purpose: str = "revocation",
    url: str = LIST_URL,
    encoded: str | None = None,
) -> dict[str, Any]:
    return {
        "@context": [ob3.VC_V2_CONTEXT],
        "id": url,
        "type": ["VerifiableCredential", "BitstringStatusListCredential"],
        "issuer": ISSUER,
        "validFrom": "2026-11-14T00:00:00Z",
        "credentialSubject": {
            "id": f"{url}#list",
            "type": "BitstringStatusList",
            "statusPurpose": purpose,
            "encodedList": encoded if encoded is not None else bitstring.encode(revoked),
        },
    }


def _credential() -> dict[str, Any]:
    c = ob3.build_credential(
        ob3.CredentialInputs(
            credential_id="urn:uuid:0190f3a2-7b1c-7d2e-8f00-123456789abc",
            issuer=ob3.IssuerProfile(id=ISSUER, name="Skills Centre", url="https://u.example/"),
            achievement=ob3.AchievementInfo(
                id="https://u.example/achievements/1",
                name="Academic Writing",
                description="Completed academic writing.",
                criteria_narrative="Complete three modules.",
                image_url="https://u.example/assets/default-badge.svg",
                image_caption="Badge",
                alignments=(),
            ),
            valid_from=datetime(2026, 11, 13, 12, 0, tzinfo=UTC),
            recipient_hash=ob3.email_identity_hash("learner@uni.example", "00ff"),
            recipient_salt="00ff",
            status=ob3.StatusEntry(list_url=LIST_URL, index=42),
        )
    )
    c["proof"] = {
        "type": "DataIntegrityProof",
        "cryptosuite": "eddsa-rdfc-2022",
        "created": "2026-11-13T12:00:00Z",
        "verificationMethod": f"{ISSUER}#{ISSUER.removeprefix('did:key:')}",
        "proofPurpose": "assertionMethod",
        "proofValue": "zFake",
    }
    return c


def _verify(doc: dict[str, Any], lists: dict[str, Any] | None = None):  # type: ignore[no-untyped-def]
    sources = Lists({LIST_URL: _list()} if lists is None else lists)
    res = Verifier(AcceptAllSigner(), sources).verify(doc, now=NOW)  # type: ignore[arg-type]
    return res, {c.name: c.status for c in res.checks}


def test_baseline_good_credential_is_verified() -> None:
    res, checks = _verify(_credential())
    assert res.result == Outcome.verified, res.checks
    assert checks["status"] == CheckStatus.passed


def test_baseline_revoked_credential_is_revoked() -> None:
    res, _ = _verify(_credential(), {LIST_URL: _list({42})})
    assert res.result == Outcome.revoked


def _with_status(**changes: Any) -> dict[str, Any]:
    doc = _credential()
    for k, v in changes.items():
        if v is None:
            doc["credentialStatus"].pop(k, None)
        else:
            doc["credentialStatus"][k] = v
    return doc


@pytest.mark.parametrize(
    "changes",
    [
        {"statusListIndex": "forty-two"},
        {"statusListIndex": "-1"},
        {"statusListIndex": "4.2"},
        {"statusListIndex": ""},
        {"statusListIndex": None},
        {"statusListCredential": None},
        {"statusListCredential": ""},
        {"statusListCredential": 7},
        {"statusPurpose": "something-else"},
    ],
    ids=lambda c: ",".join(f"{k}={v!r}" for k, v in c.items()),
)
def test_malformed_status_entry_is_never_verified(changes: dict[str, Any]) -> None:
    res, checks = _verify(_with_status(**changes))
    assert res.result == Outcome.unable_to_verify, res.checks
    assert checks["status"] == CheckStatus.failed


def test_malformed_status_entry_on_a_revoked_list_still_not_verified() -> None:
    # Even if the list would say "revoked", a broken entry must not fall through to green.
    res, _ = _verify(_with_status(statusListIndex="x"), {LIST_URL: _list({42})})
    assert res.result == Outcome.unable_to_verify


def test_unsupported_status_method_is_unable_to_verify() -> None:
    res, checks = _verify(_with_status(type="1EdTechRevocationList"))
    assert res.result == Outcome.unable_to_verify
    assert checks["status"] == CheckStatus.unavailable


@pytest.mark.parametrize("value", ["revoked", 42, [], ["not-an-object"]])
def test_credential_status_of_the_wrong_shape_is_invalid(value: Any) -> None:
    # The official OB 3.0 schema requires a single status object, so this fails on structure.
    doc = _credential()
    doc["credentialStatus"] = value
    res, checks = _verify(doc)
    assert res.result == Outcome.invalid
    assert checks["structure"] == CheckStatus.failed


def test_several_status_entries_are_rejected_by_the_schema() -> None:
    doc = _credential()
    good = doc["credentialStatus"]
    doc["credentialStatus"] = [good, {**good, "statusListIndex": "oops"}]
    res, _ = _verify(doc)
    assert res.result == Outcome.invalid


@pytest.mark.parametrize(
    "lists",
    [
        {},  # list not found
        {LIST_URL: Unavailable("connection refused")},
        {LIST_URL: _list(encoded="not-multibase")},
        {LIST_URL: _list(encoded="u" + "A" * 40)},  # not gzip
        {LIST_URL: _list(encoded=bitstring.encode(set())[:30])},  # truncated gzip
        {LIST_URL: _list(purpose="suspension")},  # list for the wrong purpose
        {LIST_URL: _list(url="https://elsewhere.example/l")},  # list id does not match its URL
    ],
    ids=["missing", "unreachable", "not-multibase", "not-gzip", "truncated", "purpose", "id"],
)
def test_unreadable_or_untrustworthy_list_is_unable_to_verify(lists: dict[str, Any]) -> None:
    res, checks = _verify(_credential(), lists)
    assert res.result == Outcome.unable_to_verify, res.checks
    assert checks["status"] == CheckStatus.unavailable


def test_index_beyond_the_list_is_unable_to_verify() -> None:
    res, checks = _verify(_with_status(statusListIndex=str(bitstring.MIN_BITS)))
    assert res.result == Outcome.unable_to_verify
    assert checks["status"] == CheckStatus.unavailable


def test_suspension_entry_is_checked() -> None:
    doc = _with_status(statusPurpose="suspension")
    res, checks = _verify(doc, {LIST_URL: _list({42}, "suspension")})
    assert res.result == Outcome.unable_to_verify
    assert checks["status"] == CheckStatus.failed
    res, _ = _verify(doc, {LIST_URL: _list(set(), "suspension")})
    assert res.result == Outcome.verified
    res, _ = _verify(doc, {LIST_URL: _list()})  # a revocation list for a suspension entry
    assert res.result == Outcome.unable_to_verify


def test_refresh_only_status_is_reported_as_skipped() -> None:
    res, checks = _verify(_with_status(statusPurpose="refresh"))
    assert res.result == Outcome.verified
    assert checks["status"] == CheckStatus.skipped


def test_credential_without_any_status_is_verified_but_says_it_cannot_be_revoked() -> None:
    # Allowed by VC 2.0 and OB 3.0: the issuer simply offers no revocation. Removing the field
    # from a credential that had one breaks the signature, so it cannot be used to dodge a check.
    doc = _credential()
    del doc["credentialStatus"]
    res, checks = _verify(doc)
    assert res.result == Outcome.verified
    assert checks["status"] == CheckStatus.skipped
    assert "cannot be revoked" in next(c.detail for c in res.checks if c.name == "status")


class DevKeyIssuer(Lists):
    """An issuer this service knows, whose signing key is a development key."""

    def __init__(self, dev_methods: list[str]):
        super().__init__({LIST_URL: _list()})
        self.dev_methods = dev_methods

    def known_issuer(self, did: str) -> dict[str, Any] | None:
        return {
            "name": "Skills Centre",
            "approved": True,
            "dev_verification_methods": self.dev_methods,
        }


def test_a_badge_signed_with_a_development_key_is_called_a_test_badge() -> None:
    doc = _credential()
    method = doc["proof"]["verificationMethod"]
    res = Verifier(AcceptAllSigner(), DevKeyIssuer([method])).verify(doc, now=NOW)  # type: ignore[arg-type]
    assert res.result == Outcome.verified
    assert res.issuer_trust["development"] is True
    assert res.issuer_trust["detail"].startswith("Test badge:")
    real = Verifier(AcceptAllSigner(), DevKeyIssuer(["did:key:other#k"])).verify(doc, now=NOW)  # type: ignore[arg-type]
    assert real.issuer_trust["development"] is False
    assert "registered with this service" in real.issuer_trust["detail"]


# ---- several proofs on one credential (whole-product review, 16 Nov 2026, finding 19) -------


class RecordingSigner(AcceptAllSigner):
    """Accepts the proof and remembers the document it was asked to check."""

    def __init__(self) -> None:
        self.seen: list[dict[str, Any]] = []

    def verify(self, credential: dict[str, Any], did_documents: Any = None) -> ProofCheck:
        self.seen.append(credential)
        return super().verify(credential, did_documents)


def _endorser_proof() -> dict[str, Any]:
    return {
        "type": "DataIntegrityProof",
        "cryptosuite": "eddsa-rdfc-2022",
        "created": "2026-11-13T12:05:00Z",
        "verificationMethod": "did:key:z6MkEndorser#z6MkEndorser",
        "proofPurpose": "assertionMethod",
        "proofValue": "zOther",
    }


def test_a_credential_with_an_extra_proof_is_checked_by_the_issuers_proof() -> None:
    doc = _credential()
    issuer_proof = doc["proof"]
    doc["proof"] = [_endorser_proof(), issuer_proof]  # the issuer's proof is not the first
    signer = RecordingSigner()
    res = Verifier(signer, Lists({LIST_URL: _list()})).verify(doc, now=NOW)  # type: ignore[arg-type]
    assert res.result == Outcome.verified
    # Each proof in a set signs the credential without the others, so that is what is checked.
    assert signer.seen[0]["proof"] == issuer_proof
    detail = next(c.detail for c in res.checks if c.name == "signature")
    assert "1 other proof" in detail and "not checked" in detail
    assert doc["proof"] == [_endorser_proof(), issuer_proof]  # the submitted document is intact


def test_a_single_proof_in_a_list_is_accepted() -> None:
    doc = _credential()
    doc["proof"] = [doc["proof"]]
    res, checks = _verify(doc)
    assert res.result == Outcome.verified and checks["signature"] == CheckStatus.passed


def test_proofs_from_other_parties_only_is_invalid() -> None:
    doc = _credential()
    doc["proof"] = [_endorser_proof()]
    res, checks = _verify(doc)
    assert res.result == Outcome.invalid and checks["issuer"] == CheckStatus.failed


def test_a_chain_of_proofs_is_unable_to_verify_not_invalid() -> None:
    doc = _credential()
    chained = {**doc["proof"], "previousProof": "urn:uuid:first"}
    doc["proof"] = [{**_endorser_proof(), "id": "urn:uuid:first"}, chained]
    res, checks = _verify(doc)
    assert res.result == Outcome.unable_to_verify
    assert checks["signature"] == CheckStatus.unavailable
