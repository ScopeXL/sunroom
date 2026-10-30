"""Photo libraries (ADR 0036; PLAN §9, §11.3, §11.4; UX §4 "Photo Libraries"): a photo server the
family connects with its address and a key, Immich first, whose photos the screensaver shows.

**Copies on the volume.** A library's photos are brought into core's photo store as the inbox's
are, under ``source_key = "source:<id>"``: the page's content-security policy shows images from
Sunroom's own address only, and the key must never reach a browser. What's brought in is the
library's preview (about 1440 px; the store re-encodes it as WebP), dated from the library's
record, at most **Keep up to** of them (500 by default), newest first.

**The picks.** People, albums and tags, by the library's ids, in ``config_json``; a photo is shown
when any pick matches, and with nothing picked every photo is. The choices themselves are cached
in ``options_json`` when the library is connected, when the sheet asks and they're over an hour
old, and on Refresh Choices.

**A pass** (``run_pass``) asks the library which photos the picks want, keeps
``photo_source_items`` in step (a photo no longer picked is removed from the store, softly, and
comes back without a fetch if it's picked again before core's 7-day prune), then brings in up to
``FETCHES_PER_PASS`` missing ones, each encoded before a short write transaction of its own.
Passes run one at a time per library, in their own task (``start_pass``), and one with work left
starts the next after a pause; the job starts one for each library that's on every 30 minutes.
A failure stays inside: a refused key leaves the library ``needs_reconnect``, a server that
doesn't answer ``error``, and its photos keep showing. A library's photos can be hidden from the
screensaver, not removed one by one (the store's dedupe would bring them back); removing the
library removes them all.

**The home network.** A parent's "This server is on your home network" tick writes the host into
the network allowlist (``ctx.network``), before the first check, and the row goes with the last
library that needed it.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, cast
from urllib.parse import urlsplit

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from sunroom.core.errors import AppError
from sunroom.core.lang import t_en
from sunroom.core.logging import get_logger
from sunroom.photos.models import Photo, PhotoKind
from sunroom.plugins.base import Problem
from sunroom.plugins.context import PluginContext, PluginDecryptError, PluginHttp
from sunroom.plugins.screensaver.models import (
    PhotoSource,
    PhotoSourceItem,
    SourceKind,
    SourceStatus,
)
from sunroom.plugins.screensaver.schemas import (
    LibraryChoiceOut,
    LibraryChoicesOut,
    LibraryIn,
    LibraryKindOut,
    LibraryOut,
    LibraryPatch,
    LibraryPicks,
    LibraryReconnectIn,
)
from sunroom.plugins.screensaver.service import EVENT, PHOTOS_EVENT, photo_counts, source_key
from sunroom.plugins.screensaver.sources.base import (
    Choice,
    Choices,
    Library,
    LibraryError,
    Picks,
    RemotePhoto,
)
from sunroom.plugins.screensaver.sources.immich import REMOTE_ID
from sunroom.plugins.screensaver.sources.registry import LIBRARIES, kinds, library_for

log = get_logger(__name__)

NETWORK_LABEL = "Photos & Screensaver"  # the allowlist rows the tick writes are named so
DEFAULT_LIMIT = 500
CHOICES_FRESH = timedelta(hours=1)
FETCHES_PER_PASS = 200
PUBLISH_EVERY = 20  # photos.changed after every so many photos brought in
FETCH_TRIES = 3  # a photo that fails this many passes in a row is left out
NEXT_PASS_S = 2.0
MAX_ROUNDS = 50  # passes one start may chain (10,000 photos)
SYNC_EVERY_S = 30 * 60
PRETEND_WAIT_TICKS = 600  # the test route waits up to 30 s for a pass already running
KEY_WIPED = "api.photos.library_key_unreadable"
UNKNOWN_KIND = "api.photos.unknown_kind"

# Libraries with a pass running (or about to): one at a time each, and what "checking" says.
_passing: set[str] = set()


def library_gone() -> AppError:
    return AppError(404, "not_found", "api.photos.library_gone")


# ---- what's kept -------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LibraryConfig:
    """``config_json``: where it is, what's picked, how many to keep, and what the last check
    said of the server."""

    url: str
    picks: Picks
    limit: int = DEFAULT_LIMIT
    version: str | None = None
    library_photos: int | None = None

    def as_json(self) -> str:
        return json.dumps(
            {
                "url": self.url,
                "picks": {
                    "people": list(self.picks.people),
                    "albums": list(self.picks.albums),
                    "tags": list(self.picks.tags),
                },
                "limit": self.limit,
                "server": {"version": self.version, "photos": self.library_photos},
            }
        )


def _ids(value: object) -> tuple[str, ...]:
    items = cast(list[object], value) if isinstance(value, list) else []
    return tuple(item for item in items if isinstance(item, str) and REMOTE_ID.match(item))


def read_config(source: PhotoSource) -> LibraryConfig:
    try:
        raw = json.loads(source.config_json or "{}")
    except ValueError:
        raw = {}
    data = cast(dict[str, Any], raw) if isinstance(raw, dict) else {}
    picked = data.get("picks")
    picks = cast(dict[str, Any], picked) if isinstance(picked, dict) else {}
    server = data.get("server")
    about = cast(dict[str, Any], server) if isinstance(server, dict) else {}
    limit = data.get("limit")
    version, photos = about.get("version"), about.get("photos")
    return LibraryConfig(
        url=str(data.get("url") or ""),
        picks=Picks(_ids(picks.get("people")), _ids(picks.get("albums")), _ids(picks.get("tags"))),
        limit=limit if isinstance(limit, int) and limit > 0 else DEFAULT_LIMIT,
        version=version if isinstance(version, str) else None,
        library_photos=photos if isinstance(photos, int) else None,
    )


def library_address(raw: str) -> str:
    """The address Sunroom keeps: its scheme, host and port, nothing after (a trailing ``/`` or
    ``/api`` is the usual extra). No scheme means http, as an Immich at home usually is."""
    text = raw.strip()
    if "://" not in text:
        text = "http://" + text
    parts = urlsplit(text)
    try:
        port = parts.port
    except ValueError:
        port = -1
    host = (parts.hostname or "").lower()
    if parts.scheme not in {"http", "https"} or not host or port == -1:
        raise AppError(
            422, "bad_address", "api.photos.library_bad_address", extra={"fields": ["url"]}
        )
    if parts.username is not None or parts.password is not None:
        raise AppError(
            422, "bad_address", "api.photos.library_no_password", extra={"fields": ["url"]}
        )
    netloc = f"[{host}]" if ":" in host else host
    return f"{parts.scheme}://{netloc}{f':{port}' if port else ''}"


def _host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


def _choices_out(raw: str, fetched_at: datetime | None) -> LibraryChoicesOut:
    try:
        data = json.loads(raw or "{}")
    except ValueError:
        data = {}
    kept = cast(dict[str, Any], data) if isinstance(data, dict) else {}

    def group(name: str) -> list[LibraryChoiceOut]:
        items = kept.get(name)
        found: list[LibraryChoiceOut] = []
        for item in cast(list[object], items) if isinstance(items, list) else []:
            try:
                found.append(LibraryChoiceOut.model_validate(item))
            except ValueError:
                continue
        return found

    unnamed = kept.get("unnamed_people")
    return LibraryChoicesOut(
        people=group("people"),
        albums=group("albums"),
        tags=group("tags"),
        unnamed_people=unnamed if isinstance(unnamed, int) else 0,
        fetched_at=fetched_at,
    )


def _choices_json(choices: Choices) -> str:
    def group(items: list[Choice]) -> list[dict[str, object]]:
        return [
            {"id": c.id, "name": c.name, "count": c.count, "has_thumb": c.has_thumb} for c in items
        ]

    return json.dumps(
        {
            "people": group(choices.people),
            "albums": group(choices.albums),
            "tags": group(choices.tags),
            "unnamed_people": choices.unnamed_people,
        }
    )


# ---- reading -----------------------------------------------------------------------------------


def library_kinds() -> list[LibraryKindOut]:
    return [
        LibraryKindOut(
            kind=kind.kind,
            name=kind.name,
            placeholder=kind.placeholder,
            address_hint=kind.address_hint,
            key_help=kind.key_help,
        )
        for kind in kinds()
    ]


def _is_library(source: PhotoSource) -> bool:
    return source.kind != SourceKind.INBOX


async def _live(session: AsyncSession, source_id: str) -> PhotoSource:
    source = await session.get(PhotoSource, source_id)
    if source is None or source.deleted_at is not None or not _is_library(source):
        raise library_gone()
    return source


async def _pending(session: AsyncSession, source_ids: list[str]) -> dict[str, int]:
    """Picked photos not brought in yet, by library."""
    if not source_ids:
        return {}
    rows = await session.execute(
        select(PhotoSourceItem.source_id, func.count())
        .where(
            PhotoSourceItem.source_id.in_(source_ids),
            PhotoSourceItem.dropped_at.is_(None),
            PhotoSourceItem.photo_id.is_(None),
        )
        .group_by(PhotoSourceItem.source_id)
    )
    return {source_id: count for source_id, count in rows}


def _library_out(
    source: PhotoSource, counts: dict[str, int], pending: dict[str, int]
) -> LibraryOut:
    config = read_config(source)
    return LibraryOut.model_validate(
        {
            "id": source.id,
            "kind": source.kind,
            "name": source.label,
            "url": config.url,
            "status": source.status,
            "enabled": source.enabled,
            "allow_private": source.allow_private,
            "picks": LibraryPicks(
                people=list(config.picks.people),
                albums=list(config.picks.albums),
                tags=list(config.picks.tags),
            ),
            "limit": config.limit,
            "photo_count": counts.get(source_key(source), 0),
            "pending": pending.get(source.id, 0),
            "checking": source.id in _passing,
            "last_scan_at": source.last_scan_at,
            "last_error": source.last_error,
            "options_at": source.options_at,
            "version": config.version,
            "library_photos": config.library_photos,
        }
    )


async def libraries(ctx: PluginContext) -> list[LibraryOut]:
    async with ctx.read() as session:
        rows = list(
            await session.scalars(
                select(PhotoSource)
                .where(
                    PhotoSource.deleted_at.is_(None),
                    PhotoSource.kind != SourceKind.INBOX.value,
                )
                .order_by(PhotoSource.created_at, PhotoSource.id)
            )
        )
        counts = await photo_counts(session)
        pending = await _pending(session, [row.id for row in rows])
    return [_library_out(row, counts, pending) for row in rows]


async def get_library(ctx: PluginContext, source_id: str) -> LibraryOut:
    async with ctx.read() as session:
        source = await _live(session, source_id)
        counts = await photo_counts(session)
        pending = await _pending(session, [source.id])
        return _library_out(source, counts, pending)


async def problems(ctx: PluginContext) -> list[Problem]:
    """A library that's on and needs its key again, or stopped answering (Needs Attention, ADR
    0034): one sentence with its name, the detail for parents, and the page that fixes it."""
    async with ctx.read() as session:
        failing = (
            await session.scalars(
                select(PhotoSource)
                .where(
                    PhotoSource.deleted_at.is_(None),
                    PhotoSource.kind != SourceKind.INBOX.value,
                    PhotoSource.enabled.is_(True),
                    PhotoSource.status.in_(
                        [SourceStatus.NEEDS_RECONNECT.value, SourceStatus.ERROR.value]
                    ),
                )
                .order_by(PhotoSource.created_at)
            )
        ).all()
    return [
        Problem(
            id=f"photos:{source.id}",
            key=(
                "api.photos.library_needs_key"
                if source.status == SourceStatus.NEEDS_RECONNECT
                else "api.photos.library_not_answering"
            ),
            params={"name": source.label},
            detail=source.last_error,
            since=source.last_scan_at,
            page="screensaver",
        )
        for source in failing
    ]


# ---- connecting and changing -------------------------------------------------------------------


def _library(kind: str, url: str, ctx: PluginContext) -> Library:
    library = library_for(kind, url, test_mode=ctx.test_mode)
    if library is None:
        raise AppError(422, "unknown_kind", UNKNOWN_KIND)
    return library


def _refused(exc: LibraryError) -> AppError:
    return AppError.said(422, exc.code, exc.words, extra={"fields": ["api_key"]})


async def _allow_home(ctx: PluginContext, url: str, *, ticked: bool) -> bool:
    """The tick lets Sunroom reach a home server: its host joins the allowlist before the check.
    True when this added the row, so a failed check takes it out again."""
    if not ticked or not _host(url):
        return False
    return await ctx.network.allow(_host(url), NETWORK_LABEL)


async def _release_home(ctx: PluginContext, host: str) -> None:
    """The host leaves the allowlist once no live library reaches it with the tick."""
    if not host:
        return
    async with ctx.read() as session:
        others = (
            await session.scalars(
                select(PhotoSource).where(
                    PhotoSource.deleted_at.is_(None),
                    PhotoSource.kind != SourceKind.INBOX.value,
                    PhotoSource.allow_private.is_(True),
                )
            )
        ).all()
    if any(_host(read_config(other).url) == host for other in others):
        return
    await ctx.network.disallow(host, NETWORK_LABEL)


async def _refresh_choices(
    ctx: PluginContext, source_id: str, library: Library, http: PluginHttp, url: str, key: str
) -> None:
    """Fetch and keep the choices; a failure is the library's line, never a refusal."""
    try:
        choices = await library.choices(http, url, key)
    except LibraryError as exc:
        async with ctx.write() as tx:
            source = await tx.session.get(PhotoSource, source_id)
            if source is not None:
                source.last_error = exc.message
                tx.publish(EVENT, {"source_id": source_id})
        return
    async with ctx.write() as tx:
        source = await tx.session.get(PhotoSource, source_id)
        if source is not None:
            source.options_json = _choices_json(choices)
            source.options_at = ctx.now()
            tx.publish(EVENT, {"source_id": source_id})


