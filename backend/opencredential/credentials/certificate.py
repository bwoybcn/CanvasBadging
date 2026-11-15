# SPDX-License-Identifier: AGPL-3.0-or-later
"""A certificate to print (PDF) and a badge image (PNG) for the holder of a badge.

The certificate is a copy for printing and for people who do not use digital wallets. It is not
the proof. The proof is the signed credential file, or the public page the QR code opens, and
the certificate says so.

Text is set in Liberation Sans, bundled in ``fonts/`` so the result does not depend on fonts
installed on the server. Scripts that need shaping or right-to-left layout are not supported:
:func:`printable` reports them so the caller can explain instead of printing boxes.
"""

from __future__ import annotations

import io
import unicodedata
from dataclasses import dataclass
from datetime import date
from functools import cache
from pathlib import Path

import resvg_py
from reportlab.graphics import renderPDF
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.utils import ImageReader, simpleSplit
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas

FONT_DIR = Path(__file__).parent / "fonts"
REGULAR_FILE = FONT_DIR / "LiberationSans-Regular.ttf"
BOLD_FILE = FONT_DIR / "LiberationSans-Bold.ttf"
FAMILY = "Liberation Sans"
REGULAR = "OC-Sans"
BOLD = "OC-Sans-Bold"

#: Pixels along the longer side of a badge image made from an SVG.
IMAGE_SIDE = 1000

