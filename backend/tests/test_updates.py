"""The daily update check (PLAN §13.6, ADR 0046, core/updates.py, meta/updates.py): on by default
for a household that's set up, once a day, with a plain line about how to update this server, and
a switch to turn it off. A stand-in GitHub answers through MockTransport; no socket is opened."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from sunroom.app import create_app
from sunroom.core.clock import FakeClock
from sunroom.core.config import InstallKind
from sunroom.core.lang import t_en
from sunroom.core.updates import HOW_KEYS, made_up, newer, parse
from sunroom.core.version import build_info
from sunroom.meta import updates
from tests.support import BASE_URL, CSRF, make_settings, run_setup, state_of

PUBLIC = "140.82.112.6"  # a made-up public address for api.github.com in these tests


class FakeGitHub:
    """GitHub, and sunroom.day beside it, which by default hasn't written its file yet."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.release = "v99.0.0"  # the latest Release's tag
        self.body: object | None = None  # an answer of another shape
        self.status = 200
        self.site: object | None = None  # version.json, when the site has one
        self.site_requests: list[httpx.Request] = []
        # The updater companion: its answers, and what it was asked.
        self.updater_ready = 200
        self.updater_status = 202
        self.updater_requests: list[httpx.Request] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        if request.headers["host"].startswith("sunroom-updater"):
            if request.url.path == "/readyz":
                return httpx.Response(self.updater_ready)
            self.updater_requests.append(request)
            return httpx.Response(self.updater_status)
        if request.headers["host"] != "api.github.com":
            self.site_requests.append(request)
            return httpx.Response(404) if self.site is None else httpx.Response(200, json=self.site)
        self.requests.append(request)
        if self.status != 200:
            return httpx.Response(self.status)
        if self.body is not None:
            return httpx.Response(200, json=self.body)
        return httpx.Response(
            200, json={"tag_name": self.release, "draft": False, "prerelease": False}
        )

    def transport(self) -> Callable[[], httpx.AsyncBaseTransport]:
        return lambda: httpx.MockTransport(self.handle)


async def resolve(host: str, port: int) -> list[str]:
    # The updater is a container on the compose network: a private address, as it really is.
    return ["172.18.0.3"] if host == "sunroom-updater" else [PUBLIC]


@pytest.fixture
def github() -> FakeGitHub:
    return FakeGitHub()


def build(data_dir: Path, clock: FakeClock, github: FakeGitHub, **settings: Any) -> FastAPI:
    return create_app(
        make_settings(data_dir, **{"sunroom_update_check": None, **settings}),
        clock=clock,
        resolver=resolve,
        http_transport=github.transport(),
    )


@pytest.fixture
async def server(data_dir: Path, clock: FakeClock, github: FakeGitHub) -> AsyncIterator[FastAPI]:
    app = build(data_dir, clock, github)
    async with app.router.lifespan_context(app):
        yield app


