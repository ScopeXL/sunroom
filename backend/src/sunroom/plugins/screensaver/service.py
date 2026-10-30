"""The screensaver's photos and where they come from (PLAN §9, §11.3, §11.4; UX §4 "Photos room",
"Screensaver"; ADR 0009).

The pictures are core's (``photos``): phones upload into the library, and this plugin's sources
import into it, each under its own ``source_key`` ("inbox", or "source:<id>" for a photo library,
libraries.py). The **manifest** is what the wall's screensaver shows: every library photo that
isn't hidden or removed, and isn't from a photo library switched off, newest first, with the
plugin's settings.

This module is the manifest and the **inbox**, a folder on the volume
(``$DATA_DIR/photos/inbox``). Every 5 minutes, and when a parent taps Check now, each photo file
at its top that has sat still for 10 seconds (by the file system's clock: a file still being
copied waits) is re-encoded into the library, which drops its EXIF and GPS, and the original
moves to ``inbox/imported/``. A file that isn't a photo Sunroom can read, or is over 50 MB, moves
to ``inbox/unreadable/``; a full disk stops the check and leaves the files for next time. A bad
file never stops the plugin. Each file is re-encoded first and then stored in its own short
write transaction, so the rest of the app never waits on the encoding.

The source's ``last_error`` is the last check's plain line about the files it handled; a check
that found nothing keeps it, so a parent still sees it later (Check now always says afresh).

Live events: ``photos.changed`` when photos came in; ``screensaver.changed {source_id}`` when a
source changed. The 5-minute check stays quiet unless it found something or its line changed.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import time
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import and_, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from sunroom.core.errors import AppError
from sunroom.core.lang import Words, match_english
from sunroom.core.logging import get_logger
from sunroom.photos.models import Photo, PhotoKind
from sunroom.photos.store import PhotoStore
from sunroom.plugins.base import Problem
from sunroom.plugins.context import PluginContext
from sunroom.plugins.screensaver.models import PhotoSource, SourceKind
from sunroom.plugins.screensaver.schemas import (
    ManifestOut,
    ManifestPhoto,
    SaverSettings,
    ScanOut,
    SourceOut,
    SourcePatch,
)

log = get_logger(__name__)

EVENT = "screensaver.changed"
PHOTOS_EVENT = "photos.changed"
INBOX_LABEL = "Photos folder"
INBOX_KEY = "inbox"  # the source_key of the photos the inbox brought in
MANIFEST_MAX = 5000
PHOTO_SUFFIXES = frozenset({".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"})
SETTLE_S = 10  # a file nobody has touched for this long has finished copying
MAX_FILE_BYTES = 50 * 1024 * 1024
IMPORTED = "imported"  # inbox/imported/: originals that came in
UNREADABLE = "unreadable"  # inbox/unreadable/: files set aside

VISIBLE = and_(
    Photo.kind == PhotoKind.LIBRARY.value,
    Photo.hidden.is_(False),
    Photo.deleted_at.is_(None),
)

# Inboxes being checked right now: the 5-minute check and a parent's Check now never run at once.
_checking: set[Path] = set()


def source_gone() -> AppError:
    return AppError(404, "not_found", "api.photos.source_gone")


def _store(ctx: PluginContext) -> PhotoStore:
    if ctx.photos is None:
        raise AppError(503, "starting", "api.photos.starting")
    return ctx.photos


# ---- the manifest ------------------------------------------------------------------------------


def saver_settings(ctx: PluginContext) -> SaverSettings:
    """The plugin's settings as the wall uses them: minutes and seconds as numbers, Never as
    None."""
    values = ctx.settings()
    start = str(values.get("start_after") or "15")
    show_clock, shuffle = values.get("show_clock"), values.get("shuffle")
    return SaverSettings(
        start_after_minutes=None if start == "never" else int(start),
        every_seconds=int(values.get("every") or "30"),
        show_clock=show_clock if isinstance(show_clock, bool) else True,
        shuffle=shuffle if isinstance(shuffle, bool) else True,
    )


async def manifest(ctx: PluginContext) -> ManifestOut:
    """Every library photo the screensaver may show, newest first (ids are time-ordered), with
    the addresses ``/photos/…`` serves them at (as the core photos API builds them). A photo
    library switched off (Show on the screensaver) keeps its photos and shows none of them."""
    async with ctx.read() as session:
        off = [
            f"source:{source_id}"
            for source_id in await session.scalars(
                select(PhotoSource.id).where(
                    PhotoSource.kind != SourceKind.INBOX.value,
                    PhotoSource.enabled.is_(False),
                    PhotoSource.deleted_at.is_(None),
                )
            )
        ]
        shown = and_(VISIBLE, Photo.source_key.not_in(off)) if off else VISIBLE
        rows = await session.execute(
            select(Photo.id, Photo.width, Photo.height, Photo.taken_at)
            .where(shown)
            .order_by(Photo.id.desc())
            .limit(MANIFEST_MAX)
        )
        photos = [
            ManifestPhoto(
                id=photo_id,
                url=f"/photos/library/{photo_id}.webp",
                thumb_url=f"/photos/thumbs/{photo_id}.webp",
                width=width,
                height=height,
                taken_at=taken_at,
            )
            for photo_id, width, height, taken_at in rows
        ]
    return ManifestOut(photos=photos, settings=saver_settings(ctx))


# ---- sources -----------------------------------------------------------------------------------


async def problems(ctx: PluginContext) -> list[Problem]:
    """The inbox on and failing (Needs Attention, ADR 0034): its last check's own line, with the
    page where it's checked again. A photo library's are libraries.py's."""
    async with ctx.read() as session:
        failing = (
            await session.scalars(
                select(PhotoSource)
                .where(
                    PhotoSource.kind == SourceKind.INBOX.value,
                    PhotoSource.deleted_at.is_(None),
                    PhotoSource.enabled.is_(True),
                    PhotoSource.last_error.is_not(None),
                )
                .order_by(PhotoSource.created_at)
            )
        ).all()
    return [_inbox_problem(source, source.last_error) for source in failing if source.last_error]


