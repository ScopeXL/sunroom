"""The lists plugin through its API (PLAN §9, §11.3; UX §4 "Lists room"): lists and their kinds,
adding without doubles, checking off with who did it, Clear done and Undo, Usuals, the Today
panel's To do, who may remove what, Recently removed, the hourly jobs, live events, and the
plugin switched off. Only this plugin is registered, so it is shown working with every other
plugin off. The fake clock reads Wednesday 2026-10-07, 10:00 in New York. Synthetic data only.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import APIRouter, FastAPI
from fastapi.routing import APIRoute
from sqlalchemy import select

from sunroom.app import create_app
from sunroom.core.clock import FakeClock
from sunroom.plugins.context import PluginContext
from sunroom.plugins.lists import service
from sunroom.plugins.lists.models import ListItem, ShoppingList
from sunroom.plugins.lists.plugin import Lists
from tests.support import (
    BASE_URL,
    CSRF,
    PASSWORD,
    PIN,
    add_member,
    login,
    make_settings,
    run_setup,
    set_pin,
    state_of,
)

Json = dict[str, Any]
Events = list[tuple[str, dict[str, Any]]]
FAMILY = (("Ana", "parent"), ("Sam", "parent"), ("Mia", "kid"), ("Leo", "kid"))
LIST_GONE: dict[str, Any] = {
    "code": "not_found",
    "message": "That list isn't here any more.",
    "key": "api.lists.list_gone",
    "params": {},
}
ITEM_GONE: dict[str, Any] = {
    "code": "not_found",
    "message": "That item isn't here any more.",
    "key": "api.lists.item_gone",
    "params": {},
}


# ---- the app, its devices and the family -------------------------------------------------------


def device(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE_URL)


async def running(plugin: Lists) -> PluginContext:
    """Turning the plugin on returns before its own task has started it."""
    for _ in range(300):
        if plugin.ctx is not None:
            return plugin.ctx
        await asyncio.sleep(0.01)
    raise AssertionError("the lists plugin never started")


@pytest.fixture
def plugin() -> Lists:
    return Lists()


@pytest.fixture
async def lists_app(data_dir: Path, clock: FakeClock, plugin: Lists) -> AsyncIterator[FastAPI]:
    application = create_app(make_settings(data_dir), clock=clock, plugins={"lists": plugin})
    async with application.router.lifespan_context(application):
        yield application


@pytest.fixture
async def phone(lists_app: FastAPI, plugin: Lists) -> AsyncIterator[httpx.AsyncClient]:
    """The phone that ran setup: a parent's."""
    async with device(lists_app) as http:
        response = await run_setup(http)
        assert response.status_code == 201, response.text
        await running(plugin)
        yield http


@pytest.fixture
async def family(phone: httpx.AsyncClient) -> dict[str, str]:
    """The Sample Family's ids by name. The phone is Ana's."""
    ids = {name: (await add_member(phone, name, role))["id"] for name, role in FAMILY}
    chosen = await phone.put("/api/auth/member", json={"member_id": ids["Ana"]}, headers=CSRF)
    assert chosen.status_code == 200, chosen.text
    return ids


@pytest.fixture
async def screen(lists_app: FastAPI, phone: httpx.AsyncClient) -> AsyncIterator[httpx.AsyncClient]:
    """The wall screen. While the household has no PIN it counts as a parent."""
    async with device(lists_app) as http:
        paired = await http.post(
            "/api/auth/kiosk/pair-with-password", json={"password": PASSWORD}, headers=CSRF
        )
        assert paired.status_code == 200, paired.text
        yield http


@pytest.fixture
async def kids_phone(
    lists_app: FastAPI, phone: httpx.AsyncClient, family: dict[str, str]
) -> AsyncIterator[httpx.AsyncClient]:
    """Mia's phone, marked as a kid's (which needs a parent PIN first)."""
    await set_pin(phone)
    async with device(lists_app) as http:
        device_id = (await login(http)).json()["device_id"]
        marked = await phone.patch(
            f"/api/auth/devices/{device_id}", json={"is_kid_device": True}, headers=CSRF
        )
        assert marked.status_code == 200, marked.text
        chosen = await http.put("/api/auth/member", json={"member_id": family["Mia"]}, headers=CSRF)
        assert chosen.status_code == 200, chosen.text
        yield http


@pytest.fixture
def published(lists_app: FastAPI) -> Events:
    """Every event published from here on, in order (after commit)."""
    seen: Events = []
    state_of(lists_app).hub.listeners.append(lambda kind, payload: seen.append((kind, payload)))
    return seen


# ---- helpers -----------------------------------------------------------------------------------


async def new_list(client: httpx.AsyncClient, name: str, **extra: Any) -> Json:
    response = await client.post("/api/lists", json={"name": name} | extra, headers=CSRF)
    assert response.status_code == 201, response.text
    made: Json = response.json()
    return made