async def add_library(ctx: PluginContext, body: LibraryIn) -> LibraryOut:
    """Connect a library: checked first (nothing is kept when the check fails), then kept with
    its key encrypted, its choices fetched, and a pass started. It shows every photo until
    something is picked."""
    if body.kind not in LIBRARIES:
        raise AppError(422, "unknown_kind", UNKNOWN_KIND)
    url = library_address(body.url)
    library = _library(body.kind, url, ctx)
    http = ctx.http(allow_private=body.allow_private)
    added = await _allow_home(ctx, url, ticked=body.allow_private)
    try:
        info = await library.check(http, url, body.api_key)
    except LibraryError as exc:
        if added:
            await ctx.network.disallow(_host(url), NETWORK_LABEL)
        raise _refused(exc) from None
    config = LibraryConfig(url, Picks(), DEFAULT_LIMIT, info.version, info.photo_count)
    async with ctx.write() as tx:
        source = PhotoSource(
            kind=body.kind,
            label=body.label or library.kind.name,
            config_json=config.as_json(),
            credentials_enc=ctx.encrypt(body.api_key),
            allow_private=body.allow_private,
            enabled=True,
            status=SourceStatus.CONNECTED.value,
            created_at=ctx.now(),
        )
        tx.session.add(source)
        await tx.session.flush()
        source_id = source.id
        tx.publish(EVENT, {"source_id": source_id})
    await _refresh_choices(ctx, source_id, library, http, url, body.api_key)
    start_pass(ctx, source_id)
    log.info("screensaver.library_added", source_id=source_id, kind=body.kind)
    return await get_library(ctx, source_id)


