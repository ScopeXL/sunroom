"""A scripted calendar server (PLAN §8.3) for the engine's tests and the test server's end-to-end
runs: calendars, series with etags, a change log behind sync tokens, and failures on demand.

Never reachable on a real server: the plugin offers the "fake" provider only in test mode.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace

from sunroom.calendar.synced import PendingSeries, SyncedSeries
from sunroom.plugins.calendar_sync.providers.base import (
    Changes,
    ErrorKind,
    Pushed,
    RemoteCalendar,
    SyncError,
)

# The test server's own sentences (test mode only), by their keys in lang/en.json.
_MESSAGES = {
    ErrorKind.AUTH: "api.testing.sync.auth",
    ErrorKind.RATE_LIMITED: "api.testing.sync.slow_down",
    ErrorKind.UNREACHABLE: "api.testing.sync.no_answer",
    ErrorKind.CONFLICT: "api.testing.sync.changed",
    ErrorKind.NOT_FOUND: "api.testing.sync.calendar_gone",
    ErrorKind.BAD_DATA: "api.testing.sync.unreadable",
    ErrorKind.REFUSED: "api.testing.sync.refused",
}


@dataclass
class FakeRemote:
    """The server's side: what it holds, and what it will do next."""

    calendars: dict[str, RemoteCalendar] = field(default_factory=dict[str, RemoteCalendar])
    # calendar id -> remote id -> series
    items: dict[str, dict[str, SyncedSeries]] = field(
        default_factory=dict[str, dict[str, SyncedSeries]]
    )
    # calendar id -> [(token, remote id, removed)]
    log: dict[str, list[tuple[int, str, bool]]] = field(
        default_factory=dict[str, list[tuple[int, str, bool]]]
    )
    failures: list[tuple[str, ErrorKind]] = field(default_factory=list[tuple[str, ErrorKind]])
    counter: int = 0
    pushes: list[str] = field(default_factory=list[str])  # remote ids pushed, in order
    deletes: list[str] = field(default_factory=list[str])

    # ---- scripting --------------------------------------------------------------------------

    def add_calendar(self, remote_id: str, name: str, *, read_only: bool = False) -> None:
        self.calendars[remote_id] = RemoteCalendar(remote_id, name, None, read_only)
        self.items.setdefault(remote_id, {})
        self.log.setdefault(remote_id, [])

    def put(self, calendar_id: str, series: SyncedSeries) -> SyncedSeries:
        """Store a series as the server would (a new etag), and log the change."""
        self.counter += 1
        remote_id = series.remote_id or f"{calendar_id}/{series.uid}.ics"
        stored = replace(series, remote_id=remote_id, etag=f'"{self.counter}"')
        self.items[calendar_id][remote_id] = stored
        self.log[calendar_id].append((self.counter, remote_id, False))
        return stored

    def remove(self, calendar_id: str, remote_id: str) -> None:
        self.counter += 1
        self.items[calendar_id].pop(remote_id, None)
        self.log[calendar_id].append((self.counter, remote_id, True))

    def fail_next(self, kind: ErrorKind, operation: str = "any") -> None:
        """Make the next ``operation`` ("calendars", "changes", "push", "delete" or "any")
        fail with ``kind``."""
        self.failures.append((operation, kind))

    def maybe_fail(self, operation: str) -> None:
        for index, (wanted, kind) in enumerate(self.failures):
            if wanted in {operation, "any"}:
                del self.failures[index]
                retry = 1.0 if kind == ErrorKind.RATE_LIMITED else None
                raise SyncError(kind, _MESSAGES[kind], retry_after=retry)


class FakeProvider:
    def __init__(self, remote: FakeRemote) -> None:
        self.remote = remote

    async def calendars(self) -> list[RemoteCalendar]:
        self.remote.maybe_fail("calendars")
        return list(self.remote.calendars.values())

    async def changes(
        self, calendar: RemoteCalendar, cursor: str | None, known: Mapping[str, str | None]
    ) -> Changes:
        remote = self.remote
        remote.maybe_fail("changes")
        if calendar.remote_id not in remote.calendars:
            raise SyncError(ErrorKind.NOT_FOUND, _MESSAGES[ErrorKind.NOT_FOUND])
        items = remote.items[calendar.remote_id]
        token = str(remote.counter)
        if cursor is None:
            return Changes(series=list(items.values()), complete=True, cursor=token)
        since = int(cursor)
        changed: dict[str, bool] = {}
        for at, remote_id, removed in remote.log[calendar.remote_id]:
            if at > since:
                changed[remote_id] = removed
        series = [items[rid] for rid, removed in changed.items() if not removed and rid in items]
        gone = [rid for rid, removed in changed.items() if removed]
        return Changes(series=series, removed=gone, cursor=token)

    async def push(self, calendar: RemoteCalendar, pending: PendingSeries) -> Pushed:
        remote = self.remote
        remote.maybe_fail("push")
        if calendar.read_only:
            raise SyncError(ErrorKind.REFUSED, _MESSAGES[ErrorKind.REFUSED])
        series = pending.series
        items = remote.items[calendar.remote_id]
        if series.remote_id is not None:
            current = items.get(series.remote_id)
            if current is None or current.etag != series.etag:
                raise SyncError(ErrorKind.CONFLICT, _MESSAGES[ErrorKind.CONFLICT])
        stored = remote.put(calendar.remote_id, replace(series, raw_ical=None))
        remote.pushes.append(stored.remote_id or "")
        return Pushed(uid=stored.uid, remote_id=stored.remote_id or "", etag=stored.etag)

    async def delete(self, calendar: RemoteCalendar, pending: PendingSeries) -> None:
        remote = self.remote
        remote.maybe_fail("delete")
        remote_id = pending.series.remote_id
        if remote_id is None or remote_id not in remote.items[calendar.remote_id]:
            return
        current = remote.items[calendar.remote_id][remote_id]
        if pending.series.etag is not None and current.etag != pending.series.etag:
            raise SyncError(ErrorKind.CONFLICT, _MESSAGES[ErrorKind.CONFLICT])
        remote.remove(calendar.remote_id, remote_id)
        remote.deletes.append(remote_id)


# The test server's scripted servers, by account id (test mode only).
FAKE_REMOTES: dict[str, FakeRemote] = {}
