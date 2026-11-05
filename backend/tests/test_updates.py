"""The daily update check (PLAN §13.6, ADR 0046, core/updates.py, meta/updates.py): on by default
for a household that's set up, once a day, with a plain line about how to update this server, and
a switch to turn it off. A stand-in GitHub answers through MockTransport; no socket is opened."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from sunroom.app import create_app
from sunroom.core.clock import FakeClock
from sunroom.core.config import InstallKind
from sunroom.core.updates import made_up, newer, parse
from sunroom.core.version import build_info
from sunroom.meta import updates
from tests.support import BASE_URL, CSRF, make_settings, run_setup, state_of

PUBLIC = "140.82.112.6"  # a made-up public address for api.github.com in these tests


class FakeGitHub:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.release = "v99.0.0"  # the latest Release's tag
        self.body: object | None = None  # an answer of another shape
        self.status = 200

    def handle(self, request: httpx.Request) -> httpx.Response:
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
    return [PUBLIC]


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
        "In Sunroom's folder on the server, run docker compose pull, then docker compose up -d"
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


async def test_a_failed_check_says_so_and_check_now_waits_a_minute(
    phone: httpx.AsyncClient, github: FakeGitHub, clock: FakeClock
) -> None:
    github.status = 500
    checked = await phone.post("/api/admin/update/check", headers=CSRF)
    assert checked.status_code == 200, checked.text
    assert checked.json()["problem"] == (
        "GitHub couldn't find Sunroom's versions. It will try again tomorrow."
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

    unreadable = "GitHub's answer wasn't one Sunroom could read. It will try again tomorrow."
    answers: list[tuple[int, object, str]] = [
        (404, None, "GitHub couldn't find Sunroom's versions. It will try again tomorrow."),
        (200, [], unreadable),
        (200, {"name": "nothing we know"}, unreadable),
        (200, {"tag_name": "nightly"}, unreadable),
        (200, {"tag_name": "v1.0.0-rc.1"}, unreadable),
        (200, {"tag_name": "v1.0.0", "prerelease": True}, unreadable),
        (200, {"tag_name": "v1.0.0", "draft": True}, unreadable),
    ]
    for status_code, body, said in answers:
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
            assert body["how"] == "On the Pi, run sudo /opt/sunroom/update.sh"
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


def test_every_install_kind_says_how_to_update() -> None:
    # Sunroom run as a program (ADR 0038) is updated from the screen that runs it.
    from sunroom.core.updates import HOW

    assert set(HOW) == set(InstallKind)
    assert "Update Now" in HOW[InstallKind.COMPUTER]
