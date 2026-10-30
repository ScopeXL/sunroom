"""The week's meals through the API (PLAN §9, §11.3; UX §4 "Meals room", §5 "Meals"): the week
and Tonight, putting a meal on a day and what it replaces, saved meals made and counted as meals
are typed, changing a meal, who cooks, removing and putting back, Swap days, Copy last week, who
added what on the wall and on a kid's phone, and live events.

Only this plugin is registered, so it is shown working with every other plugin off. Wednesday
2026-10-07 is today (10:00 in New York). The Sample Family only."""

from __future__ import annotations

import httpx

from sunroom.core.clock import FakeClock
from tests.meals.helpers import (
    DAY,
    FRI,
    MEAL_GONE,
    MON,
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
    copy_week,
    error,
    menu,
    move,
    plan,
    put_back,
    put_entry,
    remove,
    removed,
    save_meal,
    saved_meals,
    set_meals,
    tapped,
    uses,
    week,
)
from tests.support import CSRF

# ---- the week ----------------------------------------------------------------------------------


async def test_the_week_has_its_meals_in_the_days_order(
    parent: httpx.AsyncClient, family: Family
) -> None:
    empty = await parent.get("/api/meals/week")
    assert empty.status_code == 200, empty.text
    assert empty.json() == {"start": "2026-10-04", "days": 7, "slots": ["dinner"], "entries": []}
    await plan(parent, THU, "Leftovers")
    await plan(parent, TUE, "Pancakes", slot="breakfast")
    await plan(parent, TUE, "Tacos")
    await plan(parent, TUE, "Popcorn", slot="snack")
    await plan(parent, TUE, "Grilled cheese", slot="lunch")
    await plan(parent, TUE, "Soup", position=1)
    await plan(parent, SUN - DAY, "Pizza night")  # last Saturday
    await plan(parent, SUN + WEEK, "Roast chicken")  # next Sunday
    assert await menu(parent) == [
        ("2026-10-06", "breakfast", 0, "Pancakes"),
        ("2026-10-06", "lunch", 0, "Grilled cheese"),
        ("2026-10-06", "dinner", 0, "Tacos"),
        ("2026-10-06", "dinner", 1, "Soup"),
        ("2026-10-06", "snack", 0, "Popcorn"),
        ("2026-10-08", "dinner", 0, "Leftovers"),
    ]
    # Tonight on the Today panel is one day; two weeks reach next Sunday.
    assert await menu(parent, THU, days=1) == [("2026-10-08", "dinner", 0, "Leftovers")]
    assert [row[3] for row in await menu(parent, SUN, days=14)][-1] == "Roast chicken"
    for days in ("0", "15", "a week"):
        refused = await parent.get("/api/meals/week", params={"days": days})
        assert refused.status_code == 422, days
    # Without a start it's this week, from the household's first day.
    monday = await parent.patch("/api/settings", json={"week_starts_on": 0}, headers=CSRF)
    assert monday.status_code == 200, monday.text
    this_week = (await parent.get("/api/meals/week")).json()
    assert (this_week["start"], this_week["entries"][0]["text"]) == ("2026-10-05", "Pancakes")


async def test_the_slots_are_the_meals_the_family_plans(
    parent: httpx.AsyncClient, family: Family
) -> None:
    await set_meals(parent, slots=["snack", "breakfast", "dinner"])
    assert (await week(parent))["slots"] == ["breakfast", "dinner", "snack"]
    refused = await parent.put(
        "/api/plugins/meals/settings", json={"values": {"slots": []}}, headers=CSRF
    )
    assert refused.status_code == 422, refused.text
    assert refused.json()["error"]["problems"] == ["Pick at least one meal."]
    # A meal planned for a slot switched off since stays; the app shows the planned slots.
    await plan(parent, WED, "Popcorn", slot="snack")
    await set_meals(parent, slots=["dinner"])
    found = await week(parent)
    assert (found["slots"], [e["text"] for e in found["entries"]]) == (["dinner"], ["Popcorn"])


# ---- putting a meal on a day -------------------------------------------------------------------


