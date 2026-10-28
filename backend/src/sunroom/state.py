"""Everything the running app holds in memory, plus the FastAPI dependency that hands it out.

All of it is correct only because exactly one process serves the API (PLAN §5.1).
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict, deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import Depends, Request

from sunroom.auth.ratelimit import FailureLimiter
from sunroom.auth.sessions import AuthState, GrantCodec, SessionCodec
from sunroom.calendar.occurrences import CalendarRuntime
from sunroom.core.clock import Clock
from sunroom.core.config import Settings
from sunroom.core.feedback import Outbox
from sunroom.core.http import GuardedHttp
from sunroom.core.jobs import Jobs
from sunroom.core.logging import get_logger
from sunroom.core.updates import UpdateCheck
from sunroom.db.backup import BackupPolicy, BackupService
from sunroom.db.engine import Database
from sunroom.events.hub import EventHub
from sunroom.household.screenwatch import ScreenWatch
from sunroom.photos.store import PhotoStore
from sunroom.plugins.manager import PluginManager

log = get_logger(__name__)

RECENT_HOSTS = 12


@dataclass
class HouseholdCache:
    """The few household values read on almost every request, refreshed when they change."""

    zone: ZoneInfo
    setup_complete: bool = False
    password_set: bool = False
    members: set[str] = field(default_factory=set[str])  # active member ids
    backups: BackupPolicy = field(default_factory=BackupPolicy)  # Settings → Backup


@dataclass
class HelloVersion:
    """The version the live stream's hello names (events/router.py): the build's own, or on the
    test server a stand-in, as if the container had just been updated (meta/testing.py)."""

    stand_in: str | None = None
    once: bool = False  # only the next hello names the stand-in

    def named(self, real: str) -> str:
        if self.stand_in is None:
            return real
        named = self.stand_in
        if self.once:
            self.stand_in = None
        return named


def _no_restart() -> None:
    """Tests and `sunroom openapi` never run themselves again."""
    log.info("app.restart_skipped")


@dataclass
class AppState:
    settings: Settings
    clock: Clock
    secret: str
    db: Database
    hub: EventHub
    auth: AuthState
    codec: SessionCodec
    grants: GrantCodec
    login_limiter: FailureLimiter
    pin_limiter: FailureLimiter
    backups: BackupService
    http: GuardedHttp
    photos: PhotoStore
    plugins: PluginManager
    household: HouseholdCache
    jobs: Jobs = field(default_factory=Jobs)
    # The occurrence cache and the overlays plugins add (calendar/occurrences.py).
    calendar: CalendarRuntime = field(default_factory=CalendarRuntime)
    # The display's pairing long-polls wait on these, keyed by the poll token's hash.
    pairing_waiters: dict[str, asyncio.Event] = field(default_factory=dict[str, asyncio.Event])
    # Photo uploads per device in the last hour (60 at most; photos/router.py).
    uploads: dict[str, deque[datetime]] = field(default_factory=dict[str, deque[datetime]])
    # Addresses this server was recently reached at (Settings → Connection), newest last.
    recent_hosts: OrderedDict[str, datetime] = field(default_factory=OrderedDict[str, datetime])
    # The wall screen's wake and its state's long polls (household/screen.py).
    screen: ScreenWatch = field(default_factory=ScreenWatch)
    # The newest release GitHub named, when the household opted in (core/updates.py).
    updates: UpdateCheck = field(default_factory=UpdateCheck)
    # Send Feedback's sends this hour, and on the test server what it kept (core/feedback.py).
    feedback: Outbox = field(default_factory=Outbox)
    # What the stream's hello says this server is (every screen reloads on a new one).
    hello_version: HelloVersion = field(default_factory=HelloVersion)
    # How this process runs itself again after a restore (boot.reexec; under `--reload`, the dev
    # server's reload), and one upload or restore at a time (meta/restore.py, ADR 0034).
    restart: Callable[[], None] = _no_restart
    restore_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    started: bool = False

    def zone(self) -> ZoneInfo:
        return self.household.zone

    def note_host(self, host: str) -> None:
        self.recent_hosts.pop(host, None)
        self.recent_hosts[host] = self.clock.now()
        while len(self.recent_hosts) > RECENT_HOSTS:
            self.recent_hosts.popitem(last=False)


def get_state(request: Request) -> AppState:
    state: AppState = request.app.state.sunroom
    return state


StateDep = Annotated[AppState, Depends(get_state)]
