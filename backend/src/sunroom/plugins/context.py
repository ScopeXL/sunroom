"""PluginContext: the whole world a plugin sees (PLAN §6.2).

Time and zone, its own settings, read and write sessions (the write transaction's ``publish``
sends live-update events after commit), read-only facades for core data (the household, members,
photos, the calendar, which also takes overlays), the network allowlist's rows a home-network
tick writes, the SSRF-guarded HTTP client, encryption under the ``plugin-secrets-v1`` key, and job
registration. Never the engine, never app state.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Coroutine, Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import date, datetime
from typing import TYPE_CHECKING, Any, Protocol
from zoneinfo import ZoneInfo

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sunroom.core.clock import Clock
from sunroom.core.http import FetchResult, GuardedHttp
from sunroom.db.engine import WriteTx
from sunroom.household.models import Household, Member

if TYPE_CHECKING:
    from sunroom.calendar.models import Calendar
    from sunroom.calendar.occurrences import CalendarRuntime, OverlayProvider
    from sunroom.calendar.schemas import OccurrenceOut
    from sunroom.calendar.synced import MergeResult, PendingSeries, SyncedSeries
    from sunroom.photos.store import PhotoStore

Job = Callable[[], Awaitable[None]]


class PluginDecryptError(Exception):
    """A secret encrypted under another key (the secret key changed): reconnect the account."""


@dataclass(frozen=True, slots=True)
class MemberView:
    id: str
    name: str
    role: str
    color: str
    birthday: date | None


@dataclass(frozen=True, slots=True)
class HouseholdView:
    name: str
    week_starts_on: int  # 0 Monday … 6 Sunday
    kid_safe_editing: bool
    # Where the household is (Settings → Household → Location): the weather's place.
    location_label: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    # The household's language (Settings → Household → Language): a code from
    # lang/languages.json, for words that come from outside (a place's name, a holiday's).
    language: str = "en"


class Sessions(Protocol):
    def read(self) -> AbstractAsyncContextManager[AsyncSession]: ...
    def write(self) -> AbstractAsyncContextManager[WriteTx]: ...


class Runner(Protocol):
    def every(self, name: str, interval_s: float, job: Job) -> None: ...
    def spawn(self, name: str, coro: Coroutine[Any, Any, None]) -> None: ...


class HouseholdFacade:
    def __init__(self, sessions: Sessions) -> None:
        self._sessions = sessions

    async def get(self) -> HouseholdView:
        async with self._sessions.read() as session:
            home = await session.get(Household, 1)
            if home is None:
                return HouseholdView("Our home", 6, True)
            return HouseholdView(
                home.name,
                home.week_starts_on,
                home.kid_safe_editing,
                home.location_label,
                home.latitude,
                home.longitude,
                language=home.language,
            )


class NetworkFacade:
    """The network allowlist as a parent's "This server is on your home network" tick writes it
    (PLAN §12.6, ADR 0036): a plugin adds its own row for a host and takes it out again, and
    never reads the table. ``label`` names the feature ("Photos & Screensaver"), so its rows
    are its own."""

    def __init__(self, sessions: Sessions, now_of: Callable[[], datetime]) -> None:
        self._sessions = sessions
        self._now_of = now_of

    async def allow(self, target: str, label: str) -> bool:
        """The host joins the allowlist. True when a row was added (False: it was there)."""
        from sunroom.household.service import allow_network

        async with self._sessions.write() as tx:
            added = await allow_network(tx.session, target, label, self._now_of())
            if added:
                tx.publish("settings.changed", {"area": "network"})
            return added

    async def disallow(self, target: str, label: str) -> None:
        """This feature's rows for the host go; anyone else's stay."""
        from sunroom.household.service import disallow_network

        async with self._sessions.write() as tx:
            if await disallow_network(tx.session, target, label):
                tx.publish("settings.changed", {"area": "network"})


class MembersFacade:
    def __init__(self, sessions: Sessions) -> None:
        self._sessions = sessions

    async def active(self) -> list[MemberView]:
        async with self._sessions.read() as session:
            rows = await session.scalars(
                select(Member)
                .where(Member.archived_at.is_(None))
                .order_by(Member.sort, Member.created_at)
            )
            return [_member_view(member) for member in rows]

    async def get(self, member_id: str) -> MemberView | None:
        async with self._sessions.read() as session:
            member = await session.get(Member, member_id)
            return _member_view(member) if member else None


@dataclass(frozen=True, slots=True)
class CalendarView:
    id: str
    name: str
    color: str
    kind: str
    read_only: bool
    owner_member_id: str | None = None
    visible_on_display: bool = True
    deleted: bool = False


class CalendarFacade:
    """Read the calendar, add computed read-only occurrences to it (PLAN §7.6), and, for the
    calendar_sync plugin, keep synced calendars and their events (PLAN §7.5)."""

    def __init__(
        self,
        plugin_id: str,
        sessions: Sessions,
        runtime: CalendarRuntime | None,
        zone_of: Callable[[], ZoneInfo],
        now_of: Callable[[], datetime],
        enabled_of: Callable[[str], bool] | None = None,
    ) -> None:
        self._plugin_id = plugin_id
        self._sessions = sessions
        self._runtime = runtime
        self._zone_of = zone_of
        self._now_of = now_of
        self._enabled_of = enabled_of

    async def calendars(self, *, include_removed: bool = False) -> list[CalendarView]:
        from sunroom.calendar.service import list_calendars

        async with self._sessions.read() as session:
            return [
                _calendar_view(c)
                for c in await list_calendars(session, include_deleted=include_removed)
            ]

    # ---- synced calendars (calendar_sync) -----------------------------------------------------

    async def create_synced_calendar(
        self,
        *,
        name: str,
        color: str,
        owner_member_id: str | None,
        read_only: bool,
        visible_on_display: bool,
        source_label: str,
    ) -> CalendarView:
        from sunroom.calendar import sync_merge

        async with self._sessions.write() as tx:
            calendar = await sync_merge.create_calendar(
                tx,
                name=name,
                color=color,
                owner_member_id=owner_member_id,
                read_only=read_only,
                visible_on_display=visible_on_display,
                source_label=source_label,
                now=self._now_of(),
            )
            return _calendar_view(calendar)

    async def update_synced_calendar(
        self,
        calendar_id: str,
        *,
        name: str | None = None,
        color: str | None = None,
        owner_member_id: str | None = None,
        clear_owner: bool = False,
        read_only: bool | None = None,
        visible_on_display: bool | None = None,
        source_label: str | None = None,
    ) -> CalendarView:
        from sunroom.calendar import sync_merge

        async with self._sessions.write() as tx:
            calendar = await sync_merge.update_calendar(
                tx,
                calendar_id,
                now=self._now_of(),
                name=name,
                color=color,
                owner_member_id=owner_member_id,
                clear_owner=clear_owner,
                read_only=read_only,
                visible_on_display=visible_on_display,
                source_label=source_label,
            )
            return _calendar_view(calendar)

    async def remove_synced_calendar(self, calendar_id: str) -> None:
        from sunroom.calendar import sync_merge

        async with self._sessions.write() as tx:
            await sync_merge.remove_calendar(tx, calendar_id, self._now_of())

    async def restore_synced_calendar(self, calendar_id: str) -> CalendarView:
        from sunroom.calendar import sync_merge

        async with self._sessions.write() as tx:
            return _calendar_view(
                await sync_merge.restore_calendar(tx, calendar_id, self._now_of())
            )

    async def known(self, calendar_id: str) -> dict[str, str | None]:
        """Remote ids stored for a synced calendar, with their etags."""
        from sunroom.calendar import sync_merge

        async with self._sessions.read() as session:
            return await sync_merge.known(session, calendar_id)

    async def upsert_synced(
        self,
        calendar_id: str,
        series: Sequence[SyncedSeries],
        *,
        removed: Sequence[str] = (),
        complete: bool = False,
        on_progress: Callable[[int, int], Awaitable[None]] | None = None,
    ) -> MergeResult:
        """Merge what a server sent, CHUNK series per write transaction so the write lock stays
        short. ``removed``: remote ids gone from the server. ``complete``: ``series`` is the
        whole calendar, so any other synced series in it is gone."""
        from sunroom.calendar import sync_merge
        from sunroom.calendar.synced import MergeResult

        totals = MergeResult()
        for start in range(0, len(series), sync_merge.CHUNK):
            chunk = series[start : start + sync_merge.CHUNK]
            async with self._sessions.write() as tx:
                result = await sync_merge.merge_chunk(tx, calendar_id, chunk, self._now_of())
            totals = _add(totals, result)
            if on_progress is not None:
                await on_progress(min(start + len(chunk), len(series)), len(series))
        deleted = 0
        if removed:
            async with self._sessions.write() as tx:
                deleted += await sync_merge.drop_removed(tx, calendar_id, removed, self._now_of())
        if complete:
            uids = {item.uid for item in series}
            async with self._sessions.write() as tx:
                deleted += await sync_merge.drop_missing(tx, calendar_id, uids, self._now_of())
        return _add(totals, MergeResult(deleted=deleted))

    async def pending(self, calendar_ids: Sequence[str]) -> list[PendingSeries]:
        """Synced series with a person's change (or removal) waiting to be pushed."""
        from sunroom.calendar import sync_merge

        async with self._sessions.read() as session:
            return await sync_merge.pending(session, calendar_ids)

    async def mark_pushed(
        self,
        pending: PendingSeries,
        *,
        uid: str,
        remote_id: str,
        etag: str | None,
        raw_ical: str | None = None,
        overrides: dict[str, tuple[str | None, str | None]] | None = None,
    ) -> None:
        from sunroom.calendar import sync_merge

        async with self._sessions.write() as tx:
            await sync_merge.mark_pushed(
                tx,
                pending.event_id,
                pending.version,
                uid=uid,
                remote_id=remote_id,
                etag=etag,
                raw_ical=raw_ical,
                overrides=overrides,
            )

    async def mark_removed(self, pending: PendingSeries) -> None:
        from sunroom.calendar import sync_merge

        async with self._sessions.write() as tx:
            await sync_merge.mark_removed(tx, pending.event_id)

    async def occurrences(self, start: date, end: date) -> list[OccurrenceOut]:
        from sunroom.calendar.occurrences import CalendarRuntime, occurrences
        from sunroom.calendar.service import list_calendars

        async with self._sessions.read() as session:
            return await occurrences(
                session,
                self._runtime or CalendarRuntime(),
                await list_calendars(session),
                start,
                end,
                self._zone_of(),
            )

    def register_overlay(self, provider: OverlayProvider, key: str | None = None) -> None:
        """Add this plugin's occurrences when a client asks for ``overlays=<key>`` (the plugin's
        id by default). While the plugin is switched off its overlay answers nothing."""
        if self._runtime is None:
            return
        plugin_id, enabled_of = self._plugin_id, self._enabled_of

        async def gated(start: date, end: date, zone: ZoneInfo) -> Sequence[OccurrenceOut]:
            if enabled_of is not None and not enabled_of(plugin_id):
                return []
            return await provider(start, end, zone)

        self._runtime.overlays[key or plugin_id] = gated


