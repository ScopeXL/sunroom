"""Send Feedback without an account (ADR 0042, core/feedback.py, meta/feedback.py): what a family
writes goes, as Discord's webhook body, to the project's relay; nothing else is sent. A stand-in
relay answers through MockTransport; no socket is opened."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from sunroom.app import create_app
from sunroom.core import feedback
from sunroom.core.clock import FakeClock
from sunroom.core.config import ConfigError, InstallKind, load_settings
from sunroom.core.version import build_info
from sunroom.meta import feedback as meta_feedback
from tests.support import BASE_URL, CSRF, PASSWORD, add_member, make_settings, run_setup, state_of

RELAY = "https://feedback.example.com/"
# A made-up public address for the relay in these tests, in Cloudflare's range, where a Worker
# answers (the documentation ranges are private to the guard).
PUBLIC = "104.18.0.7"

IDEA = {"kind": "idea", "title": "A chore wheel", "body": "Spin it on Sundays.", "contact": "Ana"}


class FakeRelay:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.status = 204

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(self.status)

    def transport(self) -> Callable[[], httpx.AsyncBaseTransport]:
        return lambda: httpx.MockTransport(self.handle)

    def bodies(self) -> list[dict[str, Any]]:
        return [json.loads(request.content) for request in self.requests]


async def resolve(host: str, port: int) -> list[str]:
    return [PUBLIC]


@pytest.fixture
def relay() -> FakeRelay:
    return FakeRelay()


def build(data_dir: Path, clock: FakeClock, relay: FakeRelay, **settings: Any) -> FastAPI:
    return create_app(
        make_settings(data_dir, **({"sunroom_feedback_url": RELAY} | settings)),
        clock=clock,
        resolver=resolve,
        http_transport=relay.transport(),
    )


@pytest.fixture
async def server(data_dir: Path, clock: FakeClock, relay: FakeRelay) -> AsyncIterator[FastAPI]:
    app = build(data_dir, clock, relay)
    async with app.router.lifespan_context(app):
        yield app


def client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE_URL)


@pytest.fixture
async def phone(server: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """A parent's phone, set up."""
    async with client(server) as http:
        assert (await run_setup(http)).status_code == 201
        yield http


# The message itself.


def test_the_message_is_one_embed_with_the_version_and_the_install() -> None:
    sent = feedback.message(
        kind="problem",
        title="  The week is blank  ",
        words="Since this morning.",
        contact="",
        version="0.17.0",
        install="Docker",
    )
    assert sent["username"] == "Sunroom feedback"
    assert sent["allowed_mentions"] == {"parse": []}  # an @everyone in the words pings no one
    [embed] = sent["embeds"]
    assert embed["title"] == "Problem: The week is blank"
    assert embed["description"] == "Since this morning."
    assert embed["color"] == feedback.COLORS["problem"]
    assert embed["fields"] == [
        {"name": "Version", "value": "0.17.0", "inline": True},
        {"name": "Install", "value": "Docker", "inline": True},
        {"name": "Reply to", "value": "—", "inline": False},
    ]
    idea = feedback.message(
        kind="idea", title="Stickers", words="  ", contact="Mia", version="0.17.0", install="x"
    )["embeds"][0]
    assert idea["title"] == "Idea: Stickers"
    assert "description" not in idea  # no words, no description
    assert idea["fields"][2]["value"] == "Mia"


def test_the_message_keeps_to_discords_limits() -> None:
    sent = feedback.message(
        kind="idea",
        title="t" * 400,
        words="w" * 9000,
        contact="c" * 2000,
        version="0.17.0",
        install="Docker",
    )
    [embed] = sent["embeds"]
    assert len(embed["title"]) == feedback.TITLE_MAX and embed["title"].endswith("…")
    assert len(embed["description"]) <= feedback.DESCRIPTION_MAX
    assert embed["description"].endswith("…")
    assert all(len(field["value"]) <= feedback.FIELD_MAX for field in embed["fields"])
    total = len(embed["title"]) + len(embed["description"])
    total += sum(len(field["name"]) + len(field["value"]) for field in embed["fields"])
    assert total <= feedback.TOTAL_MAX


