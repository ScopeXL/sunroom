"""Restoring a backup (docs/RESTORE.md; ADR 0034): the checks and the moves ``sunroom restore``
makes while the server is stopped, and the stage Settings → Backup → Restore from a File fills
while it runs.

From the app nothing is swapped while Sunroom runs: the engines, every plugin's context and the
live stream belong to the database they opened, and the copy may need migrating (ADR 0027's
reasons, which still hold). Instead the upload is checked and kept in ``/data/restore/``;
Restore arms it with a marker and Sunroom runs itself again; boot applies the armed copy right
after taking the lock, before the pre-migration copy and the migrations, exactly as a stopped
server's restore would, and the marker is consumed either way, so a bad copy never loops.

The stage, in ``/data/restore/``: ``upload.partial`` while a file arrives; ``staged.db`` (the
checked database), ``staged.zip`` (a zip, for its photos) and ``staged.json`` (what it holds);
``apply.json`` (the marker); ``last.json`` (how the last restore went).
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
import zipfile
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from sunroom.core.clock import Clock
from sunroom.core.config import Settings
from sunroom.core.lang import plain, t_en
from sunroom.core.logging import get_logger
from sunroom.db import backup, full_backup, migrate

log = get_logger(__name__)

RESTORE_DIR = "restore"
UPLOAD = "upload.partial"
STAGED_DB = "staged.db"
STAGED_ZIP = "staged.zip"
SUMMARY = "staged.json"
MARKER = "apply.json"
LAST = "last.json"
ROOM_TO_SPARE = full_backup.ROOM_TO_SPARE
_STAGE_FILES = (UPLOAD, f"{STAGED_DB}.partial", STAGED_DB, STAGED_ZIP, SUMMARY, MARKER)


class RestoreError(Exception):
    """This backup can't be restored. ``key`` says why and what to do, in plain words
    (``lang/en.json``, ``api.restore.*``), and ``message`` is its English, which the command line
    prints; ``code`` names the cause for the API."""

    def __init__(self, code: str, key: str, **params: object) -> None:
        self.code = code
        self.key = key
        self.params = plain(params)
        self.message = t_en(key, **self.params)
        super().__init__(self.message)


@dataclass(frozen=True, slots=True)
class Summary:
    """What a staged backup holds, as Restore from a File? shows it."""

    file_name: str
    kind: str  # "db" or "zip"
    bytes: int
    app_version: str | None  # the Sunroom that made it, when it says
    schema_revision: str
    needs_upgrade: bool  # older than this Sunroom: migrated after the restore
    created_at: str | None  # when the zip was made (its manifest); a .db doesn't say
    row_counts: dict[str, int] = field(default_factory=dict[str, int])
    photo_files: int = 0  # the photos in a zip (thumbnails not counted); none in a .db


@dataclass(frozen=True, slots=True)
class Outcome:
    """How the last restore from the app went (``last.json``)."""

    ok: bool
    at: str
    file_name: str | None = None
    problem: str | None = None
    previous: str | None = None  # the database from before it, kept as a copy
    photos: str | None = None  # how many photos came back, in words


@dataclass(frozen=True, slots=True)
class Prepared:
    kind: str
    info: dict[str, object]
    manifest: dict[str, Any]
    photo_files: int = 0  # the photos in a zip (a library photo's thumbnail counts with it)


# ---- the checks and moves (both the CLI and boot) -------------------------------------------


def without_journal(db: Path) -> None:
    for suffix in ("-wal", "-shm", "-journal"):
        Path(f"{db}{suffix}").unlink(missing_ok=True)


def backup_kind_or_refuse(source: Path) -> str:
    """ "db" or "zip", or RestoreError."""
    try:
        kind = full_backup.backup_kind(source)
    except PermissionError as exc:
        raise RestoreError("unreadable", "api.restore.unreadable", name=source.name) from exc
    if kind is None:
        raise RestoreError("not_a_backup", "api.restore.not_a_backup")
    return kind


def _copy_database(source: Path, partial: Path) -> None:
    """A ``.db`` file, with what its ``-wal`` still holds: SQLite folds it in on opening."""
    shutil.copyfile(source, partial)
    wal = Path(f"{source}-wal")
    if wal.is_file():
        shutil.copyfile(wal, Path(f"{partial}-wal"))


def _room(data_dir: Path, needed: int) -> None:
    if shutil.disk_usage(data_dir).free < needed:
        raise RestoreError("no_room", "api.restore.no_room", size=f"{needed / 1024**3:.1f}")


def check_database(partial: Path) -> dict[str, object]:
    """One self-contained file that passes quick_check and was stamped by a Sunroom this image
    knows. Returns what ``backup.inspect_backup`` says about it."""
    try:
        conn = sqlite3.connect(partial)
        try:
            conn.execute("PRAGMA journal_mode=DELETE")  # folds in a -wal; one file to swap in
        finally:
            conn.close()
        info = backup.inspect_backup(partial)
    except sqlite3.DatabaseError as exc:
        raise RestoreError("backup_damaged", "api.restore.not_a_database") from exc
    finally:
        without_journal(partial)
    if info["quick_check"] != "ok":
        raise RestoreError("backup_damaged", "api.restore.damaged")
    revision = info["revision"]
    if revision is None:
        raise RestoreError("not_a_backup", "api.restore.not_ours")
    if revision not in migrate.known_revisions():
        if not info["app_version"]:
            raise RestoreError("backup_newer", "api.restore.newer_unknown")
        raise RestoreError("backup_newer", "api.restore.newer", version=info["app_version"])
    return info


def prepare(source: Path, partial: Path, photos_dir: Path, data_dir: Path) -> Prepared:
    """Check ``source`` (a .db, or the zip from Download everything) and put its database,
    checked, at ``partial``. Nothing else changes; RestoreError says why it can't be restored."""
    kind = backup_kind_or_refuse(source)
    manifest: dict[str, Any] = {}
    pictures = 0
    partial.unlink(missing_ok=True)  # left by a restore that was interrupted
    without_journal(partial)
    try:
        if kind == "zip":
            try:
                with zipfile.ZipFile(source) as archive:
                    contents = full_backup.read_archive(archive)
                    manifest = contents.manifest
                    folders = [folder for folder, _, _ in contents.photos]
                    pictures = sum(folders.count(name) for name in full_backup.PICTURE_FOLDERS)
                    _room(data_dir, full_backup.room_needed(contents, photos_dir))
                    full_backup.extract(archive, contents.database, partial)
            except zipfile.BadZipFile as exc:
                raise RestoreError("backup_damaged", "api.restore.zip_damaged") from exc
            except full_backup.ArchiveError as problem:
                raise RestoreError(problem.code, problem.key, **problem.params) from problem
        else:
            wal = Path(f"{source}-wal")
            needed = source.stat().st_size + ROOM_TO_SPARE
            _room(data_dir, needed + (wal.stat().st_size if wal.is_file() else 0))
            _copy_database(source, partial)
        info = check_database(partial)
    except BaseException:
        partial.unlink(missing_ok=True)
        without_journal(partial)
        raise
    return Prepared(kind=kind, info=info, manifest=manifest, photo_files=pictures)


