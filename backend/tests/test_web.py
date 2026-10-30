"""Security headers, the Host rule, forwarded headers and serving the built SPA (PLAN §5.1,
§12.5, §13.4; ADR 0007, ADR 0017)."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from sunroom.app import create_app
from sunroom.core.clock import FakeClock
from sunroom.web.forwarded import ForwardedHeaders
from sunroom.web.headers import DEFAULT_CSP
from sunroom.web.hosts import HostRule, host_name
from sunroom.web.spa import packaged_static
from tests.support import BASE_URL, make_settings, run_setup

INDEX = '<!doctype html><meta name="csp-nonce" content="__SUNROOM_CSP_NONCE__"><div id=root></div>'


@pytest.fixture
def static_dir(tmp_path: Path) -> Path:
    root = tmp_path / "static"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text(INDEX)
    (root / "assets" / "app-abc123.js").write_text("console.log('hi')")
    (root / "sw.js").write_text("self.addEventListener('install', () => {})")
    (root / "manifest.webmanifest").write_text('{"name": "Sunroom"}')
    return root


@pytest.fixture
async def spa_client(data_dir: Path, static_dir: Path) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(make_settings(data_dir, sunroom_static_dir=str(static_dir)))
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as client:
            yield client


async def test_security_headers_on_api_responses(
    client: httpx.AsyncClient, clock: FakeClock
) -> None:
    response = await client.get("/api/version")
    assert response.headers["content-security-policy"] == DEFAULT_CSP
    assert "style-src 'self';" in DEFAULT_CSP
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "same-origin"
    assert response.headers["cross-origin-opener-policy"] == "same-origin"
    assert "screen-wake-lock=(self)" in response.headers["permissions-policy"]
    assert response.headers["cache-control"] == "no-store"
    # The server's time is the app's clock (the display shows it; tests move it).
    assert int(response.headers["x-server-time-ms"]) == int(clock.now().timestamp() * 1000)
    assert "strict-transport-security" not in response.headers


async def test_every_page_load_gets_a_fresh_style_nonce(spa_client: httpx.AsyncClient) -> None:
    nonces: list[str] = []
    for path in ("/", "/display", "/settings/family", "/index.html"):
        response = await spa_client.get(path)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-cache"
        meta = re.search(r'name="csp-nonce" content="([^"]+)"', response.text)
        assert meta, response.text
        nonce = meta.group(1)
        assert f"style-src 'self' 'nonce-{nonce}';" in response.headers["content-security-policy"]
        assert "__SUNROOM_CSP_NONCE__" not in response.text
        nonces.append(nonce)
    assert len(set(nonces)) == len(nonces)


async def test_a_wall_run_by_sunroom_screen_may_reach_its_agent(
    spa_client: httpx.AsyncClient,
) -> None:
    """ADR 0035: only a /display document that names the agent's port widens connect-src."""
    widened = await spa_client.get("/display?dimmer=screen&screen=7800")
    policy = widened.headers["content-security-policy"]
    assert "connect-src 'self' http://127.0.0.1:7800;" in policy
    assert "style-src 'self' 'nonce-" in policy  # the rest as ever
    for plain in (
        "/display",
        "/",
        "/display?screen=80",
        "/display?screen=abc",
        "/display?screen=7800&screen=7801",
        "/display?screen=70000",
        "/?screen=7800",
        "/settings/family?screen=7800",
        "/display/extra?screen=7800",
    ):
        response = await spa_client.get(plain)
        assert "connect-src 'self';" in response.headers["content-security-policy"], plain
    api = await spa_client.get("/api/version?screen=7800")
    assert api.headers["content-security-policy"] == DEFAULT_CSP


def test_a_program_brings_its_own_app_and_a_checkout_has_none(tmp_path: Path) -> None:
    # The wheel's copy (ADR 0038): sunroom/static beside the package's modules.
    package = tmp_path / "sunroom"
    (package / "static").mkdir(parents=True)
    assert packaged_static(package) is None
    (package / "static" / "index.html").write_text(INDEX)
    assert packaged_static(package) == package / "static"
    # This checkout's package has none: `just server-build` puts it only in the wheel it builds.
    assert packaged_static() is None


async def test_unknown_api_paths_are_json_404s(spa_client: httpx.AsyncClient) -> None:
    response = await spa_client.get("/api/nope")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_hashed_assets_are_immutable_and_missing_ones_404(
    spa_client: httpx.AsyncClient,
) -> None:
    response = await spa_client.get("/assets/app-abc123.js")
    assert response.headers["cache-control"] == "public, max-age=31536000, immutable"
    missing = await spa_client.get("/assets/gone-123.js")
    assert missing.status_code == 404
    assert "id=root" not in missing.text