async def add(
    client: httpx.AsyncClient,
    list_id: str,
    *texts: str,
    headers: dict[str, str] | None = None,
    **extra: Any,
) -> list[Json]:
    """Add items (each with ``extra``); returns what was added."""
    response = await client.post(
        f"/api/lists/{list_id}/items",
        json={"items": [{"text": text} | extra for text in texts]},
        headers=CSRF | (headers or {}),
    )
    assert response.status_code == 201, response.text
    added: list[Json] = response.json()["items"]
    return added


def at(item: Json) -> str:
    return f"/api/lists/{item['list_id']}/items/{item['id']}"


async def change(
    client: httpx.AsyncClient, item: Json, headers: dict[str, str] | None = None, **body: Any
) -> Json:
    response = await client.patch(at(item), json=body, headers=CSRF | (headers or {}))
    assert response.status_code == 200, response.text
    changed: Json = response.json()
    return changed


async def detail(client: httpx.AsyncClient, list_id: str) -> Json:
    response = await client.get(f"/api/lists/{list_id}/items")
    assert response.status_code == 200, response.text
    found: Json = response.json()
    return found


async def tile(client: httpx.AsyncClient, list_id: str) -> Json:
    lists: list[Json] = (await client.get("/api/lists")).json()
    return next(row for row in lists if row["id"] == list_id)


async def restore(client: httpx.AsyncClient, list_id: str, *items: Json) -> httpx.Response:
    return await client.post(
        f"/api/lists/{list_id}/restore-items",
        json={"ids": [item["id"] for item in items]},
        headers=CSRF,
    )


async def clear_done(client: httpx.AsyncClient, list_id: str) -> list[str]:
    response = await client.post(f"/api/lists/{list_id}/clear-checked", headers=CSRF)
    assert response.status_code == 200, response.text
    ids: list[str] = response.json()["ids"]
    return ids


async def buy(client: httpx.AsyncClient, list_id: str, text: str) -> None:
    """Add it, check it off, clear it: one trip's worth of history."""
    [item] = await add(client, list_id, text)
    await change(client, item, checked=True)
    await clear_done(client, list_id)


def texts(items: list[Json]) -> list[str]:
    return [item["text"] for item in items]


def changed_lists(published: Events) -> list[str]:
    return [payload["list_id"] for kind, payload in published if kind == "lists.changed"]


async def stored(app: FastAPI) -> tuple[set[str], set[str]]:
    """Every list name and item text in the database, whatever their state."""
    async with state_of(app).db.read() as session:
        names = set(await session.scalars(select(ShoppingList.name)))
        items = set(await session.scalars(select(ListItem.text)))
    return names, items


# ---- lists -------------------------------------------------------------------------------------


async def test_a_new_list_guesses_its_kind_and_goes_last(
    phone: httpx.AsyncClient, family: dict[str, str]
) -> None:
    guesses = {
        "Groceries": "grocery",
        "Weekend errands": "todo",
        "To do": "todo",
        "Packing: beach": "packing",
        "Costco": "grocery",
        "Pharmacy": "grocery",
        "Gift ideas": "custom",
    }
    made = [await new_list(phone, name) for name in guesses]
    assert [(row["name"], row["kind"], row["sort"]) for row in made] == [
        (name, kind, index) for index, (name, kind) in enumerate(guesses.items())
    ]
    assert {row["created_by_member_id"] for row in made} == {family["Ana"]}
    first = made[0]
    assert (first["open_count"], first["done_count"], first["due_count"]) == (0, 0, 0)
    assert first["last_change"] is None
    picked = await new_list(phone, "Shopping for camp", kind="packing")  # the family's pick wins
    assert picked["kind"] == "packing"
    listed: list[Json] = (await phone.get("/api/lists")).json()
    assert [row["name"] for row in listed] == [*guesses, "Shopping for camp"]


async def test_a_list_is_renamed_and_the_lists_reordered(
    phone: httpx.AsyncClient, published: Events
) -> None:
    groceries, chores, ideas = [
        await new_list(phone, name) for name in ("Groceries", "To do", "Gift ideas")
    ]
    renamed = await phone.patch(
        f"/api/lists/{ideas['id']}", json={"name": "Birthday ideas", "kind": "todo"}, headers=CSRF
    )
    assert renamed.status_code == 200, renamed.text
    assert (renamed.json()["name"], renamed.json()["kind"]) == ("Birthday ideas", "todo")
    again = await phone.patch(
        f"/api/lists/{ideas['id']}", json={"name": "Party ideas"}, headers=CSRF
    )
    assert (again.json()["name"], again.json()["kind"]) == ("Party ideas", "todo")
    published.clear()
    order = [ideas["id"], groceries["id"], chores["id"]]
    ordered = await phone.put("/api/lists/order", json={"ids": order}, headers=CSRF)
    assert ordered.status_code == 204, ordered.text
    listed: list[Json] = (await phone.get("/api/lists")).json()
    assert [(row["name"], row["sort"]) for row in listed] == [
        ("Party ideas", 0),
        ("Groceries", 1),
        ("To do", 2),
    ]
    assert changed_lists(published) == order
    # A list someone else removed meanwhile is skipped, not an error.
    skipped = await phone.put("/api/lists/order", json={"ids": ["not-a-list"]}, headers=CSRF)
    assert skipped.status_code == 204


