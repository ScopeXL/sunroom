"""Countdowns through the API (PLAN §9, §11.3; UX §4 "Countdowns room"): adding one with who
made it (a phone's person, the wall screen's tapped person), what makes sense, the room's order,
changing only what's sent, a new day or repeat, Recently removed and Put back, surprises kept
off the wall, live events, and what isn't here. Only this plugin is registered, so it is shown
working with every other plugin off. Wednesday 2026-10-07 is today (10:00 in New York). The
Sample Family only."""

from __future__ import annotations

from typing import Any

import httpx
from fastapi import FastAPI

from sunroom.core.clock import FakeClock
from sunroom.plugins.context import PluginContext
from sunroom.plugins.countdowns.plugin import Countdowns
from tests.countdowns.helpers import (
    GONE,
    Events,
    Family,
    Json,
    add_countdown,
    change,
    changed_ids,
    day,
    error,
    listed,
    removed,
    tapped,
    titles,
    upcoming,
)
from tests.support import BASE_URL, CSRF


def at(countdown: Json) -> str:
    return f"/api/countdowns/{countdown['id']}"


# ---- adding ------------------------------------------------------------------------------------


async def test_a_countdown_keeps_what_the_family_picked(
    parent: httpx.AsyncClient, family: Family
) -> None:
    beach = await add_countdown(
        parent,
        "  Beach trip ",
        day(10),
        emoji=" 🏖️ ",
        color="sea",
        time="09:30",
        member_id=family.mia,
    )
    assert {key: value for key, value in beach.items() if key != "id"} == {
        "title": "Beach trip",
        "emoji": "🏖️",
        "color": "sea",
        "date": "2026-10-17",
        "time": "09:30",
        "repeat_yearly": False,
        "member_id": family.mia,
        "show_on_display": True,
        "created_by_member_id": family.ana,  # the phone's person
        "created_at": "2026-10-07T14:00:00Z",
    }
    plain = await add_countdown(parent, "Last day of school", day(60), emoji="")
    assert (plain["emoji"], plain["color"], plain["time"], plain["member_id"]) == (
        None,
        None,
        None,
        None,
    )
    assert (plain["repeat_yearly"], plain["show_on_display"]) == (False, True)
    assert [c["id"] for c in await listed(parent)] == [beach["id"], plain["id"]]


async def test_the_wall_screen_says_who_made_it(
    parent: httpx.AsyncClient, screen: httpx.AsyncClient, family: Family
) -> None:
    patch = await add_countdown(screen, "Pumpkin patch", day(3), headers=tapped(family.mia))
    assert patch["created_by_member_id"] == family.mia
    fair = await add_countdown(screen, "Fall fair", day(4))
    assert fair["created_by_member_id"] is None  # nobody tapped: Everyone
    # A phone is always its own person, whatever the header says.
    sale = await add_countdown(parent, "Bake sale", day(5), headers=tapped(family.leo))
    assert sale["created_by_member_id"] == family.ana


async def test_a_kids_phone_counts_down_too(
    parent: httpx.AsyncClient, kid_phone: httpx.AsyncClient, family: Family
) -> None:
    party = await add_countdown(kid_phone, "Leo's party", day(20), emoji="🎈", member_id=family.leo)
    assert party["created_by_member_id"] == family.leo
    assert (await change(kid_phone, party, date=day(21)))["date"] == day(21)
    assert (await kid_phone.delete(at(party), headers=CSRF)).status_code == 204
    assert (await kid_phone.post(f"{at(party)}/restore", headers=CSRF)).status_code == 200
    # Countdowns never ask for a parent: a kid changes a parent's one too.
    zoo = await add_countdown(parent, "Zoo day", day(9))
    assert (await change(kid_phone, zoo, title="Zoo trip"))["title"] == "Zoo trip"
    assert titles(await listed(kid_phone)) == ["Zoo trip", "Leo's party"]