async def test_top_level_files_are_served_without_caching(spa_client: httpx.AsyncClient) -> None:
    worker = await spa_client.get("/sw.js")
    assert worker.headers["cache-control"] == "no-cache"
    manifest = await spa_client.get("/manifest.webmanifest")
    assert manifest.headers["content-type"].startswith("application/manifest+json")


async def test_path_traversal_falls_back_to_index(spa_client: httpx.AsyncClient) -> None:
    response = await spa_client.get("/..%2F..%2Fetc%2Fpasswd")
    assert response.status_code in {200, 404}
    assert "root:" not in response.text


async def test_the_photos_room_is_the_app_and_only_the_files_under_it_are_reserved(
    spa_client: httpx.AsyncClient,
) -> None:
    # The wall's code opens /photos on a phone that may never have loaded the app.
    room = await spa_client.get("/photos")
    assert room.status_code == 200
    assert "id=root" in room.text
    missing = await spa_client.get("/photos/nope")
    assert missing.status_code == 404
    assert "id=root" not in missing.text


async def test_photos_need_a_session(spa_client: httpx.AsyncClient) -> None:
    path = "/photos/avatars/01890000-0000-7000-8000-000000000000.webp"
    assert (await spa_client.get(path)).status_code == 401
    await run_setup(spa_client)
    assert (await spa_client.get(path)).status_code == 404
    sneaky = await spa_client.get("/photos/avatars/..%2F..%2Fsunroom.db")
    assert sneaky.status_code == 404
    assert b"SQLite" not in sneaky.content


# ---- the Host rule (ADR 0017) ----------------------------------------------------------------


@pytest.mark.parametrize(
    "host",
    [
        "localhost",
        "localhost:8080",
        "127.0.0.1:8080",
        "192.168.1.20:8080",
        "[::1]:8080",
        "sunroom",
        "sunroom.local",
        "kitchen.lan",
        "nas.home.arpa",
        "sunroom.tail1234.ts.net",
        "calendar.example.com",
        "ha.example.org",
    ],
)
def test_lan_names_and_listed_names_pass(host: str) -> None:
    rule = HostRule(("calendar.example.com", "*.example.org"), container_hostname="abc123")
    assert rule.allows(host_name(host))


@pytest.mark.parametrize("host", ["evil.example", "example.org", "sunroom.local.evil.example", ""])
def test_other_names_dont(host: str) -> None:
    rule = HostRule(("calendar.example.com", "*.example.org"), container_hostname="abc123")
    assert not rule.allows(host_name(host))


async def test_a_foreign_host_gets_421_with_the_fix_once_the_lock_is_set(data_dir: Path) -> None:
    """APP_ALLOWED_HOSTS set: the strict Host rule, as before 0.12.0 (ADR 0034)."""
    locked = create_app(make_settings(data_dir, app_allowed_hosts="calendar.example.com"))
    async with locked.router.lifespan_context(locked):
        transport = httpx.ASGITransport(app=locked)
        async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as client:
            api = await client.get("/api/version", headers={"host": "evil.example"})
            assert api.status_code == 421
            assert api.json()["error"]["code"] == "unknown_host"
            assert "APP_ALLOWED_HOSTS" in api.json()["error"]["message"]
            assert (api.json()["error"]["key"], api.json()["error"]["params"]) == (
                "api.host.unknown",
                {"host": "evil.example"},
            )
            page = await client.get("/", headers={"host": "evil.example"})
            assert page.status_code == 421
            assert page.headers["content-type"].startswith("text/plain")
            setup = await client.post(
                "/api/setup",
                json={"password": "x" * 20, "household_name": "x", "timezone": "UTC"},
                headers={"host": "evil.example", "x-sunroom": "1"},
            )
            assert setup.status_code == 421  # DNS rebinding can't claim an unconfigured server
            allowed = await client.get("/api/version", headers={"host": "calendar.example.com"})
            assert allowed.status_code == 200


def test_any_name_passes_without_a_list() -> None:
    rule = HostRule((), container_hostname="abc123")
    for name in ("evil.example", "calendar.example.com", "sunroom.local", "192.168.1.20", ""):
        assert rule.allows(name), name


async def test_any_host_is_answered_by_default(parent: httpx.AsyncClient) -> None:
    """ADR 0034: http://<the server>:8080 works with nothing set, through any proxy."""
    found = await parent.get("/api/version", headers={"host": "evil.example"})
    assert found.status_code == 200
    diagnostics = (await parent.get("/api/admin/diagnostics")).json()
    assert "evil.example" in diagnostics["recent_addresses"]