async def update_library(ctx: PluginContext, source_id: str, body: LibraryPatch) -> LibraryOut:
    """The picks, Keep up to, Show on the screensaver and the name. A change of what's shown
    starts a pass; switched off, its photos stay and the screensaver shows none of them."""
    rerun = shown = False
    async with ctx.write() as tx:
        source = await _live(tx.session, source_id)
        config = read_config(source)
        if body.picks is not None:
            picks = Picks(
                tuple(dict.fromkeys(body.picks.people)),
                tuple(dict.fromkeys(body.picks.albums)),
                tuple(dict.fromkeys(body.picks.tags)),
            )
            rerun = rerun or picks != config.picks
            config = LibraryConfig(
                config.url, picks, config.limit, config.version, config.library_photos
            )
        if body.limit is not None and body.limit != config.limit:
            rerun = True
            config = LibraryConfig(
                config.url, config.picks, body.limit, config.version, config.library_photos
            )
        if body.enabled is not None and body.enabled != source.enabled:
            source.enabled = body.enabled
            rerun = shown = True
        if body.label is not None:
            source.label = body.label
        source.config_json = config.as_json()
        tx.publish(EVENT, {"source_id": source_id})
        if shown:
            tx.publish(PHOTOS_EVENT, {"source_id": source_id})
        enabled = source.enabled
    if rerun and enabled:
        start_pass(ctx, source_id)
    return await get_library(ctx, source_id)