def _inbox_problem(source: PhotoSource, line: str) -> Problem:
    said = inbox_line(line)
    return Problem(
        id=f"photos:{source.id}",
        key=said.key,
        params=said.params,
        since=source.last_scan_at,
        page="screensaver",
    )


# Every line an inbox check keeps (_Tally.problem), by key: the source keeps the English.
INBOX_LINES = (
    "api.photos.storage_full",
    "api.photos.inbox.stuck_one",
    "api.photos.inbox.stuck",
    "api.photos.inbox.unreadable_one",
    "api.photos.inbox.unreadable",
)


def inbox_line(line: str) -> Words:
    """The inbox's kept line, named by its key again for the page (ADR 0043). A line no key
    matches (another version's words) is shown as it was kept."""
    return match_english(line, INBOX_LINES) or Words("api.photos.inbox.line", {"line": line})


def source_key(source: PhotoSource) -> str:
    """The ``source_key`` its photos carry in core's ``photos``."""
    return INBOX_KEY if source.kind == SourceKind.INBOX else f"source:{source.id}"


def _source_out(source: PhotoSource, counts: dict[str, int]) -> SourceOut:
    return SourceOut.model_validate(
        {
            "id": source.id,
            "kind": source.kind,
            "label": source.label,
            "enabled": source.enabled,
            "last_scan_at": source.last_scan_at,
            "last_error": source.last_error,
            "items_seen": source.items_seen,
            "photo_count": counts.get(source_key(source), 0),
        }
    )


async def photo_counts(session: AsyncSession) -> dict[str, int]:
    """How many photos the screensaver shows, by source_key."""
    rows = await session.execute(
        select(Photo.source_key, func.count()).where(VISIBLE).group_by(Photo.source_key)
    )
    return {key: count for key, count in rows}


async def _inbox(session: AsyncSession) -> PhotoSource | None:
    return await session.scalar(
        select(PhotoSource)
        .where(PhotoSource.kind == SourceKind.INBOX.value)
        .order_by(PhotoSource.created_at, PhotoSource.id)
        .limit(1)
    )


async def _live_source(session: AsyncSession, source_id: str) -> PhotoSource:
    source = await session.get(PhotoSource, source_id)
    if source is None or source.deleted_at is not None:
        raise source_gone()
    return source


async def ensure_inbox(ctx: PluginContext) -> None:
    """The inbox's row: made the first time the plugin starts (and again if the table was
    emptied, as a test server's reset does)."""
    async with ctx.read() as session:
        if await _inbox(session) is not None:
            return
    async with ctx.write() as tx:
        if await _inbox(tx.session) is None:
            tx.session.add(
                PhotoSource(kind=SourceKind.INBOX.value, label=INBOX_LABEL, created_at=ctx.now())
            )


async def sources(ctx: PluginContext) -> list[SourceOut]:
    """The inbox (the photo libraries have their own list, libraries.py)."""
    await ensure_inbox(ctx)
    async with ctx.read() as session:
        rows = list(
            await session.scalars(
                select(PhotoSource)
                .where(PhotoSource.deleted_at.is_(None), PhotoSource.kind == SourceKind.INBOX.value)
                .order_by(PhotoSource.created_at, PhotoSource.id)
            )
        )
        counts = await photo_counts(session)
    return [_source_out(row, counts) for row in rows]