def test_five_an_hour_from_one_server(clock: FakeClock) -> None:
    outbox = feedback.Outbox()
    assert all(outbox.take(clock.now()) for _ in range(feedback.SENDS_PER_HOUR))
    assert not outbox.take(clock.now())
    clock.advance(minutes=59)
    assert not outbox.take(clock.now())
    clock.advance(minutes=1)
    assert outbox.take(clock.now())


# The route.


async def test_a_signed_in_device_sends_it_to_the_relay(
    server: FastAPI, phone: httpx.AsyncClient, relay: FakeRelay
) -> None:
    sent = await phone.post("/api/feedback", json=IDEA, headers=CSRF)
    assert sent.status_code == 204, sent.text
    [request] = relay.requests
    assert request.method == "POST"
    assert str(request.url).startswith(f"https://{PUBLIC}")  # pinned to the checked address
    assert request.headers["host"] == "feedback.example.com"
    assert request.headers["content-type"] == "application/json"
    install = feedback.INSTALL_WORDS[InstallKind.DOCKER]
    assert relay.bodies() == [
        feedback.message(
            kind="idea",
            title="A chore wheel",
            words="Spin it on Sundays.",
            contact="Ana",
            version=build_info().version,
            install=install,
        )
    ]
    diagnostics = (await phone.get("/api/admin/diagnostics")).json()
    assert diagnostics["feedback"] is True


async def test_nothing_private_goes_with_it(
    server: FastAPI, phone: httpx.AsyncClient, relay: FakeRelay
) -> None:
    await add_member(phone, "Leo", role="kid")
    place = {"location_label": "Sample Street", "latitude": 40.7, "longitude": -74.0}
    assert (await phone.patch("/api/settings", json=place, headers=CSRF)).status_code == 200
    event = {"title": "Dentist", "start_date": "2026-10-08"}
    assert (await phone.post("/api/calendar/events", json=event, headers=CSRF)).status_code == 201
    assert (await phone.post("/api/feedback", json=IDEA, headers=CSRF)).status_code == 204
    words = relay.requests[0].content.decode()
    for private in ("Sample Family", "Sample Street", "Leo", "Dentist", "40.7", PASSWORD):
        assert private not in words


async def test_a_paired_screen_sends_it_too_and_no_one_signed_out_does(server: FastAPI) -> None:
    async with client(server) as setup:
        assert (await run_setup(setup)).status_code == 201
    async with client(server) as screen:
        paired = await screen.post(
            "/api/auth/kiosk/pair-with-password", json={"password": PASSWORD}, headers=CSRF
        )
        assert paired.status_code == 200, paired.text
        assert (await screen.post("/api/feedback", json=IDEA, headers=CSRF)).status_code == 204
    async with client(server) as stranger:
        refused = await stranger.post("/api/feedback", json=IDEA, headers=CSRF)
        assert refused.status_code == 401


async def test_five_an_hour_then_a_plain_refusal(
    phone: httpx.AsyncClient, relay: FakeRelay, clock: FakeClock
) -> None:
    for _ in range(feedback.SENDS_PER_HOUR):
        assert (await phone.post("/api/feedback", json=IDEA, headers=CSRF)).status_code == 204
    refused = await phone.post("/api/feedback", json=IDEA, headers=CSRF)
    assert refused.status_code == 429
    assert refused.json()["error"] == {
        "code": "too_much_feedback",
        "message": "That's all Sunroom sends in an hour. Try again later.",
    }
    assert len(relay.requests) == feedback.SENDS_PER_HOUR
    clock.advance(hours=1)
    assert (await phone.post("/api/feedback", json=IDEA, headers=CSRF)).status_code == 204


