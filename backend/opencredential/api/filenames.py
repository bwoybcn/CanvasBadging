# SPDX-License-Identifier: AGPL-3.0-or-later
"""File names for downloads.

A ``Content-Disposition`` header must be Latin-1, so a badge title such as "Gŵyl Dewi" cannot go
into it as it is: the download fails with a server error. Accented letters become their plain
form ("gwyl-dewi"), anything else becomes a hyphen, and an empty result falls back to "badge".
"""

from __future__ import annotations

import unicodedata


def file_stem(title: str | None, fallback: str = "badge") -> str:
    """A lowercase ASCII stem for a download, made from ``title``."""
    plain = unicodedata.normalize("NFKD", title or "")
    plain = "".join(ch for ch in plain if not unicodedata.combining(ch))
    kept = "".join(ch if ch.isascii() and ch.isalnum() else "-" for ch in plain.lower())
    return "-".join(part for part in kept.split("-") if part) or fallback
