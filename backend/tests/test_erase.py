"""Erase everything (``POST /api/admin/erase``, ADR 0029): a parent on a phone or computer, with
the household password, after a verified copy; never from a wall screen. The household here is
the test server's Sample Family, which puts rows in every plugin's tables. Synthetic data only."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from fastapi import FastAPI

from sunroom.app import create_app
from sunroom.core.clock import ShiftableClock
from sunroom.db import backup
from sunroom.plugins.base import PluginStatus
from sunroom.plugins.spec import defaults
from tests.support import (
    BASE_URL,
    CSRF,
    StreamProbe,
    make_settings,
    picture,
    session_cookie,
    state_of,
)

SEED_PASSWORD = "sample-family-passphrase"
# What a new install holds once its plugins have started: the household, its Home calendar,
# the wall's Today panel, the app's own row, and the Photos folder as a source of photos.
NEW_INSTALL = {"app_meta": 1, "household": 1, "calendars": 1, "kiosk_panels": 1, "photo_sources": 1}


@pytest.fixture
async def server(data_dir: Path) -> AsyncIterator[FastAPI]:
    application = create_app(
        make_settings(data_dir, sunroom_test_mode=True),
        clock=ShiftableClock(),
        ping_interval_s=0.05,
    )
    async with application.router.lifespan_context(application):
        yield application


def device(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE_URL)


@pytest.fixture
async def phone(server: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """A parent's phone, signed in to the Sample Family on Wednesday 10:00 in New York."""
    async with device(server) as client:
        moved = await client.post(
            "/api/_test/clock", json={"set": "2026-10-07T14:00:00Z"}, headers=CSRF
        )
        assert moved.status_code == 204, moved.text
        seeded = await client.post(
            "/api/_test/seed", json={"password": SEED_PASSWORD}, headers=CSRF
        )
        assert seeded.status_code == 204, seeded.text
        signed = await client.post(
            "/api/auth/login", json={"password": SEED_PASSWORD}, headers=CSRF
        )
        assert signed.status_code == 200, signed.text
        yield client


def row_counts(data_dir: Path) -> dict[str, int]:
    conn = sqlite3.connect(data_dir / "sunroom.db")
    try:
        tables = [
            name
            for (name,) in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
                " AND name != 'alembic_version' AND name NOT LIKE 'sqlite_%'"
            )
        ]
        return {t: conn.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0] for t in tables}  # noqa: S608
    finally:
        conn.close()


def one_row(data_dir: Path, query: str) -> tuple[Any, ...]:
    conn = sqlite3.connect(data_dir / "sunroom.db")
    try:
        row: tuple[Any, ...] = conn.execute(query).fetchone()
        return row
    finally:
        conn.close()


async def erase(client: httpx.AsyncClient, password: str = SEED_PASSWORD) -> httpx.Response:
    return await client.post("/api/admin/erase", json={"password": password}, headers=CSRF)


async def eventually_running(app: FastAPI, within_s: float = 3.0) -> None:
    manager = state_of(app).plugins
    deadline = asyncio.get_running_loop().time() + within_s
    while any(
        manager.is_enabled(plugin_id) and manager.status(plugin_id) is not PluginStatus.RUNNING
        for plugin_id in manager.registry
    ):
        assert asyncio.get_running_loop().time() < deadline, "the plugins never started again"
        await asyncio.sleep(0.01)


async def test_a_wall_screen_cant_erase(
    server: FastAPI, phone: httpx.AsyncClient, data_dir: Path
) -> None:
    before = row_counts(data_dir)
    async with device(server) as wall:
        paired = await wall.post(
            "/api/auth/kiosk/pair-with-password", json={"password": SEED_PASSWORD}, headers=CSRF
        )
        assert paired.status_code == 200, paired.text
        # No PIN in this household, so the screen is a parent for Settings: still not for this.
        refused = await erase(wall)
        assert refused.status_code == 403, refused.text
        assert refused.json()["error"] == {
            "code": "not_on_a_screen",
            "message": "Erase everything from a signed-in device, not a paired screen.",
            "key": "api.erase.not_on_a_screen",
            "params": {},
        }
    after = row_counts(data_dir)
    assert {table: after[table] for table in before if table != "devices"} == {
        table: count for table, count in before.items() if table != "devices"
    }
    assert not (data_dir / "backups" / backup.PRE_ERASE_DIR).exists()


async def test_a_wrong_password_erases_nothing_and_counts_like_a_wrong_sign_in(
    server: FastAPI, phone: httpx.AsyncClient, data_dir: Path
) -> None:
    before = row_counts(data_dir)
    limiter = state_of(server).login_limiter
    refused = await erase(phone, "not-the-household-password")
    assert refused.status_code == 403, refused.text
    assert refused.json()["error"] == {
        "code": "wrong_password",
        "message": "That password didn't match. Try again.",
        "key": "api.auth.wrong_password",
        "params": {},
    }
    assert sum(limiter.recent_failures(key) for key in ("127.0.0.1", "unknown")) == 1
    assert row_counts(data_dir) == before
    # Still signed in, and enough wrong tries are told to wait, as at sign-in.
    assert (await phone.get("/api/members")).status_code == 200
    answers = [(await erase(phone, "still-not-the-password")).status_code for _ in range(12)]
    assert answers[0] == 403
    assert answers[-1] == 429
    assert row_counts(data_dir) == before
    signed_out = await device(server).post(
        "/api/admin/erase", json={"password": SEED_PASSWORD}, headers=CSRF
    )
    assert signed_out.status_code == 401


