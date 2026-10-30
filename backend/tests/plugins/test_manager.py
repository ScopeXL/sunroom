"""The plugin runner (PLAN §6.3, §6.4): switches, isolation, settings, events and the gate."""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import AsyncIterator, Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text

from sunroom.app import create_app
from sunroom.core.clock import FakeClock
from sunroom.core.config import Settings
from sunroom.db import migrate
from sunroom.plugins.base import PluginStatus
from tests.plugins.sample import SamplePlugin
from tests.support import BASE_URL, CSRF, PASSWORD, add_member, run_setup, set_pin, state_of

FIXTURE_0_7_0 = "fixtures/db/202610091752.sql"


async def eventually(condition: Callable[[], bool], within_s: float = 2.0) -> None:
    deadline = asyncio.get_running_loop().time() + within_s
    while not condition():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition never became true")
        await asyncio.sleep(0.01)


@pytest.fixture
def plugins() -> dict[str, SamplePlugin]:
    return {"sample": SamplePlugin(), "other": SamplePlugin("other", name="Other")}


@pytest.fixture
async def plugin_app(
    settings: Settings, clock: FakeClock, plugins: dict[str, SamplePlugin]
) -> AsyncIterator[FastAPI]:
    app = create_app(settings, clock=clock, plugins=plugins, ping_interval_s=0.05)
    async with app.router.lifespan_context(app):
        yield app


@pytest.fixture
async def home(plugin_app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=plugin_app)
    async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as client:
        await run_setup(client)
        yield client


async def test_the_real_registry_turns_its_plugins_on(parent: httpx.AsyncClient) -> None:
    listed = (await parent.get("/api/plugins")).json()
    assert [(p["id"], p["enabled"]) for p in listed] == [
        ("calendar_sync", True),
        ("lists", True),
        ("chores", True),
        ("meals", True),
        ("countdowns", True),
        ("screensaver", True),
        ("weather", True),
    ]


async def test_plugins_start_off_and_describe_themselves(home: httpx.AsyncClient) -> None:
    listed = (await home.get("/api/plugins")).json()
    sample = next(p for p in listed if p["id"] == "sample")
    assert (sample["enabled"], sample["status"]) == (False, "disabled")
    assert sample["url_prefix"] == "sample"
    assert [f["key"] for f in sample["settings_spec"]] == ["interval", "api_key", "mode", "wake"]
    assert sample["settings"] == {"interval": 60, "api_key": None, "mode": "calm", "wake": "07:00"}
    assert sample["contributes"]["display_rooms"] == [
        {"key": "room", "title": "Sample", "icon": "sparkles", "order": 50}
    ]
    assert sample["requires_parent_to_manage"] is True


async def test_off_means_404_and_on_means_running(
    home: httpx.AsyncClient, plugins: dict[str, SamplePlugin]
) -> None:
    off = await home.get("/api/sample/ping")
    assert off.status_code == 404
    assert off.json()["error"] == {
        "code": "plugin_disabled",
        "message": "Sample is turned off. A parent can turn it on in Settings.",
        "key": "api.plugins.turned_off",
        "params": {"name": "Sample"},
    }
    enabled = (await home.post("/api/plugins/sample/enable", headers=CSRF)).json()
    assert enabled["enabled"] is True
    await eventually(lambda: plugins["sample"].ticks >= 2)
    listed = (await home.get("/api/plugins")).json()
    assert next(p for p in listed if p["id"] == "sample")["status"] == "running"
    assert (await home.get("/api/sample/ping")).json()["pong"] is True
    await home.post("/api/plugins/sample/disable", headers=CSRF)
    assert plugins["sample"].disabled == 1
    assert (await home.get("/api/sample/ping")).status_code == 404
    ticks = plugins["sample"].ticks
    await asyncio.sleep(0.05)
    assert plugins["sample"].ticks == ticks  # its job stopped with it


@pytest.mark.parametrize("where", ["job", "spawn", "event", "enable"])
async def test_a_failing_plugin_stops_alone_and_keeps_its_routes(
    plugin_app: FastAPI,
    home: httpx.AsyncClient,
    plugins: dict[str, SamplePlugin],
    where: str,
) -> None:
    events: list[tuple[str, dict[str, Any]]] = []
    state_of(plugin_app).hub.listeners.append(lambda kind, data: events.append((kind, data)))
    plugins["sample"].fail_in = where
    await home.post("/api/plugins/other/enable", headers=CSRF)
    await home.post("/api/plugins/sample/enable", headers=CSRF)
    if where == "event":
        await add_member(home, "Mia", "kid")
    manager = state_of(plugin_app).plugins
    await eventually(lambda: manager.status("sample") is PluginStatus.ERRORED)
    assert "RuntimeError" in (manager.error("sample") or "")
    assert manager.status("other") is PluginStatus.RUNNING
    assert ("plugins.changed", {"id": "sample", "status": "errored"}) in events
    # Data is intact and the routes answer; only its background work stopped.
    assert (await home.get("/api/sample/ping")).status_code == 200
    plugins["sample"].fail_in = None
    restarted = await home.post("/api/plugins/sample/restart", headers=CSRF)
    assert restarted.status_code == 200
    await eventually(lambda: manager.status("sample") is PluginStatus.RUNNING)


