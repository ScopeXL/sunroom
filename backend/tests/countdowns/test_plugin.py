"""The countdowns plugin on the calendar, in its hourly job and as a plugin (PLAN §6.4, §7.6,
§11.4, §15 M4): countdowns as all-day read-only overlay chips, never before their first date and
never a surprise (birthdays are the core's own overlay since M6, ADR 0028); the tidy that moves
past countdowns to Recently removed and forgets them a week later; switched off, every route
answers 404 plugin_disabled and the data waits; the Sample Family's countdowns. Wednesday
2026-10-07 is today (10:00 in New York). The Sample Family only."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pytest
from fastapi import APIRouter, FastAPI
from fastapi.routing import APIRoute
from sqlalchemy import select

from sunroom.app import create_app
from sunroom.core.clock import FakeClock
from sunroom.plugins.base import PluginStatus
from sunroom.plugins.context import PluginContext
from sunroom.plugins.countdowns import service
from sunroom.plugins.countdowns.models import Countdown
from sunroom.plugins.countdowns.plugin import Countdowns
from tests.countdowns.helpers import (
    GONE,
    Events,
    Family,
    Json,
    add_countdown,
    changed_ids,
    day,
    listed,
    overlaid,
    removed,
    titles,
    upcoming,
)
from tests.support import BASE_URL, CSRF, make_settings, state_of

SEED_PASSWORD = "sample-family-passphrase"


async def eventually(condition: Callable[[], bool], within_s: float = 2.0) -> None:
    deadline = asyncio.get_running_loop().time() + within_s
    while not condition():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition never became true")
        await asyncio.sleep(0.01)


async def stored(app: FastAPI) -> set[str]:
    """Every countdown in the database, removed or not."""
    async with state_of(app).db.read() as session:
        return set(await session.scalars(select(Countdown.title)))


# ---- the calendar ------------------------------------------------------------------------------


async def test_the_calendar_shows_countdowns_but_leaves_birthdays_to_the_core(
    parent: httpx.AsyncClient, family: Family
) -> None:
    fair = await add_countdown(parent, "Fall fair", day(3), member_id=family.mia, color="clay")
    await add_countdown(parent, "Halloween", "2024-10-31", repeat_yearly=True)
    await add_countdown(parent, "Ana's surprise party", day(20), show_on_display=False)
    zoo = await add_countdown(parent, "Zoo day", day(9))
    assert (await parent.delete(f"/api/countdowns/{zoo['id']}", headers=CSRF)).status_code == 204
    found = await overlaid(parent, "2026-10-04", "2026-11-01")
    assert [(o["title"], o["start_date"], o["member_ids"]) for o in found] == [
        ("Fall fair", "2026-10-10", [family.mia]),
        ("Halloween", "2026-10-31", []),
    ]
    assert found[0] == {
        "key": f"countdowns|{fair['id']}|2026-10-10",
        "event_id": None,
        "recurrence_id": None,
        "calendar_id": None,
        "title": "Fall fair",
        "location": "",
        "all_day": True,
        "start_utc": None,
        "end_utc": None,
        "start_local": None,
        "end_local": None,
        "start_date": "2026-10-10",
        "end_date": "2026-10-11",
        "member_ids": [family.mia],
        "color": "clay",
        "calendar_color": None,
        "is_recurring": False,
        "is_override": False,
        "read_only": True,
        "source": "countdowns",
        "pending": False,
        "status": "confirmed",
        "overlay": "countdowns",
        "reminders": [],
        "reminders_off": False,
        "version": 0,
    }
    # Unasked, the calendar is events only.
    plain = await parent.get(
        "/api/calendar/occurrences", params={"from": "2026-10-04", "to": "2026-11-01"}
    )
    assert plain.json()["occurrences"] == []

    # Mia's birthday is the core's chip, whatever Countdowns' own birthdays setting says.
    async def core_birthdays() -> list[tuple[str, str]]:
        response = await parent.get(
            "/api/calendar/occurrences",
            params={"from": "2026-10-04", "to": "2026-11-01", "overlays": "birthdays"},
        )
        return [(o["title"], o["start_date"]) for o in response.json()["occurrences"]]

    assert await core_birthdays() == [("Mia's birthday", "2026-10-19")]
    switched = await parent.put(
        "/api/plugins/countdowns/settings", json={"values": {"birthdays": False}}, headers=CSRF
    )
    assert switched.status_code == 200, switched.text
    assert titles(await overlaid(parent, "2026-10-04", "2026-11-01")) == ["Fall fair", "Halloween"]
    assert await core_birthdays() == [("Mia's birthday", "2026-10-19")]


async def test_a_yearly_day_comes_round_each_year_from_its_first(
    parent: httpx.AsyncClient, family: Family
) -> None:
    await add_countdown(parent, "New Year's Eve", "2026-12-31", repeat_yearly=True)
    await add_countdown(parent, "Winter break", "2027-01-04", repeat_yearly=True)
    await add_countdown(parent, "Leap day party", "2016-02-29", repeat_yearly=True)

    async def winter(start: str, end: str) -> list[tuple[str, str]]:
        return [(o["title"], o["start_date"]) for o in await overlaid(parent, start, end)]

    assert await winter("2026-12-01", "2027-03-01") == [
        ("New Year's Eve", "2026-12-31"),
        ("Winter break", "2027-01-04"),
        ("Leap day party", "2027-02-28"),
    ]
    assert await winter("2027-12-01", "2028-03-01") == [
        ("New Year's Eve", "2027-12-31"),
        ("Winter break", "2028-01-04"),
        ("Leap day party", "2028-02-29"),
    ]
    # A year before their first, neither had started.
    assert await winter("2025-12-01", "2026-03-01") == [("Leap day party", "2026-02-28")]


async def test_the_overlay_counts_from_the_first_day_up_to_the_last(
    parent: httpx.AsyncClient, family: Family, ctx: PluginContext
) -> None:
    await add_countdown(parent, "Fall fair", day(3))  # Saturday the 10th

    async def span(start: int, end: int) -> list[str]:
        found = await service.overlay(ctx, date(2026, 10, start), date(2026, 10, end), ctx.zone())
        return [occurrence.title for occurrence in found]

    assert await span(10, 11) == ["Fall fair"]
    assert await span(9, 10) == []  # the last day isn't in it
    assert await span(11, 20) == []  # Mia's birthday on the 19th is the core's chip now


# ---- the hourly tidy ---------------------------------------------------------------------------


async def test_the_hourly_tidy_moves_past_countdowns_and_forgets_them(
    app: FastAPI,
    parent: httpx.AsyncClient,
    family: Family,
    ctx: PluginContext,
    clock: FakeClock,
    events: Events,
) -> None:
    fair = await add_countdown(parent, "Fall fair", day(0))
    zoo = await add_countdown(parent, "Zoo day", day(1))
    await add_countdown(parent, "Halloween", "2024-10-31", repeat_yearly=True)
    sale = await add_countdown(parent, "Bake sale", day(2))
    assert (await parent.delete(f"/api/countdowns/{sale['id']}", headers=CSRF)).status_code == 204
    events.clear()
    # 11:59 PM in New York: the fair is still today there.
    clock.set(datetime(2026, 10, 8, 3, 59, tzinfo=UTC))
    await service.tidy(ctx)
    assert titles(await listed(parent)) == ["Fall fair", "Zoo day", "Halloween"]
    assert changed_ids(events) == []
    # Midnight there: the fair has passed, and leaves for Recently removed.
    clock.set(datetime(2026, 10, 8, 4, 0, tzinfo=UTC))
    await service.tidy(ctx)
    assert titles(await listed(parent)) == ["Zoo day", "Halloween"]
    assert [(r["title"], r["deleted_at"]) for r in await removed(parent)] == [
        ("Fall fair", "2026-10-08T04:00:00Z"),
        ("Bake sale", "2026-10-07T14:00:00Z"),
    ]
    assert changed_ids(events) == [fair["id"]]
    # A week after its removal the bake sale is gone for good; the zoo day has passed too.
    events.clear()
    clock.set(datetime(2026, 10, 14, 14, 1, tzinfo=UTC))
    await service.tidy(ctx)
    assert await stored(app) == {"Fall fair", "Zoo day", "Halloween"}
    assert titles(await removed(parent)) == ["Zoo day", "Fall fair"]
    assert sorted(changed_ids(events)) == sorted([zoo["id"], sale["id"]])
    put_back = await parent.post(f"/api/countdowns/{sale['id']}/restore", headers=CSRF)
    assert (put_back.status_code, put_back.json()["error"]) == (404, GONE)
    # A yearly countdown never leaves.
    clock.set(datetime(2026, 11, 2, 14, 0, tzinfo=UTC))
    await service.tidy(ctx)
    assert await stored(app) == {"Halloween"}
    [halloween] = (await upcoming(parent, include_birthdays=False))["items"]
    assert (halloween["title"], halloween["date"]) == ("Halloween", "2027-10-31")


# ---- switched off ------------------------------------------------------------------------------


def countdown_routes() -> list[tuple[str, str]]:
    router = APIRouter()
    Countdowns().register_routes(router)
    found: list[tuple[str, str]] = []
    for route in router.routes:
        assert isinstance(route, APIRoute)
        found += [(method, route.path) for method in sorted(route.methods or ())]
    return found


async def test_off_every_route_is_404_and_on_again_the_data_is_there(
    app: FastAPI, parent: httpx.AsyncClient, family: Family
) -> None:
    fair = await add_countdown(parent, "Fall fair", day(3))
    off = await parent.post("/api/plugins/countdowns/disable", headers=CSRF)
    assert off.status_code == 200, off.text
    routes = countdown_routes()
    assert len(routes) == 7  # every route the plugin has
    for method, path in routes:
        url = "/api/countdowns" + path.format(countdown_id=fair["id"])
        body: Json | None = {} if method in {"POST", "PATCH"} else None
        response = await parent.request(method, url, json=body, headers=CSRF)
        assert response.status_code == 404, (method, url)
        assert response.json()["error"] == {
            "code": "plugin_disabled",
            "message": "Countdowns is turned off. A parent can turn it on in Settings.",
            "key": "api.plugins.turned_off",
            "params": {"name": "Countdowns"},
        }
    assert await overlaid(parent, "2026-10-04", "2026-11-01") == []  # off the calendar too
    on = await parent.post("/api/plugins/countdowns/enable", headers=CSRF)
    assert on.status_code == 200, on.text
    manager = state_of(app).plugins
    await eventually(lambda: manager.status("countdowns") is PluginStatus.RUNNING)
    assert titles(await listed(parent)) == ["Fall fair"]
    assert titles(await overlaid(parent, "2026-10-04", "2026-11-01")) == ["Fall fair"]


# ---- the Sample Family -------------------------------------------------------------------------


@pytest.fixture
async def seeded(data_dir: Path, clock: FakeClock) -> AsyncIterator[httpx.AsyncClient]:
    """The test server with only this plugin, the Sample Family seeded, a phone signed in."""
    application = create_app(
        make_settings(data_dir, sunroom_test_mode=True),
        clock=clock,
        plugins={"countdowns": Countdowns()},
    )
    async with application.router.lifespan_context(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as phone:
            body = {"password": SEED_PASSWORD, "events": False}
            response = await phone.post("/api/_test/seed", json=body, headers=CSRF)
            assert response.status_code == 204, response.text
            signed = await phone.post(
                "/api/auth/login", json={"password": SEED_PASSWORD}, headers=CSRF
            )
            assert signed.status_code == 200, signed.text
            yield phone


async def test_the_sample_family_counts_down(seeded: httpx.AsyncClient) -> None:
    found = await upcoming(seeded)
    assert [(i["kind"], i["title"], i["emoji"], i["date"], i["days"]) for i in found["items"]] == [
        ("birthday", "Mia's birthday", None, "2026-10-09", 2),
        ("countdown", "Grandma visits", "👵", "2026-10-12", 5),
        ("countdown", "Camping trip", "⛺", "2026-10-24", 17),
        ("countdown", "Halloween", "🎃", "2026-10-31", 24),
        ("countdown", "Ana's surprise party", "🎉", "2026-11-16", 40),
        ("birthday", "Leo's birthday", None, "2027-02-03", 119),
        ("birthday", "Ana's birthday", None, "2027-04-12", 187),
    ]
    people = {m["name"]: m["id"] for m in (await seeded.get("/api/members")).json()}
    rows = {row["title"]: row for row in await listed(seeded)}
    grandma, camping = rows["Grandma visits"], rows["Camping trip"]
    halloween, party = rows["Halloween"], rows["Ana's surprise party"]
    assert (grandma["member_id"], grandma["created_by_member_id"]) == (None, people["Ana"])
    assert (camping["color"], camping["member_id"]) == ("moss", None)
    assert (halloween["repeat_yearly"], halloween["member_id"]) == (True, people["Mia"])
    assert halloween["created_by_member_id"] == people["Mia"]
    assert (party["show_on_display"], party["created_by_member_id"]) == (False, people["Sam"])
    # Seeding again adds nothing twice.
    again = await seeded.post(
        "/api/_test/seed", json={"password": SEED_PASSWORD, "events": False}, headers=CSRF
    )
    assert again.status_code == 204, again.text
    assert len(await listed(seeded)) == 4
