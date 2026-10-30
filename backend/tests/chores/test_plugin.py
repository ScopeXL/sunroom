"""The chores plugin as a plugin (PLAN §6.4, §15 M3 verify): off, every route answers 404
plugin_disabled and its data waits; a job that raises stops only chores. The Sample Family
only."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from fastapi import APIRouter, FastAPI
from fastapi.routing import APIRoute

from sunroom.plugins.base import Plugin, PluginStatus
from sunroom.plugins.chores import service
from sunroom.plugins.chores.plugin import Chores
from sunroom.plugins.context import PluginContext
from tests.chores.helpers import Family, add_chore, complete, stars_now, tapped
from tests.plugins.sample import SamplePlugin
from tests.support import CSRF, state_of


@pytest.fixture
def plugins(plugin: Chores) -> dict[str, Plugin]:
    """Chores beside another plugin, to show a failure stays with chores."""
    return {"chores": plugin, "other": SamplePlugin("other", name="Other")}


def chores_routes() -> list[tuple[str, str]]:
    router = APIRouter()
    Chores().register_routes(router)
    found: list[tuple[str, str]] = []
    for route in router.routes:
        assert isinstance(route, APIRoute)
        path = "/api/chores" + route.path.replace("{", "").replace("}", "")
        found += [(method, path) for method in sorted(route.methods or ())]
    return found


async def eventually(condition: Callable[[], bool], within_s: float = 2.0) -> None:
    deadline = asyncio.get_running_loop().time() + within_s
    while not condition():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition never became true")
        await asyncio.sleep(0.01)


async def test_off_every_route_is_404_and_on_again_the_data_is_there(
    app: FastAPI, parent: httpx.AsyncClient, screen: httpx.AsyncClient, family: Family
) -> None:
    bed = await add_chore(
        parent, "Make bed", rrule="FREQ=DAILY", assignee_member_ids=[family.mia], points=2
    )
    await complete(screen, bed["id"], headers=tapped(family.mia))
    off = await parent.post("/api/plugins/chores/disable", headers=CSRF)
    assert off.status_code == 200, off.text
    routes = chores_routes()
    assert len(routes) == 31
    for method, path in routes:
        response = await parent.request(method, path, json={}, headers=CSRF)
        assert response.status_code == 404, (method, path)
        assert response.json()["error"] == {
            "code": "plugin_disabled",
            "message": "Tasks is turned off. A parent can turn it on in Settings.",
            "key": "api.plugins.turned_off",
            "params": {"name": "Tasks"},
        }
    on = await parent.post("/api/plugins/chores/enable", headers=CSRF)
    assert on.status_code == 200, on.text
    manager = state_of(app).plugins
    await eventually(lambda: manager.status("chores") is PluginStatus.RUNNING)
    assert [c["title"] for c in (await parent.get("/api/chores")).json()] == ["Make bed"]
    assert (await stars_now(parent, family.mia))["balance"] == 2


async def test_a_job_that_raises_stops_only_chores(
    app: FastAPI,
    parent: httpx.AsyncClient,
    plugin: Chores,
    family: Family,
    monkeypatch: pytest.MonkeyPatch,
    events: list[tuple[str, dict[str, Any]]],
) -> None:
    await add_chore(parent, "Make bed", rrule="FREQ=DAILY", assignee_member_ids=[family.mia])
    await parent.post("/api/plugins/other/enable", headers=CSRF)
    manager = state_of(app).plugins
    await eventually(lambda: manager.status("other") is PluginStatus.RUNNING)

    async def broken(ctx: PluginContext) -> None:
        raise RuntimeError("the prune broke")

    monkeypatch.setattr(service, "prune", broken)
    # Its jobs run as it starts, then hourly: a restart runs the prune now.
    await parent.post("/api/plugins/chores/restart", headers=CSRF)
    await eventually(lambda: manager.status("chores") is PluginStatus.ERRORED)
    assert "RuntimeError" in (manager.error("chores") or "")
    assert manager.status("other") is PluginStatus.RUNNING
    assert ("plugins.changed", {"id": "chores", "status": "errored"}) in events
    # Fixed and restarted, it runs again with its data intact.
    monkeypatch.undo()
    restarted = await parent.post("/api/plugins/chores/restart", headers=CSRF)
    assert restarted.status_code == 200
    await eventually(lambda: manager.status("chores") is PluginStatus.RUNNING)
    assert plugin.ctx is not None
    assert [c["title"] for c in (await parent.get("/api/chores")).json()] == ["Make bed"]
