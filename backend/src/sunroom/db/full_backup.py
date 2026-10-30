"""Download everything, and reading it back (PLAN §13.7; docs/RESTORE.md).

One zip, ``sunroom-YYYY-MM-DD.zip`` (the household's date), holding exactly:

    sunroom.db                     a fresh verified copy of the database, deflated
    photos/library/<id>.webp       the photos as they are (WebP doesn't shrink further)
    photos/thumbs/<id>.webp
    photos/avatars/<id>.webp
    manifest.json                  what it is: format, versions, when, counts

Never ``photos/inbox/`` or ``photos/.orphans/``, and never the secret key: it stays on the server,
so a lost zip can't sign anyone in or unlock a connected account. ``sunroom restore`` accepts
these names and nothing else.

Memory stays flat on a Pi: a worker thread writes the zip in 64 KB chunks to the event loop, at
most a few waiting at a time, so a slow phone holds the worker back instead of filling memory.
The only thing written to disk is the database copy, under ``backups/.download/``; it goes as
soon as it is in the zip, or however the download ends (an error, the phone going away).
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import sqlite3
import threading
import time
import uuid
import zipfile
import zlib
from collections.abc import AsyncIterator, Callable, Iterator
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol, cast
from zoneinfo import ZoneInfo

from sunroom.core.lang import plain, t_en
from sunroom.core.logging import get_logger
from sunroom.db import backup

log = get_logger(__name__)

FORMAT = "sunroom-full-backup"
FORMAT_VERSION = 1
DATABASE = "sunroom.db"
MANIFEST = "manifest.json"
# The photo store's folders (photos/store.py; a test keeps the two lists equal). A photo's own
# picture is in library/ or avatars/; a library photo's thumbnail comes with it.
PHOTO_FOLDERS = ("library", "thumbs", "avatars")
PICTURE_FOLDERS = ("library", "avatars")
# Row counts in the manifest: enough to recognize a backup at a glance.
MANIFEST_TABLES = (
    "members",
    "calendars",
    "events",
    "lists",
    "list_items",
    "chores",
    "meal_entries",
    "countdowns",
    "photos",
)
WORK_DIR = ".download"  # under backups/: the database copy while a download runs
STALE_AFTER = timedelta(hours=6)  # a copy this old belongs to a download the server never ended
CHUNK_BYTES = 64 * 1024
CHUNKS_IN_FLIGHT = 8
STOP_POLL_S = 0.2
MAX_MANIFEST_BYTES = 1024 * 1024
EXTRACT_CHUNK_BYTES = 1024 * 1024
ROOM_TO_SPARE = 64 * 1024 * 1024

_PHOTO_ID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
PHOTO_FILE = re.compile(rf"{_PHOTO_ID}\.webp")
PHOTO_ENTRY = re.compile(rf"photos/({'|'.join(PHOTO_FOLDERS)})/({_PHOTO_ID})\.webp")
_SQLITE_HEADER = b"SQLite format 3\x00"

DateTuple = tuple[int, int, int, int, int, int]


def zip_name(day: date) -> str:
    return f"sunroom-{day.isoformat()}.zip"


# ---- writing ---------------------------------------------------------------------------------


class Writable(Protocol):
    """What zipfile needs from the file it writes a new archive to."""

    def write(self, b: bytes, /) -> int: ...
    def flush(self) -> None: ...
    def close(self) -> None: ...


class DownloadStoppedError(Exception):
    """The download ended early (the phone went away): the worker stops writing."""


class DownloadFailedError(Exception):
    """The worker couldn't finish the zip; the response breaks off so the phone doesn't keep a
    zip that looks whole but isn't."""


def make_database_copy(db_path: Path, backup_dir: Path) -> Path:
    """A fresh, verified copy of the live database for one download. Blocking: run it in a
    thread. Copies left by a download the server never ended (it was killed) go first; file
    times are the wall clock's, so they're compared with the wall clock, not the app's."""
    work = backup_dir / WORK_DIR
    work.mkdir(parents=True, exist_ok=True)
    cutoff = time.time() - STALE_AFTER.total_seconds()
    for leftover in work.iterdir():
        try:
            if leftover.stat().st_mtime < cutoff:
                leftover.unlink()
        except FileNotFoundError:
            pass
    destination = work / f"{backup.STEM}.{uuid.uuid4().hex}.db"
    backup.take_backup(db_path, destination)
    return destination


def photo_files(root: Path) -> Iterator[tuple[str, Path]]:
    """Every stored photo file as (folder, path), in a stable order; nothing from inbox/ or
    .orphans/, and no half-written ``.partial`` file."""
    for folder in PHOTO_FOLDERS:
        try:
            names = sorted(os.listdir(root / folder))
        except FileNotFoundError:
            continue
        for name in names:
            if PHOTO_FILE.fullmatch(name):
                yield folder, root / folder / name


