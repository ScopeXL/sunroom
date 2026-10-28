"""Fixtures for the meals plugin: an app running only its own Meals instance (so its context can
be called directly, and it's shown to work with every other plugin off), the Sample Family, the
wall screen and a kid's phone. Synthetic people only."""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi import FastAPI

from sunroom.app import create_app
from sunroom.core.clock import FakeClock
from sunroom.core.config import Settings
from sunroom.plugins.base import Plugin
from sunroom.plugins.context import PluginContext
from sunroom.plugins.meals.plugin import Meals
from tests.meals.helpers import Family, running
from tests.support import BASE_URL, CSRF, PASSWORD, add_member, login, set_pin


@pytest.fixture
def plugin() -> Meals:
    return Meals()


@pytest.fixture
def plugins(plugin: Meals) -> dict[str, Plugin]:
    return {"meals": plugin}


@pytest.fixture
async def app(
    settings: Settings, clock: FakeClock, plugins: dict[str, Plugin]
) -> AsyncIterator[FastAPI]:
    application = create_app(settings, clock=clock, plugins=plugins, ping_interval_s=0.05)
    async with application.router.lifespan_context(application):
        yield application


@pytest.fixture
async def ctx(plugin: Meals, parent: httpx.AsyncClient) -> PluginContext:
    """The plugin's context, once it runs (for calling its jobs directly)."""
    return await running(plugin)


@pytest.fixture
async def third(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """A third device (a kid's phone)."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as http:
        yield http


@pytest.fixture
async def family(parent: httpx.AsyncClient, ctx: PluginContext) -> Family:
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
    """The wall screen."""
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
