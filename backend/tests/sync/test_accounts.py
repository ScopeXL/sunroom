"""Accounts through the API (PLAN §11.2): a calendar address added and on the board at once, a
private address refused until a parent allows it, holidays, mapping to people, disconnecting, an
address that stops working. Feeds come from a scripted server behind the real guarded client;
synthetic data only."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from sunroom.app import create_app
from sunroom.core.clock import FakeClock
from sunroom.plugins.calendar_sync.plugin import CalendarSync
from tests.support import BASE_URL, CSRF, add_member, make_settings, run_setup

PUBLIC = "93.184.216.34"  # a public address, resolved for every test host
FEED = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Sample//Test feed//EN
X-WR-CALNAME:School
BEGIN:VEVENT
UID:pajama-day@school.example.com
DTSTART;VALUE=DATE:20261009
SUMMARY:Pajama day
END:VEVENT
BEGIN:VEVENT
UID:field-trip@school.example.com
DTSTART;TZID=America/New_York:20261008T090000
DTEND;TZID=America/New_York:20261008T130000
SUMMARY:Field trip
LOCATION:Sample Farm
END:VEVENT
END:VCALENDAR
"""


class FeedServer:
    """The scripted feed server: answers by path, counts requests, honours If-None-Match."""

    def __init__(self) -> None:
        self.feeds: dict[str, str] = {"/school.ics": FEED}
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        body = self.feeds.get(request.url.path)
        if body is None:
            return httpx.Response(404)
        etag = f'"{hash(body) & 0xFFFF:x}"'
        if request.headers.get("if-none-match") == etag:
            return httpx.Response(304)
        return httpx.Response(
            200, text=body, headers={"content-type": "text/calendar", "etag": etag}
        )

    def transport(self) -> Callable[[], httpx.AsyncBaseTransport]:
        return lambda: httpx.MockTransport(self.handler)


async def resolve(host: str, port: int) -> list[str]:
    return [PUBLIC]


@pytest.fixture
def feeds() -> FeedServer:
    return FeedServer()


@pytest.fixture
def plugin() -> CalendarSync:
    return CalendarSync()


@pytest.fixture
async def sync_app(
    data_dir: Path, clock: FakeClock, feeds: FeedServer, plugin: CalendarSync
) -> AsyncIterator[FastAPI]:
    application = create_app(
        make_settings(data_dir),
        clock=clock,
        plugins={"calendar_sync": plugin},
        resolver=resolve,
        http_transport=feeds.transport(),
    )
    async with application.router.lifespan_context(application):
        yield application


@pytest.fixture
async def phone(sync_app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=sync_app)
    async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as http:
        response = await run_setup(http)
        assert response.status_code == 201, response.text
        yield http


async def week(phone: httpx.AsyncClient) -> list[dict[str, Any]]:
    response = await phone.get(
        "/api/calendar/occurrences", params={"from": "2026-10-04", "to": "2026-10-11"}
    )
    assert response.status_code == 200, response.text
    found: list[dict[str, Any]] = response.json()["occurrences"]
    return found


async def test_a_calendar_address_is_on_the_board_at_once(
    phone: httpx.AsyncClient, feeds: FeedServer
) -> None:
    mia = await add_member(phone, "Mia", role="kid")
    added = await phone.post(
        "/api/calendar-sync/accounts/ics",
        json={"url": "webcal://school.example.com/school.ics", "owner_member_id": mia["id"]},
        headers=CSRF,
    )
    assert added.status_code == 201, added.text
    account = added.json()
    assert (account["label"], account["provider"], account["status"]) == (
        "School",
        "ics",
        "connected",
    )
    assert account["address"] == "school.example.com/school.ics"
    assert account["read_only"] is True
    assert [(c["name"], c["mapped"], c["owner_member_id"]) for c in account["calendars"]] == [
        ("School", True, mia["id"])
    ]
    found = await week(phone)
    assert [(o["title"], o["member_ids"], o["read_only"]) for o in found] == [
        ("Field trip", [mia["id"]], True),
        ("Pajama day", [mia["id"]], True),
    ]
    assert feeds.requests[0].url.scheme == "https"  # webcal:// became https://
    # It shows events only.
    trip = found[0]
    refused = await phone.patch(
        f"/api/calendar/events/{trip['event_id']}", json={"title": "Trip"}, headers=CSRF
    )
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "calendar_read_only"
    assert "a calendar address" in refused.json()["error"]["message"]