def _database_facts(path: Path) -> tuple[str | None, dict[str, int]]:
    """The copy's migration revision and the manifest's row counts."""
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        present = {
            str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        rows = {
            table: int(conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])  # noqa: S608 - names from MANIFEST_TABLES
            for table in MANIFEST_TABLES
            if table in present
        }
        version = (
            conn.execute("SELECT version_num FROM alembic_version").fetchone()
            if "alembic_version" in present
            else None
        )
    finally:
        conn.close()
    return (str(version[0]) if version else None), rows


def _entry(name: str, method: int, stamp: DateTuple) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=stamp)
    info.compress_type = method
    return info


def _add_file(
    archive: zipfile.ZipFile, path: Path, name: str, method: int, stamp: DateTuple
) -> None:
    with path.open("rb") as source:
        info = _entry(name, method, stamp)
        # The size up front lets zipfile pick ZIP64 for a file that needs it.
        info.file_size = os.fstat(source.fileno()).st_size
        with archive.open(info, "w") as target:
            shutil.copyfileobj(source, target, CHUNK_BYTES)


def write_archive(
    out: Writable,
    *,
    db_copy: Path,
    photos_root: Path,
    app_version: str,
    created_at: datetime,
    zone: ZoneInfo,
    on_database_written: Callable[[], None] | None = None,
) -> dict[str, Any]:
    """Write the whole zip to ``out``, which needn't be seekable. Returns the manifest."""
    local = created_at.astimezone(zone)
    stamp: DateTuple = (local.year, local.month, local.day, local.hour, local.minute, local.second)
    revision, rows = _database_facts(db_copy)
    counts: dict[str, int] = dict.fromkeys(PHOTO_FOLDERS, 0)
    with zipfile.ZipFile(out, "w") as archive:
        _add_file(archive, db_copy, DATABASE, zipfile.ZIP_DEFLATED, stamp)
        if on_database_written is not None:
            on_database_written()
        for folder, path in photo_files(photos_root):
            try:
                _add_file(archive, path, f"photos/{folder}/{path.name}", zipfile.ZIP_STORED, stamp)
            except FileNotFoundError, IsADirectoryError:
                continue  # removed while the download ran
            counts[folder] += 1
        manifest: dict[str, Any] = {
            "format": FORMAT,
            "format_version": FORMAT_VERSION,
            "app_version": app_version,
            "schema_revision": revision,
            "created_at": created_at.isoformat(),
            "photo_files": counts,
            "row_counts": rows,
        }
        archive.writestr(
            _entry(MANIFEST, zipfile.ZIP_DEFLATED, stamp), json.dumps(manifest, indent=2) + "\n"
        )
    return manifest


@dataclass(frozen=True, slots=True)
class _End:
    error: Exception | None = None


class _Pipe:
    """The worker thread's end of the stream, where zipfile writes: fixed-size chunks handed to
    the event loop, at most ``in_flight`` of them waiting, so the worker waits for the phone."""

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        queue: asyncio.Queue[bytes | _End],
        slots: threading.Semaphore,
        stop: threading.Event,
        chunk_bytes: int,
    ) -> None:
        self._loop = loop
        self._queue = queue
        self._slots = slots
        self._stop = stop
        self._chunk_bytes = chunk_bytes
        self._buffer = bytearray()
        self._stopped = False
        self.chunks_sent = 0
        self.bytes_sent = 0

    def write(self, b: bytes, /) -> int:
        if not self._stopped:  # once stopped, what zipfile still writes on its way out is dropped
            self._buffer += b
            while len(self._buffer) >= self._chunk_bytes:
                chunk = bytes(self._buffer[: self._chunk_bytes])
                del self._buffer[: self._chunk_bytes]
                self._send(chunk)
        return len(b)

    def flush(self) -> None:
        """zipfile flushes once, at the very end; ``finish`` sends the rest."""

    def close(self) -> None:
        """zipfile never closes a file object it was handed."""

    def finish(self) -> None:
        if self._buffer and not self._stopped:
            chunk = bytes(self._buffer)
            self._buffer.clear()
            self._send(chunk)

    def end(self, error: Exception | None) -> None:
        self._hand_over(_End(error))

    def _send(self, chunk: bytes) -> None:
        while not self._slots.acquire(timeout=STOP_POLL_S):
            if self._stop.is_set():
                break
        if self._stop.is_set() or not self._hand_over(chunk):
            self._stopped = True
            raise DownloadStoppedError
        self.chunks_sent += 1
        self.bytes_sent += len(chunk)

    def _hand_over(self, item: bytes | _End) -> bool:
        try:
            self._loop.call_soon_threadsafe(self._queue.put_nowait, item)
        except RuntimeError:  # the event loop is closed: the server stopped
            return False
        return True


