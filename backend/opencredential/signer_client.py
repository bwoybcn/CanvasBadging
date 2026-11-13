# SPDX-License-Identifier: AGPL-3.0-or-later
"""HTTP client for the signer service (ADR-0003). The api/worker never handle private keys."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import httpx

from opencredential.settings import Settings


class SignerError(RuntimeError):
    pass


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
        try:
            r = self._client.post(
                "/v1/keys", json={"issuer_key_id": str(issuer_key_id), "dev": dev}
            )
        except httpx.HTTPError as exc:
            raise SignerError(f"signer unreachable: {exc}") from exc
        if r.status_code != 201:
            raise SignerError(f"signer refused key generation: HTTP {r.status_code} {r.text}")
        body = r.json()
        return GeneratedKey(
            issuer_key_id=uuid.UUID(body["issuer_key_id"]),
            public_key_multibase=body["public_key_multibase"],
            did=body["did"],
            verification_method_id=body["verification_method_id"],
        )

    def close(self) -> None:
        self._client.close()
