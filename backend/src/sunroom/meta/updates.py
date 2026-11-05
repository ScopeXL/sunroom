"""Settings → About's update line (PLAN §13.6, core/updates.py): whether a newer Sunroom is out,
and how to update this server. On by default, with a switch (ADR 0046)."""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter
from pydantic import BaseModel

from sunroom.auth.deps import ActorDep, ParentDep
from sunroom.core import updates
from sunroom.core.errors import AppError
from sunroom.core.http import OutboundError
from sunroom.core.lang import t_en
from sunroom.core.logging import get_logger
from sunroom.core.version import build_info
from sunroom.household import service
from sunroom.state import AppState, StateDep

log = get_logger(__name__)

router = APIRouter(prefix="/api/admin", tags=["meta"])

CHECK_NOW_EVERY = timedelta(minutes=1)
# The companion leaves an image alone for its first day, on /v1/update too, and no request can ask
# it not to (WATCHTOWER_COOLDOWN_DELAY in the compose example): Update Now waits with it.
UPDATER_WAITS = timedelta(hours=24)
# Asked again this often: quickly when it wasn't there, since it may just be starting.
UPDATER_SEEN_FOR = timedelta(hours=1)
UPDATER_MISSED_FOR = timedelta(minutes=1)


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
    updater: bool  # the updater companion answers: new versions install themselves overnight
    update_now: bool  # a new version it would install if it were asked now


async def update_out(state: AppState) -> UpdateOut:
    async with state.db.read() as db:
        home = await service.household(db)
    locked = state.settings.update_check_forced_off
    current = build_info().version
    found = state.updates
    updater = found.updater_seen and bool(state.settings.sunroom_updater_url)
    available = updates.newer(found.latest, current)
    waiting = found.published is not None and state.clock.now() - found.published < UPDATER_WAITS
    how_key = updates.HOW_KEYS[state.settings.sunroom_install_kind]
    if updater:
        how_key = "api.update.how.companion_waits" if waiting else "api.update.how.companion"
    return UpdateOut(
        enabled=home.update_check and not locked,
        locked=locked,
        current=current,
        latest=found.latest,
        available=available,
        checked_at=found.checked_at,
        problem=found.problem,
        how=t_en(how_key),
        how_key=how_key,
        updater=updater,
        update_now=updater and available and not waiting,
    )


async def tick(state: AppState) -> None:
    """Hourly: ask once a day, for a household that's set up and hasn't turned it off.
    Nothing goes out before setup. The test server answers only when a test asks (Check Now): a
    version it made up by itself would stand in every test's Needs Attention."""
    await look_for_updater(state)
    if state.settings.update_check_forced_off or state.settings.sunroom_test_mode:
        return
    async with state.db.read() as db:
        home = await service.household(db)
    now = state.clock.now()
    if home.update_check and home.onboarded_at is not None and state.updates.due(now):
        await ask(state, build_info().version, now)


async def ask(state: AppState, current: str, now: datetime) -> None:
    """Ask for the newest release. The test server never does: it makes up the next minor
    version (core/updates.py ``made_up``), as the weather makes up its forecast."""
    found = state.updates
    known = found.latest
    if state.settings.sunroom_test_mode:
        found.latest, found.checked_at, found.problem = updates.made_up(current), now, None
    else:
        url = state.settings.sunroom_update_url or updates.VERSION_URL
        await updates.check(state.http, current, now, found, url=url)
    if found.latest != known and updates.newer(found.latest, current):
        state.hub.publish("update.available", {"version": found.latest})


async def look_for_updater(state: AppState) -> None:
    """Whether the companion answers and can reach Docker, so About never promises what it can't
    do: someone may have deleted it from the compose file, or it may have stopped."""
    url = state.settings.sunroom_updater_url
    if not url:
        return
    found = state.updates
    now = state.clock.now()
    wait = UPDATER_SEEN_FOR if found.updater_seen else UPDATER_MISSED_FOR
    if found.updater_looked_at is not None and now - found.updater_looked_at < wait:
        return
    found.updater_looked_at = now
    try:
        # A container on the compose network: allowed by name (app.py's allowlist).
        answer = await state.http.get(f"{url}/readyz", allow_private=bool(url), max_bytes=4096)
    except OutboundError as exc:
        log.info("updater.not_there", reason=exc.code)
        found.updater_seen = False
        return
    found.updater_seen = answer.ok


@router.get("/update")
async def update_status(state: StateDep, actor: ActorDep) -> UpdateOut:
    await look_for_updater(state)
    return await update_out(state)


@router.post("/update", status_code=202)
async def update_now(state: StateDep, actor: ParentDep) -> UpdateOut:
    """Update Now in About: the companion pulls the new image, stops Sunroom and starts it again
    on the same volume. Every page says so meanwhile, and reloads when it's back (ADR 0046)."""
    await look_for_updater(state)
    found = await update_out(state)
    url = state.settings.sunroom_updater_url
    if not found.updater or not url:
        raise AppError(409, "no_updater", "api.update.no_updater")
    if not found.available:
        raise AppError(409, "up_to_date", "api.update.up_to_date")
    if not found.update_now:
        raise AppError(409, "too_new", "api.update.how.companion_waits")
    token = state.settings.sunroom_updater_token
    headers = {"Authorization": f"Bearer {token.get_secret_value()}"} if token else {}
    try:
        # It answers at once and works in the background: waiting on it here would hold Sunroom
        # open while it's trying to stop Sunroom.
        answer = await state.http.request(
            "POST", f"{url}/v1/update?async=true", allow_private=bool(url), headers=headers
        )
    except OutboundError as exc:
        log.warning("updater.unreachable", reason=exc.code)
        raise AppError(502, "updater_failed", "api.update.unreachable") from exc
    # A 429 is an update already under way, which is what was asked for.
    if not answer.ok and answer.status != 429:
        log.warning("updater.refused", status=answer.status)
        raise AppError(502, "updater_failed", "api.update.unreachable")
    state.hub.publish("server.updating")
    return found


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