async def test_a_countdown_must_make_sense(parent: httpx.AsyncClient, family: Family) -> None:
    async def refused(**body: Any) -> Json:
        response = await parent.post(
            "/api/countdowns", json={"title": "Fall fair", "date": day(3)} | body, headers=CSRF
        )
        assert response.status_code == 422, response.text
        problem: Json = response.json()["error"]
        return problem

    def invalid(message: str, field: str, key: str = "api.invalid") -> Json:
        return {"code": "invalid", "message": message, "key": key, "params": {}, "fields": [field]}

    assert await refused(date=day(-1)) == invalid(
        "Pick a day that hasn't passed.", "date", "api.countdowns.day_passed"
    )
    stranger = invalid(
        "That person isn't in the family.", "member_id", "api.countdowns.not_in_family"
    )
    assert await refused(member_id="someone-else") == stranger
    archived = await parent.post(f"/api/members/{family.leo}/archive", headers=CSRF)
    assert archived.status_code == 200, archived.text
    assert await refused(member_id=family.leo) == stranger
    for field, value in (
        ("title", "  "),
        ("title", "x" * 81),
        ("emoji", "🎉" * 17),
        ("color", "plaid"),
        ("time", "25:00"),
        ("time", "9:30"),
        ("date", "someday"),
    ):
        assert await refused(**{field: value}) == invalid(
            "Some of the details aren't valid.", field
        ), (field, value)
    assert await listed(parent) == []
    # Today hasn't passed, and a yearly one set years ago counts down to its next date.
    await add_countdown(parent, "Fall fair", day(0))
    halloween = await add_countdown(parent, "Halloween", "2020-10-31", repeat_yearly=True)
    assert halloween["date"] == "2020-10-31"
    assert titles(await listed(parent)) == ["Fall fair", "Halloween"]


async def test_countdowns_are_listed_soonest_first(
    parent: httpx.AsyncClient, family: Family, clock: FakeClock
) -> None:
    await add_countdown(parent, "Halloween", "2025-10-31", repeat_yearly=True)
    await add_countdown(parent, "Graduation", "2027-06-01")
    await add_countdown(parent, "Anniversary", "2019-10-08", repeat_yearly=True)
    await add_countdown(parent, "Fall fair", day(0))
    await add_countdown(parent, "Corn maze", day(3))
    await add_countdown(parent, "apple picking", day(3))
    assert [(c["title"], c["date"]) for c in await listed(parent)] == [
        ("Fall fair", "2026-10-07"),
        ("Anniversary", "2019-10-08"),  # as set: a yearly one's first date
        ("apple picking", "2026-10-10"),
        ("Corn maze", "2026-10-10"),
        ("Halloween", "2025-10-31"),
        ("Graduation", "2027-06-01"),
    ]
    # The next day the fair has passed: it comes last until the hourly tidy takes it.
    clock.advance(days=1)
    assert titles(await listed(parent)) == [
        "Anniversary",
        "apple picking",
        "Corn maze",
        "Halloween",
        "Graduation",
        "Fall fair",
    ]


# ---- changing ----------------------------------------------------------------------------------


async def test_a_change_changes_only_what_is_sent(
    parent: httpx.AsyncClient, family: Family
) -> None:
    beach = await add_countdown(
        parent, "Beach trip", day(10), emoji="🏖️", color="sea", time="09:30", member_id=family.mia
    )
    renamed = await change(parent, beach, title="Beach day")
    assert renamed == beach | {"title": "Beach day"}
    assert await change(parent, beach) == renamed  # nothing sent, nothing changed
    cleared = await change(
        parent, beach, emoji="", clear_color=True, clear_time=True, clear_member=True
    )
    assert (cleared["emoji"], cleared["color"], cleared["time"], cleared["member_id"]) == (
        None,
        None,
        None,
        None,
    )
    picked = await change(
        parent,
        beach,
        emoji="🌊",
        color="sky",
        time="08:00",
        member_id=family.leo,
        show_on_display=False,
    )
    assert (
        picked["emoji"],
        picked["color"],
        picked["time"],
        picked["member_id"],
        picked["show_on_display"],
    ) == ("🌊", "sky", "08:00", family.leo, False)
    # A clear switch wins over a value sent beside it, and needs no one real.
    both = await change(
        parent,
        beach,
        color="moss",
        clear_color=True,
        time="07:00",
        clear_time=True,
        member_id="someone-else",
        clear_member=True,
    )
    assert (both["color"], both["time"], both["member_id"]) == (None, None, None)
    refused = await parent.patch(at(beach), json={"member_id": "someone-else"}, headers=CSRF)
    assert error(refused) == (422, "invalid", "That person isn't in the family.")
    assert (await listed(parent))[0] == both  # nothing half-changed
    assert both["created_by_member_id"] == family.ana  # who made it stays