async def reconnect_library(
    ctx: PluginContext, source_id: str, body: LibraryReconnectIn
) -> LibraryOut:
    """A new key (and, from Change Address, a new address), checked before it's kept."""
    async with ctx.read() as session:
        source = await _live(session, source_id)
        config, kind, ticked = read_config(source), source.kind, source.allow_private
    url = library_address(body.url) if body.url else config.url
    library = _library(kind, url, ctx)
    http = ctx.http(allow_private=ticked)
    added = await _allow_home(ctx, url, ticked=ticked)
    try:
        info = await library.check(http, url, body.api_key)
    except LibraryError as exc:
        if added:
            await ctx.network.disallow(_host(url), NETWORK_LABEL)
        raise _refused(exc) from None
    async with ctx.write() as tx:
        stored = await _live(tx.session, source_id)
        stored.credentials_enc = ctx.encrypt(body.api_key)
        stored.config_json = LibraryConfig(
            url, config.picks, config.limit, info.version, info.photo_count
        ).as_json()
        stored.status = SourceStatus.CONNECTED.value
        stored.last_error = None
        tx.publish(EVENT, {"source_id": source_id})
    if ticked and _host(url) != _host(config.url):
        await _release_home(ctx, _host(config.url))
    await _refresh_choices(ctx, source_id, library, http, url, body.api_key)
    start_pass(ctx, source_id)
    return await get_library(ctx, source_id)


