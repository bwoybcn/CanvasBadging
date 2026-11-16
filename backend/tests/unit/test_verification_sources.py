# SPDX-License-Identifier: AGPL-3.0-or-later
"""Review finding S2: the public verifier fetches URLs taken from submitted credentials, so it
must never reach internal addresses, directly or through a redirect."""

from __future__ import annotations

import httpcore
import httpx
import pytest

from opencredential.verification.sources import (
    DefaultSources,
    PublicOnlyBackend,
    Unavailable,
    _public_address,
)


@pytest.mark.parametrize(
    "addr",
    [
        "127.0.0.1",
        "10.0.0.5",
        "172.16.3.4",
        "192.168.1.1",
        "169.254.169.254",
        "100.64.0.1",
        "0.0.0.0",  # noqa: S104 - an address under test, not a bind
        "::1",
        "fe80::1",
        "fd00::1",
        "::ffff:127.0.0.1",
        "::ffff:169.254.169.254",
        "224.0.0.1",
    ],
)
def test_non_public_addresses_are_refused(addr: str) -> None:
    assert not _public_address(addr)


@pytest.mark.parametrize("addr", ["93.184.215.14", "2606:4700:4700::1111", "8.8.8.8"])
def test_public_addresses_are_allowed(addr: str) -> None:
    assert _public_address(addr)


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "169.254.169.254", "10.1.2.3"])
def test_backend_will_not_connect_to_internal_hosts(host: str) -> None:
    with pytest.raises(httpcore.ConnectError, match="non-public"):
        PublicOnlyBackend().connect_tcp(host, 443, timeout=1)


def test_default_client_refuses_internal_target_without_leaking_detail() -> None:
    src = DefaultSources(set())
    with pytest.raises(Unavailable) as err:
        src._get_json("https://127.0.0.1:8790/v1/keys")
    assert str(err.value) == "could not fetch https://127.0.0.1:8790/v1/keys"


def _sources(handler) -> DefaultSources:  # type: ignore[no-untyped-def]
    return DefaultSources(set(), client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_redirect_to_plain_http_is_refused() -> None:
    seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(str(req.url))
        return httpx.Response(302, headers={"location": "http://169.254.169.254/latest/meta-data"})

    with pytest.raises(Unavailable, match="non-HTTPS"):
        _sources(handler)._get_json("https://attacker.example/list")
    assert seen == ["https://attacker.example/list"]


def test_https_redirects_are_followed_a_few_times_only() -> None:
    def ok(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/start":
            return httpx.Response(301, headers={"location": "/final"})
        return httpx.Response(200, json={"id": "x"})

    assert _sources(ok)._get_json("https://issuer.example/start") == {"id": "x"}

    def loop(req: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "/again"})

    with pytest.raises(Unavailable, match="too many"):
        _sources(loop)._get_json("https://issuer.example/start")


def test_the_real_client_never_connects_to_a_local_server() -> None:
    """The address check is fitted into httpx through a private attribute, so prove it on the
    client the verifier really uses: a server on this machine must never see a connection."""
    import socket
    import threading

    from opencredential.verification.sources import public_client

    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    server.settimeout(1.5)
    port = server.getsockname()[1]
    connections: list[object] = []

    def accept() -> None:
        try:
            conn, _ = server.accept()
        except OSError:
            return
        connections.append(conn)
        conn.close()

    listener = threading.Thread(target=accept)
    listener.start()
    try:
        with public_client() as client, pytest.raises(httpx.ConnectError, match="non-public"):
            client.get(f"http://127.0.0.1:{port}/status-list")
        with pytest.raises(Unavailable):
            DefaultSources(set())._get_json(f"https://127.0.0.1:{port}/status-list")
    finally:
        listener.join()
        server.close()
    assert connections == []
