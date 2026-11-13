# SPDX-License-Identifier: AGPL-3.0-or-later
"""Badge artwork validation and sanitisation (spec §5.3, §15.3).

* SVG: parsed with DTDs and entities refused, rebuilt from an allow-list of elements and
  attributes. Scripts, event handlers, ``<style>``, ``<foreignObject>``, ``<image>``, links,
  animation and every reference outside the document (``href`` or ``url()`` not starting with
  ``#``) are removed, so a rendered badge cannot run code or load anything.
* PNG: the signature, chunk CRCs and header are checked; metadata and text chunks (including
  any "baked" badge data) and animation chunks are stripped, so only image data is kept.
* Both: size limits and required alternative text.
"""

from __future__ import annotations

import re
import struct
import zlib
from dataclasses import dataclass, field
from xml.etree import ElementTree as ET

MAX_SVG_BYTES = 200_000
MAX_PNG_BYTES = 1_000_000
MIN_PNG_SIDE = 90
MAX_PNG_SIDE = 2048
RECOMMENDED_MIN_SIDE = 400
MAX_ALT_TEXT = 250

SVG_NS = "http://www.w3.org/2000/svg"
XLINK_NS = "http://www.w3.org/1999/xlink"
ET.register_namespace("", SVG_NS)
ET.register_namespace("xlink", XLINK_NS)


class ArtworkError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass
class CleanImage:
    data: bytes
    media_type: str
    width: int | None
    height: int | None
    warnings: list[str] = field(default_factory=list)


def check_alt_text(alt: str | None) -> str:
    alt = (alt or "").strip()
    if not alt:
        raise ArtworkError("ALT_TEXT_REQUIRED", "Describe the badge image for screen readers.")
    if len(alt) > MAX_ALT_TEXT:
        raise ArtworkError("ALT_TEXT_TOO_LONG", f"Alternative text is limited to {MAX_ALT_TEXT}.")
    return alt


# ---- SVG ------------------------------------------------------------------------------------

ALLOWED_ELEMENTS = {
    "svg",
    "g",
    "defs",
    "symbol",
    "use",
    "title",
    "desc",
    "path",
    "rect",
    "circle",
    "ellipse",
    "line",
    "polyline",
    "polygon",
    "text",
    "tspan",
    "textPath",
    "linearGradient",
    "radialGradient",
    "stop",
    "clipPath",
    "mask",
    "pattern",
}

ALLOWED_ATTRIBUTES = {
    "id",
    "class",
    "viewBox",
    "width",
    "height",
    "x",
    "y",
    "x1",
    "y1",
    "x2",
    "y2",
    "cx",
    "cy",
    "r",
    "rx",
    "ry",
    "fx",
    "fy",
    "d",
    "points",
    "transform",
    "preserveAspectRatio",
    "fill",
    "fill-opacity",
    "fill-rule",
    "stroke",
    "stroke-width",
    "stroke-opacity",
    "stroke-linecap",
    "stroke-linejoin",
    "stroke-dasharray",
    "stroke-dashoffset",
    "stroke-miterlimit",
    "opacity",
    "clip-path",
    "clip-rule",
    "mask",
    "style",
    "color",
    "font-family",
    "font-size",
    "font-weight",
    "font-style",
    "text-anchor",
    "dominant-baseline",
    "alignment-baseline",
    "letter-spacing",
    "word-spacing",
    "text-decoration",
    "dx",
    "dy",
    "rotate",
    "textLength",
    "lengthAdjust",
    "startOffset",
    "offset",
    "stop-color",
    "stop-opacity",
    "gradientUnits",
    "gradientTransform",
    "spreadMethod",
    "patternUnits",
    "patternContentUnits",
    "patternTransform",
    "clipPathUnits",
    "maskUnits",
    "maskContentUnits",
    "role",
    "aria-label",
    "aria-labelledby",
    "aria-hidden",
    "focusable",
    "visibility",
    "display",
    "version",
    "xml:space",
    "lang",
}

STYLE_PROPERTIES = {
    "fill",
    "fill-opacity",
    "fill-rule",
    "stroke",
    "stroke-width",
    "stroke-opacity",
    "stroke-linecap",
    "stroke-linejoin",
    "stroke-dasharray",
    "stroke-dashoffset",
    "opacity",
    "font-family",
    "font-size",
    "font-weight",
    "font-style",
    "text-anchor",
    "dominant-baseline",
    "letter-spacing",
    "stop-color",
    "stop-opacity",
    "display",
    "visibility",
    "clip-path",
    "mask",
    "color",
}