async def remove_library(ctx: PluginContext, source_id: str) -> None:
    """Gone, with its key; its photos leave the screensaver and the store (softly: core's prune
    takes the files after 7 days), its mapping goes, and its host leaves the allowlist when the
    tick put it there and no other library needs it. Nothing changes in the library itself."""
    async with ctx.write() as tx:
        source = await _live(tx.session, source_id)
        host, ticked = _host(read_config(source).url), source.allow_private
        now = ctx.now()
        source.deleted_at = now
        source.credentials_enc = None
        await tx.session.execute(
            update(Photo)
            .where(Photo.source_key == source_key(source), Photo.deleted_at.is_(None))
            .values(deleted_at=now)
        )
        await tx.session.execute(
            delete(PhotoSourceItem).where(PhotoSourceItem.source_id == source_id)
        )
        tx.publish(EVENT, {"source_id": source_id})
        tx.publish(PHOTOS_EVENT, {"source_id": source_id})
    if ticked:
        await _release_home(ctx, host)
    log.info("screensaver.library_removed", source_id=source_id)


async def _reach(ctx: PluginContext, source: PhotoSource) -> tuple[Library, PluginHttp, str, str]:
    """What it takes to ask a library something: refused when its key is gone."""
    config = read_config(source)
    if source.credentials_enc is None:
        raise LibraryError("auth", KEY_WIPED)
    try:
        key = ctx.decrypt(source.credentials_enc)
    except PluginDecryptError:
        raise LibraryError("auth", KEY_WIPED) from None
    library = library_for(source.kind, config.url, test_mode=ctx.test_mode)
    if library is None:
        raise LibraryError("not_a_library", UNKNOWN_KIND)
    return library, ctx.http(allow_private=source.allow_private), config.url, key


