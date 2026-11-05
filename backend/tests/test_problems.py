"""Needs Attention (ADR 0034): core's own causes (a stopped feature, a failed or week-old backup,
low space), what each feature reports, and who sees the quiet details. Synthetic data only."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from datetime import timedelta
from pathlib import Path
from typing import Any, NamedTuple

import httpx
import pytest
from fastapi import FastAPI

from sunroom.app import create_app
from sunroom.core.clock import FakeClock
from sunroom.core.config import Settings
from sunroom.core.lang import english, t_en
from sunroom.core.version import build_info
from sunroom.plugins.base import PluginStatus, Problem
from sunroom.plugins.context import PluginContext
from sunroom.plugins.registry import REGISTRY
from tests.plugins.sample import SamplePlugin
from tests.plugins.test_manager import eventually
from tests.support import (
    BASE_URL,
    CSRF,
    PASSWORD,
    make_settings,
    run_setup,
    set_pin,
    startup_backup_done,
    state_of,
)

PAGES = {
    "family",
    "features",
    "calendars",
    "display",
    "household",
    "devices",
    "removed",
    "backup",
    "support",
    "about",
    *REGISTRY,
}


class Usage(NamedTuple):
    total: int
    used: int
    free: int


def plenty(_path: Any) -> Usage:
    return Usage(100 * 1024**3, 10 * 1024**3, 90 * 1024**3)


@pytest.fixture
def settings(data_dir: Path) -> Settings:
    """The update check on, as a household has it (tests elsewhere keep it off)."""
    return make_settings(data_dir, sunroom_update_check=None)


@pytest.fixture(autouse=True)
def _roomy(monkeypatch: pytest.MonkeyPatch) -> None:
    """The test machine's own disk never decides what these tests see."""
    monkeypatch.setattr("sunroom.problems.service.shutil.disk_usage", plenty)


async def problems(client: httpx.AsyncClient) -> list[dict[str, Any]]:
    response = await client.get("/api/problems")
    assert response.status_code == 200, response.text
    found: list[dict[str, Any]] = response.json()["problems"]
    return found


async def test_a_new_household_needs_nothing(parent: httpx.AsyncClient) -> None:
    assert await problems(parent) == []


async def test_a_backup_a_week_old_and_one_that_failed(
    app: FastAPI, parent: httpx.AsyncClient, other: httpx.AsyncClient, clock: FakeClock
) -> None:
    await startup_backup_done(app)
    backups = state_of(app).backups
    backups.last_success_at = clock.now() - timedelta(days=8)
    [stale] = await problems(parent)
    assert (stale["id"], stale["title"], stale["page"], stale["source"]) == (
        "backup:stale",
        "The newest backup is over a week old.",
        "backup",
        "core",
    )
    assert (stale["key"], stale["params"]) == ("api.problems.backup_stale", {})
    assert stale["since"] is not None
    backups.last_error = "There isn't enough free space for a backup."
    [failed] = await problems(parent)
    assert (failed["id"], failed["title"]) == ("backup:failed", "The last backup didn't complete.")
    assert (failed["key"], failed["params"]) == ("api.problems.backup_failed", {})
    assert failed["detail"] == "The last try failed: There isn't enough free space for a backup."
    # A wall screen sees the sentence, never the detail (with a PIN set, it isn't a parent).
    await set_pin(parent)
    paired = await other.post(
        "/api/auth/kiosk/pair-with-password", json={"password": PASSWORD}, headers=CSRF
    )
    assert paired.status_code == 200, paired.text
    [seen] = await problems(other)
    assert (seen["title"], seen["detail"]) == ("The last backup didn't complete.", None)


async def test_a_new_version_is_for_a_parent_to_see(
    app: FastAPI, parent: httpx.AsyncClient, other: httpx.AsyncClient
) -> None:
    """ADR 0046: the family hears of a new version here, and it goes once it's running."""
    found = state_of(app).updates
    found.latest = "99.0.0"
    [update] = await problems(parent)
    assert (update["id"], update["title"], update["page"], update["source"]) == (
        "update:available",
        "Sunroom 99.0.0 is out.",
        "about",
        "core",
    )
    assert (update["key"], update["params"]) == (
        "api.problems.update_available",
        {"version": "99.0.0"},
    )
    assert update["detail"].startswith("In Sunroom's folder on the server")
    # A wall screen sees the sentence, never how to update (with a PIN set, it isn't a parent).
    await set_pin(parent)
    paired = await other.post(
        "/api/auth/kiosk/pair-with-password", json={"password": PASSWORD}, headers=CSRF
    )
    assert paired.status_code == 200, paired.text
    [seen] = await problems(other)
    assert (seen["title"], seen["detail"]) == ("Sunroom 99.0.0 is out.", None)
    # A household that turned the check off hears nothing.
    off = await parent.patch("/api/settings", json={"update_check": False}, headers=CSRF)
    assert off.status_code == 200, off.text
    assert await problems(parent) == []
    on = await parent.patch("/api/settings", json={"update_check": True}, headers=CSRF)
    assert on.status_code == 200, on.text
    # Gone once this is the newest.
    found.latest = build_info().version
    assert await problems(parent) == []