async def test_addresses_this_server_was_reached_at_are_remembered(
    parent: httpx.AsyncClient,
) -> None:
    await parent.get("/api/version", headers={"host": "sunroom.local:8080"})
    await parent.get("/api/version", headers={"host": "127.0.0.1:8080"})
    diagnostics = (await parent.get("/api/admin/diagnostics")).json()
    # Loopback names (this request's localhost too) only work on the server itself.
    assert diagnostics["recent_addresses"] == ["sunroom.local:8080"]


# ---- forwarded headers (PLAN §13.4) --------------------------------------------------------


async def _through(
    peer: str, headers: list[tuple[bytes, bytes]], kind: str = "http"
) -> dict[str, Any]:
    """What an app behind ForwardedHeaders sees for one connection."""
    seen: dict[str, Any] = {}

    async def app(scope: Any, receive: Any, send: Any) -> None:
        seen["scheme"] = scope["scheme"]
        seen["client"] = scope["client"][0]
        seen["host"] = dict(scope["headers"]).get(b"host", b"").decode()

    async def receive() -> dict[str, Any]:
        return {"type": "http.request"}

    async def send(_message: Any) -> None:
        return None

    scope = {
        "type": kind,
        "scheme": "http" if kind == "http" else "ws",
        "client": (peer, 4000),
        "headers": [(b"host", b"sunroom:8080"), *headers],
    }
    await ForwardedHeaders(app)(scope, receive, send)
    return seen


PROXY = [
    (b"x-forwarded-proto", b"https"),
    (b"x-forwarded-for", b"198.51.100.7"),
    (b"x-forwarded-host", b"calendar.example.com"),
]


@pytest.mark.parametrize(
    "peer", ["127.0.0.1", "192.168.1.20", "172.18.0.1", "100.64.0.5", "fe80::1", "::ffff:10.0.0.9"]
)
async def test_a_proxy_on_the_home_network_is_believed(peer: str) -> None:
    """ADR 0034: no proxy setting; loopback, private, link-local and Tailscale peers."""
    assert await _through(peer, PROXY) == {
        "scheme": "https",
        "client": "198.51.100.7",
        "host": "calendar.example.com",
    }


async def test_a_connection_from_the_internet_is_never_believed() -> None:
    assert await _through("203.0.113.9", PROXY) == {
        "scheme": "http",
        "client": "203.0.113.9",
        "host": "sunroom:8080",
    }


async def test_the_browser_is_the_right_most_hop_outside_home() -> None:
    hops = [(b"x-forwarded-for", b"198.51.100.7, 10.0.0.2")]
    assert (await _through("172.18.0.1", hops))["client"] == "198.51.100.7"
    # Every hop at home (a phone on Tailscale through a proxy): the left-most.
    tailnet = [(b"x-forwarded-for", b"100.101.102.103")]
    assert (await _through("172.18.0.1", tailnet))["client"] == "100.101.102.103"
    # Not an address: the connection's own stays.
    garbage = [(b"x-forwarded-for", b"not-an-address")]
    assert (await _through("172.18.0.1", garbage))["client"] == "172.18.0.1"
    # A websocket through the proxy is wss.
    assert (await _through("127.0.0.1", PROXY, kind="websocket"))["scheme"] == "wss"


async def test_a_proxy_at_home_sets_scheme_and_host(data_dir: Path) -> None:
    app = create_app(make_settings(data_dir, app_allowed_hosts="calendar.example.com"))
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 4000))
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://sunroom:8080",
            headers={
                "x-forwarded-proto": "https",
                "x-forwarded-for": "198.51.100.7",
                "x-forwarded-host": "calendar.example.com",
            },
        ) as client:
            setup = await run_setup(client)
            cookie = setup.headers["set-cookie"].split(";")[0]
            assert cookie.startswith("__Host-sunroom=")
            # httpx won't send a Secure cookie over the test transport's plain HTTP: by hand.
            client.cookies.clear()
            body = (await client.get("/api/admin/diagnostics", headers={"cookie": cookie})).json()
    assert body["client"] == {"scheme": "https", "host": "calendar.example.com"}


async def test_the_same_headers_from_the_internet_change_nothing(data_dir: Path) -> None:
    app = create_app(make_settings(data_dir))
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app, client=("203.0.113.9", 4000))
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://sunroom:8080",
            headers={
                "x-forwarded-proto": "https",
                "x-forwarded-for": "198.51.100.7",
                "x-forwarded-host": "calendar.example.com",
            },
        ) as client:
            setup = await run_setup(client)
            assert setup.headers["set-cookie"].startswith("sunroom=")
            body = (await client.get("/api/admin/diagnostics")).json()
    assert body["client"] == {"scheme": "http", "host": "sunroom:8080"}
