"""Settings → Backup → Restore from a File through the API (ADR 0034): a backup sent from a
signed-in device is checked and summarised, nothing changes until the household password is
typed, and then Sunroom says so on the live stream, stops its plugins and runs itself again
(here a recorder stands in for that). Boot applies it (tests/test_boot.py). Synthetic data only."""

from __future__ import annotations

import io
import json
import shutil
import zipfile
from collections.abc import AsyncIterator
from typing import Any, NamedTuple

import httpx
import pytest
from fastapi import FastAPI

from sunroom.app import create_app
from sunroom.core.clock import FakeClock
from sunroom.core.config import Settings
from sunroom.db import restore
from tests.backup_support import download_everything, seed_household
from tests.support import (
    BASE_URL,
    CSRF,
    PASSWORD,
    StreamProbe,
    login,
    run_setup,
    session_cookie,
    set_pin,
    state_of,
)

RESTORE = "/api/admin/restore"


@pytest.fixture
def restarts() -> list[str]:
    return []


@pytest.fixture
async def server(
    settings: Settings, clock: FakeClock, restarts: list[str]
) -> AsyncIterator[FastAPI]:
    application = create_app(
        settings, clock=clock, ping_interval_s=0.05, restart=lambda: restarts.append("again")
    )
    async with application.router.lifespan_context(application):
        yield application


