"""``sunroom restore`` (docs/RESTORE.md): a ``.db``, or the zip from Download everything, swapped
in while the server is stopped. On a fresh volume the zip brings back the events, the lists and
the photos, and every device signs in again (wall screens show their pair code). A zip carrying
anything Sunroom didn't put there is refused before anything changes. Synthetic data only."""

from __future__ import annotations

import fcntl
import json
import os
import re
import sqlite3
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from sunroom import cli
from sunroom.app import create_app
from sunroom.core.clock import FakeClock
from sunroom.core.version import build_info
from sunroom.db import backup
from tests.backup_support import download_everything, seed_household
from tests.support import BASE_URL, CSRF, PASSWORD, login, make_settings, state_of

MANIFEST = {"format": "sunroom-full-backup", "format_version": 1, "app_version": "0.6.0"}
AS_MADE = "Use the zip exactly as Download everything made it."


@dataclass
class Ran:
    code: int
    out: str
    err: str


Restore = Callable[[Path, Path], Ran]


@pytest.fixture
def restore(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> Restore:
    """Run ``sunroom restore <file>`` with DATA_DIR at ``data``, as the container would."""

    def run(file: Path, data: Path) -> Ran:
        capsys.readouterr()  # only what restore prints
        monkeypatch.setenv("DATA_DIR", str(data))
        try:
            cli.main(["restore", str(file)])
            code = 0
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else 1
        captured = capsys.readouterr()
        return Ran(code, captured.out, captured.err)

    return run


def scalar(db: Path, sql: str) -> Any:
    conn = sqlite3.connect(db)
    try:
        return conn.execute(sql).fetchone()[0]
    finally:
        conn.close()


def handmade(
    path: Path,
    database: Path | bytes,
    *,
    manifest: dict[str, Any] | None = MANIFEST,
    extra: dict[str, bytes] | None = None,
) -> Path:
    """A zip shaped like Download everything's, with whatever a test needs changed."""
    with zipfile.ZipFile(path, "w") as archive:
        if isinstance(database, Path):
            archive.write(database, "sunroom.db")
        else:
            archive.writestr("sunroom.db", database)
        if manifest is not None:
            archive.writestr("manifest.json", json.dumps(manifest))
        for name, data in (extra or {}).items():
            archive.writestr(name, data)
    return path


# ---- the zip from Download everything ---------------------------------------------------------


async def test_a_restore_from_download_everything_on_a_fresh_volume_brings_it_all_back(
    app: FastAPI,
    parent: httpx.AsyncClient,
    other: httpx.AsyncClient,
    clock: FakeClock,
    tmp_path: Path,
    restore: Restore,
) -> None:
    """PLAN M5's check: events, photos and lists come back, and the wall screen shows its code."""
    seeded = await seed_household(app, parent)
    paired = await other.post(
        "/api/auth/kiosk/pair-with-password", json={"password": PASSWORD}, headers=CSRF
    )
    assert paired.status_code == 200, paired.text
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    saved = downloads / "sunroom-2026-10-07.zip"
    saved.write_bytes(await download_everything(parent))
    settings = state_of(app).settings
    epoch_before = scalar(settings.db_path, "SELECT auth_epoch FROM app_meta")
    volume = tmp_path / "fresh-volume"

    ran = restore(saved, volume)

    assert ran.code == 0, ran.err
    assert ran.out.splitlines() == [
        "Restored sunroom-2026-10-07.zip. There was no database here before.",
        "4 photos came back.",
        f"It needs Sunroom {build_info().version} or newer. Start the container.",
        "Every device signs in again, and wall screens show a pair code again.",
    ]
    assert scalar(volume / "sunroom.db", "SELECT auth_epoch FROM app_meta") == epoch_before + 1
    for name in seeded.photo_names():
        inside = name.removeprefix("photos/")
        assert (volume / "photos" / inside).read_bytes() == (
            settings.photos_dir / inside
        ).read_bytes()
    assert not list(volume.glob("sunroom.restore.partial.db*"))

    restored = create_app(make_settings(volume), clock=clock)
    async with restored.router.lifespan_context(restored):
        transport = httpx.ASGITransport(app=restored)
        old = httpx.Cookies(parent.cookies)
        async with (
            httpx.AsyncClient(transport=transport, base_url=BASE_URL, cookies=old) as old_phone,
            httpx.AsyncClient(
                transport=transport, base_url=BASE_URL, cookies=httpx.Cookies(other.cookies)
            ) as old_screen,
            httpx.AsyncClient(transport=transport, base_url=BASE_URL) as screen,
            httpx.AsyncClient(transport=transport, base_url=BASE_URL) as phone,
        ):
            assert (await old_phone.get("/api/auth/session")).status_code == 401
            assert (await old_screen.get("/api/auth/session")).status_code == 401
            pairing = await screen.post("/api/auth/kiosk/pairings", headers=CSRF)
            assert pairing.status_code == 201, pairing.text  # the wall shows its pair code
            assert len(pairing.json()["code"]) == 6

            assert (await login(phone)).status_code == 200  # the household password still works
            week = await phone.get(
                "/api/calendar/occurrences", params={"from": "2026-10-04", "to": "2026-10-11"}
            )
            assert [o["title"] for o in week.json()["occurrences"]] == ["Dentist"]
            groceries = (await phone.get(f"/api/lists/{seeded.list_id}/items")).json()
            assert sorted(item["text"] for item in groceries["items"]) == ["Eggs", "Milk"]
            photos = (await phone.get("/api/photos")).json()["photos"]
            assert sorted(photo["id"] for photo in photos) == sorted(seeded.library)
            picture = await phone.get(f"/photos/library/{seeded.library[0]}.webp")
            assert picture.status_code == 200 and picture.content.startswith(b"RIFF")


async def test_a_photo_already_on_the_volume_stays_as_it_is(
    app: FastAPI, parent: httpx.AsyncClient, tmp_path: Path, restore: Restore
) -> None:
    seeded = await seed_household(app, parent)
    saved = tmp_path / "sunroom-2026-10-07.zip"
    saved.write_bytes(await download_everything(parent))
    volume = tmp_path / "volume"
    there = volume / "photos" / "library" / f"{seeded.library[0]}.webp"
    there.parent.mkdir(parents=True)
    there.write_bytes(b"already here")

    ran = restore(saved, volume)

    assert ran.code == 0, ran.err
    assert "3 photos came back. 1 photo was already here and was left as is." in ran.out
    assert there.read_bytes() == b"already here"
    assert (volume / "photos" / "thumbs" / f"{seeded.library[0]}.webp").is_file()


@pytest.mark.parametrize(
    "name",
    [
        "../x",
        "/x.webp",
        "photos/library/../../x.webp",
        "photos/inbox/from-a-camera.jpg",
        "photos/library/",
        "photos/library/not-an-id.webp",
        "secret.key",
    ],
)
def test_a_zip_with_anything_sunroom_didnt_put_there_is_refused(
    name: str, data_dir: Path, tmp_path: Path, restore: Restore
) -> None:
    saved = handmade(tmp_path / "odd.zip", data_dir / "sunroom.db", extra={name: b"surprise"})
    volume = tmp_path / "volume"

    ran = restore(saved, volume)

    assert ran.code == 1
    assert ran.err.strip() == (
        f"That zip has something in it that Sunroom didn't put there ({name}), so nothing was "
        f"restored. {AS_MADE}"
    )
    assert sorted(os.listdir(volume)) == [".lock"]  # nothing restored
    assert not (tmp_path / "x").exists() and not (tmp_path / "x.webp").exists()


def test_a_zip_without_a_manifest_is_refused(
    data_dir: Path, tmp_path: Path, restore: Restore
) -> None:
    saved = handmade(tmp_path / "no-manifest.zip", data_dir / "sunroom.db", manifest=None)
    ran = restore(saved, tmp_path / "volume")
    assert ran.code == 1
    assert ran.err.strip() == (
        "That zip has no manifest.json, so it isn't one Download everything made. "
        "Nothing was restored."
    )
    assert not (tmp_path / "volume" / "sunroom.db").exists()


def test_a_zip_from_a_newer_sunroom_is_refused(
    data_dir: Path, tmp_path: Path, restore: Restore
) -> None:
    newer = MANIFEST | {"format_version": 2, "app_version": "0.9.0"}
    saved = handmade(tmp_path / "newer.zip", data_dir / "sunroom.db", manifest=newer)
    ran = restore(saved, tmp_path / "volume")
    assert ran.code == 1
    assert ran.err.strip() == (
        "That zip is from a newer Sunroom (0.9.0). Run restore with that version's image or newer."
    )


def test_a_damaged_database_in_the_zip_changes_nothing(
    data_dir: Path, tmp_path: Path, restore: Restore
) -> None:
    before = (data_dir / "sunroom.db").read_bytes()
    damaged = b"SQLite format 3\x00" + b"\xff" * 4096
    saved = handmade(tmp_path / "damaged.zip", damaged)

    ran = restore(saved, data_dir)

    assert ran.code == 1
    assert "That backup is damaged" in ran.err
    assert (data_dir / "sunroom.db").read_bytes() == before
    assert not list(data_dir.glob("sunroom.restore.partial.db*"))
    assert not list(data_dir.glob("sunroom.pre-restore.*"))


def test_restore_refuses_while_sunroom_is_running(
    data_dir: Path, tmp_path: Path, restore: Restore
) -> None:
    saved = handmade(tmp_path / "sunroom.zip", data_dir / "sunroom.db")
    before = (data_dir / "sunroom.db").read_bytes()
    held = os.open(data_dir / ".lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)  # the running server's lock
        ran = restore(saved, data_dir)
    finally:
        os.close(held)
    assert ran.code == 1
    assert ran.err.strip() == (
        "Sunroom is running. Stop it first (docker stop sunroom), then run restore again."
    )
    assert (data_dir / "sunroom.db").read_bytes() == before


# ---- a .db file --------------------------------------------------------------------------------


def add_person(db: Path, member_id: str, name: str) -> None:
    conn = sqlite3.connect(db)
    try:
        conn.execute(
            "INSERT INTO members (id, name, role, color, sort, created_at) "
            "VALUES (?, ?, 'parent', 'clay', 0, '2026-10-06 12:00:00')",
            (member_id, name),
        )
        conn.commit()
    finally:
        conn.close()


def people(db: Path) -> list[str]:
    conn = sqlite3.connect(db)
    try:
        return [row[0] for row in conn.execute("SELECT name FROM members ORDER BY name")]
    finally:
        conn.close()


def test_a_nightly_db_swaps_in_and_the_previous_database_can_come_back(
    data_dir: Path, tmp_path: Path, restore: Restore
) -> None:
    db = data_dir / "sunroom.db"
    add_person(db, "m1", "Ana")
    nightly = tmp_path / "sunroom.2026-10-06.db"
    backup.take_backup(db, nightly)
    add_person(db, "m2", "Sam")  # added after that night's backup
    epoch = scalar(db, "SELECT auth_epoch FROM app_meta")

    ran = restore(nightly, data_dir)

    assert ran.code == 0, ran.err
    lines = ran.out.splitlines()
    kept = re.fullmatch(
        r"Restored sunroom\.2026-10-06\.db\. The previous database is kept as "
        r"(sunroom\.pre-restore\.\d{8}T\d{6}Z(?:-\d+)?\.db)\.",
        lines[0],
    )
    assert kept is not None, lines[0]
    assert lines[1] == "A .db backup holds no photos: the photos on the volume stay as they are."
    assert people(db) == ["Ana"]
    assert scalar(db, "SELECT auth_epoch FROM app_meta") == epoch + 1

    previous = data_dir / kept.group(1)
    assert people(previous) == ["Ana", "Sam"]
    again = restore(previous, data_dir)  # going back (docs/RESTORE.md)
    assert again.code == 0, again.err
    assert people(db) == ["Ana", "Sam"]
    assert previous.exists()  # a second restore never overwrites the first one's copy
    assert len(list(data_dir.glob("sunroom.pre-restore.*.db"))) == 2


def test_a_db_comes_back_with_what_its_wal_still_held(
    data_dir: Path, tmp_path: Path, restore: Restore
) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    source = elsewhere / "sunroom.db"
    source.write_bytes((data_dir / "sunroom.db").read_bytes())
    writer = sqlite3.connect(source)
    try:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute(
            "INSERT INTO members (id, name, role, color, sort, created_at) "
            "VALUES ('m1', 'Mia', 'kid', 'olive', 0, '2026-10-06 12:00:00')"
        )
        writer.commit()  # in the -wal, not yet in the file itself
        assert Path(f"{source}-wal").stat().st_size > 0
        ran = restore(source, tmp_path / "volume")
    finally:
        writer.close()
    assert ran.code == 0, ran.err
    assert people(tmp_path / "volume" / "sunroom.db") == ["Mia"]
    assert not list((tmp_path / "volume").glob("sunroom.db-*"))  # one self-contained file


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads any file")
def test_a_backup_restore_cant_read_gets_a_plain_answer(
    data_dir: Path, tmp_path: Path, restore: Restore
) -> None:
    saved = handmade(tmp_path / "sunroom.zip", data_dir / "sunroom.db")
    saved.chmod(0o000)
    try:
        ran = restore(saved, tmp_path / "volume")
    finally:
        saved.chmod(0o600)
    assert ran.code == 1
    assert ran.err.strip() == (
        "Restore isn't allowed to read sunroom.zip. Let everyone read it (chmod a+r sunroom.zip, "
        "in its folder on the server), then run restore again."
    )


def test_what_isnt_a_backup_is_refused(tmp_path: Path, restore: Restore) -> None:
    notes = tmp_path / "notes.txt"
    notes.write_text("not a backup")
    ran = restore(notes, tmp_path / "volume")
    assert ran.code == 1
    assert ran.err.strip() == (
        "That file isn't a Sunroom backup. Restore takes a .db file or the .zip from "
        "Download everything."
    )
    unzipped = tmp_path / "sunroom-2026-10-07"
    unzipped.mkdir()
    ran = restore(unzipped, tmp_path / "volume")
    assert ran.code == 1
    assert ran.err.strip() == f"{unzipped} is a folder. Give restore the .db or .zip file itself."


def test_every_device_signs_in_again_and_the_copy_from_before_is_one_file(
    data_dir: Path, tmp_path: Path, restore: Restore
) -> None:
    """ADR 0034: the sign-in epoch goes above both databases' (the backup's own plus one could
    be the live one, keeping its cookies), and the database moved aside folds in what its -wal
    held, so Settings → Backup can list, download and remove it as one file."""
    db = data_dir / "sunroom.db"
    nightly = tmp_path / "sunroom.2026-10-06.db"
    backup.take_backup(db, nightly)
    conn = sqlite3.connect(nightly)
    try:
        conn.execute("UPDATE app_meta SET auth_epoch = 3")
        conn.commit()
    finally:
        conn.close()
    writer = sqlite3.connect(db)
    writer.execute("PRAGMA journal_mode=WAL")
    writer.execute("PRAGMA wal_autocheckpoint=0")
    writer.execute("UPDATE app_meta SET auth_epoch = 5")
    writer.execute(
        "INSERT INTO members (id, name, role, color, sort, created_at) "
        "VALUES ('m2', 'Sam', 'parent', 'clay', 0, '2026-10-06 12:00:00')"
    )
    writer.commit()
    unwritten = Path(f"{db}-wal").read_bytes()
    before = db.read_bytes()
    writer.close()
    # As a pulled plug leaves it: the last changes only in the -wal.
    db.write_bytes(before)
    Path(f"{db}-wal").write_bytes(unwritten)

    ran = restore(nightly, data_dir)

    assert ran.code == 0, ran.err
    assert scalar(db, "SELECT auth_epoch FROM app_meta") == 6
    asides = sorted(path.name for path in data_dir.glob("sunroom.pre-restore.*"))
    assert len(asides) == 1 and asides[0].endswith(".db"), asides
    assert people(data_dir / asides[0]) == ["Sam"]
