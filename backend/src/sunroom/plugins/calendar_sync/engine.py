"""The sync engine (PLAN §8.2).

Every minute ``tick`` starts a worker for each account that's due, two at a time. A worker
refreshes the account's list of calendars, pulls each mapped calendar's changes and merges them
(through ``ctx.calendar``), then pushes the changes people made here. ``push_sweep`` pushes
too, every minute and soon after an edit, so a change made on the wall reaches the server
without waiting for the next pull.

Failures never stop the plugin: a refused password marks the account ``needs_reconnect`` and
stops it until someone reconnects; anything else backs off (the interval times 2^failures, at
most an hour, ±20 %) and shows as a quiet line, the account ``error`` after three in a row. A
push that meets a newer version on the server (412) pulls, merges and tries once more.
"""

from __future__ import annotations

import asyncio
import json
import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol, cast

from sqlalchemy import delete, select

from sunroom.calendar.synced import MergeResult, PendingSeries
from sunroom.core.lang import t_en
from sunroom.core.logging import get_logger
from sunroom.plugins.calendar_sync.models import (
    AccountStatus,
    RemoteCalendarRow,
    SyncAccount,
    SyncRun,
)
from sunroom.plugins.calendar_sync.providers.base import (
    CalendarProvider,
    ErrorKind,
    RemoteCalendar,
    SyncError,
)
from sunroom.plugins.context import PluginContext, PluginDecryptError

log = get_logger(__name__)

TICK_S = 60
PUSH_S = 60
MAX_CONCURRENT = 2
MAX_BACKOFF_S = 3600
ERROR_AFTER = 3  # failures in a row before an account shows as "error"
RUNS_KEPT = 50
RUNS_DAYS = 7
RECONNECT = "api.sync.saved_password_unreadable"
UNEXPECTED = "api.sync.unexpected"


class ProviderFactory(Protocol):
    def __call__(self, account: SyncAccount, secrets: dict[str, Any]) -> CalendarProvider: ...


@dataclass
class Totals:
    fetched: int = 0
    created: int = 0
    updated: int = 0
    deleted: int = 0
    pushed: int = 0

    def add(self, result: MergeResult, fetched: int) -> None:
        self.fetched += fetched
        self.created += result.created
        self.updated += result.updated
        self.deleted += result.deleted


def backoff_seconds(
    interval_s: float,
    failures: int,
    retry_after: float | None = None,
    jitter: Callable[[], float] = lambda: random.uniform(0.8, 1.2),  # noqa: S311 (not security)
) -> float:
    """How long to wait before trying again after ``failures`` failures in a row."""
    base = min(interval_s * (2 ** max(0, failures)), MAX_BACKOFF_S)
    wait = base * jitter()
    if retry_after is not None:
        wait = max(wait, retry_after)
    return min(wait, MAX_BACKOFF_S * 1.2)


def secrets_of(ctx: PluginContext, account: SyncAccount) -> dict[str, Any]:
    if not account.credentials_enc:
        return {}
    raw: object = json.loads(ctx.decrypt(account.credentials_enc))
    return cast("dict[str, Any]", raw) if isinstance(raw, dict) else {}