async def test_a_typed_meal_is_kept_as_a_saved_meal_and_counted(
    parent: httpx.AsyncClient, family: Family, clock: FakeClock
) -> None:
    tacos = await plan(
        parent, TUE, "Tacos", emoji="🌮", member_id=family.sam, note=" With the good salsa "
    )
    [saved] = await saved_meals(parent)
    assert {key: tacos[key] for key in tacos if key not in ("id", "updated_at")} == {
        "day": "2026-10-06",
        "slot": "dinner",
        "position": 0,
        "text": "Tacos",
        "emoji": "🌮",
        "recipe_url": None,
        "note": "With the good salsa",
        "member_id": family.sam,
        "saved_meal_id": saved["id"],
        "ingredients": [],
        "created_by_member_id": family.ana,
    }
    assert saved == {
        "id": tacos["saved_meal_id"],
        "text": "Tacos",
        "emoji": "🌮",
        "recipe_url": None,
        "ingredients": [],
        "use_count": 1,
        "last_used_at": "2026-10-07T14:00:00Z",
    }
    # The same meal typed again, any case: the same saved meal, one more use, its emoji.
    clock.advance(hours=1)
    again = await plan(parent, FRI, "  TACOS ")
    assert (again["text"], again["emoji"], again["saved_meal_id"]) == (
        "TACOS",
        "🌮",
        saved["id"],
    )
    [saved] = await saved_meals(parent)
    assert (saved["use_count"], saved["last_used_at"]) == (2, "2026-10-07T15:00:00Z")
    # The body's own emoji wins, and an empty one means none.
    assert (await plan(parent, SAT, "Tacos", emoji="🌯"))["emoji"] == "🌯"
    assert (await plan(parent, MON, "Tacos", emoji=""))["emoji"] is None
    assert await uses(parent) == {"Tacos": 4}


async def test_a_picked_saved_meal_brings_its_emoji_link_and_ingredients(
    parent: httpx.AsyncClient, family: Family
) -> None:
    pasta = await save_meal(
        parent,
        "Pasta night",
        emoji="🍝",
        recipe_url="https://example.com/recipes/pasta",
        ingredients=["Pasta", "Tomato sauce", " Parmesan "],
    )
    assert (pasta["ingredients"], pasta["use_count"], pasta["last_used_at"]) == (
        ["Pasta", "Tomato sauce", "Parmesan"],
        0,
        None,
    )
    picked = await plan(parent, MON, "Pasta night", saved_meal_id=pasta["id"])
    assert (
        picked["saved_meal_id"],
        picked["emoji"],
        picked["recipe_url"],
        picked["ingredients"],
    ) == (pasta["id"], "🍝", "https://example.com/recipes/pasta", pasta["ingredients"])
    # The week carries the ingredients too, for "Add ingredients to Groceries".
    [listed] = (await week(parent))["entries"]
    assert listed["ingredients"] == ["Pasta", "Tomato sauce", "Parmesan"]
    # Its own emoji and link win ("" for none).
    own = await plan(
        parent, TUE, "Pasta night", saved_meal_id=pasta["id"], emoji="🍜", recipe_url=""
    )
    assert (own["emoji"], own["recipe_url"], own["saved_meal_id"]) == ("🍜", None, pasta["id"])
    assert await uses(parent) == {"Pasta night": 2}
    missing = await put_entry(parent, WED, "Pasta night", saved_meal_id="not-a-meal")
    assert (missing.status_code, missing.json()["error"]) == (404, SAVED_GONE)


