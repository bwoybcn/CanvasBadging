# SPDX-License-Identifier: AGPL-3.0-or-later
"""Issuer identity: public base URLs, did:web identifiers and DID documents (ADR-0004).

* Production issuers are ``did:web:<verification_host>:issuers:<slug>``, resolved at
  ``https://<verification_host>/issuers/<slug>/did.json``.
* Development issuers are ``did:key`` (self-resolving), named "(DEVELOPMENT)".
* The DID document lists every *active* and *retired* key so credentials signed before a routine
  rotation keep verifying (spec §7.7, §15.5). Revoked (compromised) keys are removed, so anything
  they signed stops verifying. Pending keys are not published until activated.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote, unquote, urlsplit

from opencredential.db.models import Institution, Issuer, IssuerKey
from opencredential.settings import PLACEHOLDER_VERIFICATION_HOST, Settings

DID_CONTEXT = ["https://www.w3.org/ns/did/v1", "https://w3id.org/security/multikey/v1"]
PUBLISHED_KEY_STATES = ("active", "retired")


class IdentityError(RuntimeError):
    pass


def base_url(institution: Institution, settings: Settings) -> str:
    """Origin under which this institution's public credential URLs live (no trailing slash).

    The institution's own verification host wins; otherwise the deployment's public base URL
    (development). Production refuses the documentation placeholder host (ADR-0004).
    """
    host = institution.verification_host
    if host:
        if host == PLACEHOLDER_VERIFICATION_HOST and settings.is_production:
            raise IdentityError(
                "The verification host is still the placeholder; set the institution's real "
                "verification domain before issuing in production."
            )
        return f"https://{host}"
    if settings.is_production:
        raise IdentityError("Production institutions must configure a verification host.")
    return settings.public_base_url.rstrip("/")


def did_web_for(host: str, slug: str) -> str:
    """``did:web`` for an issuer on ``host`` (``host:port`` percent-encodes the colon)."""
    return f"did:web:{quote(host, safe='')}:issuers:{slug}"


def did_web_document_url(did: str) -> str:
    """did:web method resolution: ``did:web:example.com:a:b`` → ``https://example.com/a/b/did.json``."""
    if not did.startswith("did:web:"):
        raise IdentityError(f"not a did:web identifier: {did}")
    parts = did[len("did:web:") :].split("#")[0].split(":")
    host = unquote(parts[0])
    if not host or "/" in host:
        raise IdentityError(f"malformed did:web host in {did}")
    path = "/".join(parts[1:])
    return f"https://{host}/{path}/did.json" if path else f"https://{host}/.well-known/did.json"


def host_of(url: str) -> str:
    return urlsplit(url).netloc


def verification_method_id(issuer: Issuer, key_id: Any, did_key_vm: str) -> str:
    """did:key issuers use the key's own method id; did:web issuers get ``#key-<uuid>``."""
    if issuer.did.startswith("did:key:"):
        return did_key_vm
    return f"{issuer.did}#key-{key_id}"


def did_document(issuer: Issuer, keys: list[IssuerKey]) -> dict[str, Any]:
    if not issuer.did.startswith("did:web:"):
        raise IdentityError("DID documents are only served for did:web issuers")
    published = [k for k in keys if k.state in PUBLISHED_KEY_STATES]
    published.sort(key=lambda k: (k.state != "active", k.created_at))
    methods = [
        {
            "id": k.verification_method_id,
            "type": "Multikey",
            "controller": issuer.did,
            "publicKeyMultibase": k.public_key_multibase,
        }
        for k in published
    ]
    ids = [m["id"] for m in methods]
    return {
        "@context": DID_CONTEXT,
        "id": issuer.did,
        "verificationMethod": methods,
        "assertionMethod": ids,
    }