async def test_a_server_short_of_room(
    parent: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def tight(_path: Any) -> Usage:
        return Usage(100 * 1024**3, 98 * 1024**3, int(1.3 * 1024**3))

    monkeypatch.setattr("sunroom.problems.service.shutil.disk_usage", tight)
    [low] = await problems(parent)
    assert (low["id"], low["page"]) == ("storage:low", "about")
    assert low["title"] == (
        "The server has 1.3 GB free. Sunroom needs room for photos and backups."
    )
    # The page says it in the family's language from the key and its values (ADR 0043).
    assert (low["key"], low["params"]) == ("api.problems.storage_low", {"free": "1.3 GB"})


class Reporting(SamplePlugin):
    """A plugin with something to say, that counts how often it was asked."""

    def __init__(self, plugin_id: str = "sample", *, name: str = "Sample") -> None:
        super().__init__(plugin_id, name=name)
        self.asked = 0
        self.broken = False

    async def problems(self, ctx: PluginContext) -> list[Problem]:
        self.asked += 1
        if self.broken:
            raise RuntimeError("the hook broke")
        return [
            Problem(
                id="sample:1",
                key="api.sync.needs_password",
                params={"name": "Sample"},
                page="sample",
            )
        ]


@pytest.fixture
def reporting() -> Reporting:
    return Reporting()


@pytest.fixture
async def sample_app(
    settings: Settings, clock: FakeClock, reporting: Reporting
) -> AsyncIterator[FastAPI]:
    app = create_app(settings, clock=clock, plugins={"sample": reporting})
    async with app.router.lifespan_context(app):
        yield app


@pytest.fixture
async def home(sample_app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=sample_app)
    async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as client:
        await run_setup(client)
        yield client


async def test_a_feature_says_what_it_needs_only_while_its_on(
    home: httpx.AsyncClient, reporting: Reporting
) -> None:
    assert await problems(home) == []
    assert reporting.asked == 0  # off: never asked
    assert (await home.post("/api/plugins/sample/enable", headers=CSRF)).status_code == 200
    [said] = await problems(home)
    assert (said["id"], said["title"], said["page"], said["source"]) == (
        "sample:1",
        "Sample needs its password again.",
        "sample",
        "sample",
    )
    assert (said["key"], said["params"]) == ("api.sync.needs_password", {"name": "Sample"})
    # A hook that breaks adds nothing, and breaks nothing.
    reporting.broken = True
    assert await problems(home) == []


async def test_a_feature_that_stopped_is_core_s_to_say(
    sample_app: FastAPI, home: httpx.AsyncClient, reporting: Reporting
) -> None:
    reporting.fail_in = "job"
    assert (await home.post("/api/plugins/sample/enable", headers=CSRF)).status_code == 200
    manager = state_of(sample_app).plugins
    await eventually(lambda: manager.status("sample") is PluginStatus.ERRORED)
    asked: Callable[[], int] = lambda: reporting.asked  # noqa: E731
    before = asked()
    [stopped] = await problems(home)
    assert (stopped["id"], stopped["title"], stopped["page"]) == (
        "plugin:sample",
        "Sample stopped working.",
        "features",
    )
    assert (stopped["key"], stopped["params"]) == (
        "api.problems.plugin_stopped",
        {"name": "Sample"},
    )
    assert asked() == before  # its own hook isn't asked while it's stopped


async def test_every_feature_answers_with_plain_problems(
    app: FastAPI, parent: httpx.AsyncClient
) -> None:
    """The contract (ADR 0034, 0043): a list of Problem, each a sentence by its key in the English
    file, with the values it names, and a page Settings knows."""
    manager = state_of(app).plugins
    for plugin_id, plugin in manager.registry.items():
        ctx = manager._idle_context(plugin_id)  # pyright: ignore[reportPrivateUsage]
        found = await plugin.problems(ctx)
        assert isinstance(found, list), plugin_id
        for problem in found:
            assert isinstance(problem, Problem), plugin_id
            assert problem.key in english(), (plugin_id, problem.key)
            assert problem.title == t_en(problem.key, **problem.params)
            assert problem.title.endswith("."), (plugin_id, problem.title)
            assert problem.page is None or problem.page in PAGES, (plugin_id, problem.page)