async def test_a_title_is_needed(phone: httpx.AsyncClient, relay: FakeRelay) -> None:
    blank = await phone.post("/api/feedback", json=IDEA | {"title": "   "}, headers=CSRF)
    assert blank.status_code == 422
    assert relay.requests == []


async def test_a_relay_that_fails_says_try_again(
    phone: httpx.AsyncClient, relay: FakeRelay
) -> None:
    relay.status = 500
    failed = await phone.post("/api/feedback", json=IDEA, headers=CSRF)
    assert failed.status_code == 502
    assert failed.json()["error"] == {
        "code": "feedback_failed",
        "message": "Couldn't send it. Try again in a moment.",
    }


async def test_an_address_at_home_is_never_posted_to(
    data_dir: Path, clock: FakeClock, relay: FakeRelay
) -> None:
    """The guard refuses a private address, as for every outbound request (PLAN §12.6)."""

    async def at_home(host: str, port: int) -> list[str]:
        return ["192.168.1.20"]

    app = create_app(
        make_settings(data_dir, sunroom_feedback_url=RELAY),
        clock=clock,
        resolver=at_home,
        http_transport=relay.transport(),
    )
    async with app.router.lifespan_context(app), client(app) as phone:
        await run_setup(phone)
        failed = await phone.post("/api/feedback", json=IDEA, headers=CSRF)
        assert failed.status_code == 502
        assert failed.json()["error"]["code"] == "feedback_failed"
    assert relay.requests == []


@pytest.mark.parametrize("configured", ["", None])
async def test_off_without_an_address(
    data_dir: Path, clock: FakeClock, relay: FakeRelay, configured: str | None
) -> None:
    """Empty turns it off; unset is the project's relay, which this build doesn't name yet."""
    assert meta_feedback.FEEDBACK_URL == ""
    app = build(data_dir, clock, relay, sunroom_feedback_url=configured)
    async with app.router.lifespan_context(app), client(app) as phone:
        await run_setup(phone)
        off = await phone.post("/api/feedback", json=IDEA, headers=CSRF)
        assert off.status_code == 409
        assert off.json()["error"] == {
            "code": "feedback_off",
            "message": "Feedback isn't set up on this Sunroom.",
        }
        assert (await phone.get("/api/admin/diagnostics")).json()["feedback"] is False
    assert relay.requests == []


async def test_the_test_server_keeps_it_instead(
    data_dir: Path, clock: FakeClock, relay: FakeRelay
) -> None:
    app = build(data_dir, clock, relay, sunroom_test_mode=True)
    async with app.router.lifespan_context(app), client(app) as phone:
        await run_setup(phone)
        assert (await phone.post("/api/feedback", json=IDEA, headers=CSRF)).status_code == 204
        kept = (await phone.get("/api/_test/feedback")).json()
        assert [entry["embeds"][0]["title"] for entry in kept] == ["Idea: A chore wheel"]
        assert (await phone.post("/api/_test/reset", headers=CSRF)).status_code == 204
        assert (await phone.get("/api/_test/feedback")).json() == []
        assert state_of(app).feedback.sent_at == type(state_of(app).feedback.sent_at)()
    assert relay.requests == []


def test_the_address_is_checked_and_kept_out_of_logs(tmp_path: Path) -> None:
    base = {"DATA_DIR": str(tmp_path)}
    with pytest.raises(ConfigError) as refused:
        load_settings(base | {"SUNROOM_FEEDBACK_URL": "relay-without-a-scheme"})
    assert "SUNROOM_FEEDBACK_URL" in str(refused.value)
    assert "relay-without-a-scheme" not in str(refused.value)
    settings = load_settings(base | {"SUNROOM_FEEDBACK_URL": RELAY})
    assert RELAY in settings.secret_literals()
    assert meta_feedback.address(settings) == RELAY
    assert meta_feedback.address(load_settings(base | {"SUNROOM_FEEDBACK_URL": ""})) is None
