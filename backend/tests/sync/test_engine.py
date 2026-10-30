"""The sync engine against a scripted server (PLAN §8.2, §8.3): changes both ways, a local
change newer than the server's, a 412 and its retry, a refused password, backing off.
The clock reads Wednesday 2026-10-07, 10:00 in New York. Synthetic data only."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from sunroom.app import create_app
from sunroom.calendar.synced import SyncedEvent, SyncedSeries
from sunroom.core.clock import FakeClock
from sunroom.domain.recurrence import Timing
from sunroom.plugins.calendar_sync.engine import SyncEngine, backoff_seconds
from sunroom.plugins.calendar_sync.plugin import CalendarSync
from sunroom.plugins.calendar_sync.providers.base import ErrorKind
from sunroom.plugins.calendar_sync.providers.fake import FAKE_REMOTES, FakeRemote
from tests.support import BASE_URL, CSRF, make_settings, run_setup

WEEK = {"from": "2026-10-04", "to": "2026-10-11"}
CAL = "family"


@pytest.fixture
async def plugin() -> CalendarSync:
    return CalendarSync()


@pytest.fixture
async def sync_app(
    data_dir: Path, clock: FakeClock, plugin: CalendarSync
) -> AsyncIterator[FastAPI]:
    settings = make_settings(data_dir, sunroom_test_mode=True)
    application = create_app(settings, clock=clock, plugins={"calendar_sync": plugin})
    async with application.router.lifespan_context(application):
        yield application


@pytest.fixture
async def phone(sync_app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=sync_app)
    async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as http:
        response = await run_setup(http)
        assert response.status_code == 201, response.text
        yield http


def engine(plugin: CalendarSync) -> SyncEngine:
    assert plugin.engine is not None, "the plugin should be running"
    return plugin.engine


def timed(uid: str, title: str, start: str, minutes: int = 60, **extra: Any) -> SyncedSeries:
    begin = datetime.fromisoformat(start).replace(tzinfo=UTC)
    return SyncedSeries(
        uid=uid,
        master=SyncedEvent(
            title=title,
            timing=Timing(
                all_day=False, start_utc=begin, end_utc=begin + timedelta(minutes=minutes)
            ),
            tzid="America/New_York",
        ),
        **extra,
    )


async def connected(phone: httpx.AsyncClient, plugin: CalendarSync) -> tuple[str, FakeRemote]:
    """A scripted account with one writable calendar, mapped and synced once."""
    response = await phone.post("/api/calendar-sync/_test/fake", headers=CSRF)
    assert response.status_code == 201, response.text
    account_id = response.json()["id"]
    remote = FAKE_REMOTES[account_id]
    remote.add_calendar(CAL, "Family")
    await engine(plugin).sync_account(account_id)
    account = await get_account(phone, account_id)
    row = account["calendars"][0]
    mapped = await phone.put(
        f"/api/calendar-sync/accounts/{account_id}/calendars/{row['id']}",
        json={"mapped": True},
        headers=CSRF,
    )
    assert mapped.status_code == 200, mapped.text
    await engine(plugin).sync_account(account_id)
    return account_id, remote


async def get_account(phone: httpx.AsyncClient, account_id: str) -> dict[str, Any]:
    accounts = (await phone.get("/api/calendar-sync/accounts")).json()
    found: dict[str, Any] = next(a for a in accounts if a["id"] == account_id)
    return found


async def week(phone: httpx.AsyncClient) -> list[dict[str, Any]]:
    response = await phone.get("/api/calendar/occurrences", params=WEEK)
    assert response.status_code == 200, response.text
    found: list[dict[str, Any]] = response.json()["occurrences"]
    return found


def titles(found: list[dict[str, Any]]) -> list[str]:
    return [o["title"] for o in found]


async def test_server_changes_arrive_and_leave(
    phone: httpx.AsyncClient, plugin: CalendarSync
) -> None:
    account_id, remote = await connected(phone, plugin)
    remote.put(CAL, timed("dentist@test", "Dentist", "2026-10-08T18:30:00"))
    await engine(plugin).sync_account(account_id)
    found = await week(phone)
    assert [(o["title"], o["start_local"], o["source"]) for o in found] == [
        ("Dentist", "2026-10-08T14:30:00", "sync")
    ]
    # Changed on the server: a new etag, a new title.
    remote.put(
        CAL,
        replace(
            remote.items[CAL][f"{CAL}/dentist@test.ics"],
            master=SyncedEvent(
                title="Dentist (Mia)",
                timing=Timing(
                    all_day=False,
                    start_utc=datetime(2026, 10, 8, 18, 30, tzinfo=UTC),
                    end_utc=datetime(2026, 10, 8, 19, 30, tzinfo=UTC),
                ),
                tzid="America/New_York",
            ),
        ),
    )
    await engine(plugin).sync_account(account_id)
    assert titles(await week(phone)) == ["Dentist (Mia)"]
    # Removed on the server: gone here, and in Recently removed.
    remote.remove(CAL, f"{CAL}/dentist@test.ics")
    await engine(plugin).sync_account(account_id)
    assert await week(phone) == []
    removed = (await phone.get("/api/calendar/removed")).json()
    assert [e["title"] for e in removed] == ["Dentist (Mia)"]
    account = await get_account(phone, account_id)
    assert account["status"] == "connected" and account["last_error"] is None


async def test_changes_made_here_reach_the_server(
    phone: httpx.AsyncClient, plugin: CalendarSync
) -> None:
    account_id, remote = await connected(phone, plugin)
    calendar_id = (await get_account(phone, account_id))["calendars"][0]["calendar_id"]
    added = await phone.post(
        "/api/calendar/events",
        json={"title": "Piano lesson", "start": "2026-10-07T15:30", "calendar_id": calendar_id},
        headers=CSRF,
    )
    assert added.status_code == 201, added.text
    event_id = added.json()["event"]["id"]
    assert added.json()["event"]["pending"] is True
    await engine(plugin).push_sweep()
    await engine(plugin).sync_account(account_id)  # the sweep's worker, done synchronously
    assert [s.master.title for s in remote.items[CAL].values() if s.master] == ["Piano lesson"]
    assert (await phone.get(f"/api/calendar/events/{event_id}")).json()["pending"] is False

    changed = await phone.patch(
        f"/api/calendar/events/{event_id}", json={"title": "Piano"}, headers=CSRF
    )
    assert changed.status_code == 200, changed.text
    await engine(plugin).sync_account(account_id)
    assert [s.master.title for s in remote.items[CAL].values() if s.master] == ["Piano"]

    removed = await phone.delete(f"/api/calendar/events/{event_id}", headers=CSRF)
    assert removed.status_code == 200, removed.text
    await engine(plugin).sync_account(account_id)
    assert remote.items[CAL] == {}
    assert len(remote.deletes) == 1


async def test_a_newer_local_change_waits_for_its_push(
    phone: httpx.AsyncClient, plugin: CalendarSync, clock: FakeClock
) -> None:
    account_id, remote = await connected(phone, plugin)
    long_ago = datetime(2026, 10, 1, tzinfo=UTC)
    remote.put(CAL, timed("vet@test", "Vet", "2026-10-07T13:00:00", updated_at=long_ago))
    await engine(plugin).sync_account(account_id)
    event_id = (await week(phone))[0]["event_id"]
    # Changed here, not pushed yet; the server's copy changes too, but earlier.
    changed = await phone.patch(
        f"/api/calendar/events/{event_id}", json={"title": "Vet (Ana)"}, headers=CSRF
    )
    assert changed.status_code == 200
    remote.put(
        CAL,
        timed(
            "vet@test",
            "Vet appointment",
            "2026-10-07T13:00:00",
            remote_id=f"{CAL}/vet@test.ics",
            updated_at=long_ago + timedelta(days=1),
        ),
    )
    await engine(plugin).sync_account(account_id)
    assert titles(await week(phone)) == ["Vet (Ana)"]
    assert [s.master.title for s in remote.items[CAL].values() if s.master] == ["Vet (Ana)"]

    # A server change newer than the local one wins, and nothing is left to push.
    changed = await phone.patch(
        f"/api/calendar/events/{event_id}", json={"title": "Vet at 9"}, headers=CSRF
    )
    assert changed.status_code == 200
    clock.advance(minutes=5)
    remote.put(
        CAL,
        timed(
            "vet@test",
            "Vet moved",
            "2026-10-07T14:00:00",
            remote_id=f"{CAL}/vet@test.ics",
            updated_at=clock.now(),
        ),
    )
    await engine(plugin).sync_account(account_id)
    found = await week(phone)
    assert [(o["title"], o["pending"]) for o in found] == [("Vet moved", False)]


async def test_a_conflict_pulls_merges_and_tries_once_more(
    phone: httpx.AsyncClient, plugin: CalendarSync
) -> None:
    account_id, remote = await connected(phone, plugin)
    old = datetime(2026, 10, 1, tzinfo=UTC)
    remote.put(CAL, timed("book@test", "Book club", "2026-10-08T23:00:00", updated_at=old))
    await engine(plugin).sync_account(account_id)
    event_id = (await week(phone))[0]["event_id"]
    await phone.patch(
        f"/api/calendar/events/{event_id}", json={"title": "Book club!"}, headers=CSRF
    )
    # The server's copy moves on (a new etag) without our pull seeing it: the push gets a 412.
    remote.put(
        CAL,
        timed(
            "book@test",
            "Book club (Sam)",
            "2026-10-08T23:00:00",
            remote_id=f"{CAL}/book@test.ics",
            updated_at=old,
        ),
    )
    await engine(plugin).push_sweep()
    await engine(plugin).sync_account(account_id)
    assert [s.master.title for s in remote.items[CAL].values() if s.master] == ["Book club!"]


async def test_a_refused_password_asks_to_reconnect(
    phone: httpx.AsyncClient, plugin: CalendarSync, sync_app: FastAPI
) -> None:
    account_id, remote = await connected(phone, plugin)
    remote.fail_next(ErrorKind.AUTH)
    await engine(plugin).sync_account(account_id)
    account = await get_account(phone, account_id)
    assert account["status"] == "needs_reconnect"
    assert account["last_error"] == "The test server said that password isn't right."
    assert account["next_sync_at"] is None
    # Needs Attention names it, with the page that fixes it (ADR 0034).
    listed = (await phone.get("/api/problems")).json()["problems"]
    assert [(p["id"], p["title"], p["page"], p["detail"]) for p in listed] == [
        (
            f"sync:{account_id}",
            "Test server needs its password again.",
            "calendars",
            "The test server said that password isn't right.",
        )
    ]
    assert [(p["key"], p["params"]) for p in listed] == [
        ("api.sync.needs_password", {"name": "Test server"})
    ]
    # It isn't tried again until someone reconnects it.
    await engine(plugin).tick()
    assert not engine(plugin).is_running(account_id)


async def test_failures_back_off_and_show_after_three(
    phone: httpx.AsyncClient, plugin: CalendarSync, clock: FakeClock
) -> None:
    account_id, remote = await connected(phone, plugin)
    for expected in ("connected", "connected", "error"):
        remote.fail_next(ErrorKind.UNREACHABLE)
        await engine(plugin).sync_account(account_id)
        account = await get_account(phone, account_id)
        assert account["status"] == expected
        assert account["last_error"] == "The test server didn't answer."
        assert datetime.fromisoformat(account["next_sync_at"]) > clock.now()
        listed = (await phone.get("/api/problems")).json()["problems"]
        # Only once it's an error, after three in a row (ADR 0034): since it last answered.
        assert [p["title"] for p in listed] == (
            ["Test server hasn't answered. Showing what we had."] if expected == "error" else []
        )
    assert listed[0]["since"] == account["last_success_at"]
    await engine(plugin).sync_account(account_id)
    account = await get_account(phone, account_id)
    assert (account["status"], account["last_error"]) == ("connected", None)
    assert (await phone.get("/api/problems")).json()["problems"] == []


def test_backoff_doubles_up_to_an_hour_and_honours_retry_after() -> None:
    flat = lambda: 1.0  # noqa: E731
    assert backoff_seconds(300, 1, jitter=flat) == 600
    assert backoff_seconds(300, 2, jitter=flat) == 1200
    assert backoff_seconds(300, 10, jitter=flat) == 3600
    assert backoff_seconds(300, 1, retry_after=900, jitter=flat) == 900
    assert 0.8 * 600 <= backoff_seconds(300, 1) <= 1.2 * 600
