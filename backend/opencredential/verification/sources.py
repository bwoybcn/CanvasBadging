# SPDX-License-Identifier: AGPL-3.0-or-later
"""Where verification gets DID documents and status lists from.

Remote material is fetched over HTTPS with short timeouts and a size cap, only from public
internet addresses (checked on every connection, redirects included), because the URLs come from
credentials anyone can submit to the public verifier. Material this
deployment publishes itself is read straight from the database, so the api never calls itself
(and tests need no web server). Every failure is reported as *unavailable*, which the service
turns into "Unable to verify", never into "Invalid" or "Revoked" (spec §16.2).
"""

from __future__ import annotations

import ipaddress
import json
import re
import socket
import uuid
from datetime import UTC, datetime
from typing import Any, Protocol
from urllib.parse import unquote, urlsplit

import httpcore
import httpx
from sqlalchemy import select, text

from opencredential.db.models import Institution, Issuer, IssuerKey, StatusList
from opencredential.db.session import tenant_session
from opencredential.institutions.identity import (
    IdentityError,
    did_document,
    did_web_document_url,
)

MAX_BYTES = 2 * 1024 * 1024
MAX_REDIRECTS = 3
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


def _did_web_host(did: str) -> str | None:
    if not did.startswith("did:web:"):
        return None
    return unquote(did[len("did:web:") :].split("#")[0].split(":")[0]).lower()


def _host_belongs_to(db: Any, iid: uuid.UUID, did: str) -> bool:
    """A did:web issuer is only answered locally under its own institution's host (S3).

    Otherwise an institution could create an issuer under a host it does not own and have this
    service vouch for it. did:key issuers carry no host and are unaffected.
    """
    host = _did_web_host(did)
    if host is None:
        return True
    inst = db.get(Institution, iid)
    return inst is not None and (inst.verification_host or "").lower() == host


def local_did_document(did: str) -> dict[str, Any] | None:
    iid = _institution_for("institution_for_issuer_did", did)
    if iid is None:
        return None
    with tenant_session(iid) as db:
        issuer = db.scalar(select(Issuer).where(Issuer.did == did))
        if issuer is None or not did.startswith("did:web:"):
            return None
        if not _host_belongs_to(db, iid, did):
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
        if issuer is None or not _host_belongs_to(db, iid, did):
            return None
        return {
            "id": issuer.did,
            "name": issuer.name,
            "status": issuer.status,
            "approved": issuer.approved_by is not None,
        }


def _public_address(addr: str) -> bool:
    ip = ipaddress.ip_address(addr.split("%", 1)[0])
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


class PublicOnlyBackend(httpcore.SyncBackend):
    """Connects only to public internet addresses (no loopback, private, link-local, metadata).

    The host is resolved here and the connection made to the address that was checked, so DNS
    cannot answer differently between the check and the connection. TLS still verifies the
    certificate against the original host name.
    """

    def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Any = None,
    ) -> httpcore.NetworkStream:
        try:
            infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except OSError as exc:
            raise httpcore.ConnectError(f"cannot resolve {host}") from exc
        addresses = [str(info[4][0]) for info in infos]
        if not addresses or not all(_public_address(a) for a in addresses):
            raise httpcore.ConnectError("refusing to connect to a non-public address")
        return super().connect_tcp(
            addresses[0],
            port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )


def public_client() -> httpx.Client:
    """An HTTP client that can only reach public addresses and never follows redirects itself.

    Environment proxy settings are ignored: a proxy would make the address check meaningless.
    """
    transport = httpx.HTTPTransport(trust_env=False)
    # httpx has no option for the network backend, so replace the pool it built.
    transport._pool = httpcore.ConnectionPool(
        ssl_context=httpx.create_ssl_context(trust_env=False),
        network_backend=PublicOnlyBackend(),
    )
    return httpx.Client(
        timeout=TIMEOUT, follow_redirects=False, trust_env=False, transport=transport
    )


class DefaultSources:
    """Local database for our own origins, HTTPS for everything else."""

    def __init__(self, own_origins: set[str], *, client: httpx.Client | None = None):
        self.own_origins = own_origins
        self._client = client or public_client()

    def _get_json(self, url: str) -> dict[str, Any]:
        first = url
        try:
            for _ in range(MAX_REDIRECTS + 1):
                # Checked on every hop: a redirect must not downgrade to plain HTTP.
                if urlsplit(url).scheme != "https":
                    raise Unavailable(f"refusing to fetch non-HTTPS URL {url}")
                with self._client.stream("GET", url, headers={"accept": "application/json"}) as r:
                    if r.is_redirect and "location" in r.headers:
                        url = str(r.url.join(r.headers["location"]))
                        continue
                    if r.status_code != 200:
                        raise Unavailable(f"{first} answered HTTP {r.status_code}")
                    body = b""
                    for chunk in r.iter_bytes():
                        body += chunk
                        if len(body) > MAX_BYTES:
                            raise Unavailable(f"{first} is larger than {MAX_BYTES} bytes")
                    break
            else:
                raise Unavailable(f"{first} redirected too many times")
        except httpx.HTTPError as exc:
            # No exception detail: it would tell a caller which internal ports exist.
            raise Unavailable(f"could not fetch {first}") from exc
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
