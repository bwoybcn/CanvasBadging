# SPDX-License-Identifier: AGPL-3.0-or-later
"""An *independent* eddsa-rdfc-2022 verifier, used only by tests (ADR-0003, C-INDEP-01).

It shares no code with the signer: canonicalisation is pyld (Python RDFC-1.0 / URDNA2015), the
signature check is ``cryptography``'s Ed25519, multibase decoding is ``base58``. It follows the
W3C *Data Integrity EdDSA Cryptosuites v1.0* algorithm literally:

    hashData = SHA-256(canonical proof options) ‖ SHA-256(canonical unsecured document)

Contexts are read from ``tests/conformance/contexts`` (copies of the official files), so the
check runs offline and with nothing but public material, as an external verifier would.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import base58
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pyld import jsonld

CONTEXT_DIR = Path(__file__).resolve().parents[3] / "tests" / "conformance" / "contexts"
CONTEXT_FILES = {
    "https://www.w3.org/ns/credentials/v2": "credentials-v2.jsonld",
    "https://purl.imsglobal.org/spec/ob/v3p0/context-3.0.3.json": "ob-v3p0-context-3.0.3.json",
    "https://purl.imsglobal.org/spec/ob/v3p0/extensions.json": "ob-v3p0-extensions.json",
}


class NotVerified(Exception):
    pass


def _loader(url: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
    name = CONTEXT_FILES.get(url)
    if name is None:
        raise jsonld.JsonLdError(f"offline loader has no {url}", "loading document failed")
    return {
        "contentType": "application/ld+json",
        "contextUrl": None,
        "documentUrl": url,
        "document": json.loads((CONTEXT_DIR / name).read_text(encoding="utf-8")),
    }


def _canonize(doc: dict[str, Any]) -> bytes:
    nquads = jsonld.normalize(
        doc,
        {"algorithm": "URDNA2015", "format": "application/n-quads", "documentLoader": _loader},
    )
    return str(nquads).encode("utf-8")


def _ed25519_from_multikey(multibase: str) -> Ed25519PublicKey:
    if not multibase.startswith("z"):
        raise NotVerified("public key is not base58btc multibase")
    raw = base58.b58decode(multibase[1:])
    if raw[:2] != b"\xed\x01" or len(raw) != 34:
        raise NotVerified("public key is not an Ed25519 multikey")
    return Ed25519PublicKey.from_public_bytes(raw[2:])


def public_key_for(vm: str, did_documents: dict[str, dict[str, Any]]) -> Ed25519PublicKey:
    did = vm.split("#")[0]
    if did.startswith("did:key:"):
        fragment = vm.split("#")[1]
        if fragment != did[len("did:key:") :]:
            raise NotVerified("did:key fragment does not match the key")
        return _ed25519_from_multikey(fragment)
    doc = did_documents.get(did)
    if doc is None:
        raise NotVerified(f"no DID document for {did}")
    if vm not in doc.get("assertionMethod", []):
        raise NotVerified("verification method is not an assertionMethod of the issuer")
    for method in doc.get("verificationMethod", []):
        if method.get("id") == vm and method.get("controller") == did:
            return _ed25519_from_multikey(method["publicKeyMultibase"])
    raise NotVerified("verification method not found in DID document")


def verify(
    credential: dict[str, Any], did_documents: dict[str, dict[str, Any]] | None = None
) -> None:
    """Raise ``NotVerified`` unless the credential's eddsa-rdfc-2022 proof is valid."""
    doc = copy.deepcopy(credential)
    proof = doc.pop("proof", None)
    if not isinstance(proof, dict):
        raise NotVerified("exactly one embedded proof expected")
    if proof.get("type") != "DataIntegrityProof" or proof.get("cryptosuite") != "eddsa-rdfc-2022":
        raise NotVerified("not an eddsa-rdfc-2022 DataIntegrityProof")
    if proof.get("proofPurpose") != "assertionMethod":
        raise NotVerified("proofPurpose must be assertionMethod")
    issuer = doc["issuer"]["id"] if isinstance(doc["issuer"], dict) else doc["issuer"]
    vm = proof["verificationMethod"]
    if vm.split("#")[0] != issuer:
        raise NotVerified("proof key is not controlled by the issuer")
    proof_value = proof.pop("proofValue")
    proof["@context"] = doc["@context"]
    hash_data = hashlib.sha256(_canonize(proof)).digest() + hashlib.sha256(_canonize(doc)).digest()
    if not proof_value.startswith("z"):
        raise NotVerified("proofValue must be base58btc multibase")
    signature = base58.b58decode(proof_value[1:])
    try:
        public_key_for(vm, did_documents or {}).verify(signature, hash_data)
    except InvalidSignature as exc:
        raise NotVerified("signature does not match") from exc