async def update_source(ctx: PluginContext, source_id: str, body: SourcePatch) -> SourceOut:
    async with ctx.write() as tx:
        source = await _live_source(tx.session, source_id)
        before = (source.label, source.enabled)
        if body.label is not None:
            source.label = body.label
        if body.enabled is not None:
            source.enabled = body.enabled
        if (source.label, source.enabled) != before:
            tx.publish(EVENT, {"source_id": source.id})
        return _source_out(source, await photo_counts(tx.session))


# ---- checking the inbox ------------------------------------------------------------------------


@dataclass(slots=True)
class _Tally:
    """What one check of the inbox did."""

    seen: int = 0  # files it looked at
    imported: int = 0  # photos new to the library
    unreadable: int = 0  # files moved to unreadable/
    stuck: int = 0  # files that couldn't be moved out of the inbox
    full: Words | None = None  # the store's "Photos need room" line, when that stopped it

    def problem(self) -> Words | None:
        """The plain line a parent sees under the source, or None when all went well. One
        sentence for one file and one for more: the server says no plurals (ADR 0043)."""
        if self.full:
            return self.full
        if self.stuck == 1:
            return Words("api.photos.inbox.stuck_one")
        if self.stuck:
            return Words("api.photos.inbox.stuck", {"count": self.stuck})
        if self.unreadable == 1:
            return Words("api.photos.inbox.unreadable_one")
        if self.unreadable:
            return Words("api.photos.inbox.unreadable", {"count": self.unreadable})
        return None


def _ready_files(inbox: Path, now_s: float) -> list[tuple[Path, int]]:
    """The photo files at the top of the inbox that have sat still for SETTLE_S, by name, with
    their sizes. Dotfiles, ``*.partial`` files, folders, links and other files stay put."""
    if not inbox.is_dir():
        return []
    ready: list[tuple[Path, int]] = []
    with os.scandir(inbox) as entries:
        for entry in entries:
            name = entry.name
            if name.startswith(".") or name.endswith(".partial"):
                continue
            if Path(name).suffix.lower() not in PHOTO_SUFFIXES:
                continue
            try:
                if not entry.is_file(follow_symlinks=False):
                    continue
                info = entry.stat(follow_symlinks=False)
            except OSError:
                continue
            if now_s - info.st_mtime >= SETTLE_S:
                ready.append((Path(entry.path), info.st_size))
    return sorted(ready)


def _read(path: Path) -> tuple[bytes, str]:
    data = path.read_bytes()
    return data, hashlib.sha256(data).hexdigest()


def _move_into(path: Path, folder: str) -> bool:
    """Move an inbox file into one of the inbox's folders, as "name (2).jpg" and so on when its
    name is taken there. False when it couldn't leave the inbox."""
    target_dir = path.parent / folder
    try:
        target_dir.mkdir(exist_ok=True)
        target = target_dir / path.name
        number = 2
        while target.exists():
            target = target_dir / f"{path.stem} ({number}){path.suffix}"
            number += 1
        path.rename(target)
    except OSError:
        return not path.exists()  # gone already counts as moved
    return True


async def _set_aside(path: Path, tally: _Tally) -> None:
    if await asyncio.to_thread(_move_into, path, UNREADABLE):
        tally.unreadable += 1
    else:
        tally.stuck += 1


async def _import_files(ctx: PluginContext, store: PhotoStore) -> _Tally:
    tally = _Tally()
    ready = await asyncio.to_thread(_ready_files, store.inbox, time.time())
    tally.seen = len(ready)
    for path, size in ready:
        if size > MAX_FILE_BYTES:
            await _set_aside(path, tally)
            continue
        try:
            data, digest = await asyncio.to_thread(_read, path)
        except FileNotFoundError:
            continue  # taken away since the folder was listed
        except OSError:
            await _set_aside(path, tally)
            continue
        fresh = False
        try:
            # The slow part, before the write lock: everything else in the app waits on it.
            encoded = await store.encode(data, kind=PhotoKind.LIBRARY, zone=ctx.zone())
            async with ctx.write() as tx:
                known = await tx.session.scalar(
                    select(Photo).where(
                        Photo.kind == PhotoKind.LIBRARY.value, Photo.sha256 == digest
                    )
                )
                # A photo already shown isn't new; one that was removed comes back.
                fresh = known is None or known.deleted_at is not None
                await store.ingest(
                    tx.session,
                    data,
                    kind=PhotoKind.LIBRARY,
                    zone=ctx.zone(),
                    now=ctx.now(),
                    source_key=INBOX_KEY,
                    original_name=path.name,
                    encoded=encoded,
                )
        except AppError as exc:
            if exc.status == 507:
                tally.full = Words(exc.key, exc.params)
                break
            await _set_aside(path, tally)
            continue
        except SQLAlchemyError, OSError:
            raise  # the database or the disk, not this file: the plugin says it stopped
        except Exception as exc:  # a file the image library chokes on is just a bad file
            log.warning("screensaver.inbox_unreadable", error=type(exc).__name__)
            await _set_aside(path, tally)
            continue
        if fresh:
            tally.imported += 1
        if not await asyncio.to_thread(_move_into, path, IMPORTED):
            tally.stuck += 1
    return tally