@pytest.fixture
async def phone(server: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """A parent's phone, set up."""
    transport = httpx.ASGITransport(app=server)
    async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as http:
        assert (await run_setup(http)).status_code == 201
        yield http


async def status(client: httpx.AsyncClient) -> dict[str, Any]:
    response = await client.get("/api/admin/update")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def test_versions_compare_by_number() -> None:
    assert parse("v0.10.2") == (0, 10, 2)
    assert parse("0.6.0-rc1") is None
    assert newer("0.10.0", "0.9.9")
    assert not newer("0.5.0", "0.5.0")
    assert not newer(None, "0.5.0")
    assert not newer("nonsense", "0.5.0")


async def test_nothing_goes_out_before_a_household_is_set_up(
    server: FastAPI, github: FakeGitHub
) -> None:
    await updates.tick(state_of(server))
    assert github.requests == []


async def test_it_is_on_by_default_and_asks_once_a_day(
    server: FastAPI, phone: httpx.AsyncClient, github: FakeGitHub, clock: FakeClock
) -> None:
    state = state_of(server)
    await updates.tick(state)
    assert len(github.requests) == 1
    sent = github.requests[0]
    # Pinned to the address the guard checked, with GitHub's name in the Host header.
    assert sent.headers["host"] == "api.github.com"
    assert sent.url.path == "/repos/ScopeXL/sunroom/releases/latest"
    assert sent.headers["user-agent"] == f"Sunroom/{build_info().version}"
    body = await status(phone)
    assert (body["enabled"], body["locked"], body["latest"], body["available"]) == (
        True,
        False,
        "99.0.0",
        True,
    )
    assert body["current"] == build_info().version
    assert body["how"] == (
        "In Sunroom's folder on the server, run docker compose pull, then docker compose up -d."
    )

    await updates.tick(state)  # not again the same day
    assert len(github.requests) == 1
    clock.advance(hours=24)
    github.release = f"v{build_info().version}"
    await updates.tick(state)
    assert len(github.requests) == 2
    assert (await status(phone))["available"] is False


async def test_a_household_can_turn_it_off(
    server: FastAPI, phone: httpx.AsyncClient, github: FakeGitHub
) -> None:
    off = await phone.patch("/api/settings", json={"update_check": False}, headers=CSRF)
    assert off.json()["update_check"] is False
    await updates.tick(state_of(server))
    assert github.requests == []
    assert (await status(phone))["enabled"] is False
    refused = await phone.post("/api/admin/update/check", headers=CSRF)
    assert refused.status_code == 409
    assert refused.json()["error"]["message"] == "Turn on Tell me about new versions first."


async def test_it_asks_the_site_first_and_github_only_when_that_doesnt_answer(
    server: FastAPI, phone: httpx.AsyncClient, github: FakeGitHub, clock: FakeClock
) -> None:
    github.site = {"version": "98.0.0", "published": "2026-10-07T12:00:00Z", "notes": "ignored"}
    await updates.tick(state_of(server))
    assert len(github.site_requests) == 1
    assert github.site_requests[0].headers["host"] == "sunroom.day"
    assert github.requests == []  # the only address that sees the request is the project's own
    assert (await status(phone))["latest"] == "98.0.0"
    assert state_of(server).updates.published == datetime(2026, 10, 7, 12, tzinfo=UTC)

    # A site that's down, or a file it can't read: GitHub's Release instead.
    for answer in (None, {"version": "nonsense"}, ["not", "an", "object"]):
        github.site = answer
        github.requests.clear()
        clock.advance(hours=24)
        await updates.tick(state_of(server))
        assert len(github.requests) == 1, answer
        assert (await status(phone))["latest"] == "99.0.0"


async def test_a_self_hoster_can_point_it_at_their_own_copy(
    data_dir: Path, clock: FakeClock, github: FakeGitHub
) -> None:
    app = build(data_dir, clock, github, sunroom_update_url="https://mirror.example.com/v.json")
    github.site = {"version": "97.0.0"}
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as http:
            await run_setup(http)
            await updates.tick(state_of(app))
            assert (await status(http))["latest"] == "97.0.0"
    assert github.site_requests[0].headers["host"] == "mirror.example.com"


async def test_a_failed_check_says_so_and_check_now_waits_a_minute(
    phone: httpx.AsyncClient, github: FakeGitHub, clock: FakeClock
) -> None:
    github.status = 500
    checked = await phone.post("/api/admin/update/check", headers=CSRF)
    assert checked.status_code == 200, checked.text
    assert checked.json()["problem"] == (
        "Sunroom couldn't find out its latest version. It will try again tomorrow."
    )
    assert checked.json()["available"] is False
    again = await phone.post("/api/admin/update/check", headers=CSRF)
    assert again.status_code == 429
    clock.advance(minutes=1, seconds=1)
    github.status = 200
    later = await phone.post("/api/admin/update/check", headers=CSRF)
    assert later.json()["problem"] is None
    assert later.json()["available"] is True


async def test_it_reads_the_latest_release(
    phone: httpx.AsyncClient, github: FakeGitHub, clock: FakeClock
) -> None:
    """A version counts once its Release exists. A pre-release isn't one, nor is an answer that
    isn't a version, and each failure says so in its own words."""
    github.release = "v0.10.0"
    checked = await phone.post("/api/admin/update/check", headers=CSRF)
    assert (checked.json()["latest"], checked.json()["problem"]) == ("0.10.0", None)

    said = "Sunroom couldn't find out its latest version. It will try again tomorrow."
    answers: list[tuple[int, object]] = [
        (404, None),
        (200, []),
        (200, {"name": "nothing we know"}),
        (200, {"tag_name": "nightly"}),
        (200, {"tag_name": "v1.0.0-rc.1"}),
        (200, {"tag_name": "v1.0.0", "prerelease": True}),
        (200, {"tag_name": "v1.0.0", "draft": True}),
    ]
    for status_code, body in answers:
        clock.advance(minutes=1, seconds=1)
        github.status, github.body = status_code, body
        answer = await phone.post("/api/admin/update/check", headers=CSRF)
        assert answer.json()["problem"] == said, (status_code, body)
        # What it knew stays: a bad day at GitHub doesn't forget the version that's out.
        assert answer.json()["latest"] == "0.10.0"


async def test_the_server_can_keep_it_off_and_say_how_to_update_a_pi(
    data_dir: Path, clock: FakeClock, github: FakeGitHub
) -> None:
    app = build(
        data_dir,
        clock,
        github,
        sunroom_update_check=False,
        sunroom_install_kind=InstallKind.PI,
    )
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as http:
            await run_setup(http)
            on = await http.patch("/api/settings", json={"update_check": True}, headers=CSRF)
            assert (on.json()["update_check"], on.json()["update_check_locked"]) == (False, True)
            await updates.tick(state_of(app))
            assert github.requests == []
            body = (await http.get("/api/admin/update")).json()
            assert (body["enabled"], body["locked"]) == (False, True)
            assert body["how"] == (
                "This screen installs it tonight, or tap Update Sunroom under This Screen."
            )
            assert body["how_key"] == "api.update.how.pi"
            refused = await http.post("/api/admin/update/check", headers=CSRF)
            assert refused.status_code == 409
            assert refused.json()["error"]["message"] == "This server keeps update checks off."


async def test_checking_now_is_a_parents(server: FastAPI, phone: httpx.AsyncClient) -> None:
    transport = httpx.ASGITransport(app=server)
    async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as stranger:
        assert (await stranger.post("/api/admin/update/check", headers=CSRF)).status_code == 401
    assert timedelta(minutes=1) == updates.CHECK_NOW_EVERY


async def test_the_test_server_makes_up_its_answer_and_sends_nothing(
    data_dir: Path, clock: FakeClock, github: FakeGitHub
) -> None:
    """End-to-end runs and `just seed` never reach GitHub: the next minor version stands in."""
    app = build(data_dir, clock, github, sunroom_test_mode=True)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as http:
            assert (await run_setup(http)).status_code == 201
            await updates.tick(state_of(app))
            assert state_of(app).updates.checked_at is None  # only when a test asks
            checked = await http.post("/api/admin/update/check", headers=CSRF)
            assert checked.status_code == 200, checked.text
            body = checked.json()
            # The next end-to-end test starts from nothing: the answer goes with the reset.
            assert (await http.post("/api/_test/reset", headers=CSRF)).status_code == 204
            assert state_of(app).updates.checked_at is None
    assert github.requests == []
    assert (body["latest"], body["available"]) == (made_up(build_info().version), True)
    assert made_up("0.6.0") == "0.7.0"
    assert made_up("not a version") is None


@pytest.fixture
async def with_updater(
    data_dir: Path, clock: FakeClock, github: FakeGitHub
) -> AsyncIterator[tuple[FastAPI, httpx.AsyncClient]]:
    """A household whose compose file has the updater companion, and a parent's phone."""
    app = build(
        data_dir,
        clock,
        github,
        sunroom_updater_url="http://sunroom-updater:8080",
        sunroom_updater_token="the-updaters-token",
    )
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as http:
            assert (await run_setup(http)).status_code == 201
            yield app, http


def a_version_is_out(app: FastAPI, clock: FakeClock, *, days_ago: float = 2) -> None:
    found = state_of(app).updates
    found.latest = "99.0.0"
    found.published = clock.now() - timedelta(days=days_ago)


async def test_update_now_asks_the_updater_and_every_page_hears(
    with_updater: tuple[FastAPI, httpx.AsyncClient], github: FakeGitHub, clock: FakeClock
) -> None:
    app, phone = with_updater
    a_version_is_out(app, clock)
    body = await status(phone)
    assert (body["updater"], body["update_now"]) == (True, True)
    assert body["how"] == "It installs itself tonight, or tap Update Now."
    assert body["how_key"] == "api.update.how.companion"
    heard: list[str] = []
    state_of(app).hub.listeners.append(lambda event_type, _payload: heard.append(event_type))
    answer = await phone.post("/api/admin/update", headers=CSRF)
    assert answer.status_code == 202, answer.text
    [sent] = github.updater_requests
    assert sent.method == "POST"
    assert (sent.url.path, sent.url.params["async"]) == ("/v1/update", "true")
    assert sent.headers["authorization"] == "Bearer the-updaters-token"
    assert "server.updating" in heard


async def test_a_version_waits_out_its_first_day_as_the_updater_does(
    with_updater: tuple[FastAPI, httpx.AsyncClient], github: FakeGitHub, clock: FakeClock
) -> None:
    """The companion's cooldown gates /v1/update too, and no request can ask it not to: a button
    here would do nothing, so About says what will happen instead."""
    app, phone = with_updater
    a_version_is_out(app, clock, days_ago=0.1)
    body = await status(phone)
    assert (body["available"], body["updater"], body["update_now"]) == (True, True, False)
    assert body["how"] == "It installs itself overnight, a day after it comes out."
    refused = await phone.post("/api/admin/update", headers=CSRF)
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "too_new"
    assert github.updater_requests == []
    clock.advance(hours=24)
    assert (await status(phone))["update_now"] is True


async def test_about_only_promises_what_the_updater_can_do(
    with_updater: tuple[FastAPI, httpx.AsyncClient], github: FakeGitHub, clock: FakeClock
) -> None:
    """Deleted from the compose file, stopped, or cut off from Docker: back to the plain words."""
    app, phone = with_updater
    a_version_is_out(app, clock)
    github.updater_ready = 503
    state_of(app).updates.updater_looked_at = None
    body = await status(phone)
    assert (body["updater"], body["update_now"]) == (False, False)
    assert body["how_key"] == "api.update.how.docker"
    refused = await phone.post("/api/admin/update", headers=CSRF)
    assert (refused.status_code, refused.json()["error"]["code"]) == (409, "no_updater")
    # Back again: seen within the minute.
    github.updater_ready = 200
    clock.advance(minutes=1, seconds=1)
    assert (await status(phone))["updater"] is True


async def test_an_updater_that_refuses_says_so_and_no_page_waits(
    with_updater: tuple[FastAPI, httpx.AsyncClient], github: FakeGitHub, clock: FakeClock
) -> None:
    app, phone = with_updater
    a_version_is_out(app, clock)
    heard: list[str] = []
    state_of(app).hub.listeners.append(lambda event_type, _payload: heard.append(event_type))
    github.updater_status = 500
    failed = await phone.post("/api/admin/update", headers=CSRF)
    assert (failed.status_code, failed.json()["error"]["message"]) == (
        502,
        "Couldn't reach the updater. It still installs updates overnight.",
    )
    assert "server.updating" not in heard
    # Busy with an update already: that's what was asked for.
    github.updater_status = 429
    assert (await phone.post("/api/admin/update", headers=CSRF)).status_code == 202
    assert "server.updating" in heard


async def test_with_no_updater_in_the_compose_file_there_is_no_update_now(
    server: FastAPI, phone: httpx.AsyncClient, clock: FakeClock
) -> None:
    a_version_is_out(server, clock)
    body = await status(phone)
    assert (body["updater"], body["update_now"]) == (False, False)
    assert body["how_key"] == "api.update.how.docker"
    refused = await phone.post("/api/admin/update", headers=CSRF)
    assert (refused.status_code, refused.json()["error"]["code"]) == (409, "no_updater")


async def test_update_now_needs_a_new_version_and_a_parent(
    with_updater: tuple[FastAPI, httpx.AsyncClient], github: FakeGitHub
) -> None:
    app, phone = with_updater
    assert (await status(phone))["update_now"] is False
    current = await phone.post("/api/admin/update", headers=CSRF)
    assert (current.status_code, current.json()["error"]["code"]) == (409, "up_to_date")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as stranger:
        assert (await stranger.post("/api/admin/update", headers=CSRF)).status_code == 401
    assert github.updater_requests == []


def test_the_updaters_token_is_scrubbed_from_logs(data_dir: Path) -> None:
    settings = make_settings(data_dir, sunroom_updater_token="the-updaters-token")
    assert "the-updaters-token" in settings.secret_literals()


def test_every_install_kind_says_how_to_update() -> None:
    """In the family's words, each with a key, and a NAS's own Update button where it has one."""
    assert set(HOW_KEYS) == set(InstallKind)
    for kind, key in HOW_KEYS.items():
        assert t_en(key).endswith("."), kind
    # Sunroom run as a program (ADR 0038) is updated from the screen that runs it.
    assert "Update Now" in t_en(HOW_KEYS[InstallKind.COMPUTER])
    assert "Unraid" in t_en(HOW_KEYS[InstallKind.UNRAID])
    assert "CasaOS" in t_en(HOW_KEYS[InstallKind.CASAOS])
    assert "Container Manager" in t_en(HOW_KEYS[InstallKind.SYNOLOGY])
    assert "Re-pull image" in t_en(HOW_KEYS[InstallKind.PORTAINER])