async def test_subscribed_events_arrive_in_order(
    home: httpx.AsyncClient, plugins: dict[str, SamplePlugin]
) -> None:
    await home.post("/api/plugins/sample/enable", headers=CSRF)
    await eventually(lambda: plugins["sample"].ticks > 0)
    await add_member(home, "Mia", "kid")
    await add_member(home, "Leo", "kid")
    await home.patch("/api/settings", json={"theme": "dark"}, headers=CSRF)  # not subscribed
    await eventually(lambda: len(plugins["sample"].events) == 2)
    assert [event.type for event in plugins["sample"].events] == ["members.changed"] * 2


async def test_settings_are_coerced_validated_and_secrets_masked(
    plugin_app: FastAPI, home: httpx.AsyncClient
) -> None:
    put = await home.put(
        "/api/plugins/sample/settings",
        json={"values": {"interval": "30", "api_key": "sk-sample-0000", "mode": "busy"}},
        headers=CSRF,
    )
    assert put.status_code == 200, put.text
    assert put.json() == {"interval": 30, "api_key": "***", "mode": "busy", "wake": "07:00"}
    stored = state_of(plugin_app).plugins.settings("sample")
    assert stored["api_key"] == "sk-sample-0000"
    # Sending the mask back keeps the stored secret.
    again = await home.put(
        "/api/plugins/sample/settings",
        json={"values": {"interval": 45, "api_key": "***", "mode": "busy"}},
        headers=CSRF,
    )
    assert again.status_code == 200
    assert state_of(plugin_app).plugins.settings("sample")["api_key"] == "sk-sample-0000"
    # An empty secret clears it (Remove keys): nothing is stored, and nothing reads as set.
    cleared = await home.put(
        "/api/plugins/sample/settings",
        json={"values": {"interval": 45, "api_key": "", "mode": "busy"}},
        headers=CSRF,
    )
    assert cleared.status_code == 200
    assert cleared.json()["api_key"] is None
    assert state_of(plugin_app).plugins.settings("sample")["api_key"] is None
    for bad, problem in (
        ({"interval": 0}, "How often must be at least 1"),
        ({"mode": "wild"}, "Mode: isn't one of the choices"),
        ({"wake": "7am"}, "Wake at: expected a time like 07:30"),
        ({"surprise": 1}, "unknown setting 'surprise'"),
        ({"interval": 5, "mode": "busy"}, "Busy mode needs an interval of at least 10."),
    ):
        refused = await home.put("/api/plugins/sample/settings", json={"values": bad}, headers=CSRF)
        assert refused.status_code == 422, bad
        assert problem in refused.json()["error"]["problems"], refused.json()


async def test_settings_survive_a_restart(
    settings: Settings, clock: FakeClock, plugins: dict[str, SamplePlugin]
) -> None:
    app = create_app(settings, clock=clock, plugins=plugins)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as client:
            await run_setup(client)
            await client.post("/api/plugins/sample/enable", headers=CSRF)
            await client.put(
                "/api/plugins/sample/settings", json={"values": {"interval": 90}}, headers=CSRF
            )
    fresh = {"sample": SamplePlugin(), "other": SamplePlugin("other")}
    again = create_app(settings, clock=clock, plugins=fresh)
    async with again.router.lifespan_context(again):
        manager = state_of(again).plugins
        assert manager.is_enabled("sample")
        assert manager.settings("sample")["interval"] == 90
        await eventually(lambda: fresh["sample"].ticks > 0)


class RenamedSample(SamplePlugin):
    """The sample a version on: "How often" was ``interval`` and is now ``pace``."""

    def __init__(self) -> None:
        super().__init__()
        spec = tuple(
            replace(field, key="pace") if field.key == "interval" else field
            for field in self.manifest.settings_spec
        )
        self.manifest = replace(self.manifest, version="1.1.0", settings_spec=spec)
        self.upgraded_from: list[str] = []

    def upgrade_settings(self, raw: dict[str, Any], from_version: str) -> dict[str, Any]:
        self.upgraded_from.append(from_version)
        return {("pace" if key == "interval" else key): value for key, value in raw.items()}


