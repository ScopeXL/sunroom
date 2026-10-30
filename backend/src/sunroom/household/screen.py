"""The wall screen's sleep and brightness, for the Pi's helper (PLAN §11.1, §13.5).

``GET /api/display/state`` says what the panel should be doing now (domain/screen.py: on or off,
how bright, and why) and, given the etag the caller saw last, waits up to 55 seconds for that to
change: the 30-second schedule tick (dusk and bedtime arrive by themselves), a tap that wakes the
sleeping screen (``POST /api/display/wake``), or a changed setting. It's public and holds nothing
private, because kiosk/sunroom-screen on the Pi has no session; the browser draws the dim clock
or the black screen itself from the same settings.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel

from sunroom.auth.deps import ActorDep
from sunroom.core.errors import AppError
from sunroom.domain.screen import Schedule, screen_state
from sunroom.domain.timeparts import to_local
from sunroom.household import service
from sunroom.state import AppState, StateDep

router = APIRouter(prefix="/api/display", tags=["display"])

WAKE_FOR = timedelta(minutes=2)
MAX_WAIT_S = 55
TICK_S = 30


class ScheduleOut(BaseModel):
    sleep_from: str | None
    sleep_to: str | None
    sleep_mode: Literal["dim_clock", "screen_off"]
    dim_from: str | None
    dim_level: int


class DisplayStateOut(BaseModel):
    etag: str  # changes whenever anything but server_time does
    screen: Literal["on", "off"]
    brightness: int  # percent of full; 0 while off
    reason: Literal["day", "dim", "sleep", "awake"]
    awake_until: datetime | None
    schedule: ScheduleOut
    server_time: datetime


async def current(state: AppState) -> DisplayStateOut:
    now = state.clock.now()
    async with state.db.read() as db:
        home = await service.household(db)
    local = to_local(now, state.zone())
    awake_until = state.screen.awake_until
    if awake_until is not None and awake_until <= now:
        awake_until = None
    schedule = Schedule(
        home.sleep_from, home.sleep_to, home.sleep_mode, home.dim_from, home.dim_level
    )
    found = screen_state(schedule, local.hour * 60 + local.minute, awake=awake_until is not None)
    body: dict[str, Any] = {
        "screen": found.screen,
        "brightness": found.brightness,
        "reason": found.reason,
        "awake_until": awake_until.isoformat() if awake_until else None,
        "schedule": {
            "sleep_from": home.sleep_from,
            "sleep_to": home.sleep_to,
            "sleep_mode": home.sleep_mode,
            "dim_from": home.dim_from,
            "dim_level": home.dim_level,
        },
    }
    etag = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()[:16]
    return DisplayStateOut.model_validate({**body, "etag": etag, "server_time": now})


async def tick(state: AppState) -> None:
    """Every 30 seconds: wake the long polls when the time of day changed the state."""
    found = await current(state)
    if found.etag != state.screen.last_etag:
        state.screen.last_etag = found.etag
        state.screen.notify()


def on_event(state: AppState, event_type: str) -> None:
    """A hub listener: a changed setting (sleep, dim) may change the state now."""
    if event_type == "settings.changed":
        state.screen.notify()


@router.get("/state")
async def display_state(
    state: StateDep,
    response: Response,
    wait: Annotated[int, Query(ge=0, le=MAX_WAIT_S)] = 0,
    etag: Annotated[str | None, Query(max_length=64)] = None,
) -> DisplayStateOut:
    """What the panel should be doing. With ``etag`` and ``wait``, the answer comes when that
    changes or after ``wait`` seconds, whichever is first."""
    response.headers["Cache-Control"] = "no-store"
    loop = asyncio.get_running_loop()
    deadline = loop.time() + wait
    while True:
        changed = state.screen.changed
        found = await current(state)
        remaining = deadline - loop.time()
        if etag is None or found.etag != etag or remaining <= 0:
            return found
        try:
            await asyncio.wait_for(changed.wait(), timeout=remaining)
        except TimeoutError:
            return await current(state)


@router.post("/wake", status_code=204)
async def wake(state: StateDep, actor: ActorDep) -> None:
    """A tap on the sleeping wall screen: it stays on for 2 minutes (PLAN §13.5)."""
    if not actor.is_kiosk:
        raise AppError(403, "not_a_screen", "api.devices.wake_screen_only")
    state.screen.awake_until = state.clock.now() + WAKE_FOR
    state.screen.notify()
