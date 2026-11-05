"""Outbound requests (PLAN §12.6): the guard, the pinned client, and the rule that only
core/http.py makes an HTTP client. Sockets are off: a fake resolver and MockTransport stand in."""

from __future__ import annotations

import ast
from collections.abc import Callable, Sequence
from pathlib import Path

import httpx
import pytest

import sunroom
from sunroom.core.http import GuardedHttp
from sunroom.core.netguard import NetGuard, OutboundError

DNS = {
    "calendar.example.com": ["93.184.216.34"],
    "elsewhere.example.org": ["93.184.216.36"],
    "router.lan": ["192.168.1.1"],
    "nas.lan": ["192.168.1.20"],
    "sneaky.example.com": ["93.184.216.35", "10.0.0.5"],  # one public, one private answer
    "cgnat.example.com": ["100.64.0.9"],
    "mapped.example.com": ["::ffff:127.0.0.1"],
}


async def fake_resolve(host: str, port: int) -> list[str]:
    if host not in DNS:
        raise OSError("not found")
    return DNS[host]


def guard(allowlist: Sequence[str] = (), *, everywhere: bool = False) -> NetGuard:
    async def entries() -> Sequence[str]:
        return allowlist

    return NetGuard(resolver=fake_resolve, allowlist=entries, allow_private_everywhere=everywhere)


async def test_public_addresses_pass() -> None:
    target = await guard().check("https://calendar.example.com/feed.ics")
    assert not target.private
    assert target.port == 443
    assert str(target.addresses[0]) == "93.184.216.34"


@pytest.mark.parametrize(
    "url",
    [
        "http://router.lan/admin",
        "http://127.0.0.1:7867/api/export",
        "http://[::1]/",
        "http://169.254.169.254/latest/meta-data",
        "https://sneaky.example.com/",
        "https://cgnat.example.com/",
        "https://mapped.example.com/",
        "http://0.0.0.0/",
    ],
)
async def test_private_addresses_are_refused_by_default(url: str) -> None:
    with pytest.raises(OutboundError) as caught:
        await guard().check(url, allow_private=True)
    assert caught.value.code == "private_address"


@pytest.mark.parametrize(
    ("url", "code"),
    [
        ("file:///etc/passwd", "bad_address"),
        ("ftp://calendar.example.com/x", "bad_address"),
        ("https://user:secret@calendar.example.com/x", "bad_address"),
        ("https:///nohost", "bad_address"),
        ("https://unknown.example.com/", "not_found"),
    ],
)
async def test_bad_addresses_say_why(url: str, code: str) -> None:
    with pytest.raises(OutboundError) as caught:
        await guard().check(url)
    assert caught.value.code == code


async def test_a_private_server_needs_both_the_opt_in_and_the_allowlist() -> None:
    allowed = guard(["nas.lan"])
    with pytest.raises(OutboundError):
        await allowed.check("http://nas.lan/photos")  # the account didn't opt in
    target = await allowed.check("http://nas.lan/photos", allow_private=True)
    assert target.private
    by_range = guard(["192.168.1.0/24"])
    assert (await by_range.check("http://nas.lan/", allow_private=True)).private
    with pytest.raises(OutboundError):
        await guard(["192.168.2.0/24"]).check("http://nas.lan/", allow_private=True)


async def test_the_environment_switch_skips_the_allowlist_but_not_the_opt_in() -> None:
    everywhere = guard(everywhere=True)
    assert (await everywhere.check("http://nas.lan/", allow_private=True)).private
    with pytest.raises(OutboundError):
        await everywhere.check("http://nas.lan/")


def recording(
    respond: Callable[[httpx.Request], httpx.Response],
) -> tuple[list[httpx.Request], Callable[[], httpx.AsyncBaseTransport]]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return respond(request)

    return seen, lambda: httpx.MockTransport(handler)


async def test_requests_are_pinned_to_the_checked_address() -> None:
    seen, transport = recording(lambda _r: httpx.Response(200, text="BEGIN:VCALENDAR"))
    http = GuardedHttp(guard(), transport_factory=transport)
    result = await http.get("https://calendar.example.com/feed.ics?x=1")
    assert result.ok and result.text() == "BEGIN:VCALENDAR"
    request = seen[0]
    assert request.url.host == "93.184.216.34"
    assert request.url.query == b"x=1"
    assert request.headers["host"] == "calendar.example.com"
    assert request.extensions["sni_hostname"] == "calendar.example.com"
    assert request.headers["user-agent"].startswith("Sunroom/")
    assert result.url == "https://calendar.example.com/feed.ics?x=1"


