"""The agent's loops (state.py), a tick at a time: the health check, the re-find of a found
Sunroom that moved (never a typed one), the watchdog that shows "Can't reach" only after two
minutes with no Sunroom on the screen, and the page a start opens. Synthetic data only."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from sunroom_kiosk import config as settings_file
from sunroom_kiosk import state as agent_module
from sunroom_kiosk.browser import NoBrowser, PageLook
from sunroom_kiosk.config import Config
from sunroom_kiosk.state import Agent
from tests.support import AGENT, PORT, SUNROOM, SUNROOM_ID, FakeSunrooms


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    tick = Clock()
    monkeypatch.setattr(agent_module.time, "monotonic", tick)
    monkeypatch.setattr(agent_module, "ACTION_DELAY_S", 0)
    return tick


class Looking(NoBrowser):
    def __init__(self) -> None:
        super().__init__()
        self.seen = PageLook(answered=True, href=f"{SUNROOM}/display", sunroom=True)

    async def look(self) -> PageLook:
        return self.seen


def test_the_start_page_follows_the_address_and_whether_it_answers(agent: Agent) -> None:
    assert agent.start_page() == f"{AGENT}/"
    agent.save(Config(url=SUNROOM, found="typed"))
    assert agent.start_page() == f"{AGENT}/opening"
    agent.reachable = True
    assert agent.start_page() == f"{SUNROOM}/display?dimmer=page&screen={PORT}"


async def test_a_found_sunroom_that_moved_is_followed(
    make_agent: Callable[..., Agent],
    sunrooms: FakeSunrooms,
    clock: Clock,
    config_path: Path,
    browser: NoBrowser,
) -> None:
    agent = make_agent()
    agent.save(Config(url=SUNROOM, sunroom_id=SUNROOM_ID, found="discovered"))
    moved = "http://192.168.1.44:8080"
    sunrooms.new[moved] = sunrooms.new.pop(SUNROOM)
    sunrooms.healthy = {moved}
    toasts: list[object] = []
    agent.hub.publish = lambda kind, data: toasts.append(data) if kind == "toast" else None  # type: ignore[method-assign]
    await agent.health_tick()  # down: noted
    clock.now += 119
    await agent.health_tick()
    assert settings_file.load(config_path).url == SUNROOM  # not yet: two minutes
    clock.now += 2
    await agent.health_tick()
    assert settings_file.load(config_path).url == moved
    assert {"message": "Found Sunroom at its new address."} in toasts
    # No page chose it, so the open one is sent there; the browser isn't restarted (ADR 0042).
    assert browser.calls == [f"navigate {moved}/display?dimmer=page&screen={PORT}"]


async def test_a_typed_address_is_never_changed_by_itself(
    make_agent: Callable[..., Agent], sunrooms: FakeSunrooms, clock: Clock, config_path: Path
) -> None:
    agent = make_agent()
    agent.save(Config(url=SUNROOM, sunroom_id=SUNROOM_ID, found="typed"))
    sunrooms.new["http://192.168.1.44:8080"] = sunrooms.new.pop(SUNROOM)
    for _ in range(3):
        await agent.health_tick()
        clock.now += 300
    assert settings_file.load(config_path).url == SUNROOM


async def test_the_watchdog_waits_two_minutes_then_shows_cant_reach(
    make_agent: Callable[..., Agent], clock: Clock
) -> None:
    browser = Looking()
    agent = make_agent(browser=browser)
    agent.save(Config(url=SUNROOM, found="typed"))
    await agent.watch_tick()
    assert browser.calls == []
    browser.seen = PageLook(answered=True, href="chrome-error://chromewebdata/", sunroom=False)
    await agent.watch_tick()
    clock.now += 119
    await agent.watch_tick()
    assert browser.calls == []
    clock.now += 2
    await agent.watch_tick()
    assert browser.calls == [f"navigate {AGENT}/cant-reach"]


async def test_its_own_pages_count_as_showing_something(
    make_agent: Callable[..., Agent], clock: Clock
) -> None:
    browser = Looking()
    agent = make_agent(browser=browser)
    agent.save(Config(url=SUNROOM, found="typed"))
    browser.seen = PageLook(answered=True, href=f"{AGENT}/cant-reach", sunroom=False)
    for _ in range(3):
        await agent.watch_tick()
        clock.now += 100
    assert browser.calls == []


async def test_a_browser_that_stopped_answering_is_started_again(
    make_agent: Callable[..., Agent], clock: Clock
) -> None:
    browser = Looking()
    agent = make_agent(browser=browser)
    agent.save(Config(url=SUNROOM, found="typed"))
    browser.seen = PageLook(answered=False)
    await agent.watch_tick()
    clock.now += 121
    await agent.watch_tick()
    assert browser.calls == [f"restart {AGENT}/cant-reach"]


async def test_every_watchdog_look_keeps_the_window_full_screen(
    make_agent: Callable[..., Agent], clock: Clock
) -> None:
    """Edge runs without its kiosk mode (ADR 0040), so each look puts it back full screen; even
    before the screen has a Sunroom, on its own pages."""

    class Counting(Looking):
        def __init__(self) -> None:
            super().__init__()
            self.kept = 0

        async def keep_full_screen(self) -> None:
            self.kept += 1

    browser = Counting()
    agent = make_agent(browser=browser)
    await agent.watch_tick()
    agent.save(Config(url=SUNROOM, found="typed"))
    await agent.watch_tick()
    assert browser.kept == 2
    assert browser.calls == []


async def test_reachability_is_published_when_it_changes(
    make_agent: Callable[..., Agent], sunrooms: FakeSunrooms, clock: Clock
) -> None:
    agent = make_agent()
    agent.save(Config(url=SUNROOM, found="typed"))
    kinds: list[str] = []
    agent.hub.publish = lambda kind, data: kinds.append(kind)  # type: ignore[method-assign]
    await agent.health_tick()
    assert agent.reachable and kinds == ["state"]
    await agent.health_tick()
    assert kinds == ["state"]  # unchanged: nothing sent
    sunrooms.healthy.clear()
    await agent.health_tick()
    assert not agent.reachable and kinds == ["state", "state"]


LOCAL = "http://localhost:8080"


async def test_run_it_here_waits_for_the_new_sunroom_then_shows_it(
    make_agent: Callable[..., Agent],
    sunrooms: FakeSunrooms,
    config_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(agent_module, "RUN_SUNROOM_PAUSE_S", 0)
    sunrooms.new[LOCAL] = {**sunrooms.new[SUNROOM], "setup_complete": False}
    sunrooms.healthy = set()  # its database is still being made
    agent = make_agent()
    said: list[tuple[str, object]] = []
    agent.hub.publish = lambda kind, data: said.append((kind, data))  # type: ignore[method-assign]
    asked = 0
    answers = agent.healthy

    async def healthy(url: str) -> bool:
        nonlocal asked
        asked += 1
        if asked == 3:
            sunrooms.healthy.add(LOCAL)
        return await answers(url)

    agent.healthy = healthy  # type: ignore[method-assign]
    await agent.run_sunroom()
    saved = settings_file.load(config_path)
    assert (saved.url, saved.found) == (LOCAL, "local")
    steps = [data for kind, data in said if kind == "run.progress"]
    assert steps[-2:] == [
        {"percent": 92, "step": "Starting Sunroom…", "message": None},
        {"percent": 100, "step": "Sunroom is running.", "message": None},
    ]
    assert not agent.running_sunroom


async def test_run_it_here_says_so_when_sunroom_never_answers(
    make_agent: Callable[..., Agent],
    sunrooms: FakeSunrooms,
    config_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(agent_module, "RUN_SUNROOM_PAUSE_S", 0)
    monkeypatch.setattr(agent_module, "RUN_SUNROOM_TRIES", 3)
    sunrooms.healthy = set()
    agent = make_agent()
    said: list[tuple[str, object]] = []
    agent.hub.publish = lambda kind, data: said.append((kind, data))  # type: ignore[method-assign]
    await agent.run_sunroom()
    # The page shows why, with Try Again: the run's last progress carries it.
    steps = [data for kind, data in said if kind == "run.progress"]
    assert steps[-1] == {
        "percent": 100,
        "step": "Stopped",
        "message": "Sunroom didn't start. Restart this screen, then try again.",
    }
    assert settings_file.load(config_path).url is None
    assert not agent.running_sunroom


async def test_a_second_tap_joins_the_run_already_going(
    make_agent: Callable[..., Agent], monkeypatch: pytest.MonkeyPatch
) -> None:
    agent = make_agent()
    started: list[object] = []
    monkeypatch.setattr(agent, "spawn", started.append)
    agent.start_run()
    agent.start_run()
    assert len(started) == 1 and agent.running_sunroom
    for work in started:  # never awaited here; close it so Python doesn't warn
        work.close()  # type: ignore[attr-defined]


def test_every_screen_installs_updates_overnight_unless_turned_off(
    make_agent: Callable[..., Agent], config_path: Path
) -> None:
    """Install overnight is every screen's default (ADR 0042; it was Sunroom OS's alone); a
    screen whose Updates was set to Off keeps Off."""
    from sunroom_kiosk.platform.fake import FakePlatform

    for kind in ("pi", "desktop"):
        assert make_agent(platform=FakePlatform(kind)).update_check() == "nightly"
    agent = make_agent()
    agent.set_update_check("off")
    assert settings_file.load(config_path).update_check == "off"
    assert make_agent().update_check() == "off"