async def test_a_spot_holds_one_meal_and_the_one_there_is_replaced(
    parent: httpx.AsyncClient, family: Family
) -> None:
    tacos = await plan(parent, WED, "Tacos")
    await plan(parent, WED, "Soup", position=1)
    response = await put_entry(parent, WED, "Pizza night")
    assert response.status_code == 200, response.text
    pizza, replaced = response.json()["entry"], response.json()["replaced"]
    assert (replaced["id"], replaced["text"], replaced["day"]) == (
        tacos["id"],
        "Tacos",
        "2026-10-07",
    )
    assert await menu(parent) == [
        ("2026-10-07", "dinner", 0, "Pizza night"),
        ("2026-10-07", "dinner", 1, "Soup"),
    ]
    assert [e["text"] for e in (await removed(parent))["entries"]] == ["Tacos"]
    # Undo: the new one off, the replaced one back in its place.
    await remove(parent, pizza)
    back = await put_back(parent, tacos)
    assert (back.status_code, back.json()["position"]) == (200, 0)
    assert await menu(parent) == [
        ("2026-10-07", "dinner", 0, "Tacos"),
        ("2026-10-07", "dinner", 1, "Soup"),
    ]
    # Nothing replaces anything in another meal of the day, and ten dinners are the most.
    assert (await put_entry(parent, WED, "Waffles", slot="breakfast")).json()["replaced"] is None
    wrongs: list[Json] = [
        {"position": 10},
        {"position": -1},
        {"slot": "brunch"},
        {"emoji": "🌮" * 17},
    ]
    for wrong in wrongs:
        assert (await put_entry(parent, WED, "Cake", **wrong)).status_code == 422, wrong
    assert (await put_entry(parent, WED, " ")).status_code == 422


async def test_changing_a_meal_counts_a_use_only_when_the_meal_changes(
    parent: httpx.AsyncClient, family: Family, events: Events, clock: FakeClock
) -> None:
    tacos = await plan(parent, MON, "Tacos", emoji="🌮", member_id=family.ana, note="Early")
    [saved] = await saved_meals(parent)
    events.clear()
    # Another day, cook and note, the case of its name: the same meal and link, no new use.
    moved = await plan(parent, TUE, "tacos", id=tacos["id"], emoji="🌮", member_id=family.sam)
    assert (moved["id"], moved["day"], moved["text"], moved["member_id"], moved["note"]) == (
        tacos["id"],
        "2026-10-06",
        "tacos",
        family.sam,
        None,
    )
    assert (moved["saved_meal_id"], moved["created_by_member_id"]) == (saved["id"], family.ana)
    assert await uses(parent) == {"Tacos": 1}
    assert changed_days(events) == [["2026-10-05", "2026-10-06"]]
    # A link it keeps doesn't bring the saved meal's emoji back: a change sends the whole meal.
    assert (await plan(parent, TUE, "Tacos", id=tacos["id"]))["emoji"] is None
    # Another meal: kept as a saved meal of its own, and counted.
    clock.advance(minutes=1)
    burritos = await plan(parent, TUE, "Burritos", id=tacos["id"])
    assert burritos["saved_meal_id"] not in (None, saved["id"])
    assert [(s["text"], s["use_count"]) for s in await saved_meals(parent)] == [
        ("Burritos", 1),
        ("Tacos", 1),
    ]
    # Onto a spot another meal holds: that one is replaced.
    pizza = await plan(parent, FRI, "Pizza night")
    onto = await put_entry(parent, FRI, "Burritos", id=tacos["id"])
    assert onto.json()["replaced"]["id"] == pizza["id"]
    assert await menu(parent) == [("2026-10-09", "dinner", 0, "Burritos")]
    # A meal that's gone can't change.
    await remove(parent, tacos)
    for meal_id in (tacos["id"], "not-a-meal"):
        gone = await put_entry(parent, FRI, "Tacos", id=meal_id)
        assert (gone.status_code, gone.json()["error"]) == (404, MEAL_GONE)


async def test_the_cook_is_someone_in_the_family(parent: httpx.AsyncClient, family: Family) -> None:
    refused = await put_entry(parent, WED, "Soup", member_id="someone-else")
    assert refused.status_code == 422
    assert refused.json()["error"] == {
        "code": "invalid",
        "message": "That person isn't in the family.",
        "key": "api.meals.not_in_family",
        "params": {},
        "fields": ["member_id"],
    }
    tacos = await plan(parent, WED, "Tacos", member_id=family.leo)
    archived = await parent.post(f"/api/members/{family.leo}/archive", headers=CSRF)
    assert archived.status_code == 200, archived.text
    # Leo can't be picked any more...
    refused = await put_entry(parent, THU, "Soup", member_id=family.leo)
    assert error(refused) == (422, "invalid", "That person isn't in the family.")
    # ...but a meal he cooks keeps him through other changes.
    kept = await plan(parent, WED, "Tacos", id=tacos["id"], member_id=family.leo, note="Mild")
    assert (kept["member_id"], kept["note"]) == (family.leo, "Mild")
    # A refused meal leaves nothing behind, not even a saved meal.
    assert await menu(parent) == [("2026-10-07", "dinner", 0, "Tacos")]
    assert await uses(parent) == {"Tacos": 1}