async def library_choices(
    ctx: PluginContext, source_id: str, *, refresh: bool
) -> LibraryChoicesOut:
    """The people, albums and tags to pick from: the cache, fetched again when asked (Refresh
    Choices: a failure says so) or when it's over an hour old (a failure keeps the cache)."""
    async with ctx.read() as session:
        source = await _live(session, source_id)
        stale = source.options_at is None or ctx.now() - source.options_at > CHOICES_FRESH
        if not (refresh or stale):
            return _choices_out(source.options_json, source.options_at)
    try:
        library, http, url, key = await _reach(ctx, source)
        fresh = await library.choices(http, url, key)
    except LibraryError as exc:
        if refresh:
            raise AppError.said(422, exc.code, exc.words) from None
        return _choices_out(source.options_json, source.options_at)
    async with ctx.write() as tx:
        stored = await _live(tx.session, source_id)
        stored.options_json = _choices_json(fresh)
        stored.options_at = ctx.now()
        return _choices_out(stored.options_json, stored.options_at)


async def library_thumb(
    ctx: PluginContext, source_id: str, *, person: str | None, asset: str | None
) -> tuple[bytes, str]:
    """A person's face (or a photo's small picture), fetched through Sunroom so the key never
    reaches a browser."""
    wanted = person if person is not None else asset
    if (person is None) == (asset is None) or wanted is None or not REMOTE_ID.match(wanted):
        raise AppError(404, "not_found", "api.photos.picture_gone")
    async with ctx.read() as session:
        source = await _live(session, source_id)
    try:
        library, http, url, key = await _reach(ctx, source)
        return await library.thumb(http, url, key, person=person, asset=asset)
    except LibraryError as exc:
        if exc.code == "not_found":
            raise AppError(404, "not_found", "api.photos.picture_gone") from None
        raise AppError.said(502, exc.code, exc.words) from None


# ---- passes ------------------------------------------------------------------------------------


def checking(source_id: str) -> bool:
    return source_id in _passing


def start_pass(ctx: PluginContext, source_id: str) -> bool:
    """A pass in its own task, followed by more while photos are still to come in. False when
    one is running already."""
    if source_id in _passing:
        return False
    _passing.add(source_id)
    ctx.spawn(f"library-{source_id}", _passes(ctx, source_id))
    return True


async def _passes(ctx: PluginContext, source_id: str) -> None:
    try:
        for _round in range(MAX_ROUNDS):
            if not await _guarded(ctx, source_id):
                break
            await asyncio.sleep(NEXT_PASS_S)
    finally:
        _passing.discard(source_id)
        ctx.publish(EVENT, {"source_id": source_id})


async def sync_library(ctx: PluginContext, source_id: str) -> bool:
    """Passes, here and now, until nothing's left to bring in (the test route and the tests).
    False when one is running already."""
    if source_id in _passing:
        return False
    _passing.add(source_id)
    try:
        for _round in range(MAX_ROUNDS):
            if not await _guarded(ctx, source_id):
                break
    finally:
        _passing.discard(source_id)
    return True


async def _guarded(ctx: PluginContext, source_id: str) -> bool:
    """A pass that can't take the plugin down with it (hard rule 7: the inbox keeps going)."""
    try:
        return await run_pass(ctx, source_id)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log.warning(
            "screensaver.library_pass_failed", source_id=source_id, error=type(exc).__name__
        )
        return False


async def sync_all(ctx: PluginContext) -> None:
    """Every 30 minutes (``screensaver:library-sync``): a pass for each library that's on, each
    in its own task."""
    async with ctx.read() as session:
        ids = list(
            await session.scalars(
                select(PhotoSource.id).where(
                    PhotoSource.deleted_at.is_(None),
                    PhotoSource.kind != SourceKind.INBOX.value,
                    PhotoSource.enabled.is_(True),
                )
            )
        )
    for source_id in ids:
        start_pass(ctx, source_id)


async def _failed(ctx: PluginContext, source_id: str, exc: LibraryError) -> None:
    status = (
        SourceStatus.NEEDS_RECONNECT if exc.code in {"auth", "forbidden"} else SourceStatus.ERROR
    )
    async with ctx.write() as tx:
        source = await tx.session.get(PhotoSource, source_id)
        if source is None:
            return
        if (source.status, source.last_error) != (status.value, exc.message):
            source.status = status.value
            source.last_error = exc.message
            tx.publish(EVENT, {"source_id": source_id})
    log.warning("screensaver.library_refused", source_id=source_id, code=exc.code)