async def test_a_new_day_or_repeat(parent: httpx.AsyncClient, family: Family) -> None:
    fair = await add_countdown(parent, "Fall fair", day(3))
    refused = await parent.patch(at(fair), json={"date": day(-1)}, headers=CSRF)
    assert error(refused) == (422, "invalid", "Pick a day that hasn't passed.")
    assert (await change(parent, fair, date=day(0)))["date"] == day(0)
    # Every year from a day that has passed: it counts down to the next one.
    yearly = await change(parent, fair, date="2025-10-04", repeat_yearly=True)
    assert (yearly["date"], yearly["repeat_yearly"]) == ("2025-10-04", True)
    [item] = (await upcoming(parent, include_birthdays=False))["items"]
    assert (item["date"], item["days"]) == ("2027-10-04", 362)
    # Stopping the repeat on another day that has passed is refused…
    refused = await parent.patch(
        at(fair), json={"repeat_yearly": False, "date": "2025-10-05"}, headers=CSRF
    )
    assert error(refused) == (422, "invalid", "Pick a day that hasn't passed.")
    # …but stopping it alone keeps the day it was counting down to.
    once = await change(parent, fair, repeat_yearly=False)
    assert (once["date"], once["repeat_yearly"]) == ("2027-10-04", False)
    # A countdown whose day hasn't come keeps it when it starts repeating.
    again = await change(parent, fair, repeat_yearly=True)
    assert (again["date"], again["repeat_yearly"]) == ("2027-10-04", True)


async def test_an_editor_sending_the_whole_form_saves_what_changed(
    parent: httpx.AsyncClient, family: Family
) -> None:
    halloween = await add_countdown(
        parent, "Halloween", "2025-10-31", repeat_yearly=True, member_id=family.leo
    )
    party = await add_countdown(parent, "Mia's party", day(20), member_id=family.mia)
    archived = await parent.post(f"/api/members/{family.leo}/archive", headers=CSRF)
    assert archived.status_code == 200, archived.text
    form = {
        key: halloween[key]
        for key in (
            "title",
            "date",
            "emoji",
            "color",
            "time",
            "repeat_yearly",
            "member_id",
            "show_on_display",
        )
    }
    # Someone archived since stays on their countdown, and its first day stays as it was…
    saved = await change(parent, halloween, **(form | {"title": "Halloween night"}))
    assert (saved["title"], saved["date"], saved["member_id"]) == (
        "Halloween night",
        "2025-10-31",
        family.leo,
    )
    # …but can't be picked anew.
    refused = await parent.patch(at(party), json={"member_id": family.leo}, headers=CSRF)
    assert error(refused) == (422, "invalid", "That person isn't in the family.")
    # Every year switched off with the day sent unchanged: the next one, once.
    once = await change(parent, halloween, **(form | {"repeat_yearly": False}))
    assert (once["date"], once["repeat_yearly"]) == ("2026-10-31", False)


# ---- removing and putting back -----------------------------------------------------------------


async def test_a_removed_countdown_waits_a_week_to_be_put_back(
    parent: httpx.AsyncClient, family: Family, clock: FakeClock
) -> None:
    fair = await add_countdown(parent, "Fall fair", day(3))
    zoo = await add_countdown(parent, "Zoo day", day(9))
    assert (await parent.delete(at(fair), headers=CSRF)).status_code == 204
    clock.advance(hours=1)
    assert (await parent.delete(at(zoo), headers=CSRF)).status_code == 204
    assert await listed(parent) == []
    assert (await upcoming(parent, include_birthdays=False))["items"] == []
    assert await removed(parent) == [
        {"id": zoo["id"], "title": "Zoo day", "date": day(9), "deleted_at": "2026-10-07T15:00:00Z"},
        {
            "id": fair["id"],
            "title": "Fall fair",
            "date": day(3),
            "deleted_at": "2026-10-07T14:00:00Z",
        },
    ]
    back = await parent.post(f"{at(fair)}/restore", headers=CSRF)
    assert (back.status_code, back.json()) == (200, fair)
    assert titles(await listed(parent)) == ["Fall fair"]
    assert titles(await removed(parent)) == ["Zoo day"]
    again = await parent.post(f"{at(fair)}/restore", headers=CSRF)  # here already: no change
    assert (again.status_code, again.json()) == (200, fair)
    clock.advance(days=7, minutes=1)
    assert await removed(parent) == []  # a week on, it isn't offered any more