# ---- removing, putting back and moving ---------------------------------------------------------


async def test_a_removed_meal_comes_back_to_its_spot_or_the_next_free_one(
    parent: httpx.AsyncClient, family: Family, clock: FakeClock
) -> None:
    tacos = await plan(parent, WED, "Tacos", emoji="🌮", member_id=family.sam)
    await remove(parent, tacos)
    assert await menu(parent) == []
    again = await parent.delete(f"/api/meals/entries/{tacos['id']}", headers=CSRF)
    assert (again.status_code, again.json()["error"]) == (404, MEAL_GONE)
    clock.advance(minutes=1)
    back = await put_back(parent, tacos)
    assert back.status_code == 200, back.text
    restored = back.json()
    assert (restored["id"], restored["position"], restored["emoji"], restored["member_id"]) == (
        tacos["id"],
        0,
        "🌮",
        family.sam,
    )
    assert restored["updated_at"] == "2026-10-07T14:01:00Z"
    # Putting back what's here already changes nothing.
    assert (await put_back(parent, tacos)).json()["position"] == 0
    # Its spot taken meanwhile, it goes to the next free one that day.
    await remove(parent, tacos)
    await plan(parent, WED, "Pizza night")
    await plan(parent, WED, "Salad", position=1)
    assert (await put_back(parent, tacos)).json()["position"] == 2
    assert await menu(parent) == [
        ("2026-10-07", "dinner", 0, "Pizza night"),
        ("2026-10-07", "dinner", 1, "Salad"),
        ("2026-10-07", "dinner", 2, "Tacos"),
    ]
    unknown = await parent.post("/api/meals/entries/not-a-meal/restore", headers=CSRF)
    assert (unknown.status_code, unknown.json()["error"]) == (404, MEAL_GONE)


async def test_moving_a_meal_swaps_it_with_the_one_there(
    parent: httpx.AsyncClient, family: Family, events: Events
) -> None:
    tacos = await plan(parent, WED, "Tacos", member_id=family.sam)
    leftovers = await plan(parent, THU, "Leftovers")
    soup = await plan(parent, THU, "Soup", position=1)
    events.clear()
    swapped = await move(parent, tacos, THU)
    assert (swapped["moved"]["id"], swapped["moved"]["day"], swapped["moved"]["position"]) == (
        tacos["id"],
        "2026-10-08",
        0,
    )
    assert (swapped["swapped"]["id"], swapped["swapped"]["day"]) == (leftovers["id"], "2026-10-07")
    assert swapped["moved"]["member_id"] == family.sam
    assert await menu(parent) == [
        ("2026-10-07", "dinner", 0, "Leftovers"),
        ("2026-10-08", "dinner", 0, "Tacos"),
        ("2026-10-08", "dinner", 1, "Soup"),
    ]
    assert changed_days(events) == [["2026-10-07", "2026-10-08"]]
    # To an open day nothing swaps, and the position stays.
    alone = await move(parent, soup, SAT)
    assert (alone["moved"]["day"], alone["moved"]["position"], alone["swapped"]) == (
        "2026-10-10",
        1,
        None,
    )
    # Into another meal of a day: the one there takes the old spot, meal and all.
    lunch = await plan(parent, FRI, "Sandwiches", slot="lunch")
    across = await move(parent, leftovers, FRI, slot="lunch")
    assert (across["moved"]["day"], across["moved"]["slot"]) == ("2026-10-09", "lunch")
    assert (across["swapped"]["id"], across["swapped"]["day"], across["swapped"]["slot"]) == (
        lunch["id"],
        "2026-10-07",
        "dinner",
    )
    # Where it is already, nothing moves.
    still = await move(parent, tacos, THU)
    assert (still["moved"]["day"], still["swapped"]) == ("2026-10-08", None)
    assert await menu(parent) == [
        ("2026-10-07", "dinner", 0, "Sandwiches"),
        ("2026-10-08", "dinner", 0, "Tacos"),
        ("2026-10-09", "lunch", 0, "Leftovers"),
        ("2026-10-10", "dinner", 1, "Soup"),
    ]
    await remove(parent, soup)
    gone = await parent.post(
        f"/api/meals/entries/{soup['id']}/move", json={"day": "2026-10-04"}, headers=CSRF
    )
    assert (gone.status_code, gone.json()["error"]) == (404, MEAL_GONE)