def _member_view(member: Member) -> MemberView:
    return MemberView(member.id, member.name, member.role, member.color, member.birthday)


def _calendar_view(calendar: Calendar) -> CalendarView:
    return CalendarView(
        calendar.id,
        calendar.name,
        calendar.color,
        calendar.kind,
        calendar.read_only,
        calendar.owner_member_id,
        calendar.visible_on_display,
        calendar.deleted_at is not None,
    )


def _add(a: MergeResult, b: MergeResult) -> MergeResult:
    from sunroom.calendar.synced import MergeResult

    return MergeResult(
        created=a.created + b.created,
        updated=a.updated + b.updated,
        deleted=a.deleted + b.deleted,
        kept_local=a.kept_local + b.kept_local,
        unchanged=a.unchanged + b.unchanged,
        refused=a.refused + b.refused,
    )


class PluginHttp:
    """GuardedHttp with this plugin's ``allow_private`` choice baked in."""

    def __init__(self, http: GuardedHttp, *, allow_private: bool) -> None:
        self._http = http
        self._allow_private = allow_private

    async def get(
        self, url: str, *, headers: Mapping[str, str] | None = None, max_bytes: int | None = None
    ) -> FetchResult:
        if max_bytes is None:
            return await self._http.get(url, allow_private=self._allow_private, headers=headers)
        return await self._http.get(
            url, allow_private=self._allow_private, headers=headers, max_bytes=max_bytes
        )

    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        content: bytes | None = None,
        max_bytes: int | None = None,
        follow_redirects: bool = True,
    ) -> FetchResult:
        if max_bytes is None:
            return await self._http.request(
                method,
                url,
                allow_private=self._allow_private,
                headers=headers,
                content=content,
                follow_redirects=follow_redirects,
            )
        return await self._http.request(
            method,
            url,
            allow_private=self._allow_private,
            headers=headers,
            content=content,
            max_bytes=max_bytes,
            follow_redirects=follow_redirects,
        )


