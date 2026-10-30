"""Shared fixtures: an agent on the pretend platform (no browser, no commands), its API through
httpx's ASGI transport, and a pretend Sunroom server for discovery (httpx.MockTransport). Nothing
here touches the network or the machine. Synthetic data only."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from sunroom_kiosk.app import create_app
from sunroom_kiosk.browser import NoBrowser
from sunroom_kiosk.discovery import Discovery
from sunroom_kiosk.events import EventHub
from sunroom_kiosk.platform.fake import FakePlatform
from sunroom_kiosk.state import Agent
from sunroom_kiosk.updater import FakeUpdater
from tests.support import AGENT, PORT, FakeSunrooms


@pytest.fixture
def sunrooms() -> FakeSunrooms:
    return FakeSunrooms()


@pytest.fixture
def config_path(tmp_path: Path) -> Path:
    return tmp_path / "sunroom-kiosk" / "config"


@pytest.fixture
def platform() -> FakePlatform:
    return FakePlatform("pi")


@pytest.fixture
def browser() -> NoBrowser:
    return NoBrowser()


@pytest.fixture
def make_agent(
    config_path: Path, platform: FakePlatform, browser: NoBrowser, sunrooms: FakeSunrooms
) -> Callable[..., Agent]:
    def make(**overrides: Any) -> Agent:
        hub = EventHub(ping_s=0.05)
        discovery = Discovery(
            hub.publish,
            client=sunrooms.client,
            addresses=lambda: [("192.168.1.30", 24)],
            announced=_nothing_announced,
        )
        options: dict[str, Any] = {
            "port": PORT,
            "config_path": config_path,
            "platform": platform,
            "browser": browser,
            "updater": FakeUpdater(step_s=0, away_s=0),
            "hub": hub,
            "discovery": discovery,
            "http": sunrooms.client,
            "fake": True,
        }
        options.update(overrides)
        return Agent(**options)

    return make


async def _nothing_announced(seconds: float) -> list[str]:
    return []


@pytest.fixture
def agent(make_agent: Callable[..., Agent]) -> Agent:
    return make_agent()


@pytest.fixture
def app(agent: Agent) -> FastAPI:
    return create_app(agent, static=None, test_routes=True, run_agent=False)


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url=AGENT) as http:
        yield http