async def test_a_newer_plugin_carries_its_old_settings_over_once(
    settings: Settings, clock: FakeClock, plugins: dict[str, SamplePlugin]
) -> None:
    app = create_app(settings, clock=clock, plugins=plugins)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as client:
            await run_setup(client)
            await client.post("/api/plugins/sample/enable", headers=CSRF)
            await client.put(
                "/api/plugins/sample/settings", json={"values": {"interval": 90}}, headers=CSRF
            )
    newer = RenamedSample()
    again = create_app(settings, clock=clock, plugins={"sample": newer})
    async with again.router.lifespan_context(again):
        # Without the hook the old key would be dropped, and "How often" back at 60.
        assert newer.upgraded_from == ["1.0.0"]
        assert state_of(again).plugins.settings("sample")["pace"] == 90
    # What it carried was stored under the new version: the next start has nothing to do.
    later = RenamedSample()
    third = create_app(settings, clock=clock, plugins={"sample": later})
    async with third.router.lifespan_context(third):
        assert later.upgraded_from == []
        assert state_of(third).plugins.settings("sample")["pace"] == 90


async def test_a_household_from_the_last_release_keeps_what_it_chose(
    data_dir: Path, settings: Settings, clock: FakeClock
) -> None:
    """0.7.0's database under this release's plugins: dinner stays on the calendar (one switch
    then, a choice per meal now), and photos set to start after 10 minutes, which is no longer
    offered, start after the default."""
    db = data_dir / "sunroom.db"
    db.unlink()
    conn = sqlite3.connect(db)
    conn.executescript((Path(__file__).parent.parent / FIXTURE_0_7_0).read_text())
    conn.close()
    migrate.upgrade(db)
    app = create_app(settings, clock=clock)
    async with app.router.lifespan_context(app):
        manager = state_of(app).plugins
        assert manager.settings("meals") == {"slots": ["dinner"], "calendar_slots": ["dinner"]}
        assert manager.settings("screensaver")["start_after"] == "15"
        assert manager.settings("screensaver")["every"] == "30"
    conn = sqlite3.connect(db)
    try:
        stored = conn.execute(
            "SELECT plugin_version, settings_json FROM plugin_state WHERE plugin_id = 'meals'"
        ).fetchone()
    finally:
        conn.close()
    assert stored == ("1.1.0", '{"slots": ["dinner"], "calendar_slots": ["dinner"]}')


async def test_reset_returns_every_plugin_to_its_default(
    plugin_app: FastAPI, home: httpx.AsyncClient, plugins: dict[str, SamplePlugin]
) -> None:
    await home.post("/api/plugins/sample/enable", headers=CSRF)
    await home.put("/api/plugins/sample/settings", json={"values": {"interval": 90}}, headers=CSRF)
    await eventually(lambda: plugins["sample"].ticks > 0)
    state = state_of(plugin_app)
    manager = state.plugins

    async def erase() -> None:
        # While everything is being erased no plugin runs, so no job writes into its tables.
        assert plugins["sample"].disabled == 1
        assert manager.status("sample") is PluginStatus.DISABLED
        async with state.db.write() as tx:
            await tx.session.execute(text("DELETE FROM plugin_state"))

    await manager.reset(erase)
    # A new install's rows: the sample starts off, with its default settings.
    assert not manager.is_enabled("sample")
    assert manager.status("sample") is PluginStatus.DISABLED
    assert manager.settings("sample")["interval"] == 60
    listed = (await home.get("/api/plugins")).json()
    assert [(p["id"], p["enabled"], p["settings"]["interval"]) for p in listed] == [
        ("sample", False, 60),
        ("other", False, 60),
    ]


async def test_a_reset_that_fails_starts_the_plugins_as_they_were(
    plugin_app: FastAPI, home: httpx.AsyncClient, plugins: dict[str, SamplePlugin]
) -> None:
    await home.post("/api/plugins/sample/enable", headers=CSRF)
    await home.put("/api/plugins/sample/settings", json={"values": {"interval": 90}}, headers=CSRF)
    await eventually(lambda: plugins["sample"].ticks > 0)
    manager = state_of(plugin_app).plugins

    async def erase() -> None:
        raise RuntimeError("the disk is full")

    with pytest.raises(RuntimeError, match="the disk is full"):
        await manager.reset(erase)
    assert manager.is_enabled("sample")
    assert manager.settings("sample")["interval"] == 90
    ticks = plugins["sample"].ticks
    await eventually(lambda: plugins["sample"].ticks > ticks)
    assert manager.status("sample") is PluginStatus.RUNNING


async def test_only_a_parent_turns_features_on_and_off(
    plugin_app: FastAPI, home: httpx.AsyncClient
) -> None:
    await set_pin(home)
    transport = httpx.ASGITransport(app=plugin_app)
    async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as screen:
        await screen.post(
            "/api/auth/kiosk/pair-with-password", json={"password": PASSWORD}, headers=CSRF
        )
        assert (await screen.get("/api/plugins")).status_code == 200
        refused = await screen.post("/api/plugins/sample/enable", headers=CSRF)
        assert refused.status_code == 403
        assert refused.json()["error"]["pin"] is True


async def test_unknown_plugins_are_404(home: httpx.AsyncClient) -> None:
    assert (await home.post("/api/plugins/nope/enable", headers=CSRF)).status_code == 404