def aside_stamp(db: Path, now: datetime) -> str:
    """The time for sunroom.pre-restore.<time>.db, never one already taken (two restores in the
    same second would otherwise overwrite the first one's copy)."""
    base = now.strftime(backup.STAMP_FORMAT)
    stamp, n = base, 1
    while any(
        db.with_name(f"sunroom.pre-restore.{stamp}.db{suffix}").exists()
        for suffix in ("", "-wal", "-shm")
    ):
        n += 1
        stamp = f"{base}-{n}"
    return stamp


def _epoch(db: Path) -> int:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        row = conn.execute("SELECT auth_epoch FROM app_meta").fetchone()
    except sqlite3.DatabaseError:
        return 0
    finally:
        conn.close()
    return int(row[0]) if row else 0


def fold_wal(db: Path) -> None:
    """A database moved aside with its -wal, made one file again (the copy Settings → Backup
    lists, downloads and removes)."""
    conn = sqlite3.connect(db)
    try:
        conn.execute("PRAGMA journal_mode=DELETE")
    finally:
        conn.close()
    without_journal(db)


def swap_in(db: Path, prepared: Path, stamp: str) -> list[str]:
    """Put the checked copy in place of the live database, which is moved aside with its -wal
    and -shm as sunroom.pre-restore.<stamp>.db and made one file again. Every device signs in
    again: the copy's sign-in epoch goes above both databases' (the backup's own plus one could
    be the live one, and keep its cookies). Returns the names moved aside."""
    live = _epoch(db) if db.exists() else 0
    conn = sqlite3.connect(prepared)
    try:
        row = conn.execute("SELECT auth_epoch FROM app_meta").fetchone()
        epoch = max(live, int(row[0]) if row else 0) + 1
        conn.execute("UPDATE app_meta SET auth_epoch = ?", (epoch,))
        conn.commit()
        check = conn.execute("PRAGMA quick_check").fetchone()
    finally:
        conn.close()
    if not check or check[0] != "ok":
        raise RestoreError("backup_damaged", "api.restore.swap_check_failed")
    moved: list[str] = []
    for suffix in ("", "-wal", "-shm"):  # together: a stale -wal would corrupt the new file
        current = Path(f"{db}{suffix}")
        if current.exists():
            aside = db.with_name(f"sunroom.pre-restore.{stamp}.db{suffix}")
            os.replace(current, aside)
            moved.append(aside.name)
    os.replace(prepared, db)
    if moved:
        fold_wal(db.with_name(moved[0]))
    return moved