async def test_the_wall_screen_never_shows_a_surprise(
    parent: httpx.AsyncClient,
    screen: httpx.AsyncClient,
    kid_phone: httpx.AsyncClient,
    family: Family,
    clock: FakeClock,
) -> None:
    party = await add_countdown(parent, "Ana's surprise party", day(40), show_on_display=False)
    fair = await add_countdown(parent, "Fall fair", day(3))
    wall = titles((await upcoming(screen))["items"])
    assert wall == ["Fall fair", "Mia's birthday", "Leo's birthday", "Ana's birthday"]
    assert titles(await listed(screen)) == ["Fall fair"]
    on_phone = (await upcoming(parent, include_birthdays=False))["items"]
    assert [(i["title"], i["show_on_display"]) for i in on_phone] == [
        ("Fall fair", True),
        ("Ana's surprise party", False),
    ]
    # Only the wall keeps it hidden: phones, a kid's too, see it.
    assert titles(await listed(kid_phone)) == ["Fall fair", "Ana's surprise party"]
    assert (await parent.delete(at(party), headers=CSRF)).status_code == 204
    clock.advance(minutes=1)
    assert (await parent.delete(at(fair), headers=CSRF)).status_code == 204
    assert titles(await removed(screen)) == ["Fall fair"]
    assert titles(await removed(parent)) == ["Fall fair", "Ana's surprise party"]


# ---- live events, missing things, starting -----------------------------------------------------


async def test_every_change_tells_every_screen(
    parent: httpx.AsyncClient, family: Family, events: Events
) -> None:
    fair = await add_countdown(parent, "Fall fair", day(3))
    await change(parent, fair, title="Fall festival")
    await parent.delete(at(fair), headers=CSRF)
    await parent.post(f"{at(fair)}/restore", headers=CSRF)
    assert changed_ids(events) == [fair["id"]] * 4
    assert events[-1] == ("countdowns.changed", {"id": fair["id"]})
    events.clear()
    for path in ("/api/countdowns", "/api/countdowns/upcoming", "/api/countdowns/removed"):
        assert (await parent.get(path)).status_code == 200
    await parent.post(f"{at(fair)}/restore", headers=CSRF)  # here already
    refused = await parent.patch(at(fair), json={"date": day(-1)}, headers=CSRF)
    assert refused.status_code == 422
    assert changed_ids(events) == []  # reading tells nobody, nor does a change that isn't one


async def test_what_isnt_here_says_so(parent: httpx.AsyncClient, family: Family) -> None:
    fair = await add_countdown(parent, "Fall fair", day(3))
    for method, path, body in (
        ("PATCH", "/api/countdowns/nope", {"title": "Zoo day"}),
        ("DELETE", "/api/countdowns/nope", None),
        ("POST", "/api/countdowns/nope/restore", None),
    ):
        response = await parent.request(method, path, json=body, headers=CSRF)
        assert (response.status_code, response.json()["error"]) == (404, GONE), path
    assert (await parent.delete(at(fair), headers=CSRF)).status_code == 204
    for response in (
        await parent.patch(at(fair), json={"title": "Zoo day"}, headers=CSRF),
        await parent.delete(at(fair), headers=CSRF),
    ):
        assert (response.status_code, response.json()["error"]) == (404, GONE)


async def test_countdowns_need_a_signed_in_device(app: FastAPI, parent: httpx.AsyncClient) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as stranger:
        response = await stranger.get("/api/countdowns/upcoming")
    assert error(response) == (401, "signed_out", "Please sign in.")


async def test_while_countdowns_start_a_request_asks_to_try_again(
    parent: httpx.AsyncClient, plugin: Countdowns, ctx: PluginContext
) -> None:
    plugin.ctx = None
    try:
        response = await parent.get("/api/countdowns")
    finally:
        plugin.ctx = ctx
    assert error(response) == (503, "starting", "Countdowns are still starting. Try again.")
