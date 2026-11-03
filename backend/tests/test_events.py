"""The live-update stream (PLAN §11.5), driven through a hand-written ASGI harness."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from sunroom.app import create_app
from sunroom.core.clock import ShiftableClock
from sunroom.core.version import build_info
from sunroom.events.hub import EventHub
from sunroom.state import AppState
from tests.support import (
    BASE_URL,
    CSRF,
    StreamProbe,
    login,
    make_settings,
    run_setup,
    session_cookie,
    state_of,
)


def hub_of(app: FastAPI) -> EventHub:
    state: AppState = app.state.sunroom
    return state.hub


def types(frames: list[dict[str, Any]]) -> list[str]:
    return [frame["type"] for frame in frames]


@pytest.fixture
async def signed_in(client: httpx.AsyncClient) -> httpx.AsyncClient:
    await run_setup(client)
    return client


@pytest.fixture
async def stream(app: FastAPI, signed_in: httpx.AsyncClient) -> AsyncIterator[StreamProbe]:
    probe = StreamProbe(app, cookie=session_cookie(signed_in)).start()
    await probe.wait_started()
    yield probe
    await probe.close()


async def test_headers_retry_and_hello_come_first(stream: StreamProbe) -> None:
    assert stream.status == 200
    assert stream.headers["content-type"].startswith("text/event-stream")
    assert stream.headers["cache-control"] == "no-cache, no-transform"
    assert stream.headers["x-accel-buffering"] == "no"
    frames = await stream.wait_for(lambda f: len(f) >= 1)
    assert stream.raw().startswith("retry: 3000\n\n")
    assert frames[0]["type"] == "hello"
    assert frames[0]["mode"] == "live"
    # Every screen compares this with its own build, and reloads on a new one (ADR 0028).
    assert frames[0]["version"] == build_info().version


async def test_published_events_arrive_with_positions(
    app: FastAPI, signed_in: httpx.AsyncClient, stream: StreamProbe
) -> None:
    await stream.wait_for(lambda f: "hello" in types(f))
    await signed_in.post("/api/members", json={"name": "Mia"}, headers=CSRF)
    frames = await stream.wait_for(lambda f: "members.changed" in types(f))
    event = next(f for f in frames if f["type"] == "members.changed")
    epoch, _, seq = event["_id"].rpartition(":")
    assert epoch == hub_of(app).epoch
    assert int(seq) == hub_of(app).seq


async def test_pings_are_data_events(stream: StreamProbe) -> None:
    frames = await stream.wait_for(lambda f: "ping" in types(f), within_s=1.0)
    ping = next(f for f in frames if f["type"] == "ping")
    assert "_id" not in ping  # pings don't move the stream position


async def test_reconnect_replays_what_was_missed(
    app: FastAPI, signed_in: httpx.AsyncClient
) -> None:
    hub = hub_of(app)
    position = f"{hub.epoch}:{hub.seq}"
    for name in ("Mia", "Leo"):
        await signed_in.post("/api/members", json={"name": name}, headers=CSRF)
    probe = StreamProbe(app, cookie=session_cookie(signed_in), query=f"since={position}").start()
    try:
        frames = await probe.wait_for(lambda f: types(f).count("members.changed") == 2)
        assert frames[0]["type"] == "hello" and frames[0]["mode"] == "replay"
    finally:
        await probe.close()


async def test_unknown_epoch_means_resync(app: FastAPI, signed_in: httpx.AsyncClient) -> None:
    probe = StreamProbe(app, cookie=session_cookie(signed_in), query="since=deadbeef:5").start()
    try:
        frames = await probe.wait_for(lambda f: len(f) >= 1)
        assert frames[0] == frames[0] | {"type": "hello", "mode": "resync"}
    finally:
        await probe.close()


async def test_overflow_turns_into_resync_not_silent_loss(
    app: FastAPI, stream: StreamProbe
) -> None:
    await stream.wait_for(lambda f: "hello" in types(f))
    hub = hub_of(app)
    for index in range(hub.queue_size + 50):
        hub.publish("members.changed", {"n": index})
    frames = await stream.wait_for(
        lambda f: any(x["type"] == "hello" and x["mode"] == "resync" for x in f)
    )
    resync = [x for x in frames if x["type"] == "hello" and x["mode"] == "resync"]
    assert resync and resync[0]["version"] == build_info().version


async def test_no_session_means_401(app: FastAPI) -> None:
    probe = StreamProbe(app).start()
    try:
        await probe.wait_started()
        assert probe.status == 401
    finally:
        await probe.close()


async def test_revoking_the_device_ends_the_stream(
    app: FastAPI, client: httpx.AsyncClient, stream: StreamProbe
) -> None:
    await stream.wait_for(lambda f: "hello" in types(f))
    other = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost:7867"
    )
    async with other:
        await login(other)
        await other.post("/api/auth/devices/sign-out-others", json={}, headers=CSRF)
    frames = await stream.wait_for(lambda f: "session.expired" in types(f))
    assert frames[-1]["type"] == "session.expired"
    assert await stream.finished()


async def test_disconnect_releases_the_connection(
    app: FastAPI, signed_in: httpx.AsyncClient
) -> None:
    probe = StreamProbe(app, cookie=session_cookie(signed_in)).start()
    await probe.wait_for(lambda f: "hello" in types(f))
    assert hub_of(app).connection_count == 1
    await probe.close()
    assert hub_of(app).connection_count == 0


async def first_hello(app: FastAPI, cookie: str) -> dict[str, Any]:
    probe = StreamProbe(app, cookie=cookie).start()
    try:
        frames = await probe.wait_for(lambda f: "hello" in types(f))
        return frames[0]
    finally:
        await probe.close()


async def test_the_test_server_can_pretend_it_was_updated(data_dir: Path) -> None:
    """End-to-end runs check that screens reload for a new version: the next hello (or every
    one until a reset) names a stand-in."""
    app = create_app(make_settings(data_dir, sunroom_test_mode=True), clock=ShiftableClock())
    real = build_info().version
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as http:
            assert (await run_setup(http)).status_code == 201
            cookie = session_cookie(http)
            once = {"version": "9.9.9", "once": True}
            assert (
                await http.post("/api/_test/version", json=once, headers=CSRF)
            ).status_code == 204
            assert (await first_hello(app, cookie))["version"] == "9.9.9"
            assert (await first_hello(app, cookie))["version"] == real
            every = {"version": "9.9.9"}
            assert (
                await http.post("/api/_test/version", json=every, headers=CSRF)
            ).status_code == 204
            assert (await first_hello(app, cookie))["version"] == "9.9.9"
            assert (await first_hello(app, cookie))["version"] == "9.9.9"
            assert (await http.post("/api/_test/reset", headers=CSRF)).status_code == 204
            assert state_of(app).hello_version.stand_in is None