def photos_back(zip_path: Path, photos_dir: Path) -> full_backup.PhotosBack:
    """The zip's photos, put back beside what's already there (kept exactly as it is)."""
    with zipfile.ZipFile(zip_path) as archive:
        contents = full_backup.read_archive(archive)
        return full_backup.restore_photos(archive, contents, photos_dir)


def photos_line(photos: full_backup.PhotosBack) -> str:
    """How many photos came back, in words."""

    def count(n: int) -> str:
        return f"{n} photo{'' if n == 1 else 's'}"

    if not photos.restored and not photos.kept and not photos.unreadable:
        return "There were no photos in the backup."
    line = f"{count(photos.restored)} came back."
    if photos.kept:
        verb = "was" if photos.kept == 1 else "were"
        line += f" {count(photos.kept)} {verb} already here and {verb} left as is."
    if photos.unreadable:
        line += f" {count(photos.unreadable)} couldn't be read from the zip."
    return line


# ---- the stage (Settings → Backup → Restore from a File) ----------------------------------


def stage_dir(settings: Settings) -> Path:
    return settings.data_dir / RESTORE_DIR


def _write_json(path: Path, data: dict[str, Any]) -> None:
    """Written whole or not at all, and on the disk before this returns."""
    partial = path.with_name(path.name + ".partial")
    with partial.open("w", encoding="utf-8") as handle:
        json.dump(data, handle)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(partial, path)
    if sys.platform == "win32":  # a folder can't be opened to sync there; NTFS logs the rename
        return
    folder = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(folder)
    finally:
        os.close(folder)


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        loaded: object = json.loads(path.read_text(encoding="utf-8"))
    except OSError, ValueError:
        return None
    return loaded if isinstance(loaded, dict) else None  # pyright: ignore[reportUnknownVariableType]


def _clear(folder: Path, keep: Path | None = None) -> None:
    for name in _STAGE_FILES:
        path = folder / name
        if path != keep:
            path.unlink(missing_ok=True)
    without_journal(folder / STAGED_DB)


def stage(settings: Settings, upload: Path, file_name: str) -> Summary:
    """Check an uploaded backup and keep it, ready to restore. Any earlier stage goes first. A
    file that can't be restored is removed and RestoreError says why."""
    folder = upload.parent
    _clear(folder, keep=upload)
    partial = folder / f"{STAGED_DB}.partial"
    try:
        prepared = prepare(upload, partial, settings.photos_dir, settings.data_dir)
        size = upload.stat().st_size
        if prepared.kind == "zip":
            os.replace(upload, folder / STAGED_ZIP)
        os.replace(partial, folder / STAGED_DB)
    finally:
        upload.unlink(missing_ok=True)
    info, manifest = prepared.info, prepared.manifest
    revision = str(info["revision"])
    rows = cast(dict[str, int], info["row_counts"])  # backup.inspect_backup's counts
    made, version = manifest.get("created_at"), info["app_version"] or manifest.get("app_version")
    summary = Summary(
        file_name=file_name,
        kind=prepared.kind,
        bytes=size,
        app_version=version if isinstance(version, str) else None,
        schema_revision=revision,
        needs_upgrade=revision != migrate.head_revision(),
        created_at=made if isinstance(made, str) else None,
        row_counts={t: n for t, n in rows.items() if t in full_backup.MANIFEST_TABLES},
        photo_files=prepared.photo_files,
    )
    _write_json(folder / SUMMARY, asdict(summary))
    log.info("restore.staged", kind=summary.kind, bytes=summary.bytes)
    return summary


def staged(settings: Settings) -> Summary | None:
    folder = stage_dir(settings)
    data = _read_json(folder / SUMMARY)
    if data is None or not (folder / STAGED_DB).is_file():
        return None
    try:
        return Summary(**data)
    except TypeError:
        return None


def discard(settings: Settings) -> None:
    _clear(stage_dir(settings))


def arm(settings: Settings, requested_at: datetime, device_id: str | None) -> None:
    """Mark the staged copy to be restored at the next start. LookupError when nothing is
    staged; RestoreError when it no longer passes its check."""
    folder = stage_dir(settings)
    staged_db = folder / STAGED_DB
    if not staged_db.is_file() or not (folder / SUMMARY).is_file():
        raise LookupError("nothing staged")
    conn = sqlite3.connect(f"file:{staged_db}?mode=ro", uri=True)
    try:
        check = conn.execute("PRAGMA quick_check").fetchone()
    except sqlite3.DatabaseError:
        check = None
    finally:
        conn.close()
    if not check or check[0] != "ok":
        raise RestoreError("backup_damaged", "api.restore.damaged")
    _write_json(
        folder / MARKER,
        {"step": "armed", "requested_at": requested_at.isoformat(), "device_id": device_id},
    )