class SyncEngine:
    def __init__(
        self,
        ctx: PluginContext,
        providers: ProviderFactory,
        *,
        jitter: Callable[[], float] | None = None,
    ) -> None:
        self.ctx = ctx
        self.providers = providers
        self._jitter = jitter or (lambda: random.uniform(0.8, 1.2))  # noqa: S311
        self._limit = asyncio.Semaphore(MAX_CONCURRENT)
        self._locks: dict[str, asyncio.Lock] = {}
        self._running: set[str] = set()
        self._push_soon = False

    # ---- scheduling --------------------------------------------------------------------------

    def is_running(self, account_id: str) -> bool:
        return account_id in self._running

    async def tick(self) -> None:
        """Start a worker for every account that's due."""
        now = self.ctx.now()
        async with self.ctx.read() as session:
            due = (
                await session.scalars(
                    select(SyncAccount.id).where(
                        SyncAccount.deleted_at.is_(None),
                        SyncAccount.status.in_([AccountStatus.CONNECTED, AccountStatus.ERROR]),
                    )
                )
            ).all()
            accounts = [
                account
                for account in [await session.get(SyncAccount, account_id) for account_id in due]
                if account is not None
                and (account.next_sync_at is None or account.next_sync_at <= now)
            ]
        for account in accounts:
            self.start(account.id)

    def start(self, account_id: str) -> bool:
        """Sync this account soon (False when it's already syncing)."""
        if account_id in self._running:
            return False
        self._running.add(account_id)
        self.ctx.spawn(f"sync:{account_id}", self._worker(account_id))
        return True

    async def _worker(self, account_id: str) -> None:
        try:
            async with self._limit:
                await self.sync_account(account_id)
        finally:
            self._running.discard(account_id)

    def _lock(self, account_id: str) -> asyncio.Lock:
        return self._locks.setdefault(account_id, asyncio.Lock())

    # ---- one account -------------------------------------------------------------------------

    async def sync_account(self, account_id: str) -> None:
        """Pull every mapped calendar of the account, then push. Never raises."""
        async with self._lock(account_id):
            started = self.ctx.now()
            clock = time.monotonic()
            run_id = await self._start_run(account_id, started)
            totals = Totals()
            try:
                provider = await self._provider(account_id)
                if provider is None:
                    await self._finish_run(run_id, clock, totals, "auth", t_en(RECONNECT))
                    return
                await self._refresh_calendars(account_id, provider)
                await self._pull_all(account_id, provider, totals)
                totals.pushed += await self._push(account_id, provider)
            except SyncError as exc:
                await self._failed(account_id, exc)
                await self._finish_run(run_id, clock, totals, _outcome(exc), exc.message)
                return
            except Exception:
                log.exception("sync.unexpected", account_id=account_id)
                await self._failed(account_id, SyncError(ErrorKind.UNREACHABLE, UNEXPECTED))
                await self._finish_run(run_id, clock, totals, "error", t_en(UNEXPECTED))
                return
            await self._succeeded(account_id)
            await self._finish_run(run_id, clock, totals, "ok", None)

    async def _provider(self, account_id: str) -> CalendarProvider | None:
        async with self.ctx.read() as session:
            account = await session.get(SyncAccount, account_id)
            if account is None or account.deleted_at is not None:
                return None
            try:
                secrets = secrets_of(self.ctx, account)
            except PluginDecryptError:
                secrets = None
        if secrets is None:
            await self._failed(account_id, SyncError(ErrorKind.AUTH, RECONNECT))
            return None
        return self.providers(account, secrets)

    async def _refresh_calendars(self, account_id: str, provider: CalendarProvider) -> None:
        """New calendars on the server show up unmapped; names follow the server."""
        listed = await provider.calendars()
        now = self.ctx.now()
        async with self.ctx.write() as tx:
            rows = {
                row.remote_id: row
                for row in (
                    await tx.session.scalars(
                        select(RemoteCalendarRow).where(RemoteCalendarRow.account_id == account_id)
                    )
                ).all()
            }
            for remote in listed:
                row = rows.get(remote.remote_id)
                if row is None:
                    tx.session.add(
                        RemoteCalendarRow(
                            account_id=account_id,
                            remote_id=remote.remote_id,
                            name=remote.name[:200],
                            color_hint=remote.color_hint,
                            read_only=remote.read_only,
                            created_at=now,
                        )
                    )
                else:
                    row.name = remote.name[:200]
                    row.color_hint = remote.color_hint
                    row.read_only = remote.read_only
            gone = {row.remote_id for row in rows.values()} - {r.remote_id for r in listed}
            for remote_id in gone:
                rows[remote_id].last_error = t_en("api.sync.calendar_gone")

    async def _mapped(self, account_id: str) -> list[RemoteCalendarRow]:
        async with self.ctx.read() as session:
            return list(
                (
                    await session.scalars(
                        select(RemoteCalendarRow).where(
                            RemoteCalendarRow.account_id == account_id,
                            RemoteCalendarRow.mapped.is_(True),
                            RemoteCalendarRow.calendar_id.is_not(None),
                        )
                    )
                ).all()
            )

    async def _pull_all(self, account_id: str, provider: CalendarProvider, totals: Totals) -> None:
        for row in await self._mapped(account_id):
            try:
                await self.pull(account_id, provider, row, totals)
            except SyncError as exc:
                if exc.kind != ErrorKind.NOT_FOUND:
                    raise
                await self._calendar_error(row.id, exc.message)

    async def pull(
        self,
        account_id: str,
        provider: CalendarProvider,
        row: RemoteCalendarRow,
        totals: Totals | None = None,
    ) -> MergeResult:
        assert row.calendar_id is not None
        calendar = _remote(row)
        known = await self.ctx.calendar.known(row.calendar_id)
        changes = await provider.changes(calendar, row.sync_token, known)
        big = len(changes.series) > 500

        async def progress(done: int, total: int) -> None:
            if big:
                self.ctx.publish(
                    "sync.changed",
                    {"account_id": account_id, "status": "importing", "done": done, "total": total},
                )

        result = await self.ctx.calendar.upsert_synced(
            row.calendar_id,
            changes.series,
            removed=changes.removed,
            complete=changes.complete,
            on_progress=progress,
        )
        async with self.ctx.write() as tx:
            stored = await tx.session.get(RemoteCalendarRow, row.id)
            if stored is not None:
                if changes.cursor is not None:
                    stored.sync_token = changes.cursor
                stored.last_synced_at = self.ctx.now()
                stored.last_error = None
        if totals is not None:
            totals.add(result, len(changes.series))
        return result

    # ---- pushing -----------------------------------------------------------------------------

    async def push_sweep(self) -> None:
        """Push every connected account's waiting changes (every minute, and after an edit)."""
        self._push_soon = False
        async with self.ctx.read() as session:
            accounts = (
                await session.scalars(
                    select(SyncAccount.id).where(
                        SyncAccount.deleted_at.is_(None),
                        SyncAccount.status == AccountStatus.CONNECTED,
                    )
                )
            ).all()
        for account_id in accounts:
            if account_id in self._running:
                continue  # its worker pushes when it's done pulling
            if not await self._has_pending(account_id):
                continue
            self._running.add(account_id)
            self.ctx.spawn(f"push:{account_id}", self._push_worker(account_id))

    def push_soon(self) -> None:
        """Called on events.changed: push without waiting for the next minute."""
        if self._push_soon:
            return
        self._push_soon = True
        self.ctx.spawn("push-soon", self._delayed_sweep())

    async def _delayed_sweep(self) -> None:
        await asyncio.sleep(2)
        await self.push_sweep()

    async def _has_pending(self, account_id: str) -> bool:
        rows = await self._mapped(account_id)
        ids = [row.calendar_id for row in rows if row.calendar_id and not row.read_only]
        return bool(ids) and bool(await self.ctx.calendar.pending(ids))

    async def _push_worker(self, account_id: str) -> None:
        try:
            async with self._limit, self._lock(account_id):
                try:
                    provider = await self._provider(account_id)
                    if provider is None:
                        return
                    await self._push(account_id, provider)
                except SyncError as exc:
                    await self._failed(account_id, exc)
                except Exception:
                    log.exception("sync.push_unexpected", account_id=account_id)
                    await self._failed(account_id, SyncError(ErrorKind.UNREACHABLE, UNEXPECTED))
        finally:
            self._running.discard(account_id)

    async def _push(self, account_id: str, provider: CalendarProvider) -> int:
        rows = {
            row.calendar_id: row
            for row in await self._mapped(account_id)
            if row.calendar_id is not None and not row.read_only
        }
        if not rows:
            return 0
        pushed = 0
        for item in await self.ctx.calendar.pending(list(rows)):
            row = rows[item.calendar_id]
            if await self._push_one(account_id, provider, row, item):
                pushed += 1
        return pushed

    async def _push_one(
        self,
        account_id: str,
        provider: CalendarProvider,
        row: RemoteCalendarRow,
        item: PendingSeries,
    ) -> bool:
        calendar = _remote(row)
        for attempt in range(2):
            try:
                if item.deleted:
                    await provider.delete(calendar, item)
                    await self.ctx.calendar.mark_removed(item)
                else:
                    pushed = await provider.push(calendar, item)
                    await self.ctx.calendar.mark_pushed(
                        item,
                        uid=pushed.uid,
                        remote_id=pushed.remote_id,
                        etag=pushed.etag,
                        raw_ical=pushed.raw_ical,
                    )
                return True
            except SyncError as exc:
                if exc.kind != ErrorKind.CONFLICT or attempt == 1:
                    raise
            # 412: someone changed it on the server too. Pull, merge (a newer local change
            # keeps its content and takes the server's etag), and try once more.
            await self.pull(account_id, provider, row)
            fresh = [
                p
                for p in await self.ctx.calendar.pending([row.calendar_id or ""])
                if p.event_id == item.event_id
            ]
            if not fresh:
                return False  # the server's version won; nothing left to push
            item = fresh[0]
        return False

    # ---- bookkeeping -------------------------------------------------------------------------

    async def _start_run(self, account_id: str, started: datetime) -> str:
        async with self.ctx.write() as tx:
            run = SyncRun(account_id=account_id, started_at=started)
            tx.session.add(run)
            await tx.session.flush()
            tx.publish("sync.changed", {"account_id": account_id, "status": "syncing"})
            return run.id

    async def _finish_run(
        self, run_id: str, clock: float, totals: Totals, outcome: str, error: str | None
    ) -> None:
        now = self.ctx.now()
        async with self.ctx.write() as tx:
            run = await tx.session.get(SyncRun, run_id)
            if run is None:
                return
            run.finished_at = now
            run.outcome = outcome
            run.fetched, run.created, run.updated = totals.fetched, totals.created, totals.updated
            run.deleted, run.pushed = totals.deleted, totals.pushed
            run.error = error
            run.duration_ms = int((time.monotonic() - clock) * 1000)
            # Keep the last RUNS_KEPT runs of this account, and none older than RUNS_DAYS.
            keep = (
                select(SyncRun.id)
                .where(SyncRun.account_id == run.account_id)
                .order_by(SyncRun.started_at.desc())
                .limit(RUNS_KEPT)
            )
            await tx.session.execute(
                delete(SyncRun).where(SyncRun.account_id == run.account_id, SyncRun.id.not_in(keep))
            )
            await tx.session.execute(
                delete(SyncRun).where(SyncRun.started_at < now - timedelta(days=RUNS_DAYS))
            )

    async def _succeeded(self, account_id: str) -> None:
        now = self.ctx.now()
        async with self.ctx.write() as tx:
            account = await tx.session.get(SyncAccount, account_id)
            if account is None:
                return
            account.status = AccountStatus.CONNECTED
            account.consecutive_failures = 0
            account.last_sync_at = now
            account.last_success_at = now
            account.last_error = None
            account.last_error_at = None
            account.next_sync_at = now + timedelta(seconds=account.interval_s)
            tx.publish("sync.changed", {"account_id": account_id, "status": account.status})

    async def _failed(self, account_id: str, exc: SyncError) -> None:
        now = self.ctx.now()
        async with self.ctx.write() as tx:
            account = await tx.session.get(SyncAccount, account_id)
            if account is None:
                return
            account.last_sync_at = now
            account.last_error = exc.message[:300]
            account.last_error_at = now
            if exc.kind == ErrorKind.AUTH:
                account.status = AccountStatus.NEEDS_RECONNECT
                account.next_sync_at = None
            else:
                account.consecutive_failures += 1
                if account.consecutive_failures >= ERROR_AFTER:
                    account.status = AccountStatus.ERROR
                wait = backoff_seconds(
                    account.interval_s,
                    account.consecutive_failures,
                    exc.retry_after,
                    self._jitter,
                )
                account.next_sync_at = now + timedelta(seconds=wait)
            log.info("sync.failed", account_id=account_id, kind=exc.kind.value)
            tx.publish("sync.changed", {"account_id": account_id, "status": account.status})

    async def _calendar_error(self, row_id: str, message: str) -> None:
        async with self.ctx.write() as tx:
            row = await tx.session.get(RemoteCalendarRow, row_id)
            if row is not None:
                row.last_error = message[:300]


def _remote(row: RemoteCalendarRow) -> RemoteCalendar:
    return RemoteCalendar(row.remote_id, row.name, row.color_hint, row.read_only)


def _outcome(exc: SyncError) -> str:
    return "auth" if exc.kind == ErrorKind.AUTH else "error"
