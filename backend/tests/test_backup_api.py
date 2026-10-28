"""Settings → Backup through the API (ADR 0034): every copy on the server listed with its kind,
removed only from a signed-in device and never while a backup is written; Data Only, a fresh
checked copy that leaves nothing behind; and the household's policy for the nightly copies."""

from __future__ import annotations

import asyncio
import os
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from sunroom.app import create_app
from sunroom.core.clock import FakeClock, ShiftableClock
from sunroom.db import backup, full_backup
from tests.support import BASE_URL, CSRF, PASSWORD, add_member, make_settings, state_of

BACKUPS = "/api/admin/backups"


def _at(path: Path, when: datetime) -> Path:
    os.utime(path, (when.timestamp(), when.timestamp()))
    return path


def _place_copies(data_dir: Path) -> None:
    """One of each kind, a nightly one from before, and files that aren't copies at all."""
    backups = data_dir / "backups"
    (backups / backup.PRE_MIGRATE_DIR).mkdir(parents=True, exist_ok=True)
    (backups / backup.PRE_ERASE_DIR).mkdir(parents=True, exist_ok=True)
    (backups / ".download").mkdir(exist_ok=True)
    (backups / "sunroom.2026-10-05.db").write_bytes(b"n" * 40)
    _at(backups / "sunroom.2026-10-05.db", datetime(2026, 10, 5, 7, 30, tzinfo=UTC))
    (backups / backup.PRE_MIGRATE_DIR / "sunroom.202610151730.20261006T120000Z.db").write_bytes(
        b"m" * 30
    )
    (backups / backup.PRE_ERASE_DIR / "sunroom.20261006T090000Z.db").write_bytes(b"e" * 20)
    (data_dir / "sunroom.pre-restore.20261006T080000Z.db").write_bytes(b"r" * 10)
    (data_dir / "sunroom.pre-restore.20261006T080000Z.db-wal").write_bytes(b"w")
    for noise in (
        backups / "sunroom.2026-10-04.partial.db",
        backups / "notes.txt",
        backups / ".download" / "sunroom.0123abcd.db",
        backups / backup.PRE_MIGRATE_DIR / "sunroom.202610151730.20261006T110000Z.partial.db",
        data_dir / "sunroom.pre-restore.20261006T080000Z.partial.db",
    ):
        noise.write_bytes(b"x")


async def _screen(other: httpx.AsyncClient) -> httpx.AsyncClient:
    """The wall screen, paired; with no PIN in the household it counts as a parent."""
    paired = await other.post(
        "/api/auth/kiosk/pair-with-password",
        json={"password": PASSWORD, "label": "Wall screen"},
        headers=CSRF,
    )
    assert paired.status_code == 200, paired.text
    return other


async def test_every_copy_is_listed_newest_first_with_its_kind_and_the_policy(
    app: FastAPI, parent: httpx.AsyncClient, data_dir: Path
) -> None:
    ran = await parent.post(f"{BACKUPS}/run", headers=CSRF)
    assert ran.status_code == 200, ran.text
    _at(data_dir / "backups" / ran.json()["file"], datetime(2026, 10, 7, 7, 30, tzinfo=UTC))
    _place_copies(data_dir)

    status = (await parent.get(BACKUPS)).json()
    assert (status["enabled"], status["keep_daily"], status["keep_weekly"]) == (True, 14, 8)
    assert status["retention"] == "14 daily + 8 weekly"
    assert status["busy"] is False
    assert [(f["name"], f["kind"]) for f in status["files"]] == [
        ("sunroom.2026-10-07.db", "nightly"),
        ("sunroom.202610151730.20261006T120000Z.db", "pre-migrate"),
        ("sunroom.20261006T090000Z.db", "pre-erase"),
        ("sunroom.pre-restore.20261006T080000Z.db", "pre-restore"),
        ("sunroom.2026-10-05.db", "nightly"),
    ]
    by_name = {f["name"]: f for f in status["files"]}
    # When a copy was made: the time in its name, in the household's zone (a restore moves the
    # old database aside without touching it), else the file's own time.
    assert by_name["sunroom.pre-restore.20261006T080000Z.db"]["made_at"] == (
        "2026-10-06T04:00:00-04:00"
    )
    assert by_name["sunroom.2026-10-07.db"]["made_at"] == "2026-10-07T03:30:00-04:00"
    assert by_name["sunroom.20261006T090000Z.db"]["bytes"] == 20


