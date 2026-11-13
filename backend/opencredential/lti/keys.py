# SPDX-License-Identifier: AGPL-3.0-or-later
"""The tool's own RSA key: signs client assertions for LTI Advantage services (NRPS).

Its public half is published at ``/lti/jwks`` and pasted into the Canvas LTI developer key.
Development creates the PEM file on first use. Production never generates a key silently: the
operator runs ``oc lti keygen`` and mounts the file.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from joserfc.jwk import RSAKey

from opencredential.logging import get_logger
from opencredential.settings import Settings

log = get_logger("lti.keys")


class ToolKeyMissing(RuntimeError):
    pass


def generate(path: Path) -> RSAKey:
    key = RSAKey.generate_key(2048, private=True, auto_kid=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    pem = key.as_pem(private=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(pem)
    log.info("lti.tool_key_generated", path=str(path))
    return key


@lru_cache
def _load(path_str: str, allow_generate: bool) -> RSAKey:
    path = Path(path_str)
    if not path.is_file():
        if not allow_generate:
            raise ToolKeyMissing(
                f"LTI tool key not found at {path}. Run `oc lti keygen` and set "
                "OC_LTI_PRIVATE_KEY_FILE."
            )
        try:
            return generate(path)
        except FileExistsError:
            pass  # another process (api or worker) created it first
    key = RSAKey.import_key(path.read_bytes(), {"use": "sig", "alg": "RS256"})
    key.ensure_kid()
    return key


def tool_key(settings: Settings) -> RSAKey:
    return _load(settings.lti_private_key_file, not settings.is_production)


def public_jwk(settings: Settings) -> dict[str, Any]:
    data = tool_key(settings).as_dict(private=False)
    data.update({"alg": "RS256", "use": "sig"})
    return dict(data)


def jwks(settings: Settings) -> dict[str, Any]:
    return {"keys": [public_jwk(settings)]}