async def test_erase_starts_over_after_a_copy(
    server: FastAPI, phone: httpx.AsyncClient, data_dir: Path
) -> None:
    state = state_of(server)
    uploaded = await phone.post(
        "/api/photos",
        content=picture((800, 600)),
        headers=CSRF | {"content-type": "image/jpeg", "x-filename": "garden.jpg"},
    )
    assert uploaded.status_code == 201, uploaded.text
    photos = data_dir / "photos"
    (photos / "inbox" / "from-a-camera.jpg").write_bytes(picture())
    before = row_counts(data_dir)
    assert before["members"] == 4
    assert all(before[table] for table in ("events", "lists", "chores", "meal_entries", "photos"))
    assert any((photos / "library").iterdir())
    epoch_before = one_row(data_dir, "SELECT auth_epoch FROM app_meta")[0]
    changed = await phone.put(
        "/api/plugins/lists/settings", json={"values": {"auto_clear_days": "3"}}, headers=CSRF
    )
    assert changed.status_code == 200, changed.text
    stream = StreamProbe(server, cookie=session_cookie(phone)).start()
    try:
        await stream.wait_for(lambda frames: any(f["type"] == "hello" for f in frames))

        answer = await erase(phone)
        assert answer.status_code == 200, answer.text
        assert answer.json() == {"ok": True}

        # Every open screen hears that its session ended, and its stream closes.
        frames = await stream.wait_for(
            lambda frames: any(f["type"] == "session.expired" for f in frames)
        )
        assert frames[-1]["type"] == "session.expired"
        assert await stream.finished()
    finally:
        await stream.close()

    # The copy made first holds the family, and reads as a good backup.
    copies = list((data_dir / "backups" / backup.PRE_ERASE_DIR).iterdir())
    assert [copy.suffix for copy in copies] == [".db"]
    kept = backup.inspect_backup(copies[0])
    assert kept["quick_check"] == "ok"
    counted = cast("dict[str, int]", kept["row_counts"])
    assert {table: counted[table] for table in before} == before

    # Every table is as a new install has it, once the plugins have started again.
    await eventually_running(server)
    after = row_counts(data_dir)
    registry = state.plugins.registry
    assert {table: count for table, count in after.items() if count} == {
        **NEW_INSTALL,
        "plugin_state": len(registry),
    }
    assert one_row(data_dir, "SELECT name, onboarded_at, timezone FROM household") == (
        "Our home",
        None,
        None,
    )
    home = one_row(data_dir, "SELECT id, name FROM calendars")
    assert home[1] == "Home"
    assert one_row(data_dir, "SELECT default_calendar_id FROM household") == (home[0],)
    assert one_row(data_dir, "SELECT auth_epoch, password_hash FROM app_meta") == (
        epoch_before + 1,
        None,
    )
    conn = sqlite3.connect(data_dir / "sunroom.db")
    try:
        stored = {
            plugin_id: (bool(enabled), json.loads(settings))
            for plugin_id, enabled, settings in conn.execute(
                "SELECT plugin_id, enabled, settings_json FROM plugin_state"
            )
        }
    finally:
        conn.close()
    assert stored == {
        plugin_id: (plugin.manifest.default_enabled, defaults(plugin.manifest.settings_spec))
        for plugin_id, plugin in registry.items()
    }
    assert state.plugins.settings("lists")["auto_clear_days"] == "never"

    # The pictures are gone; what the family dropped in the Photos folder is theirs.
    for folder in ("library", "thumbs", "avatars"):
        assert list((photos / folder).iterdir()) == []
    assert [path.name for path in (photos / "inbox").iterdir()] == ["from-a-camera.jpg"]

    # Nobody is signed in, and Sunroom asks to be set up.
    assert (await phone.get("/api/members")).status_code == 401
    status = (await phone.get("/api/setup/status")).json()
    assert status["setup_complete"] is False
    assert not state.auth.devices
    async with device(server) as fresh:
        again = await fresh.post(
            "/api/setup",
            json={
                "password": "another-household-passphrase",
                "household_name": "Sample Family",
                "timezone": "America/New_York",
            },
            headers=CSRF,
        )
        assert again.status_code == 201, again.text
        assert (await fresh.get("/api/members")).json() == []
        assert [o for o in (await fresh.get("/api/lists")).json()] == []


async def test_without_a_copy_nothing_is_erased(
    server: FastAPI,
    phone: httpx.AsyncClient,
    data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def no_room(source: Path, destination: Path) -> backup.BackupResult:
        raise backup.NoRoomError("not enough free disk space for a verified copy")

    monkeypatch.setattr(backup, "take_backup", no_room)
    before = row_counts(data_dir)
    answer = await erase(phone)
    assert answer.status_code == 500, answer.text
    assert answer.json()["error"] == {
        "code": "backup_failed",
        "message": (
            "Nothing was erased: the copy to keep first couldn't be made "
            "(not enough free disk space for a verified copy)."
        ),
        "key": "api.erase.copy_failed",
        "params": {"reason": "not enough free disk space for a verified copy"},
    }
    assert row_counts(data_dir) == before
    assert (await phone.get("/api/members")).status_code == 200
    assert state_of(server).plugins.status("lists") is PluginStatus.RUNNING
