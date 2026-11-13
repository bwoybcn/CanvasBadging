# SPDX-License-Identifier: AGPL-3.0-or-later
"""HTTP client for the signer service (ADR-0003). The api/worker never handle private keys."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx

from opencredential.settings import Settings


class SignerError(RuntimeError):
    """Base class. ``SignerUnavailable`` is transient (retry); ``SignerRejected`` is not."""


class SignerUnavailable(SignerError):
    pass


class SignerRejected(SignerError):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(f"signer refused: HTTP {status} {code}: {message}")
        self.status = status
        self.code = code


@dataclass(frozen=True)
class ProofCheck:
    verified: bool
    verification_method: str | None
    unresolvable: bool
    errors: list[dict[str, str]]


@dataclass(frozen=True)
class GeneratedKey:
    issuer_key_id: uuid.UUID
    public_key_multibase: str
    did: str
    verification_method_id: str


class SignerClient:
    def __init__(self, settings: Settings, *, transport: httpx.BaseTransport | None = None):
        self._client = httpx.Client(
            base_url=settings.signer_url,
            headers={"authorization": f"Bearer {settings.signer_shared_secret.get_secret_value()}"},
            timeout=10.0,
            transport=transport,
        )

    def create_key(self, issuer_key_id: uuid.UUID, *, dev: bool) -> GeneratedKey:
        """Ask the signer to generate an Ed25519 key and store it encrypted (did:key form)."""
        body = self._post("/v1/keys", {"issuer_key_id": str(issuer_key_id), "dev": dev})
        return GeneratedKey(
            issuer_key_id=uuid.UUID(body["issuer_key_id"]),
            public_key_multibase=body["public_key_multibase"],
            did=body["did"],
            verification_method_id=body["verification_method_id"],
        )

    def _post(self, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            r = self._client.post(path, json=body or {})
        except httpx.HTTPError as exc:
            raise SignerUnavailable(f"signer unreachable: {exc}") from exc
        if r.status_code >= 500:
            raise SignerUnavailable(f"signer error: HTTP {r.status_code}")
        if r.status_code >= 400:
            try:
                problem = r.json()
            except ValueError:
                problem = {}
            raise SignerRejected(
                r.status_code,
                str(problem.get("code", "ERROR")),
                str(problem.get("detail") or problem.get("title") or r.text[:200]),
            )
        return dict(r.json())

    def sign(
        self,
        *,
        issuer_key_id: uuid.UUID,
        verification_method_id: str,
        document: dict[str, Any],
        created: datetime | None = None,
    ) -> dict[str, Any]:
        """Return ``document`` with an ``eddsa-rdfc-2022`` DataIntegrityProof added."""
        body: dict[str, Any] = {
            "issuer_key_id": str(issuer_key_id),
            "verification_method_id": verification_method_id,
            "document": document,
        }
        if created is not None:
            body["created"] = created.isoformat().replace("+00:00", "Z")
        return dict(self._post("/v1/sign", body)["signed"])

    def verify(
        self, credential: dict[str, Any], did_documents: dict[str, dict[str, Any]] | None = None
    ) -> ProofCheck:
        """Check the proof only (signature, method, issuer control). No dates, no status."""
        body = self._post(
            "/v1/verify", {"credential": credential, "did_documents": did_documents or {}}
        )
        return ProofCheck(
            verified=bool(body.get("verified")),
            verification_method=body.get("verification_method"),
            unresolvable=bool(body.get("unresolvable")),
            errors=list(body.get("errors") or []),
        )

    def retire_key(self, issuer_key_id: uuid.UUID) -> None:
        self._post(f"/v1/keys/{issuer_key_id}/retire")

    def destroy_key(self, issuer_key_id: uuid.UUID) -> None:
        self._post(f"/v1/keys/{issuer_key_id}/destroy")

    def close(self) -> None:
        self._client.close()