async def _record(ctx: PluginContext, source_id: str, tally: _Tally, *, asked: bool) -> None:
    async with ctx.write() as tx:
        source = await tx.session.get(PhotoSource, source_id)
        if source is None:
            return
        before = (source.items_seen, source.last_error)
        source.last_scan_at = ctx.now()
        source.items_seen += tally.imported
        if asked or tally.seen:
            said = tally.problem()
            source.last_error = said.english if said else None
        if tally.imported:
            tx.publish(PHOTOS_EVENT, {"source_id": source.id, "count": tally.imported})
        if asked or (source.items_seen, source.last_error) != before:
            tx.publish(EVENT, {"source_id": source.id})
    if tally.seen:
        log.info(
            "screensaver.inbox_checked",
            imported=tally.imported,
            unreadable=tally.unreadable,
            stuck=tally.stuck,
            full=tally.full is not None,
        )


async def _check_inbox(
    ctx: PluginContext, store: PhotoStore, source_id: str, *, asked: bool
) -> _Tally | None:
    """One check of the inbox; None when a check is already running."""
    inbox = store.inbox
    if inbox in _checking:
        return None
    _checking.add(inbox)
    try:
        tally = await _import_files(ctx, store)
        await _record(ctx, source_id, tally, asked=asked)
    finally:
        _checking.discard(inbox)
    return tally


async def scan_inbox(ctx: PluginContext) -> None:
    """The 5-minute check (``screensaver:inbox-scan``). Nothing while the inbox is off."""
    store = ctx.photos
    if store is None:
        return
    await ensure_inbox(ctx)
    async with ctx.read() as session:
        source = await _inbox(session)
        if source is None or source.deleted_at is not None or not source.enabled:
            return
        source_id = source.id
    await _check_inbox(ctx, store, source_id, asked=False)


async def scan_source(ctx: PluginContext, source_id: str) -> ScanOut:
    """Check now, from Settings → Screensaver."""
    store = _store(ctx)
    async with ctx.read() as session:
        source = await _live_source(session, source_id)
        kind, enabled = source.kind, source.enabled
    if kind != SourceKind.INBOX:
        # A photo library has its own Check Now (libraries.py, POST libraries/{id}/scan).
        raise AppError(409, "cant_check", "api.photos.cant_check")
    if not enabled:
        raise AppError(409, "source_off", "api.photos.turn_on_first")
    tally = await _check_inbox(ctx, store, source_id, asked=True)
    if tally is None:
        raise AppError(409, "already_checking", "api.photos.checking_folder")
    async with ctx.read() as session:
        source = await _live_source(session, source_id)
        out = _source_out(source, await photo_counts(session))
    return ScanOut(source=out, imported=tally.imported, unreadable=tally.unreadable)


# ---- thumbnails --------------------------------------------------------------------------------


def _missing_thumbs(store: PhotoStore, photos: list[Photo]) -> list[Photo]:
    return [photo for photo in photos if store.thumb_missing(photo)]


async def thumb_backlog(ctx: PluginContext) -> None:
    """Every 10 minutes (``screensaver:thumb-backlog``): thumbnails a crash mid-import left
    missing are made again from the stored picture. A failure is only logged."""
    store = ctx.photos
    if store is None:
        return
    async with ctx.read() as session:
        photos = list(
            await session.scalars(
                select(Photo).where(
                    Photo.kind == PhotoKind.LIBRARY.value, Photo.deleted_at.is_(None)
                )
            )
        )
    rebuilt = 0
    for photo in await asyncio.to_thread(_missing_thumbs, store, photos):
        try:
            if await asyncio.to_thread(store.rebuild_thumb, photo):
                rebuilt += 1
        except Exception as exc:  # one bad picture mustn't stop the rest
            log.warning("screensaver.thumb_failed", photo_id=photo.id, error=type(exc).__name__)
    if rebuilt:
        log.info("screensaver.thumbs_rebuilt", count=rebuilt)
        ctx.publish(PHOTOS_EVENT, {"thumbs": rebuilt})