async def run_pass(ctx: PluginContext, source_id: str) -> bool:
    """One pass (see the module). True when photos are still waiting to come in."""
    store = ctx.photos
    if store is None:
        return False
    async with ctx.read() as session:
        source = await session.get(PhotoSource, source_id)
        if source is None or source.deleted_at is not None or not _is_library(source):
            return False
        if not source.enabled:
            return False
        config = read_config(source)
    try:
        library, http, url, key = await _reach(ctx, source)
        wanted = await library.find(http, url, key, config.picks, config.limit)
        await _keep_in_step(ctx, source_id, wanted)
        fetched, more, full = await _bring_in(ctx, source_id, library, http, url, key)
    except LibraryError as exc:
        await _failed(ctx, source_id, exc)
        return False
    async with ctx.write() as tx:
        stored = await tx.session.get(PhotoSource, source_id)
        if stored is None:
            return False
        stored.status = SourceStatus.CONNECTED.value
        stored.last_error = full
        stored.last_scan_at = ctx.now()
        stored.items_seen += fetched
        tx.publish(EVENT, {"source_id": source_id})
        if fetched:
            tx.publish(PHOTOS_EVENT, {"source_id": source_id, "count": fetched})
    if fetched:
        log.info("screensaver.library_brought_in", source_id=source_id, count=fetched)
    return more and full is None


async def _keep_in_step(ctx: PluginContext, source_id: str, wanted: list[RemotePhoto]) -> None:
    """The mapping follows the picks: new photos get a row; a photo no longer picked is
    dropped and its copy removed (softly); one picked again comes back, its copy restored when
    core still has it (a photo hidden from the screensaver stays hidden)."""
    now = ctx.now()
    own = f"source:{source_id}"
    async with ctx.write() as tx:
        rows = {
            row.remote_id: row
            for row in await tx.session.scalars(
                select(PhotoSourceItem).where(PhotoSourceItem.source_id == source_id)
            )
        }
        back: list[str] = []
        gone: list[str] = []
        for photo in wanted:
            row = rows.get(photo.id)
            if row is None:
                tx.session.add(
                    PhotoSourceItem(
                        source_id=source_id,
                        remote_id=photo.id,
                        taken_at=photo.taken_at,
                        seen_at=now,
                    )
                )
                continue
            row.seen_at = now
            row.taken_at = photo.taken_at or row.taken_at
            if row.dropped_at is not None and row.fetch_failures < FETCH_TRIES:
                row.dropped_at = None
                if row.photo_id:
                    back.append(row.photo_id)
        picked = {photo.id for photo in wanted}
        for remote_id, row in rows.items():
            if remote_id not in picked and row.dropped_at is None:
                row.dropped_at = now
                if row.photo_id:
                    gone.append(row.photo_id)
        if back:
            await tx.session.execute(
                update(Photo)
                .where(Photo.id.in_(back), Photo.source_key == own, Photo.deleted_at.is_not(None))
                .values(deleted_at=None)
            )
        if gone:
            await tx.session.execute(
                update(Photo)
                .where(Photo.id.in_(gone), Photo.source_key == own, Photo.deleted_at.is_(None))
                .values(deleted_at=now)
            )
        if back or gone:
            tx.publish(PHOTOS_EVENT, {"source_id": source_id})


@dataclass(frozen=True, slots=True)
class _Waiting:
    item_id: str
    remote_id: str
    taken_at: datetime | None


async def _waiting(ctx: PluginContext, source_id: str) -> list[_Waiting]:
    """Picked photos without a copy (never brought in, or core has since let it go), newest
    first."""
    async with ctx.read() as session:
        rows = (
            await session.execute(
                select(
                    PhotoSourceItem.id,
                    PhotoSourceItem.remote_id,
                    PhotoSourceItem.taken_at,
                    PhotoSourceItem.photo_id,
                )
                .where(PhotoSourceItem.source_id == source_id, PhotoSourceItem.dropped_at.is_(None))
                .order_by(PhotoSourceItem.taken_at.desc(), PhotoSourceItem.remote_id)
            )
        ).all()
        have = {
            photo_id
            for photo_id in await session.scalars(
                select(Photo.id).where(Photo.id.in_([row[3] for row in rows if row[3]]))
            )
        }
    return [
        _Waiting(item_id, remote_id, taken_at)
        for item_id, remote_id, taken_at, photo_id in rows
        if photo_id is None or photo_id not in have
    ]