INK = HexColor("#1F2937")
MUTED = HexColor("#4B5563")
RULE = HexColor("#1F2A44")
HAIRLINE = HexColor("#C7CDD6")

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class CertificateError(ValueError):
    """The certificate or image cannot be made; ``code`` says why."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Certificate:
    badge_name: str
    issuer_name: str
    institution_name: str
    description: str
    issued_on: date | None
    valid_until: date | None
    expired: bool
    credential_id: str
    #: The holder's name, only when they asked for it to be printed.
    recipient_name: str | None
    #: The holder's public page for this badge, when they have turned one on.
    public_url: str | None
    #: The page where anyone can check a credential file.
    check_url: str
    image_png: bytes | None
    produced_on: date


@cache
def _fonts() -> tuple[TTFont, TTFont]:
    regular, bold = TTFont(REGULAR, str(REGULAR_FILE)), TTFont(BOLD, str(BOLD_FILE))
    pdfmetrics.registerFont(regular)
    pdfmetrics.registerFont(bold)
    return regular, bold


def tidy(text: str | None) -> str:
    """Composed characters and single spaces, so accents print as one glyph."""
    return " ".join(unicodedata.normalize("NFC", text or "").split())


def printable(text: str | None) -> bool:
    """True when every character of ``text`` can be printed correctly on the certificate."""
    regular, bold = _fonts()
    for ch in tidy(text):
        if ch == " ":
            continue
        if unicodedata.category(ch)[0] in ("M", "C"):
            return False  # combining marks and control characters need shaping we do not do
        if unicodedata.bidirectional(ch) in ("R", "AL", "AN"):
            return False  # right-to-left scripts would print back to front
        code = ord(ch)
        if code not in regular.face.charToGlyph or code not in bold.face.charToGlyph:
            return False
    return True


def badge_png(data: bytes, media_type: str, side: int = IMAGE_SIDE) -> bytes:
    """The badge artwork as a PNG. SVG artwork is drawn at ``side`` pixels wide."""
    if media_type == "image/png":
        if not data.startswith(PNG_SIGNATURE):
            raise CertificateError("IMAGE_UNREADABLE", "The badge image could not be read.")
        return data
    if media_type != "image/svg+xml":
        raise CertificateError("IMAGE_UNREADABLE", "The badge image could not be read.")
    try:
        png = resvg_py.svg_to_bytes(
            svg_string=data.decode("utf-8"),
            width=side,
            # Only the bundled font, so the same badge looks the same on every server. Artwork
            # that asks for Arial or Helvetica gets Liberation Sans, which has the same widths.
            skip_system_fonts=True,
            font_files=[str(REGULAR_FILE), str(BOLD_FILE)],
            font_family=FAMILY,
            sans_serif_family=FAMILY,
            serif_family=FAMILY,
            monospace_family=FAMILY,
            cursive_family=FAMILY,
            fantasy_family=FAMILY,
        )
    except (ValueError, UnicodeDecodeError) as exc:
        raise CertificateError("IMAGE_UNREADABLE", "The badge image could not be read.") from exc
    return bytes(png)


def long_date(day: date) -> str:
    return f"{day.day} {day:%B %Y}"


def _fit(
    text: str, font: str, sizes: tuple[float, ...], width: float, max_lines: int
) -> tuple[float, list[str]]:
    """The largest of ``sizes`` at which ``text`` fits in ``max_lines``; else shortened."""
    lines: list[str] = []
    for size in sizes:
        lines = simpleSplit(text, font, size, width)
        if len(lines) <= max_lines and all(
            pdfmetrics.stringWidth(line, font, size) <= width for line in lines
        ):
            return size, lines
    size = sizes[-1]
    kept = lines[:max_lines]
    last = kept[-1] if kept else ""
    while last and pdfmetrics.stringWidth(last + "…", font, size) > width:
        last = last[:-1]
    if kept:
        kept[-1] = last.rstrip() + "…"
    return size, kept


def _lines(c: Canvas, lines: list[str], font: str, size: float, x: float, y: float) -> float:
    """Draw ``lines`` downwards from baseline ``y``; return the baseline after the last."""
    c.setFont(font, size)
    for line in lines:
        c.drawString(x, y, line)
        y -= size * 1.25
    return y


def _qr(c: Canvas, value: str, x: float, y: float, side: float) -> None:
    widget = QrCodeWidget(value, barLevel="M")
    x0, y0, x1, y1 = widget.getBounds()
    drawing = Drawing(side, side, transform=[side / (x1 - x0), 0, 0, side / (y1 - y0), 0, 0])
    drawing.add(widget)
    renderPDF.draw(drawing, c, x, y)


def render(cert: Certificate) -> bytes:
    """One A4 landscape page."""
    _fonts()
    width, height = landscape(A4)
    out = io.BytesIO()
    c = Canvas(out, pagesize=(width, height), lang="en-GB", pageCompression=1)
    c.setTitle(f"Badge certificate: {cert.badge_name}")
    c.setAuthor(cert.issuer_name)
    c.setSubject(f"Certificate for the badge {cert.badge_name}, issued by {cert.issuer_name}")
    c.setCreator("OpenCredential")

    # Frame: a strong outer line and a fine inner one.
    c.setStrokeColor(RULE)
    c.setLineWidth(2)
    c.rect(28, 28, width - 56, height - 56)
    c.setLineWidth(0.5)
    c.rect(35, 35, width - 70, height - 70)

    left, right = 62.0, width - 62.0
    top = height - 78

    # Header: who issued it, and what this page is.
    c.setFillColor(INK)
    size, lines = _fit(cert.issuer_name, BOLD, (15, 13, 11), right - left - 190, 2)
    y = _lines(c, lines, BOLD, size, left, top)
    if tidy(cert.institution_name).casefold() != tidy(cert.issuer_name).casefold():
        c.setFillColor(MUTED)
        size, lines = _fit(cert.institution_name, REGULAR, (11, 10), right - left - 190, 1)
        y = _lines(c, lines, REGULAR, size, left, y - 1)
    c.setFillColor(MUTED)
    c.setFont(REGULAR, 11)
    c.drawRightString(right, top, "Badge certificate")
    header_bottom = min(y, top - 22) - 2
    c.setStrokeColor(HAIRLINE)
    c.setLineWidth(0.75)
    c.line(left, header_bottom, right, header_bottom)

    # Foot of the page, worked out first so the middle knows how much room it has.
    foot_top = 196.0
    c.line(left, foot_top, right, foot_top)

    # Middle: the badge image on the left, the statement on the right.
    image_side = 170.0
    middle_top, middle_bottom = header_bottom - 20, foot_top + 16
    text_left = left
    if cert.image_png:
        image_y = middle_top - image_side - max(0.0, (middle_top - middle_bottom - image_side) / 2)
        try:
            c.drawImage(
                ImageReader(io.BytesIO(cert.image_png)),
                left,
                image_y,
                image_side,
                image_side,
                mask="auto",
                preserveAspectRatio=True,
                anchor="c",
            )
            text_left = left + image_side + 30
        except Exception:  # an unreadable image must not stop the certificate
            text_left = left
    text_width = right - text_left

    blocks: list[tuple[str, float, list[str], object, float]] = []  # font, size, lines, colour, gap
    if cert.recipient_name:
        blocks.append((REGULAR, 13, ["This certifies that"], MUTED, 10))
        size, lines = _fit(cert.recipient_name, BOLD, (28, 24, 20, 17), text_width, 2)
        blocks.append((BOLD, size, lines, INK, 10))
        blocks.append((REGULAR, 13, ["has earned the badge"], MUTED, 10))
    else:
        blocks.append((REGULAR, 13, ["This certificate records the award of the badge"], MUTED, 10))
    size, lines = _fit(cert.badge_name, BOLD, (26, 22, 19, 16), text_width, 3)
    blocks.append((BOLD, size, lines, INK, 12))

    def tall(items: list[tuple[str, float, list[str], object, float]]) -> float:
        return sum(len(ls) * s * 1.25 + gap for _f, s, ls, _c, gap in items)

    # The description takes whatever room is left, up to four lines, and is left out when a
    # long name and a long title leave none.
    room = int((middle_top - middle_bottom - tall(blocks)) // (10.5 * 1.25))
    if cert.description and room >= 1:
        sizes = (11.5, 10.5) if room >= 4 else (10.5,)
        size, lines = _fit(cert.description, REGULAR, sizes, text_width, min(4, room))
        blocks.append((REGULAR, size, lines, INK, 0))
    block_height = tall(blocks)
    y = middle_top - max(0.0, (middle_top - middle_bottom - block_height) / 2)
    for font, size, lines, colour, gap in blocks:
        c.setFillColor(colour)
        y -= size * 0.95  # from the top of the line to its baseline
        y = _lines(c, lines, font, size, text_left, y) + size * 0.95 - gap

    # Foot: the facts on the left, the QR code on the right.
    qr_side = 104.0
    facts_right = right
    if cert.public_url:
        qr_x, qr_y = right - qr_side, foot_top - 14 - qr_side
        _qr(c, cert.public_url, qr_x, qr_y, qr_side)
        c.linkURL(cert.public_url, (qr_x, qr_y, qr_x + qr_side, qr_y + qr_side), relative=0)
        c.setFillColor(INK)
        c.setFont(BOLD, 9.5)
        c.drawCentredString(qr_x + qr_side / 2, qr_y - 12, "Scan to check this badge")
        facts_right = qr_x - 28

    issuer = cert.issuer_name
    if tidy(cert.institution_name).casefold() != tidy(cert.issuer_name).casefold():
        issuer = f"{cert.issuer_name}, {cert.institution_name}"
    facts: list[tuple[str, str, str | None]] = [("Issued by", issuer, None)]
    if cert.issued_on:
        facts.append(("Issued on", long_date(cert.issued_on), None))
    if cert.valid_until:
        facts.append(
            ("Expired on" if cert.expired else "Expires on", long_date(cert.valid_until), None)
        )
    else:
        facts.append(("Expires on", "Does not expire", None))
    facts.append(("Credential ID", cert.credential_id, None))
    if cert.public_url:
        facts.append(("Check online", cert.public_url, cert.public_url))
    else:
        facts.append(
            (
                "How to check",
                f"Ask the holder for the credential file, then check it at {cert.check_url}",
                None,
            )
        )
    label_width = 82.0
    value_width = facts_right - left - label_width
    y = foot_top - 24
    for label, value, link in facts:
        c.setFillColor(MUTED)
        c.setFont(BOLD, 9.5)
        c.drawString(left, y, label)
        c.setFillColor(INK)
        size, lines = _fit(value, REGULAR, (9.5, 8.5, 7.5), value_width, 2)
        start = y
        y = _lines(c, lines, REGULAR, size, left + label_width, y)
        if link:
            c.linkURL(
                link,
                (left + label_width, y + size, left + label_width + value_width, start + size),
                relative=0,
            )
        y -= 2.5

    # The honest note: what this page is, and where the proof lives.
    proof = "the signed credential file"
    if cert.public_url:
        proof = "the page behind the QR code, or the signed credential file"
    note = (
        f"Produced on {long_date(cert.produced_on)}. This certificate is a copy for printing. "
        f"The proof is {proof}, which shows whether the badge is still valid."
    )
    c.setFillColor(MUTED)
    size, lines = _fit(note, REGULAR, (8.5, 8), facts_right - left, 2)
    _lines(c, lines, REGULAR, size, left, 62 if len(lines) == 1 else 62 + size * 1.25)

    c.showPage()
    c.save()
    return out.getvalue()
