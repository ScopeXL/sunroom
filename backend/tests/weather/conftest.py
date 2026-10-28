"""Fixtures for the weather plugin: an app running only its own Weather (so it's shown working with
every other plugin off), with Open-Meteo's hosts scripted behind the real guarded client (sockets
are off: a fake resolver and httpx's MockTransport stand in), the Sample Family, the wall screen
and a kid's phone. The fake clock reads Wednesday 2026-10-07, 10:00 in New York. Synthetic data
only."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from sunroom.app import create_app
from sunroom.core.clock import FakeClock
from sunroom.plugins.context import PluginContext
from tests.support import (
    BASE_URL,
    CSRF,
    PASSWORD,
    add_member,
    login,
    make_settings,
    set_pin,
)
from tests.weather.helpers import Family, OpenMeteo, TrackedWeather, resolve, running


@pytest.fixture
def open_meteo() -> OpenMeteo:
    return OpenMeteo()


@pytest.fixture
def plugin() -> TrackedWeather:
    return TrackedWeather()


@pytest.fixture
def test_mode() -> bool:
    """The test server (SUNROOM_TEST_MODE) when a module says so."""
    return False


@pytest.fixture
async def app(
    data_dir: Path,
    clock: FakeClock,
    plugin: TrackedWeather,
    open_meteo: OpenMeteo,
    test_mode: bool,
) -> AsyncIterator[FastAPI]:
    application = create_app(
        make_settings(data_dir, sunroom_test_mode=test_mode),
        clock=clock,
        plugins={"weather": plugin},
        resolver=resolve,
        http_transport=open_meteo.transport(),
        ping_interval_s=0.05,
    )
    async with application.router.lifespan_context(application):
        yield application


@pytest.fixture
async def ctx(parent: httpx.AsyncClient, plugin: TrackedWeather) -> PluginContext:
    """The running plugin's context, once the household is set up."""
    return await running(plugin)


@pytest.fixture
async def third(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """A third device (a kid's phone)."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as http:
        yield http


@pytest.fixture
async def family(parent: httpx.AsyncClient) -> Family:
    """Ana and Sam (parents), Mia and Leo (kids); the phone that ran setup is Ana's."""
    ana = await add_member(parent, "Ana")
    sam = await add_member(parent, "Sam")
    mia = await add_member(parent, "Mia", "kid")
    leo = await add_member(parent, "Leo", "kid")
    chosen = await parent.put("/api/auth/member", json={"member_id": ana["id"]}, headers=CSRF)
    assert chosen.status_code == 200, chosen.text
    return Family(ana["id"], sam["id"], mia["id"], leo["id"])


@pytest.fixture
async def screen(other: httpx.AsyncClient, family: Family) -> httpx.AsyncClient:
    """The wall screen. Without a parent PIN it counts as a parent (ADR 0006)."""
    paired = await other.post(
        "/api/auth/kiosk/pair-with-password", json={"password": PASSWORD}, headers=CSRF
    )
    assert paired.status_code == 200, paired.text
    return other


@pytest.fixture
async def kid_phone(
    parent: httpx.AsyncClient, third: httpx.AsyncClient, family: Family
) -> httpx.AsyncClient:
    """Leo's phone, marked as a kid's (which needs a parent PIN first)."""
    device = (await login(third)).json()["device_id"]
    await set_pin(parent)
    marked = await parent.patch(
        f"/api/auth/devices/{device}", json={"is_kid_device": True}, headers=CSRF
    )
    assert marked.status_code == 200, marked.text
    chosen = await third.put("/api/auth/member", json={"member_id": family.leo}, headers=CSRF)
    assert chosen.status_code == 200, chosen.text
    return third
