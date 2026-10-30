"""The meals plugin as a plugin (PLAN §6.4, §7.6, §11.4, §15 M4 verify): dinner on the calendar
as an overlay (``occurrences?overlays=meals``), the hourly prune, the Sample Family's week, and
switched off: every route answers 404 plugin_disabled, the overlay goes quiet and the data waits.

Wednesday 2026-10-07 is today (10:00 in New York). The Sample Family only."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import date
from pathlib import Path

import httpx
import pytest
from fastapi import APIRouter, FastAPI
from fastapi.routing import APIRoute
from sqlalchemy import select

from sunroom.app import create_app
from sunroom.core.clock import FakeClock, ShiftableClock
from sunroom.plugins.context import PluginContext
from sunroom.plugins.meals import service
from sunroom.plugins.meals.models import MealEntry, SavedMeal
from sunroom.plugins.meals.plugin import Meals
from tests.meals.helpers import (
    FRI,
    MEAL_GONE,
    SAT,
    SAVED_GONE,
    SUN,
    THU,
    TODAY,
    TUE,
    WED,
    WEEK,
    Events,
    Family,
    Json,
    changed_days,
    menu,
    plan,
    put_back,
    remove,
    running,
    saved_meals,
    set_meals,
    week,
)
from tests.support import BASE_URL, CSRF, make_settings, state_of

SEED_PASSWORD = "sample-family-passphrase"


async def occurrences(
    client: httpx.AsyncClient, start: date = SUN, end: date = SUN + WEEK, *, overlay: bool = True
) -> list[Json]:
    params: dict[str, str] = {"from": start.isoformat(), "to": end.isoformat()}
    if overlay:
        params["overlays"] = "meals"
    response = await client.get("/api/calendar/occurrences", params=params)
    assert response.status_code == 200, response.text
    found: list[Json] = response.json()["occurrences"]
    return found


async def stored(app: FastAPI) -> tuple[list[str], list[str]]:
    """Every meal's and saved meal's name in the database, whatever their state."""
    async with state_of(app).db.read() as session:
        entries = sorted(await session.scalars(select(MealEntry.text)))
        saved = sorted(await session.scalars(select(SavedMeal.text)))
    return entries, saved


def meals_routes() -> list[tuple[str, str]]:
    router = APIRouter()
    Meals().register_routes(router)
    found: list[tuple[str, str]] = []
    for route in router.routes:
        assert isinstance(route, APIRoute)
        path = "/api/meals" + route.path.replace("{", "").replace("}", "")
        found += [(method, path) for method in sorted(route.methods or ())]
    return found


# ---- dinner on the calendar --------------------------------------------------------------------


async def test_dinner_shows_on_the_calendar_when_the_family_asks(
    parent: httpx.AsyncClient, family: Family
) -> None:
    tacos = await plan(parent, WED, "Tacos", emoji="🌮", member_id=family.sam)
    soup = await plan(parent, WED, "Soup", position=1)
    await plan(parent, THU, "Pancakes", slot="breakfast")  # not a dinner
    await remove(parent, await plan(parent, FRI, "Pizza night"))  # removed
    await plan(parent, SUN + WEEK, "Roast chicken")  # next week
    assert await occurrences(parent) == []  # "Show dinner on the calendar" starts off
    await set_meals(parent, slots=["breakfast", "dinner"], calendar_slots=["dinner"])
    found = await occurrences(parent)
    assert [
        (o["key"], o["title"], o["start_date"], o["end_date"], o["member_ids"]) for o in found
    ] == [
        (f"meals|{soup['id']}", "Soup", "2026-10-07", "2026-10-08", []),
        (f"meals|{tacos['id']}", "🌮 Tacos", "2026-10-07", "2026-10-08", [family.sam]),
    ]
    chip = found[1]
    assert {
        key: chip[key]
        for key in chip
        if key not in ("key", "title", "start_date", "end_date", "member_ids")
    } == {
        "event_id": None,
        "recurrence_id": None,
        "calendar_id": None,
        "location": "",
        "all_day": True,
        "start_utc": None,
        "end_utc": None,
        "start_local": None,
        "end_local": None,
        "color": None,
        "calendar_color": None,
        "is_recurring": False,
        "is_override": False,
        "read_only": True,
        "source": "meals",
        "pending": False,
        "status": "confirmed",
        "overlay": "meals",
        "reminders": [],
        "reminders_off": False,
        "version": 0,
    }
    # Only asked for: the board without the overlay has none of them.
    assert await occurrences(parent, overlay=False) == []
    # [from, to): next Sunday's dinner is in next week only.
    assert [o["title"] for o in await occurrences(parent, SUN + WEEK, SUN + WEEK + WEEK)] == [
        "Roast chicken"
    ]
    assert await occurrences(parent, THU, SAT) == []


# ---- the hourly prune --------------------------------------------------------------------------


async def test_prune_forgets_what_was_removed_over_a_week_ago(
    app: FastAPI,
    parent: httpx.AsyncClient,
    ctx: PluginContext,
    family: Family,
    clock: FakeClock,
    events: Events,
) -> None:
    await plan(parent, TUE, "Tacos")
    soup = await plan(parent, WED, "Soup")
    await remove(parent, soup)
    pizza = await plan(parent, FRI, "Pizza night", emoji="🍕")
    archived = await parent.delete(f"/api/meals/saved/{pizza['saved_meal_id']}", headers=CSRF)
    assert archived.status_code == 204, archived.text
    clock.advance(days=6)
    await service.prune(ctx)  # still in Recently removed
    assert await stored(app) == (["Pizza night", "Soup", "Tacos"], ["Pizza night", "Soup", "Tacos"])
    clock.advance(days=1, minutes=1)
    events.clear()
    await service.prune(ctx)
    # The removed meal is gone; the archived saved meal too, and Friday's pizza night loses only
    # its link to it.
    assert await stored(app) == (["Pizza night", "Tacos"], ["Soup", "Tacos"])
    friday = next(e for e in (await week(parent))["entries"] if e["day"] == "2026-10-09")
    assert (friday["text"], friday["emoji"], friday["saved_meal_id"], friday["ingredients"]) == (
        "Pizza night",
        "🍕",
        None,
        [],
    )
    assert changed_days(events) == [["2026-10-07", "2026-10-09"]]
    gone = await put_back(parent, soup)
    assert (gone.status_code, gone.json()["error"]) == (404, MEAL_GONE)
    restored = await parent.post(f"/api/meals/saved/{pizza['saved_meal_id']}/restore", headers=CSRF)
    assert (restored.status_code, restored.json()["error"]) == (404, SAVED_GONE)
    # Nothing left to forget: nothing to tell.
    events.clear()
    await service.prune(ctx)
    assert changed_days(events) == []


async def test_each_meal_the_family_plans_can_show_on_the_calendar(
    parent: httpx.AsyncClient, family: Family
) -> None:
    await plan(parent, WED, "Tacos")
    await plan(parent, WED, "Leftovers", slot="lunch")
    await plan(parent, WED, "Pancakes", slot="breakfast")
    await plan(parent, WED, "Fruit", slot="breakfast", position=1)
    await plan(parent, TUE, "Soup")

    async def shown() -> list[tuple[str, str]]:
        return [(o["start_date"], o["title"]) for o in await occurrences(parent)]

    everything = ["breakfast", "lunch", "dinner", "snack"]
    await set_meals(parent, slots=everything, calendar_slots=["dinner", "breakfast"])
    # All-day chips: the calendar orders a day's by name, as it does its own.
    assert await shown() == [
        ("2026-10-06", "Soup"),
        ("2026-10-07", "Fruit"),
        ("2026-10-07", "Pancakes"),
        ("2026-10-07", "Tacos"),
    ]
    await set_meals(parent, slots=everything, calendar_slots=["lunch"])
    assert await shown() == [("2026-10-07", "Leftovers")]
    # A meal the family stopped planning isn't drawn, though its switch was on.
    await set_meals(parent, slots=["dinner"], calendar_slots=everything)
    assert await shown() == [("2026-10-06", "Soup"), ("2026-10-07", "Tacos")]
    refused = await parent.put(
        "/api/plugins/meals/settings",
        json={"values": {"slots": ["dinner"], "calendar_slots": ["brunch"]}},
        headers=CSRF,
    )
    assert refused.status_code == 422, refused.text


def test_the_old_dinner_switch_becomes_dinner_on_the_calendar() -> None:
    upgrade = Meals().upgrade_settings
    assert upgrade({"slots": ["lunch", "dinner"], "show_on_calendar": True}, "1.0.0") == {
        "slots": ["lunch", "dinner"],
        "calendar_slots": ["dinner"],
    }
    assert upgrade({"slots": ["dinner"], "show_on_calendar": False}, "1.0.0") == {
        "slots": ["dinner"],
        "calendar_slots": [],
    }
    # Nothing to carry: never set, or already in the new shape.
    assert upgrade({}, "1.0.0") == {}
    current = {"slots": ["dinner"], "calendar_slots": ["breakfast"]}
    assert upgrade(current, "1.0.0") == current


# ---- switched off, starting, signed out --------------------------------------------------------


async def test_off_every_route_is_404_and_on_again_the_data_is_there(
    parent: httpx.AsyncClient, plugin: Meals, family: Family
) -> None:
    await plan(parent, TODAY, "Tacos")
    await set_meals(parent, calendar_slots=["dinner"])
    assert len(await occurrences(parent)) == 1
    off = await parent.post("/api/plugins/meals/disable", headers=CSRF)
    assert off.status_code == 200, off.text
    assert off.json()["enabled"] is False
    routes = meals_routes()
    assert len(routes) == 12  # every route the plugin has
    for method, path in routes:
        response = await parent.request(method, path, json={}, headers=CSRF)
        assert response.status_code == 404, (method, path)
        assert response.json()["error"] == {
            "code": "plugin_disabled",
            "message": "Meals is turned off. A parent can turn it on in Settings.",
            "key": "api.plugins.turned_off",
            "params": {"name": "Meals"},
        }
    assert await occurrences(parent) == []  # the overlay goes quiet too
    on = await parent.post("/api/plugins/meals/enable", headers=CSRF)
    assert on.status_code == 200, on.text
    await running(plugin)
    assert await menu(parent) == [("2026-10-07", "dinner", 0, "Tacos")]
    assert [meal["text"] for meal in await saved_meals(parent)] == ["Tacos"]
    assert [o["title"] for o in await occurrences(parent)] == ["Tacos"]


async def test_while_meals_start_a_request_asks_to_try_again(
    parent: httpx.AsyncClient, plugin: Meals, family: Family
) -> None:
    ctx, plugin.ctx = plugin.ctx, None
    try:
        response = await parent.get("/api/meals/week")
    finally:
        plugin.ctx = ctx
    assert response.status_code == 503
    assert response.json()["error"] == {
        "code": "starting",
        "message": "Meals are still starting. Try again.",
        "key": "api.meals.starting",
        "params": {},
    }


async def test_meals_need_a_signed_in_device(app: FastAPI, parent: httpx.AsyncClient) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as stranger:
        response = await stranger.get("/api/meals/week")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "signed_out"


# ---- the Sample Family -------------------------------------------------------------------------


@pytest.fixture
async def test_server(data_dir: Path) -> AsyncIterator[FastAPI]:
    """The test server with only this plugin: ``POST /api/_test/seed`` as ``just seed`` runs it."""
    application = create_app(
        make_settings(data_dir, sunroom_test_mode=True),
        clock=ShiftableClock(),
        plugins={"meals": Meals()},
    )
    async with application.router.lifespan_context(application):
        yield application


async def test_the_sample_family_has_a_week_of_dinners(test_server: FastAPI) -> None:
    transport = httpx.ASGITransport(app=test_server)
    async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as phone:
        moved = await phone.post(
            "/api/_test/clock", json={"set": "2026-10-07T14:00:00Z"}, headers=CSRF
        )
        assert moved.status_code == 204, moved.text
        seeded = await phone.post("/api/_test/seed", json={"password": SEED_PASSWORD}, headers=CSRF)
        assert seeded.status_code == 204, seeded.text
        signed = await phone.post("/api/auth/login", json={"password": SEED_PASSWORD}, headers=CSRF)
        assert signed.status_code == 200, signed.text
        names = {m["id"]: m["name"] for m in (await phone.get("/api/members")).json()}
        this_week = (await phone.get("/api/meals/week")).json()
        assert this_week["start"] == "2026-10-04"  # Sunday
        assert [
            (e["day"], e["emoji"], e["text"], names.get(e["member_id"]))
            for e in this_week["entries"]
        ] == [
            ("2026-10-04", "🍗", "Roast chicken", "Ana"),
            ("2026-10-05", "🍝", "Pasta night", None),
            ("2026-10-06", "🐟", "Salmon and rice", "Sam"),
            ("2026-10-07", "🌮", "Tacos", "Sam"),
            ("2026-10-08", None, "Leftovers", None),
            ("2026-10-09", "🍕", "Pizza night", "Ana"),
        ]
        [tonight] = (await week(phone, TODAY, days=1))["entries"]
        assert tonight["ingredients"] == ["Tortillas", "Ground beef", "Cheese", "Lettuce", "Salsa"]
        last_week = await menu(phone, SUN - WEEK)
        assert [day for day, *_ in last_week] == [
            "2026-09-27",
            "2026-09-28",
            "2026-09-29",
            "2026-09-30",
            "2026-10-01",
            "2026-10-02",
        ]
        library = await saved_meals(phone)
        assert [(meal["text"], meal["use_count"]) for meal in library] == [
            ("Tacos", 9),
            ("Pizza night", 7),
            ("Pasta night", 6),
            ("Leftovers", 5),
            ("Roast chicken", 4),
            ("Salmon and rice", 3),
            ("Grilled cheese and soup", 2),
        ]
        pasta = next(meal for meal in library if meal["text"] == "Pasta night")
        assert pasta["ingredients"] == ["Pasta", "Tomato sauce", "Parmesan"]
        # Seeding again adds nothing twice.
        again = await phone.post("/api/_test/seed", json={"password": SEED_PASSWORD}, headers=CSRF)
        assert again.status_code == 204, again.text
        assert len((await week(phone, SUN - WEEK, days=14))["entries"]) == 12
        assert len(await saved_meals(phone)) == 7