async def test_any_copy_downloads_by_its_name_and_nothing_else_does(
    parent: httpx.AsyncClient, data_dir: Path
) -> None:
    _place_copies(data_dir)
    restored = await parent.get(f"{BACKUPS}/sunroom.pre-restore.20261006T080000Z.db")
    assert restored.status_code == 200
    assert restored.content == b"r" * 10
    assert "sunroom.pre-restore.20261006T080000Z.db" in restored.headers["content-disposition"]
    for name in (
        "sunroom.db",  # the live database is no copy
        "sunroom.2026-10-04.partial.db",
        "notes.txt",
        "sunroom.0123abcd.db",
        "full.zip.db",
    ):
        response = await parent.get(f"{BACKUPS}/{name}")
        assert response.status_code == 404, name
        removed = await parent.delete(f"{BACKUPS}/{name}", headers=CSRF)
        assert removed.status_code == 404, name
        assert removed.json()["error"] == {
            "code": "not_found",
            "message": "That backup doesn't exist.",
        }
    # A slash never reaches the route: the path matches only the page's own (GET) fallback.
    for name in ("..%2Fsunroom.db", "sunroom.2026-10-05.db%2F..", "pre-erase%2Fsunroom.db"):
        assert (await parent.get(f"{BACKUPS}/{name}")).status_code == 404, name
        removed = await parent.delete(f"{BACKUPS}/{name}", headers=CSRF)
        assert removed.status_code in {404, 405}, name
    assert (await parent.delete(f"{BACKUPS}/data.db", headers=CSRF)).status_code == 404
    assert (await parent.delete(f"{BACKUPS}/full.zip", headers=CSRF)).status_code == 404
    assert (data_dir / "sunroom.db").is_file()
    assert (data_dir / "backups" / "sunroom.2026-10-05.db").is_file()


async def test_a_parent_removes_a_copy_and_a_wall_screen_cant(
    parent: httpx.AsyncClient, other: httpx.AsyncClient, data_dir: Path
) -> None:
    _place_copies(data_dir)
    screen = await _screen(other)
    name = "sunroom.pre-restore.20261006T080000Z.db"
    refused = await screen.delete(f"{BACKUPS}/{name}", headers=CSRF)
    assert refused.status_code == 403, refused.text
    assert refused.json()["error"] == {
        "code": "not_on_a_screen",
        "message": "Remove backups from a signed-in device.",
    }
    assert (data_dir / name).is_file()
    # The screen still sees the copies, to know they're there.
    assert name in [f["name"] for f in (await screen.get(BACKUPS)).json()["files"]]

    removed = await parent.delete(f"{BACKUPS}/{name}", headers=CSRF)
    assert removed.status_code == 204, removed.text
    assert not (data_dir / name).exists()
    assert not (data_dir / f"{name}-wal").exists()  # what SQLite left beside it goes too
    names = [f["name"] for f in (await parent.get(BACKUPS)).json()["files"]]
    assert name not in names
    assert "sunroom.2026-10-05.db" in names
    again = await parent.delete(f"{BACKUPS}/{name}", headers=CSRF)
    assert again.status_code == 404