async def test_an_address_that_isnt_a_calendar_says_so(
    phone: httpx.AsyncClient, feeds: FeedServer
) -> None:
    feeds.feeds["/page.html"] = "<html>not a calendar</html>"
    for path, message in (
        ("/page.html", "That address didn't give us a calendar"),
        ("/missing.ics", "That calendar address doesn't work any more"),
    ):
        response = await phone.post(
            "/api/calendar-sync/accounts/ics",
            json={"url": f"https://school.example.com{path}"},
            headers=CSRF,
        )
        assert response.status_code == 422, response.text
        assert response.json()["error"]["message"].startswith(message)
    assert (await phone.get("/api/calendar-sync/accounts")).json() == []


async def allowlist(phone: httpx.AsyncClient) -> list[tuple[str, str]]:
    response = await phone.get("/api/network-allowlist")
    assert response.status_code == 200, response.text
    return [(row["target"], row["label"]) for row in response.json()]


async def test_a_private_address_waits_for_a_parent_s_tick(phone: httpx.AsyncClient) -> None:
    body = {"url": "http://192.168.1.20/school.ics"}
    refused = await phone.post("/api/calendar-sync/accounts/ics", json=body, headers=CSRF)
    assert refused.status_code == 422
    assert refused.json()["error"]["code"] == "address_failed"
    assert refused.json()["error"]["message"] == (
        'That address is on your home network. A parent can allow it: tick "This server is on '
        'your home network".'
    )
    assert await allowlist(phone) == []
    # The tick does what it says (ADR 0036): the host joins the allowlist, named after the
    # feature, and the account is added.
    added = await phone.post(
        "/api/calendar-sync/accounts/ics", json=body | {"allow_private": True}, headers=CSRF
    )
    assert added.status_code == 201, added.text
    assert await allowlist(phone) == [("192.168.1.20/32", "Calendars & Accounts")]
    # A second account on the same server shares the row; the row goes with the last of them.
    second = await phone.post(
        "/api/calendar-sync/accounts/ics",
        json={"url": "http://192.168.1.20/school.ics?term=2", "allow_private": True},
        headers=CSRF,
    )
    assert second.status_code == 201, second.text
    assert await allowlist(phone) == [("192.168.1.20/32", "Calendars & Accounts")]
    gone = await phone.delete(f"/api/calendar-sync/accounts/{added.json()['id']}", headers=CSRF)
    assert gone.status_code == 204
    assert await allowlist(phone) == [("192.168.1.20/32", "Calendars & Accounts")]
    gone = await phone.delete(f"/api/calendar-sync/accounts/{second.json()['id']}", headers=CSRF)
    assert gone.status_code == 204
    assert await allowlist(phone) == []


async def test_a_tick_on_an_address_that_fails_leaves_the_allowlist_as_it_was(
    phone: httpx.AsyncClient,
) -> None:
    by_hand = await phone.post(
        "/api/network-allowlist", json={"target": "nas.lan", "label": "Sample NAS"}, headers=CSRF
    )
    assert by_hand.status_code == 201, by_hand.text
    for url in ("http://192.168.1.20/missing.ics", "http://nas.lan/missing.ics"):
        failed = await phone.post(
            "/api/calendar-sync/accounts/ics",
            json={"url": url, "allow_private": True},
            headers=CSRF,
        )
        assert failed.status_code == 422, failed.text
    # Nothing of the failed attempts stays, and a row added by hand is never taken out.
    assert await allowlist(phone) == [("nas.lan", "Sample NAS")]


async def test_holidays_need_no_address(phone: httpx.AsyncClient) -> None:
    places = (await phone.get("/api/calendar-sync/holidays/places")).json()
    assert any(p["country"] == "US" and "CA" in p["subdivisions"] for p in places)
    added = await phone.post(
        "/api/calendar-sync/accounts/holidays",
        json={"country": "us", "subdivision": "ca"},
        headers=CSRF,
    )
    assert added.status_code == 201, added.text
    assert added.json()["label"] == "Holidays · US-CA"
    response = await phone.get(
        "/api/calendar/occurrences", params={"from": "2026-12-20", "to": "2026-12-31"}
    )
    assert "Christmas Day" in [o["title"] for o in response.json()["occurrences"]]
    unknown = await phone.post(
        "/api/calendar-sync/accounts/holidays", json={"country": "ZZ"}, headers=CSRF
    )
    assert unknown.status_code == 422


