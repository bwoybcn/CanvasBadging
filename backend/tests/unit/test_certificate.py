# SPDX-License-Identifier: AGPL-3.0-or-later
"""The certificate PDF and badge image (product review recommendation 12)."""

from __future__ import annotations

import io
import struct
from datetime import date
from pathlib import Path
from string import Template

import pytest
from pypdf import PdfReader

from opencredential.credentials import certificate as cert

TEMPLATES = Path(cert.__file__).parents[1] / "authoring" / "artwork_templates"
PUBLIC = "https://badges.example.ac.uk/verify/q3J8xN2mT7vB1kLpW9sZcA"


def _svg(name: str = "ribbon", label: str = "Data skills") -> bytes:
    text = Template((TEMPLATES / f"{name}.svg").read_text(encoding="utf-8"))
    return text.substitute(
        primary="#0B3D91", secondary="#F2A900", text="#FFFFFF", label=label
    ).encode()


def _certificate(**changes: object) -> cert.Certificate:
    values: dict[str, object] = {
        "badge_name": "Research Data Management",
        "issuer_name": "University Library",
        "institution_name": "Example University",
        "description": "Awarded for planning, storing and sharing research data responsibly.",
        "issued_on": date(2026, 11, 14),
        "valid_until": None,
        "expired": False,
        "credential_id": "urn:uuid:3f0c2d3e-7a54-4b5e-9a1e-2f6b8f1c9d10",
        "recipient_name": "Priya Sharma",
        "public_url": PUBLIC,
        "check_url": "https://badges.example.ac.uk/verify",
        "image_png": cert.badge_png(_svg(), "image/svg+xml"),
        "produced_on": date(2026, 11, 15),
    }
    values.update(changes)
    return cert.Certificate(**values)  # type: ignore[arg-type]


def _text(pdf: bytes) -> str:
    return " ".join(PdfReader(io.BytesIO(pdf)).pages[0].extract_text().split())


def _links(pdf: bytes) -> set[str]:
    page = PdfReader(io.BytesIO(pdf)).pages[0]
    return {a.get_object()["/A"]["/URI"] for a in page.get("/Annots", [])}


def test_certificate_is_one_landscape_a4_page_with_the_facts() -> None:
    pdf = cert.render(_certificate())
    reader = PdfReader(io.BytesIO(pdf))
    assert len(reader.pages) == 1
    box = reader.pages[0].mediabox
    assert (round(float(box.width)), round(float(box.height))) == (842, 595)
    assert reader.metadata is not None
    assert reader.metadata.title == "Badge certificate: Research Data Management"
    text = _text(pdf)
    for expected in (
        "This certifies that",
        "Priya Sharma",
        "has earned the badge",
        "Research Data Management",
        "University Library, Example University",
        "14 November 2026",
        "Does not expire",
        "urn:uuid:3f0c2d3e-7a54-4b5e-9a1e-2f6b8f1c9d10",
        "Scan to check this badge",
        PUBLIC,
        "Produced on 15 November 2026",
        "This certificate is a copy for printing",
    ):
        assert expected in text, expected
    # The QR code and the printed address both open the holder's public page.
    assert _links(pdf) == {PUBLIC}


def test_certificate_without_a_name_or_public_link() -> None:
    pdf = cert.render(_certificate(recipient_name=None, public_url=None))
    text = _text(pdf)
    assert "This certificate records the award of the badge" in text
    assert "Priya" not in text and "This certifies that" not in text
    assert "Scan to check" not in text
    assert "Ask the holder for the credential file" in text
    assert "https://badges.example.ac.uk/verify" in text
    assert _links(pdf) == set()


def test_certificate_says_when_the_badge_expired() -> None:
    text = _text(cert.render(_certificate(valid_until=date(2025, 1, 31), expired=True)))
    assert "Expired on 31 January 2025" in text
    text = _text(cert.render(_certificate(valid_until=date(2030, 1, 31))))
    assert "Expires on 31 January 2030" in text


def test_long_names_and_titles_stay_on_the_page() -> None:
    pdf = cert.render(
        _certificate(
            recipient_name="Maximilian Alexander von Hohenzollern-Sigmaringen Łukasiewicz-Nguyễn",
            badge_name=(
                "Advanced Qualitative and Quantitative Research Methods for Postgraduate "
                "Researchers in the Health and Life Sciences (Level 3)"
            ),
            issuer_name="Faculty of Health and Life Sciences Researcher Development Programme",
            description="A very long description. " * 80,
        )
    )
    assert len(PdfReader(io.BytesIO(pdf)).pages) == 1
    text = _text(pdf)
    assert "Łukasiewicz-Nguyễn" in text
    assert "(Level 3)" in text
    # The description is cut to the room that is left instead of running into the facts.
    assert 1 <= text.count("A very long description.") < 20
    assert "…" in text


def test_certificate_is_still_made_without_an_image_or_with_a_broken_one() -> None:
    assert cert.render(_certificate(image_png=None)).startswith(b"%PDF")
    assert cert.render(_certificate(image_png=b"not an image")).startswith(b"%PDF")


@pytest.mark.parametrize(
    ("text", "ok"),
    [
        ("Priya Sharma", True),
        ("Łukasz Nguyễn-Çelik", True),
        ("Zoë Müller", True),  # a combining mark that composes to one character
        ("Ελένη Иванова", True),
        ("", True),
        ("王伟", False),
        ("محمد", False),
        ("דוד", False),
        ("ą́x", False),  # marks left over after composing
        ("tab\x07bell", False),
    ],
)
def test_printable(text: str, ok: bool) -> None:
    assert cert.printable(text) is ok


@pytest.mark.parametrize("name", ["hexagon", "ribbon", "roundel", "shield"])
def test_badge_image_from_each_template_is_a_square_png(name: str) -> None:
    png = cert.badge_png(_svg(name), "image/svg+xml")
    assert png.startswith(cert.PNG_SIGNATURE)
    width, height = struct.unpack(">II", png[16:24])
    assert (width, height) == (cert.IMAGE_SIDE, cert.IMAGE_SIDE)


def test_badge_image_draws_the_label_text() -> None:
    """The label is text in the SVG; it must be drawn with the bundled font, not left out."""
    with_label = cert.badge_png(_svg(label="Data skills"), "image/svg+xml")
    other_label = cert.badge_png(_svg(label="Leadership"), "image/svg+xml")
    assert with_label != other_label


def test_png_artwork_is_passed_through_and_rubbish_is_refused() -> None:
    png = cert.badge_png(_svg(), "image/svg+xml")
    assert cert.badge_png(png, "image/png") == png
    for data, media in ((b"nope", "image/png"), (b"<svg", "image/svg+xml"), (b"x", "text/plain")):
        with pytest.raises(cert.CertificateError):
            cert.badge_png(data, media)
