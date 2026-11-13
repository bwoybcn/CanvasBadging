# SPDX-License-Identifier: AGPL-3.0-or-later
"""``/api/v1/assets`` and ``/api/v1/artwork-templates``: badge artwork (spec §5.3).

Uploads are JSON with base64 content (≤ 1 MB images), which avoids a multipart parser
dependency; the server validates and sanitises before storing anything.
"""

from __future__ import annotations

import base64
import binascii
import uuid
from typing import Literal

from fastapi import APIRouter
from fastapi.responses import Response
from pydantic import BaseModel, Field

from opencredential.api.deps import ActorDep, TenantDb
from opencredential.authoring import assets, templates
from opencredential.authoring.artwork import MAX_ALT_TEXT, MAX_PNG_BYTES
from opencredential.authoring.preview import asset_data_url
from opencredential.db.models import BadgeAsset
from opencredential.errors import Invalid, NotFound
from opencredential.storage import get_store

router = APIRouter(prefix="/api/v1", tags=["artwork"])


class UploadIn(BaseModel):
    media_type: Literal["image/svg+xml", "image/png"]
    data_base64: str = Field(max_length=(MAX_PNG_BYTES * 4) // 3 + 8)
    alt_text: str = Field(max_length=MAX_ALT_TEXT)
    licence: str | None = Field(default=None, max_length=120)


class TemplateIn(BaseModel):
    template: str
    primary_colour: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")
    secondary_colour: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")
    label: str = Field(max_length=templates.MAX_LABEL)
    alt_text: str = Field(max_length=MAX_ALT_TEXT)


class AssetOut(BaseModel):
    id: uuid.UUID
    kind: str
    media_type: str
    width: int | None
    height: int | None
    bytes: int
    sha256: str
    alt_text: str
    licence: str | None
    data_url: str | None
    warnings: list[str] = []


def _out(a: BadgeAsset, warnings: list[str] | None = None) -> AssetOut:
    return AssetOut(
        id=a.id,
        kind=a.kind,
        media_type=a.media_type,
        width=a.width,
        height=a.height,
        bytes=a.bytes,
        sha256=a.sha256,
        alt_text=a.alt_text,
        licence=a.licence,
        data_url=asset_data_url(a),
        warnings=warnings or [],
    )


@router.get("/artwork-templates")
def list_templates() -> list[dict[str, str]]:
    return [
        {"key": t.key, "name": t.name, "description": t.description, "licence": templates.LICENCE}
        for t in templates.TEMPLATES.values()
    ]


@router.post("/assets", response_model=AssetOut, status_code=201)
def upload_asset(body: UploadIn, db: TenantDb, actor: ActorDep) -> AssetOut:
    try:
        data = base64.b64decode(body.data_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise Invalid("IMAGE_INVALID", "The file content is not valid base64.") from exc
    asset, warnings = assets.upload(
        db,
        actor,
        data=data,
        media_type=body.media_type,
        alt_text=body.alt_text,
        licence=body.licence,
    )
    return _out(asset, warnings)


@router.post("/assets/from-template", response_model=AssetOut, status_code=201)
def asset_from_template(body: TemplateIn, db: TenantDb, actor: ActorDep) -> AssetOut:
    asset, warnings = assets.from_template(
        db,
        actor,
        template=body.template,
        primary=body.primary_colour,
        secondary=body.secondary_colour,
        label=body.label,
        alt_text=body.alt_text,
    )
    return _out(asset, warnings)


@router.get("/assets/{asset_id}", response_model=AssetOut)
def get_asset(asset_id: uuid.UUID, db: TenantDb, actor: ActorDep) -> AssetOut:
    asset = db.get(BadgeAsset, asset_id)
    if asset is None:
        raise NotFound("NOT_FOUND", "No such image.")
    return _out(asset)


@router.get("/assets/{asset_id}/content", response_class=Response)
def asset_content(asset_id: uuid.UUID, db: TenantDb, actor: ActorDep) -> Response:
    asset = db.get(BadgeAsset, asset_id)
    if asset is None:
        raise NotFound("NOT_FOUND", "No such image.")
    return Response(
        get_store().get(asset.storage_key),
        media_type=asset.media_type,
        headers={
            # Sanitised already; belt and braces against script execution if opened directly.
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; sandbox",
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, max-age=3600, immutable",
        },
    )