# ---- Copy last week ----------------------------------------------------------------------------


async def test_copy_last_week_fills_the_open_spots(
    parent: httpx.AsyncClient, family: Family, events: Events, clock: FakeClock
) -> None:
    last = SUN - WEEK
    pasta = await save_meal(parent, "Pasta night", emoji="🍝")
    await plan(parent, last, "Roast chicken", emoji="🍗", member_id=family.ana, note="Brine it")
    await plan(
        parent,
        MON - WEEK,
        "Pasta night",
        saved_meal_id=pasta["id"],
        recipe_url="https://example.com/recipes/pasta",
    )
    await plan(parent, TUE - WEEK, "Tacos")
    await plan(parent, TUE - WEEK, "Pancakes", slot="breakfast")
    await remove(parent, await plan(parent, WED - WEEK, "Soup"))  # removed: not copied
    await plan(parent, FRI - WEEK, "Pizza night", member_id=family.leo)
    await plan(parent, last - DAY, "Waffles")  # the Saturday before: another week
    await plan(parent, TUE, "Fish sticks")  # this Tuesday's dinner is planned already
    archived = await parent.post(f"/api/members/{family.leo}/archive", headers=CSRF)
    assert archived.status_code == 200, archived.text
    events.clear()
    clock.advance(hours=1)
    response = await copy_week(parent, last, SUN)
    assert response.status_code == 200, response.text
    copied = response.json()
    assert copied["skipped"] == 1
    entries = (await week(parent))["entries"]
    assert [
        (e["day"], e["slot"], e["text"], e["emoji"], e["recipe_url"], e["member_id"], e["note"])
        for e in entries
    ] == [
        ("2026-10-04", "dinner", "Roast chicken", "🍗", None, family.ana, None),
        (
            "2026-10-05",
            "dinner",
            "Pasta night",
            "🍝",
            "https://example.com/recipes/pasta",
            None,
            None,
        ),
        ("2026-10-06", "breakfast", "Pancakes", None, None, None, None),
        ("2026-10-06", "dinner", "Fish sticks", None, None, None, None),
        ("2026-10-09", "dinner", "Pizza night", None, None, None, None),  # Leo has left
    ]
    made = [e for e in entries if e["text"] != "Fish sticks"]
    assert copied["ids"] == [e["id"] for e in made]
    assert {e["created_by_member_id"] for e in made} == {family.ana}
    assert {e["updated_at"] for e in made} == {"2026-10-07T15:00:00Z"}
    assert made[1]["saved_meal_id"] == pasta["id"]
    # Each copy counts a use of its saved meal.
    assert await uses(parent) == {
        "Pasta night": 2,
        "Roast chicken": 2,
        "Pancakes": 2,
        "Pizza night": 2,
        "Tacos": 1,
        "Soup": 1,
        "Waffles": 1,
        "Fish sticks": 1,
    }
    assert changed_days(events) == [["2026-10-04", "2026-10-05", "2026-10-06", "2026-10-09"]]
    # Again, everything is there already; a week can't be copied onto itself.
    assert (await copy_week(parent, last, SUN)).json() == {"ids": [], "skipped": 5}
    assert error(await copy_week(parent, SUN, SUN)) == (422, "invalid", "Pick another week.")


# ---- who did it --------------------------------------------------------------------------------


