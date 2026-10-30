"""Helpers for the countdowns tests. Wednesday 2026-10-07 is today (14:00 UTC, 10:00 in New
York). The Sample Family's birthdays: Ana April 12, 1988; Mia October 19, 2017; Leo February 3,
2020; Sam has none set."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import httpx

from sunroom.plugins.context import PluginContext
from sunroom.plugins.countdowns.plugin import Countdowns
from tests.support import CSRF

Json = dict[str, Any]
Events = list[tuple[str, dict[str, Any]]]
TODAY = date(2026, 10, 7)
GONE: dict[str, Any] = {
    "code": "not_found",
    "message": "That countdown isn't here any more.",
    "key": "api.countdowns.gone",
    "params": {},
}


@dataclass(frozen=True, slots=True)
class Family:
    ana: str
    sam: str
    mia: str
    leo: str


def tapped(member_id: str) -> dict[str, str]:
    """A wall-screen request saying who tapped."""
    return CSRF | {"X-Sunroom-Member": member_id}


def day(offset: int) -> str:
    """The household's today plus ``offset`` days, as the API writes a date."""
    return (TODAY + timedelta(days=offset)).isoformat()


async def add_countdown(
    client: httpx.AsyncClient,
    title: str,
    on: str,
    *,
    headers: dict[str, str] = CSRF,
    **body: Any,
) -> Json:
    response = await client.post(
        "/api/countdowns", json={"title": title, "date": on} | body, headers=headers
    )
    assert response.status_code == 201, response.text
    made: Json = response.json()
    return made


async def change(client: httpx.AsyncClient, countdown: Json, **body: Any) -> Json:
    response = await client.patch(f"/api/countdowns/{countdown['id']}", json=body, headers=CSRF)
    assert response.status_code == 200, response.text
    changed: Json = response.json()
    return changed


async def listed(client: httpx.AsyncClient) -> list[Json]:
    response = await client.get("/api/countdowns")
    assert response.status_code == 200, response.text
    found: list[Json] = response.json()
    return found


async def upcoming(client: httpx.AsyncClient, **params: Any) -> Json:
    response = await client.get("/api/countdowns/upcoming", params=params)
    assert response.status_code == 200, response.text
    found: Json = response.json()
    return found


async def removed(client: httpx.AsyncClient) -> list[Json]:
    response = await client.get("/api/countdowns/removed")
    assert response.status_code == 200, response.text
    found: list[Json] = response.json()
    return found


async def overlaid(client: httpx.AsyncClient, start: str, end: str) -> list[Json]:
    """The calendar's countdown occurrences in [start, end)."""
    response = await client.get(
        "/api/calendar/occurrences",
        params={"from": start, "to": end, "overlays": "countdowns"},
    )
    assert response.status_code == 200, response.text
    found: list[Json] = response.json()["occurrences"]
    return [item for item in found if item["overlay"] == "countdowns"]


def titles(items: list[Json]) -> list[str]:
    return [item["title"] for item in items]


def changed_ids(events: Events) -> list[str]:
    return [payload["id"] for kind, payload in events if kind == "countdowns.changed"]


def error(response: httpx.Response) -> tuple[int, str, str]:
    body = response.json()["error"]
    return response.status_code, body["code"], body["message"]


async def running(plugin: Countdowns) -> PluginContext:
    """Turning the plugin on returns before its own task has started it."""
    for _ in range(300):
        if plugin.ctx is not None:
            return plugin.ctx
        await asyncio.sleep(0.01)
    raise AssertionError("the countdowns plugin never started")
