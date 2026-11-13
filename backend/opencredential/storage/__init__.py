# SPDX-License-Identifier: AGPL-3.0-or-later
"""Content-addressed asset storage.

Files are written once under ``<root>/<sha[:2]>/<sha>.<ext>`` and never changed, so a key always
names the same bytes (badge images referenced by issued credentials must not change). The
filesystem store is the MVP backend; an S3-compatible store can implement the same protocol.
"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from pathlib import Path
from typing import Protocol

from opencredential.settings import get_settings

_KEY = re.compile(r"^[0-9a-f]{2}/[0-9a-f]{64}\.(svg|png)$")
EXTENSIONS = {"image/svg+xml": "svg", "image/png": "png"}


class AssetStore(Protocol):
    def put(self, data: bytes, media_type: str) -> tuple[str, str]: ...

    def get(self, key: str) -> bytes: ...


class LocalFileStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def _path(self, key: str) -> Path:
        if not _KEY.match(key):
            raise ValueError("invalid storage key")
        return self.root / key

    def put(self, data: bytes, media_type: str) -> tuple[str, str]:
        """Store ``data``; returns ``(key, sha256)``. Idempotent for identical bytes."""
        sha = hashlib.sha256(data).hexdigest()
        key = f"{sha[:2]}/{sha}.{EXTENSIONS[media_type]}"
        path = self._path(key)
        if path.exists():
            return key, sha
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".upload-")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
        return key, sha

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()


def get_store() -> AssetStore:
    return LocalFileStore(get_settings().storage_dir)
