# SPDX-License-Identifier: AGPL-3.0-or-later
"""The template packs load, and their wording follows the product's rules."""

from __future__ import annotations

import re

from opencredential.authoring.service import CREDIT_TERMS, PLACEHOLDER
from opencredential.governance import packs


def _texts(pack: packs.Pack) -> list[str]:
    out = [pack.pack.description]
    for a in pack.attributes:
        out += [a.name, a.description or ""]
    for t in pack.templates:
        d = t.defaults
        out += [t.name, t.description or ""]
        out += [
            d.title or "",
            d.short_description or "",
            d.description or "",
            d.criteria_narrative or "",
            d.evidence_description or "",
            *(d.learning_outcomes or []),
        ]
    return out


def test_every_pack_loads_and_its_templates_use_its_own_attributes() -> None:
    loaded = packs.load_all()
    assert "liverpool" in loaded
    for pack in loaded.values():
        keys = {a.key for a in pack.attributes}
        assert len(keys) == len(pack.attributes)
        for t in pack.templates:
            assert set(t.defaults.graduate_attributes or []) <= keys, t.name
            # Something real is demonstrated and evidenced (no badges for logging in).
            assert t.defaults.evidence_description, t.name
            assert t.defaults.criteria_narrative, t.name
            # The lecturer has something to fill in.
            assert PLACEHOLDER.search(t.defaults.title or ""), t.name


def test_pack_wording_uses_the_words_on_the_screen() -> None:
    for pack in packs.load_all().values():
        for text in _texts(pack):
            assert not CREDIT_TERMS.search(text), text
            assert not re.search(r"\b(learners?|micro-credentials?)\b", text, re.I), text
            # No points, levels or leaderboards.
            assert not re.search(r"\b(points?|levels?|leaderboards?|streaks?)\b", text, re.I), text


def test_the_liverpool_pack_has_the_six_starter_templates() -> None:
    pack = packs.get("liverpool")
    assert [a.name for a in pack.attributes] == [
        "Confidence",
        "Digital Fluency",
        "Global Citizenship",
    ]
    assert len(pack.templates) == 6
