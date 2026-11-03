"""Download everything (PLAN §13.7): one zip with a fresh copy of the database, the photos and a
manifest, streamed with bounded memory, for parents only, leaving nothing behind on the server.
The household is the synthetic Sample Family; every photo is a flat color."""

from __future__ import annotations

import asyncio
import io
import json
import os
import sqlite3
import threading
import time
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from sunroom.core.version import build_info
from sunroom.db import backup, full_backup, migrate
from sunroom.photos.store import FOLDERS
from tests.backup_support import FULL_ZIP, NY, download_everything, seed_household
from tests.support import BASE_URL, CSRF, PASSWORD, login, session_cookie, set_pin, state_of

WORKER = "download-everything"


def work_dir(app: FastAPI) -> Path:
    return state_of(app).settings.backup_dir / full_backup.WORK_DIR


def leftovers(app: FastAPI) -> list[str]:
    folder = work_dir(app)
    return sorted(path.name for path in folder.iterdir()) if folder.is_dir() else []


def workers() -> list[threading.Thread]:
    return [thread for thread in threading.enumerate() if thread.name == WORKER]


async def until(condition: Callable[[], bool], within_s: float = 5.0) -> None:
    deadline = time.monotonic() + within_s
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(0.02)


def counts(db: Path, tables: tuple[str, ...]) -> dict[str, int]:
    conn = sqlite3.connect(db)
    try:
        return {
            table: int(conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])  # noqa: S608
            for table in tables
        }
    finally:
        conn.close()


async def test_download_everything_holds_the_database_photos_and_a_manifest(
    app: FastAPI, parent: httpx.AsyncClient, tmp_path: Path
) -> None:
    seeded = await seed_household(app, parent)
    photos = state_of(app).photos.root
    # Never in the zip: what waits in the inbox, what the reconcile set aside, a half-written
    # file, and anything that isn't a photo's own file.
    (photos / "inbox" / "from-a-camera.jpg").write_bytes(b"inbox")
    (photos / ".orphans" / f"library-{seeded.library[0]}.webp").write_bytes(b"orphan")
    (photos / "library" / f"{seeded.library[0]}.webp.partial").write_bytes(b"half")
    (photos / "library" / "notes.txt").write_bytes(b"stray")

    response = await parent.get(FULL_ZIP)

    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/zip"
    # 10:00 on Wednesday in New York: the household's date names the file.
    assert (
        response.headers["content-disposition"] == 'attachment; filename="sunroom-2026-10-07.zip"'
    )
    assert response.headers["cache-control"] == "no-store"
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        names = archive.namelist()
        assert archive.testzip() is None  # every entry's checksum matches
        assert names[0] == "sunroom.db" and names[-1] == "manifest.json"
        assert sorted(names[1:-1]) == seeded.photo_names()
        assert archive.getinfo("sunroom.db").compress_type == zipfile.ZIP_DEFLATED
        assert {archive.getinfo(name).compress_type for name in names[1:-1]} == {zipfile.ZIP_STORED}
        for name in names[1:-1]:
            assert archive.read(name) == (photos / name.removeprefix("photos/")).read_bytes()
        manifest = json.loads(archive.read("manifest.json"))
        (tmp_path / "sunroom.db").write_bytes(archive.read("sunroom.db"))

    copy = tmp_path / "sunroom.db"
    conn = sqlite3.connect(copy)
    try:
        assert conn.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        assert conn.execute("SELECT title FROM events").fetchall() == [("Dentist",)]
        items = conn.execute("SELECT text FROM list_items ORDER BY text").fetchall()
        assert items == [("Eggs",), ("Milk",)]
    finally:
        conn.close()
    assert manifest == {
        "format": "sunroom-full-backup",
        "format_version": 1,
        "app_version": build_info().version,
        "schema_revision": migrate.head_revision(),
        "created_at": "2026-10-07T14:00:00+00:00",
        "photo_files": {"library": 3, "thumbs": 3, "avatars": 1},
        "row_counts": counts(copy, full_backup.MANIFEST_TABLES),
    }
    rows = manifest["row_counts"]
    assert (rows["members"], rows["events"], rows["list_items"], rows["photos"]) == (2, 1, 2, 4)
    assert leftovers(app) == []  # the database copy went as soon as it was in the zip


async def test_only_a_parent_can_download_everything(
    app: FastAPI, parent: httpx.AsyncClient, other: httpx.AsyncClient
) -> None:
    await set_pin(parent)
    kid_phone = (await login(other)).json()["device_id"]
    marked = await parent.patch(
        f"/api/auth/devices/{kid_phone}", json={"is_kid_device": True}, headers=CSRF
    )
    assert marked.status_code == 200, marked.text
    refused = await other.get(FULL_ZIP)
    assert refused.status_code == 403
    assert refused.json()["error"]["code"] == "parent_required"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE_URL) as wall:
        paired = await wall.post(
            "/api/auth/kiosk/pair-with-password", json={"password": PASSWORD}, headers=CSRF
        )
        assert paired.status_code == 200, paired.text
        assert (await wall.get(FULL_ZIP)).status_code == 403  # a PIN exists: the screen asks it
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url=BASE_URL
    ) as stranger:
        assert (await stranger.get(FULL_ZIP)).status_code == 401
    assert leftovers(app) == []  # nothing was copied for anyone turned away