_URL = re.compile(r"url\s*\(\s*['\"]?\s*([^)'\"]*)", re.IGNORECASE)
_DANGEROUS = re.compile(r"(javascript:|expression\s*\(|@import|data:)", re.IGNORECASE)
_DECL = re.compile(rb"<!(DOCTYPE|ENTITY|ELEMENT|ATTLIST)", re.IGNORECASE)
_LENGTH = re.compile(r"^\s*([0-9]*\.?[0-9]+)\s*(px)?\s*$")


def _safe_value(value: str) -> bool:
    if _DANGEROUS.search(value):
        return False
    return all(ref.strip().startswith("#") for ref in _URL.findall(value))


def _clean_style(style: str) -> str:
    kept = []
    for decl in style.split(";"):
        name, sep, value = decl.partition(":")
        name, value = name.strip().lower(), value.strip()
        if sep and name in STYLE_PROPERTIES and _safe_value(value):
            kept.append(f"{name}:{value}")
    return ";".join(kept)


def _local(tag: str) -> tuple[str | None, str]:
    if tag.startswith("{"):
        ns, _, name = tag[1:].partition("}")
        return ns, name
    return None, tag


def _copy(src: ET.Element, removed: set[str]) -> ET.Element | None:
    ns, name = _local(src.tag) if isinstance(src.tag, str) else (None, "")
    if ns != SVG_NS or name not in ALLOWED_ELEMENTS:
        removed.add(name or "comment")
        return None
    dst = ET.Element(src.tag)
    for key, value in src.attrib.items():
        a_ns, a_name = _local(key)
        if a_name == "href" and a_ns in (None, XLINK_NS):
            if value.strip().startswith("#") and name in (
                "use",
                "textPath",
                "linearGradient",
                "radialGradient",
                "pattern",
            ):
                dst.set(f"{{{XLINK_NS}}}href" if a_ns else "href", value.strip())
            else:
                removed.add(f"@{a_name}")
            continue
        if key == "{http://www.w3.org/XML/1998/namespace}space":
            dst.set(key, value)
            continue
        if a_ns is not None or a_name not in ALLOWED_ATTRIBUTES:
            removed.add(f"@{a_name}")
            continue
        if a_name == "style":
            cleaned = _clean_style(value)
            if cleaned:
                dst.set("style", cleaned)
            continue
        if not _safe_value(value):
            removed.add(f"@{a_name}")
            continue
        dst.set(a_name, value)
    dst.text = src.text if name in ("text", "tspan", "textPath", "title", "desc") else None
    for child in src:
        c = _copy(child, removed)
        if c is not None:
            if child.tail and _local(child.tag)[1] in ("tspan",):
                c.tail = child.tail
            dst.append(c)
    return dst


def _length(v: str | None) -> float | None:
    if v is None:
        return None
    m = _LENGTH.match(v)
    return float(m.group(1)) if m else None


def sanitise_svg(data: bytes) -> CleanImage:
    if len(data) > MAX_SVG_BYTES:
        raise ArtworkError(
            "IMAGE_TOO_LARGE", f"SVG files are limited to {MAX_SVG_BYTES // 1000} KB."
        )
    if _DECL.search(data):
        raise ArtworkError(
            "SVG_DTD_NOT_ALLOWED", "SVG files with DOCTYPE or entity declarations are not accepted."
        )
    try:
        root = ET.fromstring(data)  # noqa: S314  (no DTD/entities possible after the check above)
    except ET.ParseError as exc:
        raise ArtworkError("IMAGE_INVALID", f"The SVG file could not be read: {exc}") from exc
    if root.tag != f"{{{SVG_NS}}}svg":
        raise ArtworkError(
            "IMAGE_INVALID",
            "The file is not an SVG image (root element must be <svg> in the SVG namespace).",
        )
    removed: set[str] = set()
    clean = _copy(root, removed)
    assert clean is not None
    width, height = _length(clean.get("width")), _length(clean.get("height"))
    vb = clean.get("viewBox")
    if vb:
        parts = re.split(r"[\s,]+", vb.strip())
        try:
            vw, vh = float(parts[2]), float(parts[3])
        except (IndexError, ValueError) as exc:
            raise ArtworkError("IMAGE_INVALID", "The SVG viewBox is not valid.") from exc
        width, height = width or vw, height or vh
    if not width or not height:
        raise ArtworkError("IMAGE_INVALID", "The SVG needs a viewBox or a width and height.")
    warnings = []
    if removed:
        warnings.append(
            "Removed unsafe or unsupported content: " + ", ".join(sorted(removed)) + "."
        )
    if abs(width - height) / max(width, height) > 0.05:
        warnings.append("Badges display best as square images.")
    out = ET.tostring(clean, encoding="utf-8", xml_declaration=False)
    return CleanImage(out, "image/svg+xml", round(width), round(height), warnings)