class FullBackupStream:
    """One Download everything: a worker thread writes the zip, ``chunks()`` reads it, and
    ``close()`` ends it however the response ended."""

    def __init__(
        self,
        *,
        db_copy: Path,
        photos_root: Path,
        app_version: str,
        created_at: datetime,
        zone: ZoneInfo,
        chunk_bytes: int | None = None,
        in_flight: int | None = None,
    ) -> None:
        self.db_copy = db_copy
        self.photos_root = photos_root
        self.app_version = app_version
        self.created_at = created_at
        self.zone = zone
        self.manifest: dict[str, Any] | None = None
        self._chunk_bytes = chunk_bytes or CHUNK_BYTES
        self._slots = threading.BoundedSemaphore(in_flight or CHUNKS_IN_FLIGHT)
        self._stop = threading.Event()
        self._queue: asyncio.Queue[bytes | _End] = asyncio.Queue()
        self.pipe: _Pipe | None = None
        self.thread: threading.Thread | None = None

    async def chunks(self) -> AsyncIterator[bytes]:
        """The zip, chunk by chunk. The worker starts with the first read."""
        self.pipe = _Pipe(
            asyncio.get_running_loop(), self._queue, self._slots, self._stop, self._chunk_bytes
        )
        self.thread = threading.Thread(target=self._work, name="download-everything", daemon=True)
        self.thread.start()
        try:
            while True:
                item = await self._queue.get()
                if isinstance(item, _End):
                    if item.error is not None:
                        raise item.error
                    return
                self._slots.release()
                yield item
        finally:
            self.close()

    def close(self) -> None:
        """Stop the worker at its next chunk and remove the database copy (it may be gone
        already). Doesn't wait, so it's safe in a cancelled task; safe to call twice."""
        self._stop.set()
        self._drop_copy()

    def _drop_copy(self) -> None:
        self.db_copy.unlink(missing_ok=True)

    def _work(self) -> None:
        pipe = self.pipe
        assert pipe is not None
        started = time.monotonic()
        try:
            try:
                manifest = write_archive(
                    pipe,
                    db_copy=self.db_copy,
                    photos_root=self.photos_root,
                    app_version=self.app_version,
                    created_at=self.created_at,
                    zone=self.zone,
                    on_database_written=self._drop_copy,
                )
                pipe.finish()
            finally:
                self._drop_copy()
        except DownloadStoppedError:
            log.info("backup.download_stopped", bytes=pipe.bytes_sent)
            return
        except Exception as exc:
            log.error("backup.download_failed", reason=f"{type(exc).__name__}: {exc}")
            pipe.end(
                DownloadFailedError("The download broke off: the server couldn't read a file.")
            )
            return
        self.manifest = manifest
        log.info(
            "backup.downloaded",
            bytes=pipe.bytes_sent,
            photo_files=sum(manifest["photo_files"].values()),
            seconds=round(time.monotonic() - started, 1),
        )
        pipe.end(None)


# ---- reading it back (sunroom restore) -------------------------------------------------------


class ArchiveError(Exception):
    """This zip can't be restored. ``key`` says why and what to do, in plain words
    (``lang/en.json``), and the message is its English; ``code`` names the cause for the API
    (Settings → Backup → Restore from a File, ADR 0034)."""

    def __init__(self, key: str, *, code: str = "zip_not_ours", **params: object) -> None:
        self.key = key
        self.params = plain(params)
        super().__init__(t_en(key, **self.params))
        self.code = code


@dataclass(frozen=True, slots=True)
class Archive:
    manifest: dict[str, Any]
    database: zipfile.ZipInfo
    photos: tuple[tuple[str, str, zipfile.ZipInfo], ...]  # (folder, photo id, entry)


@dataclass(slots=True)
class PhotosBack:
    restored: int = 0  # photos put back (a library photo's thumbnail counts with it)
    kept: int = 0  # photos already in place, left exactly as they were
    unreadable: int = 0  # photos damaged in the zip, skipped


def backup_kind(path: Path) -> str | None:
    """What a backup file is: "db" (an SQLite file), "zip", or None (anything else)."""
    with path.open("rb") as handle:
        head = handle.read(len(_SQLITE_HEADER))
    if head == _SQLITE_HEADER:
        return "db"
    return "zip" if zipfile.is_zipfile(path) else None


def _printable(name: str) -> str:
    shown = "".join(char if char.isprintable() else "?" for char in name)
    return shown if len(shown) <= 80 else shown[:77] + "..."