async def test_each_redirect_is_checked_again() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "http://router.lan/admin"})

    _seen, transport = recording(respond)
    http = GuardedHttp(guard(), transport_factory=transport)
    with pytest.raises(OutboundError) as caught:
        await http.get("https://calendar.example.com/feed.ics")
    assert caught.value.code == "private_address"


async def test_credentials_never_follow_a_redirect_to_another_server() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/start":
            return httpx.Response(301, headers={"location": "/moved"})
        if path == "/moved":
            return httpx.Response(302, headers={"location": "https://elsewhere.example.org/x"})
        return httpx.Response(200, text="ok")

    seen, transport = recording(respond)
    http = GuardedHttp(guard(), transport_factory=transport)
    secret = {"Authorization": "Basic c2FtcGxlOnNhbXBsZQ==", "Cookie": "a=b"}
    result = await http.get("https://calendar.example.com/start", headers=secret)
    assert result.ok
    assert [r.headers["host"] for r in seen] == [
        "calendar.example.com",
        "calendar.example.com",
        "elsewhere.example.org",
    ]
    # The same server keeps them; another server never sees them.
    assert "authorization" in seen[1].headers and "cookie" in seen[1].headers
    assert "authorization" not in seen[2].headers and "cookie" not in seen[2].headers


async def test_a_photo_library_s_api_key_never_follows_a_redirect_to_another_server() -> None:
    # Immich's X-Api-Key (ADR 0036): kept on the same server, dropped on the way to another.
    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/people":
            return httpx.Response(302, headers={"location": "/api/people/"})
        if request.url.path == "/api/people/":
            return httpx.Response(302, headers={"location": "https://elsewhere.example.org/x"})
        return httpx.Response(200, text="ok")

    seen, transport = recording(respond)
    http = GuardedHttp(guard(), transport_factory=transport)
    result = await http.get("https://calendar.example.com/api/people", headers={"X-Api-Key": "k"})
    assert result.ok
    assert [r.headers.get("x-api-key") for r in seen] == ["k", "k", None]


async def test_redirect_loops_stop() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(301, headers={"location": "/again"})

    seen, transport = recording(respond)
    http = GuardedHttp(guard(), transport_factory=transport)
    with pytest.raises(OutboundError) as caught:
        await http.get("https://calendar.example.com/start")
    assert caught.value.code == "too_many_redirects"
    assert len(seen) == 4  # the first request and three redirects


async def test_bodies_over_the_cap_are_refused_not_cut() -> None:
    _seen, transport = recording(lambda _r: httpx.Response(200, content=b"x" * 2048))
    http = GuardedHttp(guard(), transport_factory=transport)
    with pytest.raises(OutboundError) as caught:
        await http.get("https://calendar.example.com/big", max_bytes=1024)
    assert caught.value.code == "too_large"


async def test_unreachable_servers_say_so() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    _seen, transport = recording(respond)
    http = GuardedHttp(guard(), transport_factory=transport)
    with pytest.raises(OutboundError) as caught:
        await http.get("https://calendar.example.com/")
    assert caught.value.code == "unreachable"


def test_only_core_http_makes_an_http_client() -> None:
    """PLAN §12.6: every outbound request goes through the guard."""
    root = Path(sunroom.__file__).parent
    offenders: list[str] = []
    for path in root.rglob("*.py"):
        if path.relative_to(root).as_posix() == "core/http.py":
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Call):
                name = ast.unparse(node.func)
                if name.endswith(("AsyncClient", "httpx.Client")) or name in {
                    "httpx.get",
                    "httpx.post",
                    "httpx.request",
                    "urllib.request.urlopen",
                }:
                    offenders.append(f"{path.relative_to(root)}: {name}")
    # The healthcheck probes this server itself (localhost), with the standard library.
    assert offenders == ["healthcheck.py: urllib.request.urlopen"]