async def test_a_copy_isnt_removed_while_a_backup_is_written(
    app: FastAPI,
    parent: httpx.AsyncClient,
    data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _place_copies(data_dir)
    state = state_of(app)
    started, release = threading.Event(), threading.Event()
    real = backup.take_backup

    def slow(source: Path, destination: Path) -> backup.BackupResult:
        started.set()
        release.wait(5)
        return real(source, destination)

    monkeypatch.setattr(backup, "take_backup", slow)
    running = asyncio.create_task(state.backups.run_now())
    try:
        assert await asyncio.to_thread(started.wait, 5)
        assert (await parent.get(BACKUPS)).json()["busy"] is True
        refused = await parent.delete(f"{BACKUPS}/sunroom.2026-10-05.db", headers=CSRF)
        assert refused.status_code == 409, refused.text
        assert refused.json()["error"] == {
            "code": "backup_busy",
            "message": "A backup is being written. Try again in a moment.",
        }
        assert (data_dir / "backups" / "sunroom.2026-10-05.db").is_file()
    finally:
        release.set()
        await running
    assert (await parent.get(BACKUPS)).json()["busy"] is False
    removed = await parent.delete(f"{BACKUPS}/sunroom.2026-10-05.db", headers=CSRF)
    assert removed.status_code == 204


async def test_data_only_is_a_fresh_checked_copy_that_leaves_nothing_behind(
    app: FastAPI, parent: httpx.AsyncClient, data_dir: Path
) -> None:
    ran = await parent.post(f"{BACKUPS}/run", headers=CSRF)
    assert ran.status_code == 200
    await add_member(parent, "Leo", "kid")  # after the nightly copy: only a fresh one has him

    response = await parent.get(f"{BACKUPS}/data.db")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/vnd.sqlite3"
    assert response.headers["cache-control"] == "no-store"
    # The household's date (10 AM in New York on Oct 7).
    assert 'filename="sunroom-2026-10-07.db"' in response.headers["content-disposition"]
    copy = data_dir / "downloaded.db"
    copy.write_bytes(response.content)
    conn = sqlite3.connect(copy)
    try:
        assert conn.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
        names = {row[0] for row in conn.execute("SELECT name FROM members")}
    finally:
        conn.close()
    assert "Leo" in names
    work = data_dir / "backups" / full_backup.WORK_DIR
    assert list(work.iterdir()) == []
    # Not a copy on the server either: the list is what it was.
    files = (await parent.get(BACKUPS)).json()["files"]
    assert [f["name"] for f in files] == [ran.json()["file"]]


async def test_the_nightly_copies_follow_the_households_choices(
    app: FastAPI, parent: httpx.AsyncClient, data_dir: Path, clock: FakeClock
) -> None:
    """The app made today's copy as it started (it's past 3:30 AM): Oct 7's."""
    state = state_of(app)
    changed = await parent.patch(
        "/api/settings",
        json={"backups_enabled": False, "backups_keep_daily": 2, "backups_keep_weekly": 0},
        headers=CSRF,
    )
    assert changed.status_code == 200, changed.text
    body = changed.json()
    assert (body["backups_enabled"], body["backups_keep_daily"], body["backups_keep_weekly"]) == (
        False,
        2,
        0,
    )
    status = (await parent.get(BACKUPS)).json()
    assert (status["enabled"], status["keep_daily"], status["keep_weekly"]) == (False, 2, 0)

    # Off: the 3:30 AM job makes nothing the next day, and a week without a copy isn't "behind".
    clock.advance(hours=20)  # 6 AM on Oct 8 in New York
    assert not state.backups.due()
    await state.backups.tick()
    assert not (data_dir / "backups" / "sunroom.2026-10-08.db").exists()

    # Back Up Now still makes one, and keeps only as many as chosen.
    for day in ("2026-10-01", "2026-10-02", "2026-10-03"):
        (data_dir / "backups" / f"sunroom.{day}.db").write_bytes(b"x")
    ran = await parent.post(f"{BACKUPS}/run", headers=CSRF)
    assert ran.status_code == 200, ran.text
    assert ran.json()["file"] == "sunroom.2026-10-08.db"
    kept = sorted(path.name for path in (data_dir / "backups").glob("sunroom.*.db"))
    assert kept == ["sunroom.2026-10-07.db", "sunroom.2026-10-08.db"]
    clock.advance(days=9)
    assert (await parent.get(BACKUPS)).json()["stale"] is False

    # On again: due after 3:30 AM, as before.
    on = await parent.patch("/api/settings", json={"backups_enabled": True}, headers=CSRF)
    assert on.status_code == 200
    assert state.backups.due()


@pytest.mark.parametrize(
    ("change", "accepted"),
    [
        ({"backups_keep_daily": 0}, False),
        ({"backups_keep_daily": 1}, True),
        ({"backups_keep_daily": 30}, True),
        ({"backups_keep_daily": 31}, False),
        ({"backups_keep_weekly": 0}, True),
        ({"backups_keep_weekly": 12}, True),
        ({"backups_keep_weekly": 13}, False),
        ({"backups_keep_weekly": -1}, False),
    ],
)
async def test_the_counts_stay_in_range(
    parent: httpx.AsyncClient, change: dict[str, int], accepted: bool
) -> None:
    response = await parent.patch("/api/settings", json=change, headers=CSRF)
    assert response.status_code == (200 if accepted else 422), response.text


async def test_erase_puts_the_policy_back(app: FastAPI, parent: httpx.AsyncClient) -> None:
    state = state_of(app)
    await parent.patch(
        "/api/settings", json={"backups_enabled": False, "backups_keep_daily": 3}, headers=CSRF
    )
    assert state.household.backups == backup.BackupPolicy(enabled=False, keep_daily=3)
    erased = await parent.post("/api/admin/erase", json={"password": PASSWORD}, headers=CSRF)
    assert erased.status_code == 200, erased.text
    assert state.household.backups == backup.BackupPolicy()


async def test_the_test_servers_reset_leaves_no_copies(data_dir: Path) -> None:
    """Every end-to-end test starts like a new server: no copies listed, none remembered."""
    application = create_app(
        make_settings(data_dir, sunroom_test_mode=True), clock=ShiftableClock()
    )
    async with application.router.lifespan_context(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as http:
            _place_copies(data_dir)
            state = state_of(application)
            assert state.backups.copies()
            reset = await http.post("/api/_test/reset", headers=CSRF)
            assert reset.status_code == 204, reset.text
            assert state.backups.copies() == []
            assert state.backups.last_success_at is None
            asides = await asyncio.to_thread(lambda: list(data_dir.glob("sunroom.pre-restore.*")))
            assert asides == []
            assert (data_dir / "sunroom.db").is_file()
