# SPDX-License-Identifier: AGPL-3.0-or-later
"""Where verification gets DID documents and status lists from.

Remote material is fetched over HTTPS with short timeouts and a size cap. Material this
deployment publishes itself is read straight from the database, so the api never calls itself
(and tests need no web server). Every failure is reported as *unavailable*, which the service
turns into "Unable to verify", never into "Invalid" or "Revoked" (spec §16.2).
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime
from typing import Any, Protocol
from urllib.parse import unquote, urlsplit

import httpx
from sqlalchemy import select, text

from opencredential.db.models import Issuer, IssuerKey, StatusList
from opencredential.db.session import tenant_session
from opencredential.institutions.identity import (
    IdentityError,
    did_document,
    did_web_document_url,
)

MAX_BYTES = 2 * 1024 * 1024
TIMEOUT = httpx.Timeout(5.0)
STATUS_PATH = re.compile(r"^/status/([a-z0-9-]+)/([0-9a-f-]{36})$")


class Unavailable(RuntimeError):
    """Required infrastructure or information could not be reached."""


class Sources(Protocol):
    def did_document(self, did: str) -> dict[str, Any]: ...
    def status_list(self, url: str) -> dict[str, Any]: ...
    def known_issuer(self, did: str) -> dict[str, Any] | None: ...


def _institution_for(fn: str, value: str) -> uuid.UUID | None:
    with tenant_session(None) as db:
        iid = db.execute(text(f"select app.{fn}(:v)"), {"v": value}).scalar()
    return uuid.UUID(str(iid)) if iid else None


def local_did_document(did: str) -> dict[str, Any] | None:
    iid = _institution_for("institution_for_issuer_did", did)
    if iid is None:
        return None
    with tenant_session(iid) as db:
        issuer = db.scalar(select(Issuer).where(Issuer.did == did))
        if issuer is None or not did.startswith("did:web:"):
            return None
        keys = list(db.scalars(select(IssuerKey).where(IssuerKey.issuer_id == issuer.id)))
        return did_document(issuer, keys)


def local_status_list(list_id: uuid.UUID, slug: str) -> dict[str, Any] | None:
    """The published list credential, or ``None`` if unknown. Raises ``Unavailable`` if stale."""
    iid = _institution_for("institution_for_status_list", str(list_id))
    if iid is None:
        return None
    with tenant_session(iid) as db:
        sl = db.get(StatusList, list_id)
        issuer = db.get(Issuer, sl.issuer_id) if sl else None
        if sl is None or issuer is None or issuer.slug != slug:
            return None
        if sl.published_credential is None:
            raise Unavailable("the status list has not been published yet")
        if sl.published_valid_until and sl.published_valid_until <= datetime.now(UTC):
            raise Unavailable("the published status list has expired and is being renewed")
        return dict(sl.published_credential)


def known_issuer_local(did: str) -> dict[str, Any] | None:
    iid = _institution_for("institution_for_issuer_did", did)
    if iid is None:
        return None
    with tenant_session(iid) as db:
        issuer = db.scalar(select(Issuer).where(Issuer.did == did))
        if issuer is None:
            return None
        return {
            "id": issuer.did,
            "name": issuer.name,
            "status": issuer.status,
            "approved": issuer.approved_by is not None,
        }


class DefaultSources:
    """Local database for our own origins, HTTPS for everything else."""

    def __init__(self, own_origins: set[str], *, client: httpx.Client | None = None):
        self.own_origins = own_origins
        self._client = client or httpx.Client(timeout=TIMEOUT, follow_redirects=True)

    def _get_json(self, url: str) -> dict[str, Any]:
        if urlsplit(url).scheme != "https":
            raise Unavailable(f"refusing to fetch non-HTTPS URL {url}")
        try:
            with self._client.stream("GET", url, headers={"accept": "application/json"}) as r:
                if r.status_code != 200:
                    raise Unavailable(f"{url} answered HTTP {r.status_code}")
                body = b""
                for chunk in r.iter_bytes():
                    body += chunk
                    if len(body) > MAX_BYTES:
                        raise Unavailable(f"{url} is larger than {MAX_BYTES} bytes")
        except httpx.HTTPError as exc:
            raise Unavailable(f"could not fetch {url}: {type(exc).__name__}") from exc
        try:
            doc = json.loads(body)
        except ValueError as exc:
            raise Unavailable(f"{url} did not return JSON") from exc
        if not isinstance(doc, dict):
            raise Unavailable(f"{url} did not return a JSON object")
        return doc

    def did_document(self, did: str) -> dict[str, Any]:
        local = local_did_document(did)
        if local is not None:
            return local
        try:
            url = did_web_document_url(did)
        except IdentityError as exc:
            raise Unavailable(str(exc)) from exc
        host = urlsplit(url).netloc
        if host in self.own_origins:
            raise Unavailable(f"{did} is not an issuer of this service")
        return self._get_json(url)

    def status_list(self, url: str) -> dict[str, Any]:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        m = STATUS_PATH.match(parts.path)
        if (origin in self.own_origins or parts.netloc in self.own_origins) and m:
            doc = local_status_list(uuid.UUID(m.group(2)), unquote(m.group(1)))
            if doc is None:
                raise Unavailable("status list not found on this service")
            return doc
        return self._get_json(url)

    def known_issuer(self, did: str) -> dict[str, Any] | None:
        return known_issuer_local(did)


def own_origins(public_base_url: str) -> set[str]:
    """Origins (and bare hosts) whose material is read locally instead of fetched."""
    from opencredential.db.models import Institution

    parts = urlsplit(public_base_url)
    origins = {f"{parts.scheme}://{parts.netloc}", parts.netloc}
    with tenant_session(None) as db:
        for host in db.scalars(
            select(Institution.verification_host).where(Institution.verification_host.is_not(None))
        ):
            origins |= {f"https://{host}", str(host)}
    return origins