class PluginContext:
    def __init__(
        self,
        *,
        plugin_id: str,
        clock: Clock,
        zone_of: Callable[[], ZoneInfo],
        settings_of: Callable[[], dict[str, Any]],
        sessions: Sessions,
        publish: Callable[[str, dict[str, Any]], None],
        http: GuardedHttp,
        cipher: Fernet,
        runner: Runner,
        enabled_of: Callable[[str], bool],
        photos: PhotoStore | None = None,
        calendar: CalendarRuntime | None = None,
        test_mode: bool = False,
    ) -> None:
        self.plugin_id = plugin_id
        # The test server (SUNROOM_TEST_MODE): scripted stand-ins may replace real services.
        self.test_mode = test_mode
        self._clock = clock
        self._zone_of = zone_of
        self._settings_of = settings_of
        self._sessions = sessions
        self._publish = publish
        self._http = http
        self._cipher = cipher
        self._runner = runner
        self._enabled_of = enabled_of
        self.household = HouseholdFacade(sessions)
        self.members = MembersFacade(sessions)
        self.network = NetworkFacade(sessions, clock.now)
        self.photos = photos
        self.calendar = CalendarFacade(
            plugin_id, sessions, calendar, zone_of, clock.now, enabled_of
        )

    def now(self) -> datetime:
        return self._clock.now()

    def zone(self) -> ZoneInfo:
        return self._zone_of()

    def settings(self) -> dict[str, Any]:
        """This plugin's settings, coerced against its spec (secrets in the clear)."""
        return dict(self._settings_of())

    def read(self) -> AbstractAsyncContextManager[AsyncSession]:
        return self._sessions.read()

    def write(self) -> AbstractAsyncContextManager[WriteTx]:
        return self._sessions.write()

    def publish(self, event_type: str, payload: dict[str, Any] | None = None) -> None:
        """A live-update event outside a transaction (inside one, use ``tx.publish``)."""
        self._publish(event_type, payload or {})

    def http(self, *, allow_private: bool = False) -> PluginHttp:
        return PluginHttp(self._http, allow_private=allow_private)

    def encrypt(self, plaintext: str) -> str:
        return self._cipher.encrypt(plaintext.encode()).decode()

    def decrypt(self, token: str) -> str:
        try:
            return self._cipher.decrypt(token.encode()).decode()
        except InvalidToken:
            raise PluginDecryptError("stored credentials can't be read") from None

    def every(self, name: str, interval_s: float, job: Job) -> None:
        """Run ``job`` now and then every ``interval_s`` seconds, in the plugin's own task."""
        self._runner.every(name, interval_s, job)

    def spawn(self, name: str, coro: Coroutine[Any, Any, None]) -> None:
        """Background work that may run alongside the plugin's callbacks (a sync worker)."""
        self._runner.spawn(name, coro)

    def enabled(self, other_id: str) -> bool:
        return self._enabled_of(other_id)