async def test_the_zip_streams_in_small_chunks_and_waits_for_a_slow_phone(
    app: FastAPI, parent: httpx.AsyncClient
) -> None:
    seeded = await seed_household(app, parent, photos=6)
    state = state_of(app)
    copy = await asyncio.to_thread(
        full_backup.make_database_copy, state.settings.db_path, state.settings.backup_dir
    )
    stream = full_backup.FullBackupStream(
        db_copy=copy,
        photos_root=state.photos.root,
        app_version="0.0.0",
        created_at=state.clock.now(),
        zone=NY,
        chunk_bytes=4096,
        in_flight=2,
    )
    chunks = stream.chunks()
    first = await anext(chunks)
    pipe = stream.pipe
    assert pipe is not None and len(first) == 4096
    # The phone has read one chunk: the worker fills the two places in the queue, then waits.
    await until(lambda: pipe.chunks_sent == 3)
    await asyncio.sleep(0.3)
    assert pipe.chunks_sent == 3
    rest = [chunk async for chunk in chunks]
    sizes = [len(first), *(len(chunk) for chunk in rest)]
    assert len(sizes) > 3  # the worker had more to send while it waited
    assert sizes[:-1] == [4096] * (len(sizes) - 1) and 0 < sizes[-1] <= 4096
    with zipfile.ZipFile(io.BytesIO(first + b"".join(rest))) as archive:
        assert archive.testzip() is None
        assert sorted(archive.namelist()) == sorted(
            [*seeded.photo_names(), "manifest.json", "sunroom.db"]
        )
    assert stream.manifest is not None
    assert stream.manifest["photo_files"] == {"library": 6, "thumbs": 6, "avatars": 1}
    await until(lambda: not workers())
    assert not copy.exists()


@dataclass
class StalledPhone:
    """Drives the app like a phone that reads the first piece of the zip, stalls, then goes
    away. ASGI spec 2.3, as uvicorn's HTTP servers say: Starlette then listens for the
    disconnect and cancels the response."""

    app: FastAPI
    cookie: str
    started: asyncio.Event = field(default_factory=asyncio.Event)
    gone: asyncio.Event = field(default_factory=asyncio.Event)
    status: int | None = None
    body: bytes = b""
    task: asyncio.Task[None] | None = None

    def start(self) -> None:
        scope: dict[str, Any] = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": FULL_ZIP,
            "raw_path": FULL_ZIP.encode(),
            "query_string": b"",
            "root_path": "",
            "headers": [(b"host", b"localhost:7867"), (b"cookie", self.cookie.encode())],
            "client": ("127.0.0.1", 50000),
            "server": ("localhost", 7867),
        }
        asked = False
        never = asyncio.Event()

        async def receive() -> dict[str, Any]:
            nonlocal asked
            if not asked:
                asked = True
                return {"type": "http.request", "body": b"", "more_body": False}
            await self.gone.wait()
            return {"type": "http.disconnect"}

        async def send(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                self.status = message["status"]
            elif message["type"] == "http.response.body":
                if self.started.is_set():
                    await never.wait()  # stalled: nothing more is read
                self.body += message.get("body", b"")
                self.started.set()

        self.task = asyncio.create_task(self.app(scope, receive, send))  # pyright: ignore[reportArgumentType]


async def test_a_phone_that_goes_away_mid_download_leaves_nothing_behind(
    app: FastAPI, parent: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Small chunks and one place in the queue: the worker is still zipping the database when
    # the phone stalls, so its copy is still on disk.
    monkeypatch.setattr(full_backup, "CHUNK_BYTES", 1024)
    monkeypatch.setattr(full_backup, "CHUNKS_IN_FLIGHT", 1)
    await seed_household(app, parent)
    phone = StalledPhone(app, session_cookie(parent))
    phone.start()
    await asyncio.wait_for(phone.started.wait(), timeout=5)
    assert phone.status == 200 and phone.body.startswith(b"PK")
    assert len(leftovers(app)) == 1  # the database copy, being zipped
    assert workers()

    phone.gone.set()
    assert phone.task is not None
    await asyncio.wait_for(phone.task, timeout=5)

    await until(lambda: not workers())
    assert leftovers(app) == []


async def test_no_room_for_the_copy_is_a_plain_answer(
    app: FastAPI, parent: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_room(source: Path, destination: Path) -> backup.BackupResult:
        raise backup.NoRoomError("not enough free disk space for a verified copy")

    monkeypatch.setattr(backup, "take_backup", no_room)
    response = await parent.get(FULL_ZIP)
    assert response.status_code == 507
    assert response.json()["error"] == {
        "code": "storage_full",
        "message": "There isn't enough free space on the server to make the download. Free "
        "some space, then try again.",
        "key": "api.backups.no_room_download",
        "params": {},
    }
    assert leftovers(app) == []


async def test_a_copy_left_by_a_killed_download_is_cleared_by_the_next(
    app: FastAPI, parent: httpx.AsyncClient
) -> None:
    folder = work_dir(app)
    folder.mkdir(parents=True)
    stale, recent = folder / "sunroom.0123.db", folder / "sunroom.4567.db"
    stale.write_bytes(b"old")
    recent.write_bytes(b"another download, still running")
    seven_hours_ago = time.time() - 7 * 3600
    os.utime(stale, (seven_hours_ago, seven_hours_ago))
    await download_everything(parent)
    assert leftovers(app) == [recent.name]


async def test_a_nightly_backup_name_still_downloads_that_backup(
    app: FastAPI, parent: httpx.AsyncClient
) -> None:
    """full.zip is declared first; every other name is still a nightly copy's."""
    ran = await parent.post("/api/admin/backups/run", headers=CSRF)
    assert ran.status_code == 200, ran.text
    response = await parent.get(f"/api/admin/backups/{ran.json()['file']}")
    assert response.status_code == 200
    assert response.content.startswith(b"SQLite format 3\x00")


def test_the_zip_knows_every_photo_folder() -> None:
    assert set(full_backup.PHOTO_FOLDERS) == set(FOLDERS.values())
