"""Settings → About's update line (PLAN §13.6, core/updates.py): whether a newer Sunroom is out,
and how to update this server. On by default, with a switch (ADR 0046)."""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter
from pydantic import BaseModel

from sunroom.auth.deps import ActorDep, ParentDep
from sunroom.core import updates
from sunroom.core.errors import AppError
from sunroom.core.lang import t_en
from sunroom.core.version import build_info
from sunroom.household import service
from sunroom.state import AppState, StateDep

router = APIRouter(prefix="/api/admin", tags=["meta"])

CHECK_NOW_EVERY = timedelta(minutes=1)


class UpdateOut(BaseModel):
    enabled: bool  # "Tell me about new versions" is on (and not pinned off)
    locked: bool  # SUNROOM_UPDATE_CHECK=0 keeps it off
    current: str
    latest: str | None
    available: bool  # latest is newer than current
    checked_at: datetime | None
    problem: str | None  # why the last check got no answer
    how: str  # how to update this server, in plain words
    how_key: str  # that sentence in lang/en.json, for the page to say in the family's language


async def update_out(state: AppState) -> UpdateOut:
    async with state.db.read() as db:
        home = await service.household(db)
    locked = state.settings.update_check_forced_off
    current = build_info().version
    found = state.updates
    how_key = updates.HOW_KEYS[state.settings.sunroom_install_kind]
    return UpdateOut(
        enabled=home.update_check and not locked,
        locked=locked,
        current=current,
        latest=found.latest,
        available=updates.newer(found.latest, current),
        checked_at=found.checked_at,
        problem=found.problem,
        how=t_en(how_key),
        how_key=how_key,
    )


async def tick(state: AppState) -> None:
    """Hourly: ask GitHub once a day, for a household that's set up and hasn't turned it off.
    Nothing goes out before setup. The test server answers only when a test asks (Check Now): a
    version it made up by itself would stand in every test's Needs Attention."""
    if state.settings.update_check_forced_off or state.settings.sunroom_test_mode:
        return
    async with state.db.read() as db:
        home = await service.household(db)
    now = state.clock.now()
    if home.update_check and home.onboarded_at is not None and state.updates.due(now):
        await ask(state, build_info().version, now)


async def ask(state: AppState, current: str, now: datetime) -> None:
    """Ask GitHub for the newest release. The test server never does: it makes up the next minor
    version (core/updates.py ``made_up``), as the weather makes up its forecast."""
    found = state.updates
    known = found.latest
    if state.settings.sunroom_test_mode:
        found.latest, found.checked_at, found.problem = updates.made_up(current), now, None
    else:
        await updates.check(state.http, current, now, found)
    if found.latest != known and updates.newer(found.latest, current):
        state.hub.publish("update.available", {"version": found.latest})


@router.get("/update")
async def update_status(state: StateDep, actor: ActorDep) -> UpdateOut:
    return await update_out(state)


@router.post("/update/check")
async def check_now(state: StateDep, actor: ParentDep) -> UpdateOut:
    """Check now (About's button), at most once a minute."""
    found = await update_out(state)
    if found.locked:
        raise AppError(409, "update_check_off", "api.update.locked")
    if not found.enabled:
        raise AppError(409, "update_check_off", "api.update.off")
    now = state.clock.now()
    last = state.updates.checked_at
    if last is not None and now - last < CHECK_NOW_EVERY:
        raise AppError(429, "too_soon", "api.update.too_soon")
    await ask(state, found.current, now)
    return await update_out(state)