def read_archive(archive: zipfile.ZipFile) -> Archive:
    """Check every name and the manifest before anything is written. Raises ArchiveError."""
    entries: dict[str, zipfile.ZipInfo] = {}
    photos: list[tuple[str, str, zipfile.ZipInfo]] = []
    for info in archive.infolist():
        name = info.filename
        photo = PHOTO_ENTRY.fullmatch(name)
        if name not in (DATABASE, MANIFEST) and photo is None:
            raise ArchiveError("api.restore.zip_stranger", name=_printable(name))
        if name in entries:
            raise ArchiveError("api.restore.zip_twice", name=_printable(name))
        if info.flag_bits & 0x1:
            raise ArchiveError("api.restore.zip_password")
        entries[name] = info
        if photo is not None:
            photos.append((photo.group(1), photo.group(2), info))
    manifest_info = entries.get(MANIFEST)
    if manifest_info is None:
        raise ArchiveError("api.restore.zip_no_manifest")
    manifest = _read_manifest(archive, manifest_info)
    database = entries.get(DATABASE)
    if database is None:
        raise ArchiveError("api.restore.zip_no_database")
    return Archive(manifest=manifest, database=database, photos=tuple(photos))


def _read_manifest(archive: zipfile.ZipFile, info: zipfile.ZipInfo) -> dict[str, Any]:
    not_ours = ArchiveError("api.restore.zip_not_ours")
    if info.file_size > MAX_MANIFEST_BYTES:
        raise not_ours
    try:
        loaded: object = json.loads(archive.read(info))
    except (zipfile.BadZipFile, zlib.error, EOFError) as exc:
        raise ArchiveError("api.restore.zip_damaged", code="backup_damaged") from exc
    except NotImplementedError as exc:  # a compression zipfile can't read
        raise ArchiveError("api.restore.zip_repacked") from exc
    except ValueError as exc:
        raise not_ours from exc
    if not isinstance(loaded, dict):
        raise not_ours
    manifest = cast(dict[str, Any], loaded)
    version = manifest.get("format_version")
    if manifest.get("format") != FORMAT or type(version) is not int or version < 1:
        raise not_ours
    if version > FORMAT_VERSION:
        made_by = manifest.get("app_version")
        if not made_by:
            raise ArchiveError("api.restore.zip_newer_unknown", code="backup_newer")
        raise ArchiveError("api.restore.zip_newer", code="backup_newer", version=made_by)
    return manifest


def photo_path(root: Path, folder: str, photo_id: str) -> Path:
    """Where a photo goes: built from the checked folder and id, never from the raw name."""
    return root / folder / f"{photo_id}.webp"


def room_needed(contents: Archive, photos_root: Path) -> int:
    """Bytes the restore writes: the database, and every photo that isn't already in place."""
    photos = sum(
        info.file_size
        for folder, photo_id, info in contents.photos
        if not photo_path(photos_root, folder, photo_id).exists()
    )
    return contents.database.file_size + photos + ROOM_TO_SPARE


def extract(archive: zipfile.ZipFile, info: zipfile.ZipInfo, destination: Path) -> None:
    """Copy one entry to ``destination``. A damaged entry (its checksum doesn't match) raises
    ArchiveError and leaves nothing behind."""
    try:
        with archive.open(info) as source, destination.open("wb") as target:
            shutil.copyfileobj(source, target, EXTRACT_CHUNK_BYTES)
            target.flush()
            os.fsync(target.fileno())
    except (zipfile.BadZipFile, zlib.error, EOFError) as exc:
        destination.unlink(missing_ok=True)
        raise ArchiveError("api.restore.zip_damaged", code="backup_damaged") from exc
    except NotImplementedError as exc:  # a compression zipfile can't read
        destination.unlink(missing_ok=True)
        raise ArchiveError("api.restore.zip_repacked") from exc
    except BaseException:
        destination.unlink(missing_ok=True)
        raise


def restore_photos(archive: zipfile.ZipFile, contents: Archive, photos_root: Path) -> PhotosBack:
    """Put the photos back. A file already in place stays exactly as it is: a photo's id is
    never reused, so it's the same picture."""
    result = PhotosBack()
    for folder, photo_id, info in contents.photos:
        picture = folder in PICTURE_FOLDERS
        target = photo_path(photos_root, folder, photo_id)
        if target.exists():
            result.kept += 1 if picture else 0
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_name(target.name + ".partial")
        try:
            extract(archive, info, partial)
        except ArchiveError:
            result.unreadable += 1 if picture else 0
            continue
        os.replace(partial, target)
        result.restored += 1 if picture else 0
    return result
