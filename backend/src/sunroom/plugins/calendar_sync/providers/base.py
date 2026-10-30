"""The provider contract (PLAN §8.1): one protocol, one implementation per kind of account.

A provider lists an account's calendars, reports what changed in one of them since a cursor,
and pushes a local change or a removal. It speaks to servers only through the plugin's guarded
HTTP client (``PluginHttp``; ADR 0024), and turns every failure into a ``SyncError`` whose
``kind`` the engine acts on and whose message a parent can read.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

from sunroom.calendar.synced import PendingSeries, SyncedSeries
from sunroom.core.lang import Words, plain, t_en


class ErrorKind(StrEnum):
    AUTH = "auth"  # the password or key was refused, or revoked: needs_reconnect
    RATE_LIMITED = "rate_limited"  # back off (honouring retry_after)
    UNREACHABLE = "unreachable"  # network, DNS, timeouts, 5xx: back off
    CONFLICT = "conflict"  # 412 on a push: pull, merge, retry once
    NOT_FOUND = "not_found"  # the calendar or item is gone on the server
    BAD_DATA = "bad_data"  # the server sent something we can't read
    REFUSED = "refused"  # the server refused a push (read-only, forbidden, too big)


class SyncError(Exception):
    """A provider's failure: ``key`` names its sentence in ``lang/en.json`` (ADR 0043) and
    ``message`` is its English, plain, with no secrets and no URLs beyond the host."""

    def __init__(
        self,
        kind: ErrorKind,
        key: str,
        *,
        retry_after: float | None = None,
        params: Mapping[str, object] | None = None,
    ) -> None:
        self.kind = kind
        self.key = key
        self.params = plain(params)
        self.message = t_en(key, **self.params)
        super().__init__(self.message)
        self.retry_after = retry_after

    @property
    def words(self) -> Words:
        return Words(self.key, self.params)


@dataclass(frozen=True, slots=True)
class RemoteCalendar:
    remote_id: str  # CalDAV: the calendar's href; Google: its id; a feed: its address's hash
    name: str
    color_hint: str | None = None  # "#RRGGBB" as the server has it, if it says
    read_only: bool = False


@dataclass(frozen=True, slots=True)
class Changes:
    """What changed in one calendar since ``cursor``.

    ``complete`` means ``series`` is the whole calendar (a feed, a full resync): any synced
    series of that calendar not among them is gone. Otherwise ``removed`` lists the remote ids
    (hrefs, Google event ids) that went away. ``cursor`` is what to pass next time (a sync token,
    a ctag, a feed's ETag); None keeps the stored one.
    """

    series: list[SyncedSeries] = field(default_factory=list[SyncedSeries])
    removed: list[str] = field(default_factory=list[str])
    complete: bool = False
    cursor: str | None = None


@dataclass(frozen=True, slots=True)
class Pushed:
    """Where a pushed series now lives on the server."""

    uid: str
    remote_id: str
    etag: str | None  # None when the server didn't say (the next pull fills it in)
    raw_ical: str | None = None  # CalDAV: the VCALENDAR as sent


class CalendarProvider(Protocol):
    async def calendars(self) -> list[RemoteCalendar]:
        """The account's calendars that hold events."""
        ...

    async def changes(
        self, calendar: RemoteCalendar, cursor: str | None, known: Mapping[str, str | None]
    ) -> Changes:
        """What changed since ``cursor`` (None: everything). ``known`` maps the remote ids
        stored for this calendar to their etags, for servers that can only be diffed."""
        ...

    async def push(self, calendar: RemoteCalendar, pending: PendingSeries) -> Pushed:
        """Create or replace the series on the server (If-Match its etag when it has one).
        A 412 raises SyncError(CONFLICT)."""
        ...

    async def delete(self, calendar: RemoteCalendar, pending: PendingSeries) -> None:
        """Remove it from the server; already gone counts as done."""
        ...


def by_remote_id(series: Sequence[SyncedSeries]) -> dict[str, SyncedSeries]:
    return {item.remote_id: item for item in series if item.remote_id is not None}
