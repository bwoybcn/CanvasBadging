# SPDX-License-Identifier: AGPL-3.0-or-later
"""Authenticated encryption for secrets kept in the database (Canvas OAuth tokens, client
secrets), ADR-0009.

AES-256-GCM with a key derived from ``OC_TOKEN_ENCRYPTION_KEY`` by HKDF-SHA256. Each value is
bound to a *context* string (for example ``canvas_token:<integration id>:access``) via the
associated data, so a ciphertext copied into another row or column does not decrypt.

Format: ``b"v1" || nonce(12) || ciphertext+tag``.
"""

from __future__ import annotations

import hashlib
import hmac
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from opencredential.settings import Settings

_VERSION = b"v1"
_INFO = b"opencredential/secretbox/v1"


class SecretBoxError(Exception):
    pass


def _aead(settings: Settings) -> AESGCM:
    material = settings.token_encryption_key.get_secret_value().encode()
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=_INFO).derive(material)
    return AESGCM(key)


def seal(settings: Settings, plaintext: str, context: str) -> bytes:
    nonce = os.urandom(12)
    return _VERSION + nonce + _aead(settings).encrypt(nonce, plaintext.encode(), context.encode())


def open_(settings: Settings, sealed: bytes, context: str) -> str:
    if not sealed.startswith(_VERSION) or len(sealed) < 2 + 12 + 16:
        raise SecretBoxError("unrecognised ciphertext format")
    nonce, body = sealed[2:14], sealed[14:]
    try:
        return _aead(settings).decrypt(nonce, body, context.encode()).decode()
    except InvalidTag as exc:
        raise SecretBoxError("ciphertext failed authentication (wrong key or context)") from exc


def keyed_digest(settings: Settings, purpose: str, value: str) -> str:
    """A one-way, keyed fingerprint of ``value`` (HMAC-SHA256, hex).

    For records that must recognise a value again without keeping it, such as the Canvas
    identifiers of a person whose data was erased. The key is derived from
    ``OC_TOKEN_ENCRYPTION_KEY`` and bound to ``purpose``, so fingerprints made for one purpose
    match nothing else and cannot be recomputed from short identifiers without the key.
    """
    material = settings.token_encryption_key.get_secret_value().encode()
    key = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=f"opencredential/keyed-digest/v1/{purpose}".encode(),
    ).derive(material)
    return hmac.new(key, value.encode(), hashlib.sha256).hexdigest()