# ---- PNG ------------------------------------------------------------------------------------

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
KEEP_CHUNKS = {b"IHDR", b"PLTE", b"IDAT", b"IEND", b"tRNS", b"gAMA", b"cHRM", b"sRGB", b"pHYs"}


def clean_png(data: bytes) -> CleanImage:
    if len(data) > MAX_PNG_BYTES:
        raise ArtworkError(
            "IMAGE_TOO_LARGE", f"PNG files are limited to {MAX_PNG_BYTES // 1000} KB."
        )
    if not data.startswith(PNG_SIGNATURE):
        raise ArtworkError("IMAGE_INVALID", "The file is not a PNG image.")
    pos, out = len(PNG_SIGNATURE), [PNG_SIGNATURE]
    seen: list[bytes] = []
    width = height = 0
    stripped: set[str] = set()
    while pos < len(data):
        if pos + 8 > len(data):
            raise ArtworkError("IMAGE_INVALID", "The PNG file is truncated.")
        length, ctype = struct.unpack(">I4s", data[pos : pos + 8])
        body = data[pos + 8 : pos + 8 + length]
        crc_bytes = data[pos + 8 + length : pos + 12 + length]
        if len(body) != length or len(crc_bytes) != 4:
            raise ArtworkError("IMAGE_INVALID", "The PNG file is truncated.")
        if zlib.crc32(ctype + body) != struct.unpack(">I", crc_bytes)[0]:
            raise ArtworkError("IMAGE_INVALID", "The PNG file is corrupted (checksum mismatch).")
        if not seen and ctype != b"IHDR":
            raise ArtworkError("IMAGE_INVALID", "The PNG header is missing.")
        if ctype == b"IHDR":
            width, height, depth, colour = struct.unpack(">IIBB", body[:10])
            if colour not in (0, 2, 3, 4, 6) or depth not in (1, 2, 4, 8, 16):
                raise ArtworkError("IMAGE_INVALID", "Unsupported PNG colour format.")
        seen.append(ctype)
        if ctype in KEEP_CHUNKS:
            out.append(data[pos : pos + 12 + length])
        else:
            stripped.add(ctype.decode("latin-1"))
        pos += 12 + length
        if ctype == b"IEND":
            break
    if b"IEND" not in seen or b"IDAT" not in seen:
        raise ArtworkError("IMAGE_INVALID", "The PNG file has no image data.")
    if min(width, height) < MIN_PNG_SIDE or max(width, height) > MAX_PNG_SIDE:
        raise ArtworkError(
            "IMAGE_DIMENSIONS",
            f"PNG images must be between {MIN_PNG_SIDE} and {MAX_PNG_SIDE} pixels on each side.",
        )
    warnings = []
    if stripped:
        warnings.append("Removed metadata: " + ", ".join(sorted(stripped)) + ".")
    if width != height:
        warnings.append("Badges display best as square images.")
    if min(width, height) < RECOMMENDED_MIN_SIDE:
        side = f"{RECOMMENDED_MIN_SIDE} x {RECOMMENDED_MIN_SIDE}"
        warnings.append(f"Use at least {side} pixels for sharp display.")
    return CleanImage(b"".join(out), "image/png", width, height, warnings)


def clean_image(data: bytes, media_type: str) -> CleanImage:
    if media_type == "image/svg+xml":
        return sanitise_svg(data)
    if media_type == "image/png":
        return clean_png(data)
    raise ArtworkError("IMAGE_TYPE", "Upload an SVG or PNG image.")


# ---- colour contrast (for template text) -----------------------------------------------------


def _luminance(hex_colour: str) -> float:
    rgb = [int(hex_colour[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast_ratio(a: str, b: str) -> float:
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)