# ---- items -------------------------------------------------------------------------------------


async def test_adding_skips_what_is_already_on_the_list(
    phone: httpx.AsyncClient, family: dict[str, str]
) -> None:
    groceries = (await new_list(phone, "Groceries"))["id"]
    milk, eggs = await add(phone, groceries, "Milk", "Eggs")
    assert [
        (i["text"], i["position"], i["created_by_member_id"], i["version"]) for i in (milk, eggs)
    ] == [
        ("Milk", 0, family["Ana"], 1),
        ("Eggs", 1, family["Ana"], 1),
    ]
    response = await phone.post(
        f"/api/lists/{groceries}/items",
        json={
            "items": [{"text": "eggs"}, {"text": "Bread"}, {"text": "  milk "}, {"text": "bread"}]
        },
        headers=CSRF,
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert [(i["text"], i["position"]) for i in body["items"]] == [("Bread", 2)]
    assert body["already"] == ["eggs", "milk", "bread"]
    # Something checked off is no longer to get, so it can go on again.
    await change(phone, milk, checked=True)
    [again] = await add(phone, groceries, "Milk")
    assert again["position"] == 3
    found = await detail(phone, groceries)
    assert texts(found["items"]) == ["Eggs", "Bread", "Milk"]
    assert texts(found["done"]) == ["Milk"]


async def test_an_item_carries_a_quantity_a_note_a_person_and_a_day(
    phone: httpx.AsyncClient, family: dict[str, str]
) -> None:
    groceries = (await new_list(phone, "Groceries"))["id"]
    [apples] = await add(
        phone,
        groceries,
        "Apples",
        quantity=" 6 ",
        note="   ",
        due_date="2026-10-08",
        assigned_member_id=family["Mia"],
    )
    assert (
        apples["quantity"],
        apples["note"],
        apples["due_date"],
        apples["assigned_member_id"],
    ) == ("6", None, "2026-10-08", family["Mia"])
    archived = await phone.post(f"/api/members/{family['Leo']}/archive", headers=CSRF)
    assert archived.status_code == 200, archived.text
    for someone in ("someone-else", family["Leo"]):
        refused = await phone.post(
            f"/api/lists/{groceries}/items",
            json={"items": [{"text": "Pears"}, {"text": "Plums", "assigned_member_id": someone}]},
            headers=CSRF,
        )
        assert refused.status_code == 422, refused.text
        assert refused.json()["error"] == {
            "code": "invalid",
            "message": "That person isn't in the household.",
            "key": "api.lists.unknown_member",
            "params": {},
            "fields": ["items.1.assigned_member_id"],
        }
    assert texts((await detail(phone, groceries))["items"]) == ["Apples"]  # nothing half-added


async def test_changing_an_item_changes_only_what_is_sent(
    phone: httpx.AsyncClient, family: dict[str, str]
) -> None:
    packing = (await new_list(phone, "Packing: soccer camp"))["id"]
    [guards] = await add(
        phone,
        packing,
        "Shin guards",
        note="Size M",
        quantity="2",
        due_date="2026-10-08",
        assigned_member_id=family["Mia"],
    )
    renamed = await change(phone, guards, text="Soccer shin guards")
    assert (
        renamed["text"],
        renamed["note"],
        renamed["quantity"],
        renamed["due_date"],
        renamed["assigned_member_id"],
        renamed["version"],
    ) == ("Soccer shin guards", "Size M", "2", "2026-10-08", family["Mia"], 2)
    emptied = await change(phone, guards, note="", quantity=" ")
    assert (emptied["note"], emptied["quantity"]) == (None, None)
    cleared = await change(phone, guards, clear_due_date=True, clear_assignee=True)
    assert (cleared["due_date"], cleared["assigned_member_id"]) == (None, None)
    moved = await change(phone, guards, due_date="2026-10-09", assigned_member_id=family["Leo"])
    assert (moved["due_date"], moved["assigned_member_id"], moved["version"]) == (
        "2026-10-09",
        family["Leo"],
        5,
    )
    assert (await change(phone, guards))["version"] == 5  # nothing sent, nothing changed
    refused = await phone.patch(
        at(guards), json={"assigned_member_id": "someone-else"}, headers=CSRF
    )
    assert refused.status_code == 422
    assert refused.json()["error"]["message"] == "That person isn't in the household."


async def test_an_item_moves_to_its_new_place(phone: httpx.AsyncClient) -> None:
    groceries = (await new_list(phone, "Groceries"))["id"]
    milk, _eggs, _bread, butter = await add(phone, groceries, "Milk", "Eggs", "Bread", "Butter")
    to_top = await change(phone, butter, position=0)
    assert (to_top["position"], to_top["version"]) == (0, 2)
    found = await detail(phone, groceries)
    assert [(i["text"], i["position"]) for i in found["items"]] == [
        ("Butter", 0),
        ("Milk", 1),
        ("Eggs", 2),
        ("Bread", 3),
    ]
    await change(phone, milk, position=99)  # past the end: last
    found = await detail(phone, groceries)
    assert [(i["text"], i["position"]) for i in found["items"]] == [
        ("Butter", 0),
        ("Eggs", 1),
        ("Bread", 2),
        ("Milk", 3),
    ]


async def test_checking_off_says_who_did_it(
    phone: httpx.AsyncClient,
    screen: httpx.AsyncClient,
    family: dict[str, str],
    clock: FakeClock,
) -> None:
    groceries = (await new_list(phone, "Groceries"))["id"]
    milk, eggs, bread = await add(phone, groceries, "Milk", "Eggs", "Bread")
    tapped_mia = {"x-sunroom-member": family["Mia"]}
    # A phone is its own person, whatever it sends.
    checked = await change(phone, milk, headers=tapped_mia, checked=True)
    assert (checked["checked_by_member_id"], checked["checked_at"], checked["version"]) == (
        family["Ana"],
        "2026-10-07T14:00:00Z",
        2,
    )
    # The wall screen: whoever was tapped first, or Everyone.
    clock.advance(minutes=1)
    assert (await change(screen, eggs, headers=tapped_mia, checked=True))[
        "checked_by_member_id"
    ] == family["Mia"]
    clock.advance(minutes=1)
    assert (await change(screen, bread, checked=True))["checked_by_member_id"] is None
    # A second tap keeps the first name.
    again = await change(screen, eggs, headers={"x-sunroom-member": family["Leo"]}, checked=True)
    assert (again["checked_by_member_id"], again["version"]) == (family["Mia"], 2)
    found = await detail(phone, groceries)
    assert texts(found["items"]) == []
    assert texts(found["done"]) == ["Bread", "Eggs", "Milk"]  # the latest first
    assert (found["list"]["open_count"], found["list"]["done_count"]) == (0, 3)
    assert found["list"]["last_change"] == {
        "action": "checked",
        "text": "Bread",
        "member_id": None,
        "at": "2026-10-07T14:02:00Z",
    }
    # Unchecking forgets who checked it.
    unchecked = await change(phone, milk, checked=False)
    assert (unchecked["checked_at"], unchecked["checked_by_member_id"], unchecked["version"]) == (
        None,
        None,
        3,
    )
    assert texts((await detail(phone, groceries))["items"]) == ["Milk"]
    # Adding on the wall is attributed the same way.
    clock.advance(minutes=1)
    [jam] = await add(screen, groceries, "Jam", headers=tapped_mia)
    assert jam["created_by_member_id"] == family["Mia"]
    assert (await tile(phone, groceries))["last_change"] == {
        "action": "added",
        "text": "Jam",
        "member_id": family["Mia"],
        "at": "2026-10-07T14:03:00Z",
    }


async def test_clear_done_hides_checked_items_until_undo(
    phone: httpx.AsyncClient, clock: FakeClock
) -> None:
    groceries = (await new_list(phone, "Groceries"))["id"]
    milk, eggs, _bread = await add(phone, groceries, "Milk", "Eggs", "Bread")
    await change(phone, milk, checked=True)
    clock.advance(minutes=1)
    await change(phone, eggs, checked=True)
    cleared = await clear_done(phone, groceries)
    assert cleared == [eggs["id"], milk["id"]]
    found = await detail(phone, groceries)
    assert (texts(found["items"]), found["done"], found["list"]["done_count"]) == (
        ["Bread"],
        [],
        0,
    )
    # Cleared isn't removed: Recently removed doesn't list it.
    assert (await phone.get("/api/lists/removed")).json() == {"lists": [], "items": []}
    # Undo puts them back under Done, as they were.
    undone = await restore(phone, groceries, eggs, milk)
    assert undone.status_code == 200, undone.text
    assert [(i["text"], i["checked_at"] is not None, i["version"]) for i in undone.json()] == [
        ("Eggs", True, 4),
        ("Milk", True, 4),
    ]
    assert texts((await detail(phone, groceries))["done"]) == ["Eggs", "Milk"]
    assert await clear_done(phone, groceries) == [eggs["id"], milk["id"]]
    assert await clear_done(phone, groceries) == []  # nothing left to clear


async def test_usuals_are_what_the_list_often_has(
    phone: httpx.AsyncClient, clock: FakeClock
) -> None:
    groceries = (await new_list(phone, "Groceries"))["id"]
    assert (await detail(phone, groceries))["usuals"] == list(service.STAPLES)
    for _ in range(2):
        await buy(phone, groceries, "Lemons")  # half a year ago, by the end
    clock.advance(days=181)
    for spelling in ("bananas", "BANANAS", "Bananas", "oat milk", "Oat milk", "Coffee", "Coffee"):
        await buy(phone, groceries, spelling)
        clock.advance(minutes=1)
    await buy(phone, groceries, "Rice")  # once isn't usual
    for _ in range(2):  # removed things don't count
        [tofu] = await add(phone, groceries, "Tofu")
        assert (await phone.delete(at(tofu), headers=CSRF)).status_code == 204
    assert (await detail(phone, groceries))["usuals"] == [
        "Bananas",
        "Coffee",
        "Oat milk",
        "Milk",
        "Eggs",
        "Bread",
        "Apples",
        "Butter",
    ]
    # What's on the list now is left out, staples too.
    await add(phone, groceries, "Coffee", "milk")
    assert (await detail(phone, groceries))["usuals"] == [
        "Bananas",
        "Oat milk",
        "Eggs",
        "Bread",
        "Apples",
        "Butter",
        "Cheese",
        "Yogurt",
    ]
    # Other lists have only their own.
    chores = (await new_list(phone, "To do"))["id"]
    assert (await detail(phone, chores))["usuals"] == []
    for _ in range(2):
        await buy(phone, chores, "Water the plants")
    assert (await detail(phone, chores))["usuals"] == ["Water the plants"]


async def test_to_do_has_open_items_due_by_the_day(
    phone: httpx.AsyncClient, clock: FakeClock
) -> None:
    errands = (await new_list(phone, "To do"))["id"]
    packing = (await new_list(phone, "Packing: beach"))["id"]
    await add(phone, errands, "Call the plumber", due_date="2026-10-06")
    await add(phone, errands, "Return library books", due_date="2026-10-07")
    await add(phone, errands, "Book the dentist", due_date="2026-10-09")
    await add(phone, errands, "Buy stamps")
    [mailed] = await add(phone, errands, "Mail the forms", due_date="2026-10-07")
    await change(phone, mailed, checked=True)  # done isn't to do
    await add(phone, packing, "Sunscreen", due_date="2026-10-07")
    today = (await phone.get("/api/lists/todo")).json()
    assert today["date"] == "2026-10-07"
    assert [(i["text"], i["due_date"], i["list_name"], i["list_kind"]) for i in today["items"]] == [
        ("Call the plumber", "2026-10-06", "To do", "todo"),
        ("Sunscreen", "2026-10-07", "Packing: beach", "packing"),
        ("Return library books", "2026-10-07", "To do", "todo"),
    ]
    assert today["items"][0]["list_id"] == errands
    summary = await tile(phone, errands)
    assert (summary["open_count"], summary["done_count"], summary["due_count"]) == (4, 1, 2)
    later = (await phone.get("/api/lists/todo", params={"date": "2026-10-09"})).json()
    assert texts(later["items"]) == [
        "Call the plumber",
        "Sunscreen",
        "Return library books",
        "Book the dentist",
    ]
    # Half past eleven at night in New York is still Wednesday there (Thursday in UTC).
    clock.set(datetime(2026, 10, 8, 3, 30, tzinfo=UTC))
    assert (await phone.get("/api/lists/todo")).json()["date"] == "2026-10-07"
    # A removed list's items leave it.
    assert (await phone.delete(f"/api/lists/{packing}", headers=CSRF)).status_code == 204
    today = (await phone.get("/api/lists/todo")).json()
    assert texts(today["items"]) == ["Call the plumber", "Return library books"]
    nonsense = await phone.get("/api/lists/todo", params={"date": "someday"})
    assert nonsense.status_code == 422


# ---- who may remove what -----------------------------------------------------------------------


async def test_without_a_pin_the_wall_screen_removes_lists(
    phone: httpx.AsyncClient, screen: httpx.AsyncClient
) -> None:
    groceries = (await new_list(screen, "Groceries"))["id"]
    assert (await screen.delete(f"/api/lists/{groceries}", headers=CSRF)).status_code == 204
    assert (await screen.post(f"/api/lists/{groceries}/restore", headers=CSRF)).status_code == 200


async def test_only_a_parent_removes_a_list_or_a_kid_their_own(
    phone: httpx.AsyncClient,
    family: dict[str, str],
    kids_phone: httpx.AsyncClient,
    screen: httpx.AsyncClient,
) -> None:
    groceries = (await new_list(phone, "Groceries"))["id"]
    sleepover = await new_list(kids_phone, "Sleepover")
    assert sleepover["created_by_member_id"] == family["Mia"]
    await add(kids_phone, sleepover["id"], "Sleeping bag", "Pillow")
    refused = await kids_phone.delete(f"/api/lists/{groceries}", headers=CSRF)
    assert refused.status_code == 403
    assert refused.json()["error"] == {
        "code": "parent_required",
        "message": "Only a parent can do that. Enter the parent PIN.",
        "key": "api.auth.parent_pin",
        "params": {},
        "pin": True,
    }
    assert (
        await kids_phone.delete(f"/api/lists/{sleepover['id']}", headers=CSRF)
    ).status_code == 204
    assert [row["name"] for row in (await phone.get("/api/lists")).json()] == ["Groceries"]
    back = await kids_phone.post(f"/api/lists/{sleepover['id']}/restore", headers=CSRF)
    assert back.status_code == 200, back.text
    assert back.json()["open_count"] == 2  # its items came back with it
    # The wall screen asks for the PIN once there is one.
    on_wall = await screen.delete(f"/api/lists/{groceries}", headers=CSRF)
    assert on_wall.status_code == 403
    assert on_wall.json()["error"]["pin"] is True
    # A parent's phone removes any list; a kid's phone can't put back someone else's...
    assert (await phone.delete(f"/api/lists/{groceries}", headers=CSRF)).status_code == 204
    refused = await kids_phone.post(f"/api/lists/{groceries}/restore", headers=CSRF)
    assert refused.status_code == 403
    # ...until a parent enters the PIN on it.
    granted = await kids_phone.post("/api/auth/pin/verify", json={"pin": PIN}, headers=CSRF)
    assert granted.status_code == 200, granted.text
    assert (
        await kids_phone.post(f"/api/lists/{groceries}/restore", headers=CSRF)
    ).status_code == 200


async def test_a_kids_phone_removes_only_what_its_person_added(
    phone: httpx.AsyncClient,
    family: dict[str, str],
    kids_phone: httpx.AsyncClient,
    screen: httpx.AsyncClient,
) -> None:
    groceries = (await new_list(phone, "Groceries"))["id"]
    [coffee] = await add(phone, groceries, "Coffee")
    [popsicles] = await add(kids_phone, groceries, "Popsicles")
    assert popsicles["created_by_member_id"] == family["Mia"]
    refused = await kids_phone.delete(at(coffee), headers=CSRF)
    assert refused.status_code == 403
    assert refused.json()["error"]["code"] == "parent_required"
    assert (await kids_phone.delete(at(popsicles), headers=CSRF)).status_code == 204
    assert (await restore(kids_phone, groceries, popsicles)).status_code == 200
    # The wall screen removes anything, PIN or not: Undo and Recently removed cover it.
    assert (await screen.delete(at(coffee), headers=CSRF)).status_code == 204
    # Putting back someone else's removal is a parent's call on a kid's phone...
    refused = await restore(kids_phone, groceries, coffee)
    assert refused.status_code == 403
    assert refused.json()["error"]["pin"] is True
    # ...but Undo for Clear done isn't.
    [chips] = await add(phone, groceries, "Chips")
    await change(kids_phone, chips, checked=True)
    await clear_done(phone, groceries)
    assert (await restore(kids_phone, groceries, chips)).status_code == 200
    assert (await restore(phone, groceries, coffee)).status_code == 200
    assert texts((await detail(phone, groceries))["items"]) == ["Coffee", "Popsicles"]


# ---- Recently removed and the hourly jobs ------------------------------------------------------


async def test_recently_removed_keeps_lists_and_items_for_a_week(
    phone: httpx.AsyncClient, clock: FakeClock
) -> None:
    groceries = (await new_list(phone, "Groceries"))["id"]
    packing = (await new_list(phone, "Packing: beach"))["id"]
    coffee, tea = await add(phone, groceries, "Coffee", "Tea")
    _sunscreen, towels, hat = await add(phone, packing, "Sunscreen", "Towels", "Hat")
    await change(phone, towels, checked=True)  # done items come back with their list too
    assert (await phone.delete(at(hat), headers=CSRF)).status_code == 204
    assert (await phone.delete(at(coffee), headers=CSRF)).status_code == 204
    clock.advance(hours=1)
    assert (await phone.delete(f"/api/lists/{packing}", headers=CSRF)).status_code == 204
    clock.advance(hours=1)
    assert (await phone.delete(at(tea), headers=CSRF)).status_code == 204
    await buy(phone, groceries, "Milk")  # cleared isn't removed
    removed = (await phone.get("/api/lists/removed")).json()
    assert removed["lists"] == [
        {
            "id": packing,
            "name": "Packing: beach",
            "item_count": 2,
            "deleted_at": "2026-10-07T15:00:00Z",
        }
    ]
    # The hat comes back with its list, so it isn't listed on its own.
    assert [
        (i["text"], i["list_id"], i["list_name"], i["deleted_at"]) for i in removed["items"]
    ] == [
        ("Tea", groceries, "Groceries", "2026-10-07T16:00:00Z"),
        ("Coffee", groceries, "Groceries", "2026-10-07T14:00:00Z"),
    ]
    clock.advance(days=7, minutes=1)
    assert (await phone.get("/api/lists/removed")).json() == {"lists": [], "items": []}


async def test_done_items_clear_themselves_when_the_family_asks(
    phone: httpx.AsyncClient, plugin: Lists, clock: FakeClock, published: Events
) -> None:
    ctx = await running(plugin)
    groceries = (await new_list(phone, "Groceries"))["id"]
    milk, eggs, _bread = await add(phone, groceries, "Milk", "Eggs", "Bread")
    await change(phone, milk, checked=True)
    clock.advance(days=3)
    await service.auto_clear(ctx)  # "Never" until someone picks a time
    assert texts((await detail(phone, groceries))["done"]) == ["Milk"]
    chosen = await phone.put(
        "/api/plugins/lists/settings", json={"values": {"auto_clear_days": "1"}}, headers=CSRF
    )
    assert chosen.status_code == 200, chosen.text
    await change(phone, eggs, checked=True)
    clock.advance(hours=2)
    published.clear()
    await service.auto_clear(ctx)
    found = await detail(phone, groceries)
    assert (texts(found["items"]), texts(found["done"])) == (["Bread"], ["Eggs"])
    assert changed_lists(published) == [groceries]
    # Undo still brings it back, as after Clear done.
    assert (await restore(phone, groceries, milk)).status_code == 200
    assert texts((await detail(phone, groceries))["done"]) == ["Eggs", "Milk"]


async def test_prune_forgets_removed_things_after_a_week_and_history_after_half_a_year(
    phone: httpx.AsyncClient,
    plugin: Lists,
    clock: FakeClock,
    lists_app: FastAPI,
    published: Events,
) -> None:
    ctx = await running(plugin)
    groceries = (await new_list(phone, "Groceries"))["id"]
    packing = (await new_list(phone, "Packing: beach"))["id"]
    [coffee, _tea] = await add(phone, groceries, "Coffee", "Tea")
    await add(phone, packing, "Sunscreen", "Towels")
    await buy(phone, groceries, "Milk")
    assert (await phone.delete(at(coffee), headers=CSRF)).status_code == 204
    assert (await phone.delete(f"/api/lists/{packing}", headers=CSRF)).status_code == 204
    clock.advance(days=6)
    await service.prune(ctx)  # still in Recently removed
    assert await stored(lists_app) == (
        {"Groceries", "Packing: beach"},
        {"Coffee", "Tea", "Sunscreen", "Towels", "Milk"},
    )
    clock.advance(days=1, minutes=1)
    published.clear()
    await service.prune(ctx)
    assert await stored(lists_app) == ({"Groceries"}, {"Tea", "Milk"})
    assert changed_lists(published) == sorted([groceries, packing])
    restored = await restore(phone, groceries, coffee)
    assert (restored.status_code, restored.json()["error"]) == (404, ITEM_GONE)
    # A cleared item is history for the Usuals for half a year, then goes.
    clock.advance(days=174)
    await service.prune(ctx)
    assert await stored(lists_app) == ({"Groceries"}, {"Tea"})


# ---- live events, missing things, starting, switched off ---------------------------------------


async def test_every_change_tells_every_screen(phone: httpx.AsyncClient, published: Events) -> None:
    groceries = (await new_list(phone, "Groceries"))["id"]
    [milk] = await add(phone, groceries, "Milk")
    await change(phone, milk, checked=True)
    await clear_done(phone, groceries)
    await restore(phone, groceries, milk)
    await phone.delete(at(milk), headers=CSRF)
    await phone.patch(f"/api/lists/{groceries}", json={"name": "Food"}, headers=CSRF)
    await phone.put("/api/lists/order", json={"ids": [groceries]}, headers=CSRF)
    await phone.delete(f"/api/lists/{groceries}", headers=CSRF)
    await phone.post(f"/api/lists/{groceries}/restore", headers=CSRF)
    assert changed_lists(published) == [groceries] * 10
    published.clear()
    for path in ("/api/lists", f"/api/lists/{groceries}/items", "/api/lists/todo"):
        assert (await phone.get(path)).status_code == 200
    assert (await phone.get("/api/lists/removed")).status_code == 200
    assert changed_lists(published) == []  # reading tells nobody


async def test_what_isnt_here_says_so(phone: httpx.AsyncClient) -> None:
    groceries = (await new_list(phone, "Groceries"))["id"]
    errands = (await new_list(phone, "To do"))["id"]
    [milk] = await add(phone, groceries, "Milk")
    for method, path, body in (
        ("GET", "/api/lists/nope/items", None),
        ("PATCH", "/api/lists/nope", {"name": "Food"}),
        ("DELETE", "/api/lists/nope", None),
        ("POST", "/api/lists/nope/restore", None),
        ("POST", "/api/lists/nope/items", {"items": [{"text": "Milk"}]}),
        ("PATCH", f"/api/lists/nope/items/{milk['id']}", {"checked": True}),
        ("DELETE", f"/api/lists/nope/items/{milk['id']}", None),
        ("POST", "/api/lists/nope/restore-items", {"ids": [milk["id"]]}),
        ("POST", "/api/lists/nope/clear-checked", None),
    ):
        response = await phone.request(method, path, json=body, headers=CSRF)
        assert (response.status_code, response.json()["error"]) == (404, LIST_GONE), path
    # An item asked for on another list, an unknown one, or one that's removed.
    elsewhere = await phone.patch(
        f"/api/lists/{errands}/items/{milk['id']}", json={"checked": True}, headers=CSRF
    )
    assert (elsewhere.status_code, elsewhere.json()["error"]) == (404, ITEM_GONE)
    unknown = await phone.post(
        f"/api/lists/{groceries}/restore-items", json={"ids": ["nope"]}, headers=CSRF
    )
    assert (unknown.status_code, unknown.json()["error"]) == (404, ITEM_GONE)
    assert (await phone.delete(at(milk), headers=CSRF)).status_code == 204
    for response in (
        await phone.patch(at(milk), json={"checked": True}, headers=CSRF),
        await phone.delete(at(milk), headers=CSRF),
    ):
        assert (response.status_code, response.json()["error"]) == (404, ITEM_GONE)
    # The items of a removed list aren't here either.
    assert (await restore(phone, groceries, milk)).status_code == 200
    assert (await phone.delete(f"/api/lists/{groceries}", headers=CSRF)).status_code == 204
    for response in (
        await phone.get(f"/api/lists/{groceries}/items"),
        await phone.patch(at(milk), json={"checked": True}, headers=CSRF),
        await phone.delete(f"/api/lists/{groceries}", headers=CSRF),
    ):
        assert (response.status_code, response.json()["error"]) == (404, LIST_GONE)


async def test_lists_need_a_signed_in_device(lists_app: FastAPI, phone: httpx.AsyncClient) -> None:
    async with device(lists_app) as stranger:
        response = await stranger.get("/api/lists")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "signed_out"


async def test_while_lists_start_a_request_asks_to_try_again(
    phone: httpx.AsyncClient, plugin: Lists
) -> None:
    ctx, plugin.ctx = plugin.ctx, None
    try:
        response = await phone.get("/api/lists")
    finally:
        plugin.ctx = ctx
    assert response.status_code == 503
    assert response.json()["error"] == {
        "code": "starting",
        "message": "Lists are still starting. Try again.",
        "key": "api.lists.starting",
        "params": {},
    }


async def test_every_route_is_off_while_lists_are_off_and_nothing_is_lost(
    phone: httpx.AsyncClient, plugin: Lists
) -> None:
    groceries = (await new_list(phone, "Groceries"))["id"]
    [milk] = await add(phone, groceries, "Milk")
    off = await phone.post("/api/plugins/lists/disable", headers=CSRF)
    assert off.status_code == 200, off.text
    assert off.json()["enabled"] is False
    routes = APIRouter()
    Lists().register_routes(routes)
    answered: list[tuple[str, str]] = []
    for route in routes.routes:
        assert isinstance(route, APIRoute)
        path = "/api/lists" + route.path.format(list_id=groceries, item_id=milk["id"])
        for method in sorted(route.methods or ()):
            body: Json | None = {} if method in {"POST", "PUT", "PATCH"} else None
            response = await phone.request(method, path, json=body, headers=CSRF)
            assert response.status_code == 404, (method, path)
            assert response.json()["error"] == {
                "code": "plugin_disabled",
                "message": "Lists is turned off. A parent can turn it on in Settings.",
                "key": "api.plugins.turned_off",
                "params": {"name": "Lists"},
            }
            answered.append((method, route.path))
    assert len(answered) == 14  # every route the plugin has
    on = await phone.post("/api/plugins/lists/enable", headers=CSRF)
    assert on.status_code == 200, on.text
    await running(plugin)
    found = await detail(phone, groceries)
    assert (found["list"]["name"], texts(found["items"])) == ("Groceries", ["Milk"])
