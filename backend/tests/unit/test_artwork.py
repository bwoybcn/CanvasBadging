# SPDX-License-Identifier: AGPL-3.0-or-later
"""Spec §5.3 / §15.3: uploaded artwork is validated and cannot run code or load resources."""

from __future__ import annotations

import struct
import zlib

import pytest

from opencredential.authoring.artwork import (
    ArtworkError,
    check_alt_text,
    clean_png,
    contrast_ratio,
    sanitise_svg,
)
from opencredential.authoring.templates import TEMPLATES, render

OK = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><circle r="40"/></svg>'

MALICIOUS = {
    "script": b"<script>alert(1)</script>",
    "onload": b'<rect width="10" height="10" onload="alert(1)"/>',
    "foreign": b'<foreignObject><div xmlns="http://www.w3.org/1999/xhtml">x</div></foreignObject>',
    "image": b'<image href="https://evil.example/x.png"/>',
    "xlink_image": b'<image xmlns:xlink="http://www.w3.org/1999/xlink" xlink:href="http://e/x"/>',
    "style_el": b"<style>@import url(https://evil.example/x.css);</style>",
    "style_url": b'<rect style="fill:url(https://evil.example/p.svg#a);stroke:red" />',
    "attr_url": b'<rect fill="url(http://evil.example/x)"/>',
    "anchor": b'<a href="javascript:alert(1)"><rect/></a>',
    "animate": b'<animate attributeName="href" to="javascript:alert(1)"/>',
    "use_ext": b'<use href="https://evil.example/sprite.svg#icon"/>',
    "data_uri": b'<rect fill="url(data:image/svg+xml;base64,AAAA)"/>',
}


def _wrap(inner: bytes) -> bytes:
    return b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">' + inner + b"</svg>"


def test_clean_svg_passes() -> None:
    img = sanitise_svg(OK)
    assert img.media_type == "image/svg+xml" and (img.width, img.height) == (100, 100)
    assert img.warnings == []


@pytest.mark.parametrize("name", sorted(MALICIOUS))
def test_malicious_svg_is_neutralised(name: str) -> None:
    out = sanitise_svg(_wrap(MALICIOUS[name])).data.lower()
    for bad in (
        b"script",
        b"onload",
        b"javascript",
        b"evil.example",
        b"foreignobject",
        b"<image",
        b"<style",
        b"@import",
        b"<a ",
        b"animate",
        b"data:",
    ):
        assert bad not in out, (name, bad)


def test_internal_references_survive() -> None:
    svg = _wrap(
        b'<defs><linearGradient id="g"><stop offset="0" stop-color="#fff"/>'
        b'</linearGradient></defs><rect fill="url(#g)" width="10" height="10"/>'
        b'<use href="#g"/>'
    )
    out = sanitise_svg(svg).data
    assert b'fill="url(#g)"' in out and b'href="#g"' in out


@pytest.mark.parametrize(
    ("data", "code"),
    [
        (b'<?xml version="1.0"?><!DOCTYPE svg [<!ENTITY x "y">]><svg/>', "SVG_DTD_NOT_ALLOWED"),
        (b"<svg", "IMAGE_INVALID"),
        (b'<html xmlns="http://www.w3.org/1999/xhtml"/>', "IMAGE_INVALID"),
        (b'<svg xmlns="http://www.w3.org/2000/svg"/>', "IMAGE_INVALID"),  # no size
        (b"<svg>" + b" " * 200_001 + b"</svg>", "IMAGE_TOO_LARGE"),
    ],
)
def test_bad_svgs_are_rejected(data: bytes, code: str) -> None:
    with pytest.raises(ArtworkError) as e:
        sanitise_svg(data)
    assert e.value.code == code


def _chunk(kind: bytes, body: bytes) -> bytes:
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))


def make_png(w: int = 400, h: int = 400, extra: bytes = b"") -> bytes:
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    raw = b"".join(b"\x00" + b"\x80\x40\x20" * w for _ in range(h))
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", ihdr)
        + extra
        + _chunk(b"IDAT", zlib.compress(raw))
        + _chunk(b"IEND", b"")
    )


def test_png_metadata_is_stripped() -> None:
    baked = _chunk(b"iTXt", b'openbadges\x00\x00\x00\x00\x00{"fake": true}')
    img = clean_png(make_png(extra=baked + _chunk(b"tEXt", b"Comment\x00hi")))
    assert b"openbadges" not in img.data and b"tEXt" not in img.data
    assert (img.width, img.height) == (400, 400)
    assert any("metadata" in w for w in img.warnings)


def test_png_validation() -> None:
    good = make_png()
    corrupted = good[:40] + bytes([good[40] ^ 0xFF]) + good[41:]
    for data, code in [
        (b"GIF89a....", "IMAGE_INVALID"),
        (corrupted, "IMAGE_INVALID"),
        (good[:-8], "IMAGE_INVALID"),
        (make_png(40, 40), "IMAGE_DIMENSIONS"),
        (make_png(3000, 100), "IMAGE_DIMENSIONS"),
    ]:
        with pytest.raises(ArtworkError) as e:
            clean_png(data)
        assert e.value.code == code
    assert any("400" in w for w in clean_png(make_png(200, 200)).warnings)


def test_alt_text_required() -> None:
    with pytest.raises(ArtworkError):
        check_alt_text("  ")
    with pytest.raises(ArtworkError):
        check_alt_text("x" * 251)
    assert check_alt_text(" A blue shield ") == "A blue shield"


@pytest.mark.parametrize("key", sorted(TEMPLATES))
def test_templates_render_and_are_safe(key: str) -> None:
    img = render(key, primary="#1f4e79", secondary="#f2c14e", label="Research <Skills> & AI")
    assert b"&lt;Skills&gt; &amp; AI" in img.data
    assert img.warnings == []
    assert sanitise_svg(img.data).data == img.data  # already clean: idempotent


def test_template_inputs_validated_and_contrast_warned() -> None:
    with pytest.raises(ArtworkError):
        render("roundel", primary="red", secondary="#000000", label="x")
    with pytest.raises(ArtworkError):
        render("roundel", primary="#000000", secondary="#000000", label="x" * 40)
    with pytest.raises(ArtworkError):
        render("nope", primary="#000000", secondary="#000000", label="x")
    low = render("roundel", primary="#7a7a7a", secondary="#000000", label="Grey")
    assert any("contrast" in w for w in low.warnings)
    assert round(contrast_ratio("#ffffff", "#000000")) == 21