async def test_the_wall_screen_says_who_added_a_meal(
    parent: httpx.AsyncClient, screen: httpx.AsyncClient, family: Family
) -> None:
    by_mia = await plan(screen, WED, "Tacos", headers=tapped(family.mia))
    assert by_mia["created_by_member_id"] == family.mia
    assert (await plan(screen, THU, "Soup"))["created_by_member_id"] is None  # Everyone
    # A phone is its own person, whatever it sends.
    by_ana = await plan(parent, FRI, "Pizza night", headers=tapped(family.mia))
    assert by_ana["created_by_member_id"] == family.ana
    # A change keeps who added it; copies are whoever tapped Copy last week.
    changed = await plan(
        screen, WED, "Tacos", id=by_mia["id"], note="Mild", headers=tapped(family.leo)
    )
    assert (changed["created_by_member_id"], changed["note"]) == (family.mia, "Mild")
    copied = await copy_week(screen, SUN, SUN + WEEK, headers=tapped(family.sam))
    assert copied.status_code == 200, copied.text
    next_week = (await week(screen, SUN + WEEK))["entries"]
    assert {e["created_by_member_id"] for e in next_week} == {family.sam}
    assert len(next_week) == 3


async def test_a_kids_phone_plans_meals_too(
    parent: httpx.AsyncClient, kid_phone: httpx.AsyncClient, family: Family
) -> None:
    pancakes = await plan(kid_phone, SAT, "Pancakes", slot="breakfast")
    assert pancakes["created_by_member_id"] == family.leo
    # Nothing in Meals asks for a parent: Undo and Recently removed cover mistakes.
    await remove(kid_phone, pancakes)
    assert (await put_back(kid_phone, pancakes)).status_code == 200
    assert (await move(kid_phone, pancakes, SUN))["moved"]["day"] == "2026-10-04"
    assert (await copy_week(kid_phone, SUN, SUN + WEEK)).status_code == 200
    mac = await save_meal(kid_phone, "Mac and cheese", emoji="🧀")
    patched = await kid_phone.patch(
        f"/api/meals/saved/{mac['id']}", json={"ingredients": ["Macaroni", "Cheese"]}, headers=CSRF
    )
    assert patched.status_code == 200, patched.text
    assert (
        await kid_phone.delete(f"/api/meals/saved/{mac['id']}", headers=CSRF)
    ).status_code == 204
    restored = await kid_phone.post(f"/api/meals/saved/{mac['id']}/restore", headers=CSRF)
    assert restored.status_code == 200, restored.text
    assert await menu(parent, SUN, days=14) == [
        ("2026-10-04", "breakfast", 0, "Pancakes"),
        ("2026-10-11", "breakfast", 0, "Pancakes"),
    ]


# ---- live events -------------------------------------------------------------------------------


async def test_every_change_tells_every_screen(
    parent: httpx.AsyncClient, family: Family, events: Events
) -> None:
    tacos = await plan(parent, TODAY, "Tacos")
    await plan(parent, THU, "Tacos", id=tacos["id"])
    await move(parent, tacos, FRI)
    await remove(parent, tacos)
    await put_back(parent, tacos)
    await copy_week(parent, SUN, SUN + WEEK)
    pasta = await save_meal(parent, "Pasta night")
    await parent.patch(f"/api/meals/saved/{pasta['id']}", json={"emoji": "🍝"}, headers=CSRF)
    await parent.delete(f"/api/meals/saved/{pasta['id']}", headers=CSRF)
    await parent.post(f"/api/meals/saved/{pasta['id']}/restore", headers=CSRF)
    assert changed_days(events) == [
        ["2026-10-07"],
        ["2026-10-07", "2026-10-08"],
        ["2026-10-08", "2026-10-09"],
        ["2026-10-09"],
        ["2026-10-09"],
        ["2026-10-16"],
        [],
        [],
        [],
        [],
    ]
    events.clear()
    for path in ("/api/meals/week", "/api/meals/saved", "/api/meals/removed"):
        assert (await parent.get(path)).status_code == 200
    assert changed_days(events) == []  # reading tells nobody
