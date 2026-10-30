"""Helpers for the meals tests. Wednesday 2026-10-07 is today (14:00 UTC, 10:00 in New York);
the household's week starts on Sunday."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import httpx

from sunroom.plugins.context import PluginContext
from sunroom.plugins.meals.plugin import Meals
from tests.support import CSRF

SUN, MON, TUE, WED, THU, FRI, SAT = (date(2026, 10, day) for day in range(4, 11))
TODAY = WED
DAY = timedelta(days=1)
WEEK = timedelta(days=7)
MEAL_GONE: dict[str, Any] = {
    "code": "not_found",
    "message": "That meal isn't here any more.",
    "key": "api.meals.meal_gone",
    "params": {},
}
SAVED_GONE: dict[str, Any] = {
    "code": "not_found",
    "message": "That saved meal isn't here any more.",
    "key": "api.meals.saved_gone",
    "params": {},
}

Json = dict[str, Any]
Events = list[tuple[str, dict[str, Any]]]
Row = tuple[str, str, int, str]  # day, slot, position, text


@dataclass(frozen=True, slots=True)
class Family:
    ana: str
    sam: str
    mia: str
    leo: str


async def running(plugin: Meals) -> PluginContext:
    """Turning the plugin on returns before its own task has started it."""
    for _ in range(300):
        if plugin.ctx is not None:
            return plugin.ctx
        await asyncio.sleep(0.01)
    raise AssertionError("the meals plugin never started")


def tapped(member_id: str) -> dict[str, str]:
    """A wall-screen request saying who tapped."""
    return CSRF | {"X-Sunroom-Member": member_id}


async def put_entry(
    client: httpx.AsyncClient,
    day: date,
    text: str,
    *,
    headers: dict[str, str] = CSRF,
    **body: Any,
) -> httpx.Response:
    """PUT meals/entries: a meal on ``day``, plus whatever else ``body`` says."""
    sent = {"day": day.isoformat(), "text": text} | body
    return await client.put("/api/meals/entries", json=sent, headers=headers)


async def plan(
    client: httpx.AsyncClient,
    day: date,
    text: str,
    *,
    headers: dict[str, str] = CSRF,
    **body: Any,
) -> Json:
    """Put a meal on a day; returns the entry."""
    response = await put_entry(client, day, text, headers=headers, **body)
    assert response.status_code == 200, response.text
    entry: Json = response.json()["entry"]
    return entry


async def remove(client: httpx.AsyncClient, entry: Json) -> None:
    response = await client.delete(f"/api/meals/entries/{entry['id']}", headers=CSRF)
    assert response.status_code == 204, response.text


async def put_back(client: httpx.AsyncClient, entry: Json) -> httpx.Response:
    return await client.post(f"/api/meals/entries/{entry['id']}/restore", headers=CSRF)


async def move(
    client: httpx.AsyncClient,
    entry: Json,
    day: date,
    *,
    headers: dict[str, str] = CSRF,
    **body: Any,
) -> Json:
    response = await client.post(
        f"/api/meals/entries/{entry['id']}/move",
        json={"day": day.isoformat()} | body,
        headers=headers,
    )
    assert response.status_code == 200, response.text
    moved: Json = response.json()
    return moved


async def copy_week(
    client: httpx.AsyncClient, source: date, target: date, *, headers: dict[str, str] = CSRF
) -> httpx.Response:
    body = {"from_start": source.isoformat(), "to_start": target.isoformat()}
    return await client.post("/api/meals/copy-week", json=body, headers=headers)


async def week(client: httpx.AsyncClient, start: date = SUN, days: int = 7) -> Json:
    params = {"start": start.isoformat(), "days": str(days)}
    response = await client.get("/api/meals/week", params=params)
    assert response.status_code == 200, response.text
    found: Json = response.json()
    return found


def rows(entries: list[Json]) -> list[Row]:
    return [(e["day"], e["slot"], e["position"], e["text"]) for e in entries]


async def menu(client: httpx.AsyncClient, start: date = SUN, days: int = 7) -> list[Row]:
    """The meals of the days from ``start``, as (day, slot, position, text)."""
    return rows((await week(client, start, days))["entries"])


async def saved_meals(client: httpx.AsyncClient, q: str | None = None) -> list[Json]:
    response = await client.get("/api/meals/saved", params={"q": q} if q is not None else None)
    assert response.status_code == 200, response.text
    found: list[Json] = response.json()
    return found


async def uses(client: httpx.AsyncClient) -> dict[str, int]:
    """Each saved meal's use count, by name."""
    return {meal["text"]: meal["use_count"] for meal in await saved_meals(client)}


async def save_meal(client: httpx.AsyncClient, text: str, **body: Any) -> Json:
    response = await client.post("/api/meals/saved", json={"text": text} | body, headers=CSRF)
    assert response.status_code == 201, response.text
    saved: Json = response.json()
    return saved


async def removed(client: httpx.AsyncClient) -> Json:
    response = await client.get("/api/meals/removed")
    assert response.status_code == 200, response.text
    found: Json = response.json()
    return found


async def set_meals(client: httpx.AsyncClient, **values: Any) -> None:
    """The plugin's settings. What isn't sent takes its default: Dinner only, and not on the
    calendar."""
    response = await client.put(
        "/api/plugins/meals/settings", json={"values": values}, headers=CSRF
    )
    assert response.status_code == 200, response.text


def error(response: httpx.Response) -> tuple[int, str, str]:
    body = response.json()["error"]
    return response.status_code, body["code"], body["message"]


def changed_days(events: Events) -> list[list[str]]:
    """The days each ``meals.changed`` event named, in order."""
    return [payload["days"] for kind, payload in events if kind == "meals.changed"]