def last_outcome(settings: Settings) -> Outcome | None:
    data = _read_json(stage_dir(settings) / LAST)
    if data is None:
        return None
    try:
        return Outcome(**data)
    except TypeError:
        return None


def _staged_problem(settings: Settings, folder: Path) -> str | None:
    staged_db = folder / STAGED_DB
    if not staged_db.is_file():
        return "The copy to restore wasn't there any more."
    try:
        info = backup.inspect_backup(staged_db)
    except sqlite3.DatabaseError:
        return "The copy to restore couldn't be read."
    finally:
        without_journal(staged_db)
    if info["quick_check"] != "ok":
        return "The copy to restore didn't pass its check."
    if info["revision"] not in migrate.known_revisions():
        return "The copy to restore is from a newer Sunroom."
    if shutil.disk_usage(settings.data_dir).free < staged_db.stat().st_size + ROOM_TO_SPARE:
        return "There wasn't enough free space on the data volume to restore it."
    return None


def _set_aside(folder: Path, now: datetime, file_name: str | None, problem: str) -> Outcome:
    """Keep what was staged in ``restore/failed-<time>/``, never to be tried again."""
    failed = folder / f"failed-{now.strftime(backup.STAMP_FORMAT)}"
    failed.mkdir(exist_ok=True)
    for name in _STAGE_FILES:
        if (folder / name).exists():
            os.replace(folder / name, failed / name)
    outcome = Outcome(ok=False, at=now.isoformat(), file_name=file_name, problem=problem)
    _write_json(folder / LAST, asdict(outcome))
    log.error("boot.restore_set_aside", problem=problem, kept_in=failed.name)
    return outcome


def _put_back(db: Path, aside: str) -> None:
    for suffix in ("", "-wal", "-shm"):
        moved = db.with_name(f"{aside}{suffix}")
        if moved.exists():
            os.replace(moved, Path(f"{db}{suffix}"))


def apply_armed(settings: Settings, clock: Clock) -> Outcome | None:
    """At boot, after the lock: restore the armed copy, if there is one (None when not). Never
    raises for a bad copy: it's set aside, ``last.json`` says why, and the database there boots.

    A start that finds the marker at "swapping" was stopped in the middle: with the database
    moved aside and no copy in its place, the database goes back; with the copy in place, what
    was left (the photos, the tidying) is finished; with neither moved, the swap runs again."""
    folder = stage_dir(settings)
    marker = folder / MARKER
    if not marker.is_file():
        return None
    armed = _read_json(marker) or {}
    named = (_read_json(folder / SUMMARY) or {}).get("file_name")
    file_name = named if isinstance(named, str) else None
    db = settings.db_path
    now = clock.now()
    aside = armed.get("aside")
    previous = aside if isinstance(aside, str) else None
    swapping = armed.get("step") == "swapping"
    if swapping and previous is not None and not db.exists():
        _put_back(db, previous)
        back = "The restore was interrupted, so the data from before it is back."
        return _set_aside(folder, now, file_name, back)
    if swapping and db.exists() and not (folder / STAGED_DB).exists():
        if previous is not None and Path(f"{db.with_name(previous)}-wal").exists():
            fold_wal(db.with_name(previous))
    else:
        problem = _staged_problem(settings, folder)
        if problem is not None:
            return _set_aside(folder, now, file_name, problem)
        stamp = aside_stamp(db, now)
        previous = f"sunroom.pre-restore.{stamp}.db" if db.exists() else None
        _write_json(marker, {**armed, "step": "swapping", "aside": previous})
        try:
            swap_in(db, folder / STAGED_DB, stamp)
        except (RestoreError, OSError, sqlite3.DatabaseError) as exc:
            if not db.exists() and previous is not None:
                _put_back(db, previous)
            return _set_aside(folder, now, file_name, f"The copy couldn't be put in place ({exc}).")
    photos: str | None = None
    if (folder / STAGED_ZIP).is_file():
        try:
            photos = photos_line(photos_back(folder / STAGED_ZIP, settings.photos_dir))
        except (OSError, zipfile.BadZipFile, full_backup.ArchiveError) as exc:
            photos = f"Some photos couldn't be put back ({exc})."
    _clear(folder)
    outcome = Outcome(
        ok=True, at=now.isoformat(), file_name=file_name, previous=previous, photos=photos
    )
    _write_json(folder / LAST, asdict(outcome))
    log.info("boot.restored", file=file_name, previous=previous, photos=photos)
    return outcome
