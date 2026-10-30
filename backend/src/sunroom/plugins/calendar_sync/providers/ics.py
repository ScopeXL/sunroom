"""A calendar address (PLAN §8.1): any .ics link, read-only. School and team feeds, Outlook's
"Publish calendar", iCloud public calendars, Google's secret address.

The feed's ETag and Last-Modified make a refresh that changed nothing cost one 304. A changed
feed is read whole, and what it no longer lists is gone (``complete``).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Mapping
from zoneinfo import ZoneInfo

from sunroom.calendar.synced import PendingSeries
from sunroom.core.netguard import OutboundError
from sunroom.plugins.calendar_sync.addresses import feed_id
from sunroom.plugins.calendar_sync.ical import parse_calendar
from sunroom.plugins.calendar_sync.providers.base import (
    Changes,
    ErrorKind,
    Pushed,
    RemoteCalendar,
    SyncError,
)
from sunroom.plugins.context import PluginHttp

ICS_MAX_BYTES = 20 * 1024 * 1024
NOT_A_CALENDAR = "api.sync.ics.not_a_calendar"
READ_ONLY = "api.sync.ics.read_only"


class IcsProvider:
    def __init__(
        self, http: PluginHttp, url: str, name: str, household: Callable[[], ZoneInfo]
    ) -> None:
        self._http = http
        self._url = url
        self._name = name
        self._household = household
        self.refused = 0  # series in the last fetch the calendar can't show

    async def calendars(self) -> list[RemoteCalendar]:
        return [RemoteCalendar(feed_id(self._url), self._name, None, read_only=True)]

    async def fetch(self, cursor: str | None = None) -> tuple[int, bytes, str | None]:
        """The feed (status, body, the cursor for next time); 304 has no body."""
        headers: dict[str, str] = {"Accept": "text/calendar, */*;q=0.5"}
        saved: dict[str, str] = json.loads(cursor) if cursor else {}
        if saved.get("etag"):
            headers["If-None-Match"] = saved["etag"]
        if saved.get("modified"):
            headers["If-Modified-Since"] = saved["modified"]
        try:
            result = await self._http.request(
                "GET", self._url, headers=headers, max_bytes=ICS_MAX_BYTES
            )
        except OutboundError as exc:
            kind = ErrorKind.REFUSED if exc.code == "private_address" else ErrorKind.UNREACHABLE
            raise SyncError(kind, exc.key, params=exc.params) from None
        status = result.status
        if status == 304:
            return status, b"", cursor
        if status in {401, 403, 404, 410}:
            # A feed's address is its key: one that stops working (Google's secret address after
            # a reset, a feed taken down) needs its new address, like a refused password.
            raise SyncError(ErrorKind.AUTH, "api.sync.ics.address_gone")
        if status in {429, 503}:
            raise SyncError(
                ErrorKind.RATE_LIMITED,
                "api.sync.ics.slow_down",
                retry_after=_retry_after(result.headers.get("retry-after")),
            )
        if not 200 <= status < 300:
            raise SyncError(ErrorKind.UNREACHABLE, "api.sync.ics.server_trouble")
        fresh = {
            key: value
            for key, value in (
                ("etag", result.headers.get("etag")),
                ("modified", result.headers.get("last-modified")),
            )
            if value
        }
        return status, result.content, json.dumps(fresh) if fresh else None

    async def changes(
        self, calendar: RemoteCalendar, cursor: str | None, known: Mapping[str, str | None]
    ) -> Changes:
        status, body, fresh = await self.fetch(cursor)
        if status == 304:
            return Changes()
        try:
            # Off the event loop: a big feed takes seconds to read on a Pi.
            parsed = await asyncio.to_thread(parse_calendar, body, self._household())
        except ValueError:
            raise SyncError(ErrorKind.BAD_DATA, NOT_A_CALENDAR) from None
        self.refused = len(parsed.refused)
        return Changes(series=parsed.series, complete=True, cursor=fresh)

    async def push(self, calendar: RemoteCalendar, pending: PendingSeries) -> Pushed:
        raise SyncError(ErrorKind.REFUSED, READ_ONLY)

    async def delete(self, calendar: RemoteCalendar, pending: PendingSeries) -> None:
        raise SyncError(ErrorKind.REFUSED, READ_ONLY)


def _retry_after(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None
