# SPDX-License-Identifier: AGPL-3.0-or-later
"""Built-in, openly licensed (CC0) badge artwork templates (spec §5.3)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from string import Template
from xml.sax.saxutils import escape

from opencredential.authoring.artwork import ArtworkError, CleanImage, contrast_ratio, sanitise_svg

TEMPLATE_DIR = Path(__file__).with_name("artwork_templates")
LICENCE = "CC0-1.0"
MAX_LABEL = 22
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


@dataclass(frozen=True)
class ArtworkTemplate:
    key: str
    name: str
    description: str


TEMPLATES = {
    t.key: t
    for t in (
        ArtworkTemplate("roundel", "Roundel", "Circular badge with a star"),
        ArtworkTemplate("shield", "Shield", "Shield with a tick, suits completion badges"),
        ArtworkTemplate("hexagon", "Hexagon", "Hexagon with a target, suits skills badges"),
        ArtworkTemplate("ribbon", "Rosette", "Rosette with ribbons, suits awards"),
    )
}


def render(key: str, *, primary: str, secondary: str, label: str) -> CleanImage:
    if key not in TEMPLATES:
        raise ArtworkError("TEMPLATE_NOT_FOUND", "No artwork template with that name.")
    for c in (primary, secondary):
        if not _HEX.match(c):
            raise ArtworkError("COLOUR_INVALID", "Colours must be #RRGGBB hex values.")
    label = " ".join(label.split())
    if not label or len(label) > MAX_LABEL:
        raise ArtworkError("LABEL_INVALID", f"The label must be 1 to {MAX_LABEL} characters.")
    # Pick whichever text colour reads better on the primary colour.
    text = (
        "#ffffff"
        if contrast_ratio(primary, "#ffffff") >= contrast_ratio(primary, "#1a1a1a")
        else "#1a1a1a"
    )
    source = (TEMPLATE_DIR / f"{key}.svg").read_text(encoding="utf-8")
    svg = Template(source).substitute(
        primary=primary, secondary=secondary, text=text, label=escape(label)
    )
    image = sanitise_svg(svg.encode("utf-8"))
    ratio = contrast_ratio(primary, text)
    if ratio < 4.5:
        image.warnings.append(
            f"The label contrast is {ratio:.1f}:1. Choose a darker or lighter main colour to "
            "reach at least 4.5:1."
        )
    return image
