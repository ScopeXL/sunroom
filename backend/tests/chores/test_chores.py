"""Chores through the API (PLAN §11.3, §15 M3, ADR 0019, ADR 0025): adding and changing them,
the day's boxes per person, who gets the credit for a tap, Undo, approval, carrying a one-day
chore over, skipping a day, the week, streaks and stars, Recently removed and live events.

Wednesday 2026-10-07 is today (10:00 in New York). The Sample Family only."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import httpx

from sunroom.core.clock import FakeClock
from tests.chores.helpers import (
    FRI,
    MON,
    SAT,
    SUN,
    THU,
    TODAY,
    TUE,
    Family,
    add_chore,
    column,
    complete,
    day,
    error,
    give,
    set_switches,
    stars,
    stars_now,
    tapped,
    undo,
)
from tests.support import CSRF, PIN, set_pin


def box_titles(col: dict[str, Any]) -> list[str]:
    return [box["title"] for box in col["boxes"]]


# ---- adding and changing -----------------------------------------------------------------------


async def test_a_chore_reads_its_rule_and_anyone_may_add_one(
    parent: httpx.AsyncClient, family: Family, kid_phone: httpx.AsyncClient
) -> None:
    dog = await add_chore(
        parent,
        "Feed the dog",
        rrule="freq=weekly;byday=mo,we,fr",
        assignee_member_ids=[family.mia],
        points=2,
        due_time="17:00",
    )
    assert dog["rrule"] == "FREQ=WEEKLY;BYDAY=MO,WE,FR"
    assert dog["repeat_text"] == "Every week on Mon, Wed and Fri"
    assert (dog["start_date"], dog["assignee_mode"], dog["requires_approval"]) == (
        TODAY.isoformat(),
        "fixed",
        None,
    )
    once = await add_chore(parent, "Pack for the trip", assignee_member_ids=[family.leo])
    assert (once["rrule"], once["repeat_text"]) == (None, "Doesn't repeat")
    # Adding never asks for the PIN: a kid's phone adds one too.
    kids = await add_chore(kid_phone, "Water the plants", assignee_mode="any", points=1)
    assert kids["assignee_member_ids"] == []
    listed = (await parent.get("/api/chores")).json()
    assert [c["title"] for c in listed] == ["Feed the dog", "Pack for the trip", "Water the plants"]


async def test_a_chore_must_make_sense(parent: httpx.AsyncClient, family: Family) -> None:
    async def refused(**body: Any) -> tuple[int, str, str]:
        response = await parent.post("/api/chores", json={"title": "Dishes"} | body, headers=CSRF)
        return error(response)

    assert await refused(rrule="FREQ=SOMETIMES", assignee_member_ids=[family.mia]) == (
        422,
        "invalid",
        "A repeat happens daily, weekly, monthly or yearly.",
    )
    assert await refused() == (422, "invalid", "Pick who does this task.")
    assert await refused(assignee_mode="rotate", assignee_member_ids=[family.mia]) == (
        422,
        "invalid",
        "Pick at least two people to take turns.",
    )
    assert await refused(assignee_member_ids=[family.mia, family.mia]) == (
        422,
        "invalid",
        "Each person can be picked once.",
    )
    assert await refused(assignee_member_ids=["someone-else"]) == (
        422,
        "unknown_member",
        "That person isn't in the household.",
    )


async def test_a_parent_changes_a_chore_and_only_what_is_sent_changes(
    parent: httpx.AsyncClient, family: Family
) -> None:
    chore = await add_chore(
        parent,
        "Take out the trash",
        rrule="FREQ=DAILY",
        assignee_member_ids=[family.mia],
        icon="trash",
        due_time="20:00",
    )
    changed = await parent.patch(
        f"/api/chores/{chore['id']}",
        json={
            "assignee_mode": "rotate",
            "assignee_member_ids": [family.mia, family.leo],
            "rotation_index": 3,
            "clear_due_time": True,
            "icon": None,
        },
        headers=CSRF,
    )
    assert changed.status_code == 200, changed.text
    out = changed.json()
    assert (out["title"], out["assignee_mode"], out["rotation_index"]) == (
        "Take out the trash",
        "rotate",
        1,
    )
    assert (out["due_time"], out["icon"], out["rrule"]) == (None, None, "FREQ=DAILY")
    once = await parent.patch(
        f"/api/chores/{chore['id']}", json={"clear_rrule": True}, headers=CSRF
    )
    assert (once.json()["rrule"], once.json()["repeat_text"]) == (None, "Doesn't repeat")
    bad = await parent.patch(
        f"/api/chores/{chore['id']}",
        json={"assignee_mode": "fixed", "assignee_member_ids": []},
        headers=CSRF,
    )
    assert error(bad)[:2] == (422, "invalid")
    paused = await parent.patch(f"/api/chores/{chore['id']}", json={"active": False}, headers=CSRF)
    assert paused.json()["active"] is False
    assert (await parent.get("/api/chores")).json() == []
    every = (await parent.get("/api/chores", params={"include_inactive": True})).json()
    assert [c["id"] for c in every] == [chore["id"]]


# ---- the day, and who gets the credit ----------------------------------------------------------


async def test_the_day_has_a_column_per_person_with_chores_and_anyone_last(
    parent: httpx.AsyncClient, family: Family
) -> None:
    await add_chore(parent, "Make bed", rrule="FREQ=DAILY", assignee_member_ids=[family.mia])
    await add_chore(
        parent,
        "Feed the dog",
        rrule="FREQ=WEEKLY;BYDAY=MO",
        assignee_member_ids=[family.leo],
        start_date=MON.isoformat(),
    )
    await add_chore(parent, "Water the plants", rrule="FREQ=DAILY", assignee_mode="any")
    today = await day(parent)
    assert today["date"] == TODAY.isoformat()
    assert (today["stars_on"], today["rewards_on"], today["routines_on"]) == (True, True, True)
    # Household order; Leo has nothing today but still gets his column; Sam has no chores.
    assert [c["member_id"] for c in today["columns"]] == [family.mia, family.leo, None]
    assert box_titles(column(today, family.mia)) == ["Make bed"]
    assert (column(today, family.leo)["total"], column(today, family.leo)["boxes"]) == (0, [])
    anyone = column(today, None)
    assert (anyone["done"], anyone["total"], box_titles(anyone)) == (0, 1, ["Water the plants"])
    assert anyone["routines"] == []
    assert [s["member_id"] for s in today["stars"]] == [family.mia, family.leo]
    monday = await day(parent, MON)
    assert box_titles(column(monday, family.leo)) == ["Feed the dog"]


async def test_the_wall_screen_credits_whoever_tapped_and_a_phone_ignores_the_header(
    parent: httpx.AsyncClient, screen: httpx.AsyncClient, family: Family
) -> None:
    bed = await add_chore(
        parent, "Make bed", rrule="FREQ=DAILY", assignee_member_ids=[family.mia, family.leo]
    )
    plants = await add_chore(parent, "Water the plants", rrule="FREQ=DAILY", assignee_mode="any")
    # The screen says who tapped; the body can't say otherwise.
    done = await complete(screen, bed["id"], member_id=family.mia, headers=tapped(family.leo))
    assert done.status_code == 200, done.text
    assert done.json()["completion"]["member_id"] == family.leo
    assert done.json()["completion"]["status"] == "done"
    nobody = await complete(screen, bed["id"])
    assert error(nobody) == (422, "who_needed", "Who did it? Tap a name first.")
    # A phone is its person's (Ana's here): the header means nothing to it.
    phone = await complete(parent, plants["id"], headers=tapped(family.mia))
    assert phone.json()["completion"]["member_id"] == family.ana
    not_hers = await complete(parent, bed["id"], headers=tapped(family.mia))
    assert error(not_hers) == (409, "not_theirs", "That isn't Ana's task.")
    # A parent's phone may tick someone else's box.
    for_mia = await complete(parent, bed["id"], member_id=family.mia)
    assert for_mia.json()["completion"]["member_id"] == family.mia
    boxes = (
        column(await day(parent), family.mia)["boxes"]
        + column(await day(parent), family.leo)["boxes"]
    )
    assert [(b["owner_id"], b["completion"]["member_id"]) for b in boxes] == [
        (family.mia, family.mia),
        (family.leo, family.leo),
    ]


async def test_a_phone_with_nobody_chosen_asks_who_is_using_it(
    parent: httpx.AsyncClient, family: Family
) -> None:
    chore = await add_chore(parent, "Water the plants", rrule="FREQ=DAILY", assignee_mode="any")
    await parent.put("/api/auth/member", json={"member_id": None}, headers=CSRF)
    refused = await complete(parent, chore["id"])
    assert error(refused) == (422, "who_needed", "Pick who's using this device first.")


async def test_complete_then_undo_takes_the_stamp_and_the_stars_back(
    parent: httpx.AsyncClient, screen: httpx.AsyncClient, family: Family
) -> None:
    dog = await add_chore(
        parent, "Feed the dog", rrule="FREQ=DAILY", assignee_member_ids=[family.mia], points=2
    )
    bed = await add_chore(
        parent, "Make bed", rrule="FREQ=DAILY", assignee_member_ids=[family.mia], points=1
    )
    await give(parent, family.mia, 40)
    first = (await complete(screen, dog["id"], headers=tapped(family.mia))).json()
    assert first["all_done"] is False
    assert (first["stars"]["balance"], first["stars"]["week"]) == (42, 2)
    last = (await complete(screen, bed["id"], headers=tapped(family.mia))).json()
    assert last["all_done"] is True  # "All done, Mia!"
    assert last["stars"]["balance"] == 43
    mia = column(await day(parent), family.mia)
    assert (mia["done"], mia["total"]) == (2, 2)
    taken_back = await undo(screen, bed["id"], headers=tapped(family.mia))
    assert taken_back.status_code == 204
    assert (await stars_now(parent, family.mia))["balance"] == 42
    mia = column(await day(parent), family.mia)
    assert (mia["done"], [b["completion"] is None for b in mia["boxes"]]) == (1, [False, True])
    # Nothing to take back is fine.
    assert (await undo(screen, bed["id"], headers=tapped(family.mia))).status_code == 204


async def test_ticking_again_is_the_same_tick(
    parent: httpx.AsyncClient, screen: httpx.AsyncClient, family: Family
) -> None:
    bed = await add_chore(parent, "Make bed", rrule="FREQ=DAILY", assignee_member_ids=[family.mia])
    first = (await complete(screen, bed["id"], headers=tapped(family.mia))).json()
    again = await complete(screen, bed["id"], headers=tapped(family.mia))
    assert again.status_code == 200
    assert again.json()["completion"] == first["completion"]


async def test_a_rotating_chore_says_whose_turn_and_anyone_can_do_it_once(
    parent: httpx.AsyncClient, screen: httpx.AsyncClient, family: Family
) -> None:
    dishes = await add_chore(
        parent,
        "Empty the dishwasher",
        rrule="FREQ=DAILY",
        assignee_mode="rotate",
        assignee_member_ids=[family.mia, family.leo],
        start_date=MON.isoformat(),
        points=1,
    )
    turns = [column(await day(parent, d), None)["boxes"][0]["turn_id"] for d in (MON, TUE, TODAY)]
    assert turns == [family.mia, family.leo, family.mia]  # "Mia's turn" today
    # Leo does it for her: he gets the credit and the star.
    done = await complete(screen, dishes["id"], headers=tapped(family.leo))
    assert done.json()["completion"]["member_id"] == family.leo
    assert done.json()["all_done"] is True
    late = await complete(screen, dishes["id"], headers=tapped(family.mia))
    assert error(late) == (409, "already_done", "Leo did it already.")
    anyone = column(await day(parent), None)
    assert (anyone["done"], anyone["total"]) == (1, 1)
    box = anyone["boxes"][0]
    assert (box["owner_id"], box["turn_id"], box["completion"]["member_id"]) == (
        None,
        family.mia,
        family.leo,
    )
    assert (await stars_now(parent, family.leo))["balance"] == 1


# ---- approval ----------------------------------------------------------------------------------


async def test_a_parent_checks_kids_chores_when_approval_is_on(
    parent: httpx.AsyncClient, screen: httpx.AsyncClient, family: Family
) -> None:
    await set_switches(parent, approval=True)
    bed = await add_chore(
        parent, "Make bed", rrule="FREQ=DAILY", assignee_member_ids=[family.mia], points=3
    )
    dog = await add_chore(
        parent, "Feed the dog", rrule="FREQ=DAILY", assignee_member_ids=[family.leo], points=2
    )
    ticked = (await complete(screen, bed["id"], headers=tapped(family.mia))).json()
    assert ticked["completion"]["status"] == "pending"
    assert ticked["stars"]["balance"] == 0  # nothing until a parent says yes
    today = await day(parent)
    box = column(today, family.mia)["boxes"][0]
    assert (box["needs_approval"], box["completion"]["status"]) == (True, "pending")
    assert column(today, family.mia)["done"] == 1  # waiting counts as done
    assert [(w["title"], w["completion"]["id"]) for w in today["waiting"]] == [
        ("Make bed", ticked["completion"]["id"])
    ]
    approved = await parent.post(
        f"/api/chores/completions/{ticked['completion']['id']}/approve", headers=CSRF
    )
    assert approved.json()["status"] == "done"
    assert (await stars_now(parent, family.mia))["balance"] == 3
    assert (await day(parent))["waiting"] == []
    # Turned down: the box is due again, and ticking it again reuses the same row.
    leo = (await complete(screen, dog["id"], headers=tapped(family.leo))).json()["completion"]
    rejected = await parent.post(f"/api/chores/completions/{leo['id']}/reject", headers=CSRF)
    assert rejected.json()["status"] == "rejected"
    assert column(await day(parent), family.leo)["boxes"][0]["completion"] is None
    late_ok = await parent.post(f"/api/chores/completions/{leo['id']}/approve", headers=CSRF)
    assert error(late_ok)[:2] == (409, "not_waiting")
    again = (await complete(screen, dog["id"], headers=tapped(family.leo))).json()
    assert (again["completion"]["id"], again["completion"]["status"]) == (leo["id"], "pending")
    assert (await stars_now(parent, family.leo))["balance"] == 0


async def test_a_parents_phone_or_a_chore_that_says_so_skips_the_check(
    parent: httpx.AsyncClient, screen: httpx.AsyncClient, family: Family
) -> None:
    await set_switches(parent, approval=True)
    bed = await add_chore(
        parent, "Make bed", rrule="FREQ=DAILY", assignee_member_ids=[family.mia], points=1
    )
    teeth = await add_chore(
        parent,
        "Brush teeth",
        rrule="FREQ=DAILY",
        assignee_member_ids=[family.mia],
        requires_approval=False,
    )
    trash = await add_chore(
        parent, "Take out the trash", rrule="FREQ=DAILY", assignee_member_ids=[family.ana]
    )
    by_parent = (await complete(parent, bed["id"], member_id=family.mia)).json()
    assert by_parent["completion"]["status"] == "done"
    assert by_parent["stars"]["balance"] == 1
    own_rule = (await complete(screen, teeth["id"], headers=tapped(family.mia))).json()
    assert own_rule["completion"]["status"] == "done"
    grown_up = (await complete(screen, trash["id"], headers=tapped(family.ana))).json()
    assert grown_up["completion"]["status"] == "done"


async def test_the_wall_screen_with_a_pin_needs_the_grant_to_approve(
    parent: httpx.AsyncClient, screen: httpx.AsyncClient, family: Family
) -> None:
    await set_switches(parent, approval=True)
    await set_pin(parent)
    bed = await add_chore(parent, "Make bed", rrule="FREQ=DAILY", assignee_member_ids=[family.mia])
    dog = await add_chore(
        parent, "Feed the dog", rrule="FREQ=DAILY", assignee_member_ids=[family.mia]
    )
    ticked = (await complete(screen, bed["id"], headers=tapped(family.mia))).json()["completion"]
    refused = await screen.post(f"/api/chores/completions/{ticked['id']}/approve", headers=CSRF)
    assert refused.status_code == 403
    assert refused.json()["error"] == {
        "code": "parent_required",
        "message": "Only a parent can do that. Enter the parent PIN.",
        "pin": True,
    }
    granted = await screen.post("/api/auth/pin/verify", json={"pin": PIN}, headers=CSRF)
    assert granted.status_code == 200
    approved = await screen.post(
        f"/api/chores/completions/{ticked['id']}/approve", headers=tapped(family.ana)
    )
    assert approved.json()["status"] == "done"
    # With the grant, a tick on the screen needs no OK either.
    direct = (await complete(screen, dog["id"], headers=tapped(family.mia))).json()
    assert direct["completion"]["status"] == "done"


async def test_a_kids_phone_cant_change_a_chore_or_tick_another_kids_box(
    parent: httpx.AsyncClient, kid_phone: httpx.AsyncClient, family: Family
) -> None:
    hers = await add_chore(parent, "Make bed", rrule="FREQ=DAILY", assignee_member_ids=[family.mia])
    his = await add_chore(
        parent, "Feed the dog", rrule="FREQ=DAILY", assignee_member_ids=[family.leo]
    )
    plants = await add_chore(parent, "Water the plants", rrule="FREQ=DAILY", assignee_mode="any")
    for response in (
        await kid_phone.patch(f"/api/chores/{hers['id']}", json={"title": "No"}, headers=CSRF),
        await kid_phone.delete(f"/api/chores/{hers['id']}", headers=CSRF),
        await kid_phone.post(
            f"/api/chores/{hers['id']}/skip", json={"date": TODAY.isoformat()}, headers=CSRF
        ),
        await complete(kid_phone, hers["id"], member_id=family.mia),
    ):
        assert error(response) == (
            403,
            "parent_required",
            "Only a parent can do that. Enter the parent PIN.",
        )
    assert error(await complete(kid_phone, hers["id"])) == (
        409,
        "not_theirs",
        "That isn't Leo's task.",
    )
    assert (await complete(kid_phone, his["id"])).json()["completion"]["member_id"] == family.leo
    # Someone else's tick on an anyone chore is theirs to take back, or a parent's.
    await complete(parent, plants["id"], member_id=family.mia)
    assert error(await undo(kid_phone, plants["id"]))[:2] == (403, "parent_required")
    assert (await undo(parent, plants["id"], member_id=family.mia)).status_code == 204


# ---- carrying over, skipping, the week ---------------------------------------------------------


async def test_a_one_day_chore_carries_over_until_it_is_done(
    parent: httpx.AsyncClient, screen: httpx.AsyncClient, clock: FakeClock, family: Family
) -> None:
    trip = await add_chore(
        parent, "Pack for the trip", assignee_member_ids=[family.mia], start_date=MON.isoformat()
    )
    monday = column(await day(parent, MON), family.mia)["boxes"]
    assert [(b["due_date"], b["since"]) for b in monday] == [(MON.isoformat(), None)]
    today = column(await day(parent), family.mia)["boxes"]
    assert [(b["due_date"], b["since"]) for b in today] == [(MON.isoformat(), MON.isoformat())]
    assert column(await day(parent, THU), family.mia)["boxes"] == []  # not on later days yet
    wrong_day = await complete(screen, trip["id"], TUE, headers=tapped(family.mia))
    assert error(wrong_day) == (409, "not_due", "It isn't due that day.")
    done = (await complete(screen, trip["id"], MON, headers=tapped(family.mia))).json()
    assert done["all_done"] is True
    stamped = column(await day(parent), family.mia)["boxes"]
    assert [(b["since"], b["completion"]["member_id"]) for b in stamped] == [
        (MON.isoformat(), family.mia)
    ]
    clock.advance(days=1)
    # Finished, and it was Mia's only task: she has no column now (ADR 0036).
    assert [c["member_id"] for c in (await day(parent))["columns"]] == []


async def test_skip_a_day_and_put_it_back(
    parent: httpx.AsyncClient, screen: httpx.AsyncClient, family: Family
) -> None:
    bed = await add_chore(parent, "Make bed", rrule="FREQ=DAILY", assignee_member_ids=[family.mia])
    piano = await add_chore(
        parent,
        "Practice piano",
        rrule="FREQ=WEEKLY;BYDAY=MO",
        assignee_member_ids=[family.mia],
        start_date=MON.isoformat(),
    )
    url = f"/api/chores/{bed['id']}"
    skipped = await parent.post(f"{url}/skip", json={"date": TODAY.isoformat()}, headers=CSRF)
    assert skipped.status_code == 200, skipped.text
    assert column(await day(parent), family.mia)["boxes"] == []
    assert error(await complete(screen, bed["id"], headers=tapped(family.mia)))[:2] == (
        409,
        "not_due",
    )
    again = await parent.post(f"{url}/skip", json={"date": TODAY.isoformat()}, headers=CSRF)
    assert again.status_code == 200
    back = await parent.post(f"{url}/unskip", json={"date": TODAY.isoformat()}, headers=CSRF)
    assert back.status_code == 200
    assert box_titles(column(await day(parent), family.mia)) == ["Make bed"]
    not_due = await parent.post(
        f"/api/chores/{piano['id']}/skip", json={"date": TODAY.isoformat()}, headers=CSRF
    )
    assert error(not_due) == (409, "not_due", "It isn't due that day.")


async def test_the_week_counts_each_day(parent: httpx.AsyncClient, family: Family) -> None:
    bed = await add_chore(
        parent,
        "Make bed",
        rrule="FREQ=DAILY",
        assignee_member_ids=[family.mia],
        start_date=SUN.isoformat(),
    )
    piano = await add_chore(
        parent,
        "Practice piano",
        rrule="FREQ=WEEKLY;BYDAY=MO,WE,FR",
        assignee_member_ids=[family.mia],
        start_date=MON.isoformat(),
    )
    await add_chore(
        parent,
        "Water the plants",
        rrule="FREQ=WEEKLY;BYDAY=SA",
        assignee_mode="any",
        start_date=SAT.isoformat(),
    )
    for chore, when in ((bed, SUN), (bed, MON), (piano, MON)):
        response = await complete(parent, chore["id"], when, member_id=family.mia)
        assert response.status_code == 200, response.text
    week = (await parent.get("/api/chores/week")).json()
    assert week["start"] == SUN.isoformat()  # the household's week starts on Sunday
    assert [c["member_id"] for c in week["columns"]] == [family.mia, None]
    mia = [(d["date"], d["done"], d["total"]) for d in week["columns"][0]["days"]]
    assert mia == [
        (SUN.isoformat(), 1, 1),
        (MON.isoformat(), 2, 2),
        (TUE.isoformat(), 0, 1),
        (TODAY.isoformat(), 0, 2),
        (THU.isoformat(), 0, 1),
        (FRI.isoformat(), 0, 2),
        (SAT.isoformat(), 0, 1),
    ]
    anyone = [(d["done"], d["total"]) for d in week["columns"][1]["days"]]
    assert anyone == [(0, 0)] * 6 + [(0, 1)]
    later = (await parent.get("/api/chores/week", params={"start": "2026-10-11"})).json()
    assert later["start"] == "2026-10-11"
    assert [d["total"] for d in later["columns"][0]["days"]] == [1, 2, 1, 2, 1, 2, 1]


# ---- stars -------------------------------------------------------------------------------------


async def test_streaks_and_this_week_in_stars(
    parent: httpx.AsyncClient, clock: FakeClock, family: Family
) -> None:
    bed = await add_chore(
        parent,
        "Make bed",
        rrule="FREQ=DAILY",
        assignee_member_ids=[family.mia, family.leo],
        start_date="2026-10-01",
        points=1,
    )
    # Mia did hers each day from Saturday Oct 3, on the day; she missed Friday Oct 2.
    for when in (date(2026, 10, 3), SUN, MON, TUE):
        clock.set(datetime(when.year, when.month, when.day, 23, 0, tzinfo=UTC))
        assert (await complete(parent, bed["id"], when, member_id=family.mia)).status_code == 200
    clock.set(datetime(2026, 10, 7, 14, 0, tzinfo=UTC))
    today = await day(parent)
    # Today isn't done yet, which doesn't break it; Saturday was last week.
    assert stars(today, family.mia) == {
        "member_id": family.mia,
        "balance": 4,
        "held": 0,
        "week": 3,
        "streak": 4,
    }
    assert (stars(today, family.leo)["streak"], stars(today, family.leo)["week"]) == (0, 0)
    done = (await complete(parent, bed["id"], member_id=family.mia)).json()
    assert (done["stars"]["streak"], done["stars"]["week"], done["stars"]["balance"]) == (5, 4, 5)
    taken = await parent.post(
        "/api/chores/points/adjust",
        json={"member_ids": [family.mia], "points": -2, "reason": "Fair's fair"},
        headers=CSRF,
    )
    assert taken.json()["stars"][0]["balance"] == 3
    nothing = await parent.post(
        "/api/chores/points/adjust", json={"member_ids": [family.mia], "points": 0}, headers=CSRF
    )
    assert error(nothing) == (422, "invalid", "Give or take at least one star.")
    every = (await parent.get("/api/chores/points")).json()["stars"]
    assert [s["member_id"] for s in every] == [family.ana, family.sam, family.mia, family.leo]


async def test_with_stars_off_chores_give_none(
    parent: httpx.AsyncClient, screen: httpx.AsyncClient, family: Family
) -> None:
    await set_switches(parent, stars=False)
    bed = await add_chore(
        parent, "Make bed", rrule="FREQ=DAILY", assignee_member_ids=[family.mia], points=3
    )
    done = (await complete(screen, bed["id"], headers=tapped(family.mia))).json()
    assert (done["stars"], done["completion"]["points_awarded"]) == (None, 0)
    today = await day(parent)
    assert (today["stars_on"], today["stars"]) == (False, [])


# ---- removing ----------------------------------------------------------------------------------


async def test_a_removed_chore_waits_in_recently_removed_for_a_week(
    parent: httpx.AsyncClient, clock: FakeClock, family: Family
) -> None:
    bed = await add_chore(parent, "Make bed", rrule="FREQ=DAILY", assignee_member_ids=[family.mia])
    await complete(parent, bed["id"], member_id=family.mia)
    removed = await parent.delete(f"/api/chores/{bed['id']}", headers=CSRF)
    assert removed.status_code == 204
    assert (await parent.get("/api/chores")).json() == []
    assert (await day(parent))["columns"] == []
    listed = (await parent.get("/api/chores/removed")).json()
    assert [(r["id"], r["title"]) for r in listed] == [(bed["id"], "Make bed")]
    back = await parent.post(f"/api/chores/{bed['id']}/restore", headers=CSRF)
    assert back.json()["title"] == "Make bed"
    assert column(await day(parent), family.mia)["done"] == 1  # its tick came back with it
    await parent.delete(f"/api/chores/{bed['id']}", headers=CSRF)
    clock.advance(days=8)
    assert (await parent.get("/api/chores/removed")).json() == []
    gone = await parent.patch(f"/api/chores/{bed['id']}", json={"title": "X"}, headers=CSRF)
    assert error(gone) == (404, "not_found", "That task isn't here any more.")


# ---- live events -------------------------------------------------------------------------------


async def test_every_change_goes_out_live(
    parent: httpx.AsyncClient,
    screen: httpx.AsyncClient,
    family: Family,
    events: list[tuple[str, dict[str, Any]]],
) -> None:
    bed = await add_chore(parent, "Make bed", rrule="FREQ=DAILY", assignee_member_ids=[family.mia])
    assert events[-1] == ("chores.changed", {"chore_id": bed["id"]})
    events.clear()
    await complete(screen, bed["id"], headers=tapped(family.mia))
    await complete(screen, bed["id"], headers=tapped(family.mia))  # no change, no event
    await undo(screen, bed["id"], headers=tapped(family.mia))
    change = ("chores.changed", {"chore_id": bed["id"], "date": TODAY.isoformat()})
    stars_moved = ("points.changed", {"member_id": family.mia})
    assert [e for e in events if e[0] in ("chores.changed", "points.changed")] == [
        change,
        stars_moved,
        change,
        stars_moved,
    ]


async def test_a_parent_gives_stars_to_several_children_at_once(
    parent: httpx.AsyncClient, family: Family
) -> None:
    """ADR 0034: one row each, one transaction, the stars in the order asked; a child named
    twice counts once."""
    given = await parent.post(
        "/api/chores/points/adjust",
        json={"member_ids": [family.leo, family.mia, family.leo], "points": 3, "reason": "Bins"},
        headers=CSRF,
    )
    assert given.status_code == 200, given.text
    stars = given.json()["stars"]
    assert [(s["member_id"], s["balance"]) for s in stars] == [(family.leo, 3), (family.mia, 3)]
    taken = await parent.post(
        "/api/chores/points/adjust",
        json={"member_ids": [family.mia, family.leo], "points": -1},
        headers=CSRF,
    )
    assert [s["balance"] for s in taken.json()["stars"]] == [2, 2]
    every = (await parent.get("/api/chores/points")).json()["stars"]
    assert {s["member_id"]: s["balance"] for s in every}[family.mia] == 2


async def test_stars_for_too_many_or_someone_gone_are_refused(
    parent: httpx.AsyncClient, family: Family
) -> None:
    many = await parent.post(
        "/api/chores/points/adjust",
        json={"member_ids": [family.mia] * 21, "points": 1},
        headers=CSRF,
    )
    assert many.status_code == 422
    none = await parent.post(
        "/api/chores/points/adjust", json={"member_ids": [], "points": 1}, headers=CSRF
    )
    assert none.status_code == 422
    archived = await parent.post(f"/api/members/{family.leo}/archive", headers=CSRF)
    assert archived.status_code == 200, archived.text
    gone = await parent.post(
        "/api/chores/points/adjust",
        json={"member_ids": [family.mia, family.leo], "points": 1},
        headers=CSRF,
    )
    assert error(gone) == (422, "unknown_member", "That person isn't in the household.")
    # Nothing was written for Mia either.
    every = (await parent.get("/api/chores/points")).json()["stars"]
    assert {s["member_id"]: s["balance"] for s in every}[family.mia] == 0
