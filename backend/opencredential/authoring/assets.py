# SPDX-License-Identifier: AGPL-3.0-or-later
"""Badge artwork records: validated, sanitised, stored content-addressed (spec §5.3)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from opencredential import audit
from opencredential.authoring import templates
from opencredential.authoring.artwork import ArtworkError, CleanImage, check_alt_text, clean_image
from opencredential.authz import policy as authz
from opencredential.authz import roles
from opencredential.db.models import BadgeAsset
from opencredential.errors import Forbidden, Invalid
from opencredential.storage import get_store


def _require_staff(actor: authz.Actor) -> None:
    if not roles.is_staff({r for r, _, _ in actor.memberships}):
        raise Forbidden("FORBIDDEN", "Only staff can add badge artwork.")


def _store(
    db: Session,
    actor: authz.Actor,
    image: CleanImage,
    *,
    kind: str,
    alt_text: str,
    licence: str | None,
) -> tuple[BadgeAsset, list[str]]:
    key, sha = get_store().put(image.data, image.media_type)
    asset = BadgeAsset(
        institution_id=actor.institution_id,
        kind=kind,
        media_type=image.media_type,
        storage_key=key,
        sha256=sha,
        width=image.width,
        height=image.height,
        bytes=len(image.data),
        alt_text=alt_text,
        licence=licence,
        sanitised=True,
    )
    db.add(asset)
    db.flush()
    audit.record(
        db,
        action="asset.create",
        resource_type="badge_asset",
        resource_id=asset.id,
        institution_id=actor.institution_id,
        actor_user_id=actor.user_id,
        data={"kind": kind, "media_type": image.media_type, "sha256": sha},
    )
    return asset, image.warnings


def upload(
    db: Session,
    actor: authz.Actor,
    *,
    data: bytes,
    media_type: str,
    alt_text: str,
    licence: str | None = None,
) -> tuple[BadgeAsset, list[str]]:
    _require_staff(actor)
    try:
        alt = check_alt_text(alt_text)
        image = clean_image(data, media_type)
    except ArtworkError as exc:
        raise Invalid(exc.code, str(exc)) from exc
    return _store(db, actor, image, kind="upload", alt_text=alt, licence=licence)


def from_template(
    db: Session,
    actor: authz.Actor,
    *,
    template: str,
    primary: str,
    secondary: str,
    label: str,
    alt_text: str,
) -> tuple[BadgeAsset, list[str]]:
    _require_staff(actor)
    try:
        alt = check_alt_text(alt_text)
        image = templates.render(template, primary=primary, secondary=secondary, label=label)
    except ArtworkError as exc:
        raise Invalid(exc.code, str(exc)) from exc
    return _store(db, actor, image, kind="template", alt_text=alt, licence=templates.LICENCE)