@pytest.fixture
async def phone(server: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """A parent's phone, which ran setup."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=server), base_url=BASE_URL
    ) as client:
        assert (await run_setup(client)).status_code == 201
        yield client


async def send(
    client: httpx.AsyncClient, body: bytes, name: str = "sunroom-2026-10-07.zip"
) -> httpx.Response:
    return await client.post(
        RESTORE,
        content=body,
        headers=CSRF | {"Content-Type": "application/octet-stream", "X-Filename": name},
    )


def stage_files(server: FastAPI) -> list[str]:
    folder = restore.stage_dir(state_of(server).settings)
    return sorted(path.name for path in folder.iterdir()) if folder.is_dir() else []


class Sent(NamedTuple):
    zip: bytes
    db: bytes


async def backups_of(server: FastAPI, phone: httpx.AsyncClient) -> Sent:
    await seed_household(server, phone)
    data = await phone.get("/api/admin/backups/data.db")
    assert data.status_code == 200, data.text
    return Sent(zip=await download_everything(phone), db=data.content)


async def test_a_zip_and_a_db_are_checked_and_summarised(
    server: FastAPI, phone: httpx.AsyncClient
) -> None:
    sent = await backups_of(server, phone)
    staged = await send(phone, sent.zip, "sunroom-2026-10-07.zip")
    assert staged.status_code == 200, staged.text
    summary = staged.json()
    assert summary["file_name"] == "sunroom-2026-10-07.zip"
    assert summary["kind"] == "zip"
    assert summary["bytes"] == len(sent.zip)
    assert summary["photo_files"] == 4  # three library photos and an avatar
    assert summary["row_counts"]["members"] == 2
    assert summary["row_counts"]["events"] == 1
    assert summary["needs_upgrade"] is False
    assert summary["created_at"] and summary["app_version"]
    assert (await phone.get(RESTORE)).json() == {"staged": summary, "last": None}
    assert stage_files(server) == ["staged.db", "staged.json", "staged.zip"]

    # Another file replaces the first; a folder in its name is never shown.
    again = await send(phone, sent.db, "Downloads%2Fsunroom-2026-10-07.db")
    assert again.status_code == 200, again.text
    assert again.json()["file_name"] == "sunroom-2026-10-07.db"
    assert (again.json()["kind"], again.json()["photo_files"]) == ("db", 0)
    assert again.json()["created_at"] is None
    assert stage_files(server) == ["staged.db", "staged.json"]


async def test_what_isnt_a_backup_is_refused_and_nothing_is_staged(
    server: FastAPI, phone: httpx.AsyncClient
) -> None:
    refused = await send(phone, b"a shopping list, not a backup", "notes.txt")
    assert refused.status_code == 422
    assert refused.json()["error"] == {
        "code": "not_a_backup",
        "message": "That file isn't a Sunroom backup. Restore takes a .db file or the .zip from "
        "Download everything.",
        "key": "api.restore.not_a_backup",
        "params": {},
    }
    assert (await phone.get(RESTORE)).json() == {"staged": None, "last": None}
    assert stage_files(server) == []


def handmade_zip(manifest: dict[str, Any], database: bytes, **extra: bytes) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        archive.writestr("sunroom.db", database)
        archive.writestr("manifest.json", json.dumps(manifest))
        for name, data in extra.items():
            archive.writestr(name, data)
    return out.getvalue()


async def test_a_damaged_or_newer_backup_gets_restores_own_words(
    server: FastAPI, phone: httpx.AsyncClient
) -> None:
    damaged = await send(phone, b"SQLite format 3\x00" + b"\xff" * 4096, "sunroom.db")
    assert damaged.status_code == 422
    assert damaged.json()["error"] == {
        "code": "backup_damaged",
        "message": "That backup is damaged (it isn't a database Sunroom can read). Pick another.",
        "key": "api.restore.not_a_database",
        "params": {},
    }
    newer = handmade_zip(
        {"format": "sunroom-full-backup", "format_version": 2, "app_version": "9.0.0"}, b"x"
    )
    refused = await send(phone, newer, "sunroom.zip")
    assert refused.status_code == 422
    assert refused.json()["error"] == {
        "code": "backup_newer",
        "message": "That zip is from a newer Sunroom (9.0.0). Run restore with that version's "
        "image or newer.",
        "key": "api.restore.zip_newer",
        "params": {"version": "9.0.0"},
    }
    odd = handmade_zip(
        {"format": "sunroom-full-backup", "format_version": 1, "app_version": "0.6.0"},
        b"x",
        **{"secret.key": b"surprise"},
    )
    refused = await send(phone, odd, "odd.zip")
    assert refused.status_code == 422
    assert refused.json()["error"]["code"] == "zip_not_ours"
    assert "secret.key" in refused.json()["error"]["message"]
    assert stage_files(server) == []


async def test_a_wall_screen_and_a_childs_phone_cant(
    server: FastAPI, phone: httpx.AsyncClient
) -> None:
    transport = httpx.ASGITransport(app=server)
    async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as wall:
        paired = await wall.post(
            "/api/auth/kiosk/pair-with-password", json={"password": PASSWORD}, headers=CSRF
        )
        assert paired.status_code == 200, paired.text
        # No PIN in this household, so the screen is a parent for Settings: still not for this.
        for response in (
            await wall.get(RESTORE),
            await send(wall, b"SQLite format 3\x00"),
            await wall.delete(RESTORE, headers=CSRF),
            await wall.post(f"{RESTORE}/apply", json={"password": PASSWORD}, headers=CSRF),
        ):
            assert response.status_code == 403, response.text
            assert response.json()["error"] == {
                "code": "not_on_a_screen",
                "message": "Restore from a signed-in device.",
                "key": "api.restore.not_on_a_screen",
                "params": {},
            }
    await set_pin(phone)
    async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as kid:
        kid_phone = (await login(kid)).json()["device_id"]
        marked = await phone.patch(
            f"/api/auth/devices/{kid_phone}", json={"is_kid_device": True}, headers=CSRF
        )
        assert marked.status_code == 200, marked.text
        refused = await send(kid, b"SQLite format 3\x00")
        assert refused.status_code == 403
        assert refused.json()["error"]["code"] == "parent_required"
    assert stage_files(server) == []


async def test_no_room_gets_the_plain_answer(
    server: FastAPI, phone: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = shutil.disk_usage

    def full(path: Any) -> Any:
        return real(path)._replace(free=1024)

    monkeypatch.setattr(shutil, "disk_usage", full)
    refused = await send(phone, b"SQLite format 3\x00" + b"\x00" * 100, "sunroom.db")
    assert refused.status_code == 507
    assert refused.json()["error"] == {
        "code": "storage_full",
        "message": "There isn't enough free space on the server for this file. Free some space, "
        "then try again.",
        "key": "api.restore.no_room_upload",
        "params": {},
    }
    assert stage_files(server) == []


async def test_without_its_size_nothing_is_taken(phone: httpx.AsyncClient) -> None:
    async def chunks() -> AsyncIterator[bytes]:
        yield b"SQLite format 3\x00"

    refused = await phone.post(RESTORE, content=chunks(), headers=CSRF)
    assert refused.status_code == 411
    assert refused.json()["error"]["code"] == "length_required"


async def test_keeping_everything_forgets_the_file(
    server: FastAPI, phone: httpx.AsyncClient
) -> None:
    sent = await backups_of(server, phone)
    assert (await send(phone, sent.zip)).status_code == 200
    removed = await phone.delete(RESTORE, headers=CSRF)
    assert removed.status_code == 204
    assert stage_files(server) == []
    assert (await phone.get(RESTORE)).json()["staged"] is None


async def test_restoring_needs_the_password_and_a_file(
    server: FastAPI, phone: httpx.AsyncClient, restarts: list[str]
) -> None:
    nothing = await phone.post(f"{RESTORE}/apply", json={"password": PASSWORD}, headers=CSRF)
    assert nothing.status_code == 409
    assert nothing.json()["error"] == {
        "code": "nothing_staged",
        "message": "There's no file to restore. Choose one first.",
        "key": "api.restore.nothing_staged",
        "params": {},
    }
    sent = await backups_of(server, phone)
    assert (await send(phone, sent.db, "sunroom.db")).status_code == 200
    wrong = await phone.post(
        f"{RESTORE}/apply", json={"password": "not-the-password"}, headers=CSRF
    )
    assert wrong.status_code == 403
    assert wrong.json()["error"] == {
        "code": "wrong_password",
        "message": "That password didn't match. Try again.",
        "key": "api.auth.wrong_password",
        "params": {},
    }
    assert "apply.json" not in stage_files(server)
    assert restarts == []


async def test_restoring_arms_it_and_sunroom_runs_itself_again(
    server: FastAPI,
    phone: httpx.AsyncClient,
    restarts: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = state_of(server)
    stopped: list[str] = []
    stop_plugins, stop_jobs = state.plugins.stop_all, state.jobs.stop

    async def plugins_stop() -> None:
        stopped.append("plugins")
        await stop_plugins()

    async def jobs_stop(timeout_s: float = 5.0) -> None:
        stopped.append("jobs")
        await stop_jobs(timeout_s)

    monkeypatch.setattr(state.plugins, "stop_all", plugins_stop)
    monkeypatch.setattr(state.jobs, "stop", jobs_stop)
    sent = await backups_of(server, phone)
    assert (await send(phone, sent.zip)).status_code == 200
    probe = StreamProbe(server, cookie=session_cookie(phone)).start()
    try:
        await probe.wait_started()
        applied = await phone.post(f"{RESTORE}/apply", json={"password": PASSWORD}, headers=CSRF)
        assert applied.status_code == 200, applied.text
        assert applied.json() == {"ok": True}
        frames = await probe.wait_for(
            lambda f: any(frame["type"] == "server.restarting" for frame in f)
        )
        said = next(frame for frame in frames if frame["type"] == "server.restarting")
        assert said["reason"] == "restore"
    finally:
        await probe.close()
    # By the time the answer is in: the plugins and jobs stopped, then the process ran itself
    # again (here, a recorder), and the health check says "starting".
    assert stopped == ["plugins", "jobs"]
    assert restarts == ["again"]
    health = await phone.get("/api/health")
    assert (health.status_code, health.json()) == (503, {"status": "starting"})
    marker = json.loads((restore.stage_dir(state.settings) / restore.MARKER).read_text())
    assert marker["step"] == "armed"