async def _missed(ctx: PluginContext, item_id: str, remote_id: str) -> None:
    """A fetch that failed: tried again next pass, left out after FETCH_TRIES."""
    async with ctx.write() as tx:
        row = await tx.session.get(PhotoSourceItem, item_id)
        if row is None:
            return
        row.fetch_failures += 1
        if row.fetch_failures >= FETCH_TRIES:
            row.dropped_at = ctx.now()
            log.warning(
                "screensaver.library_photo_left_out", remote_id=remote_id, tries=FETCH_TRIES
            )


async def _bring_in(
    ctx: PluginContext, source_id: str, library: Library, http: PluginHttp, url: str, key: str
) -> tuple[int, bool, str | None]:
    """Up to FETCHES_PER_PASS missing photos into the store. Returns how many came in, whether
    more are waiting, and the store's "need room" line when the disk stopped it."""
    store = ctx.photos
    if store is None:
        return 0, False, None
    waiting = await _waiting(ctx, source_id)
    fetched = 0
    for item in waiting[:FETCHES_PER_PASS]:
        try:
            data = await library.fetch(http, url, key, item.remote_id)
        except LibraryError as exc:
            if exc.code in {"auth", "forbidden", "private_address"}:
                raise  # the whole library, not this photo
            await _missed(ctx, item.item_id, item.remote_id)
            continue
        try:
            # The slow part, before the write lock: everything else in the app waits on it.
            encoded = await store.encode(data, kind=PhotoKind.LIBRARY, zone=ctx.zone())
        except AppError as exc:
            if exc.status == 507:
                return fetched, True, exc.message
            await _missed(ctx, item.item_id, item.remote_id)
            continue
        async with ctx.write() as tx:
            row = await tx.session.get(PhotoSourceItem, item.item_id)
            if row is None or row.dropped_at is not None:
                continue  # unpicked while it was on its way
            photo = await store.ingest(
                tx.session,
                data,
                kind=PhotoKind.LIBRARY,
                zone=ctx.zone(),
                now=ctx.now(),
                source_key=f"source:{source_id}",
                original_name=f"{item.remote_id}.jpg",
                encoded=encoded,
                taken_at=item.taken_at,
            )
            row.photo_id = photo.id
            row.fetched_at = ctx.now()
            row.fetch_failures = 0
            fetched += 1
            if fetched % PUBLISH_EVERY == 0:
                tx.publish(PHOTOS_EVENT, {"source_id": source_id, "count": fetched})
    return fetched, len(waiting) > FETCHES_PER_PASS, None


# ---- the test server ---------------------------------------------------------------------------


async def pretend_library(ctx: PluginContext, *, wipe: bool) -> LibraryOut:
    """The test server's pretend Immich (sources/fake.py), connected and every photo brought in;
    or, with ``wipe``, its key gone as a new secret key leaves it (Needs Attention)."""
    from sunroom.plugins.screensaver.sources.fake import FAKE_KEY, FAKE_URL

    async with ctx.read() as session:
        found = await session.scalar(
            select(PhotoSource.id)
            .where(
                PhotoSource.deleted_at.is_(None),
                PhotoSource.kind == "immich",
                PhotoSource.config_json.contains(FAKE_URL),
            )
            .limit(1)
        )
    if found is None:
        added = await add_library(
            ctx, LibraryIn(kind="immich", url=FAKE_URL, api_key=FAKE_KEY, allow_private=False)
        )
        found = added.id
    for _tick in range(PRETEND_WAIT_TICKS):  # the pass add_library started: wait it out
        if not checking(found):
            break
        await asyncio.sleep(0.05)
    await sync_library(ctx, found)
    if wipe:
        async with ctx.write() as tx:
            source = await _live(tx.session, found)
            source.credentials_enc = None
            source.status = SourceStatus.NEEDS_RECONNECT.value
            source.last_error = t_en(KEY_WIPED)
            tx.publish(EVENT, {"source_id": found})
    return await get_library(ctx, found)