async def test_holidays_follow_the_households_language_at_the_next_sync(
    phone: httpx.AsyncClient, plugin: CalendarSync
) -> None:
    """The holidays are named in the household's language where the holidays package has them
    in it for that country (ADR 0043): an English household sees Spain's in English, and once
    the household speaks Spanish, the next sync names them in Spanish."""
    added = await phone.post(
        "/api/calendar-sync/accounts/holidays", json={"country": "es"}, headers=CSRF
    )
    assert added.status_code == 201, added.text

    async def new_year() -> list[str]:
        response = await phone.get(
            "/api/calendar/occurrences", params={"from": "2027-01-01", "to": "2027-01-02"}
        )
        assert response.status_code == 200, response.text
        return [o["title"] for o in response.json()["occurrences"]]

    assert await new_year() == ["New Year's Day"]
    spanish = await phone.patch("/api/settings", json={"language": "es"}, headers=CSRF)
    assert spanish.status_code == 200, spanish.text
    assert await new_year() == ["New Year's Day"]  # until the next sync
    assert plugin.engine is not None
    await plugin.engine.sync_account(added.json()["id"])
    assert await new_year() == ["Año Nuevo"]


async def test_mapping_sets_the_person_and_color_and_disconnecting_clears_the_board(
    phone: httpx.AsyncClient,
) -> None:
    added = await phone.post(
        "/api/calendar-sync/accounts/ics",
        json={"url": "https://school.example.com/school.ics"},
        headers=CSRF,
    )
    account = added.json()
    row = account["calendars"][0]
    assert {o["color"] for o in await week(phone)} == {"sea"}  # Everyone's: the calendar's color
    sam = await add_member(phone, "Sam")
    mapped = await phone.put(
        f"/api/calendar-sync/accounts/{account['id']}/calendars/{row['id']}",
        json={"owner_member_id": sam["id"]},
        headers=CSRF,
    )
    assert mapped.status_code == 200, mapped.text
    found = await week(phone)
    assert {tuple(o["member_ids"]) for o in found} == {(sam["id"],)}
    assert {o["color"] for o in found} == {None}  # the person's color now, from their id
    gone = await phone.delete(f"/api/calendar-sync/accounts/{account['id']}", headers=CSRF)
    assert gone.status_code == 204
    assert await week(phone) == []
    assert (await phone.get("/api/calendar-sync/accounts")).json() == []


async def test_a_device_that_isnt_signed_in_cant_add_accounts(
    phone: httpx.AsyncClient, sync_app: FastAPI
) -> None:
    transport = httpx.ASGITransport(app=sync_app)
    async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as other:
        response = await other.post(
            "/api/calendar-sync/accounts/ics",
            json={"url": "https://school.example.com/school.ics"},
            headers=CSRF,
        )
        assert response.status_code in {401, 403}


async def test_a_shared_calendar_takes_a_color_nobody_has(phone: httpx.AsyncClient) -> None:
    ana = await phone.post(
        "/api/members", json={"name": "Ana", "role": "parent", "color": "sea"}, headers=CSRF
    )
    assert ana.status_code == 201, ana.text
    added = await phone.post(
        "/api/calendar-sync/accounts/ics",
        json={"url": "https://school.example.com/school.ics"},
        headers=CSRF,
    )
    color = added.json()["calendars"][0]["color"]
    assert color not in {"sea", "sky"}  # Ana's, and the Home calendar's


async def test_an_address_that_stops_working_asks_for_its_new_one(
    phone: httpx.AsyncClient, feeds: FeedServer, plugin: CalendarSync
) -> None:
    mia = await add_member(phone, "Mia", role="kid")
    added = await phone.post(
        "/api/calendar-sync/accounts/ics",
        json={"url": "https://school.example.com/school.ics", "owner_member_id": mia["id"]},
        headers=CSRF,
    )
    assert added.status_code == 201, added.text
    account_id = added.json()["id"]
    # The school moves its feed (or a secret address is reset): the old address answers 404.
    feeds.feeds["/moved.ics"] = feeds.feeds.pop("/school.ics")
    assert plugin.engine is not None
    await plugin.engine.sync_account(account_id)
    [account] = (await phone.get("/api/calendar-sync/accounts")).json()
    assert (account["status"], account["last_error"]) == (
        "needs_reconnect",
        "That calendar address doesn't work any more. Paste its new address.",
    )
    assert [o["title"] for o in await week(phone)] == ["Field trip", "Pajama day"]
    # The new address is the same calendar: still Mia's, listed once.
    back = await phone.post(
        f"/api/calendar-sync/accounts/{account_id}/reconnect",
        json={"url": "https://school.example.com/moved.ics"},
        headers=CSRF,
    )
    assert back.status_code == 200, back.text
    await plugin.engine.sync_account(account_id)
    [account] = (await phone.get("/api/calendar-sync/accounts")).json()
    assert (account["status"], account["address"]) == ("connected", "school.example.com/moved.ics")
    assert [(c["mapped"], c["owner_member_id"], c["last_error"]) for c in account["calendars"]] == [
        (True, mia["id"], None)
    ]
    assert [(o["title"], o["member_ids"]) for o in await week(phone)] == [
        ("Field trip", [mia["id"]]),
        ("Pajama day", [mia["id"]]),
    ]
