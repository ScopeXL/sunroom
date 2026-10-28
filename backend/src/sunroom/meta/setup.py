"""First run (PLAN §12.1, §13.4; ADR 0006).

Until setup is done, the app's pages send everyone to /setup, and the wall screen offers to set
it up there or on a phone. ``POST /api/setup`` is public only until it succeeds; after that it
answers 410 forever. In one transaction it stores the household password (scrypt), names the
household, sets its time zone and theme, marks it onboarded and signs in the phone that ran it,
as a parent; or, run on the wall screen itself (``on_screen``, ADR 0039), that screen, as a
paired one. The rest of the wizard (people, the PIN, calendars) uses the normal signed-in routes.

With APP_PASSWORD set, the wizard skips choosing a password but must be given that password, so
an unconfigured server reachable by strangers can't be claimed by the first visitor
(PLAN §17 risk 10).
"""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field, StringConstraints

from sunroom.auth.models import DeviceKind, PairedVia
from sunroom.auth.password import (
    device_label,
    env_password_matches,
    hash_password,
    password_problem,
)
from sunroom.auth.schemas import SessionOut
from sunroom.auth.service import advertised_url, check_rate, client_ip, new_device, session_out
from sunroom.core.errors import AppError
from sunroom.core.logging import get_logger
from sunroom.core.version import build_info
from sunroom.household import service as household_service
from sunroom.household.models import AppMeta
from sunroom.household.schemas import HouseholdName, ThemeName, TimeFormat
from sunroom.state import StateDep

router = APIRouter(prefix="/api/setup", tags=["setup"])
log = get_logger(__name__)
SCREEN_LABEL = "Wall screen"  # until Name This Screen, as a screen paired with the password


class SetupStatusOut(BaseModel):
    setup_complete: bool
    password_from_env: bool  # APP_PASSWORD is set: the wizard asks for it instead of a new one
    server_timezone: str | None  # TZ, if the server has one; the phone suggests its own
    advertised_url: str  # what to open on a phone (the wall screen shows it as a QR code)
    version: str


class SetupIn(BaseModel):
    password: Annotated[str, StringConstraints(max_length=256)]
    household_name: HouseholdName
    timezone: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    week_starts_on: Annotated[int, Field(ge=0, le=6)] = 6
    time_format: TimeFormat = "12h"
    theme: ThemeName = "auto"  # chosen on the wizard's household step (ADR 0034)
    on_screen: bool = False  # run on a wall screen: it becomes a paired screen (ADR 0039)


@router.get("/status")
async def setup_status(request: Request, state: StateDep) -> SetupStatusOut:
    return SetupStatusOut(
        setup_complete=state.household.setup_complete,
        password_from_env=state.settings.app_password is not None,
        server_timezone=state.settings.tz,
        advertised_url=advertised_url(state, request),
        version=build_info().version,
    )


@router.post("", status_code=201)
async def run_setup(
    body: SetupIn, request: Request, response: Response, state: StateDep
) -> SessionOut:
    if state.household.setup_complete:
        raise AppError(410, "setup_done", "Sunroom is already set up. Sign in instead.")
    ip = client_ip(request)
    check_rate(state.login_limiter, ip)
    zone = household_service.valid_zone(body.timezone)
    if zone is None:
        raise AppError(
            422,
            "invalid",
            "That time zone isn't one Sunroom knows.",
            extra={"fields": ["timezone"]},
        )
    env_password = state.settings.app_password
    if env_password is not None:
        if not env_password_matches(body.password, env_password):
            state.login_limiter.record_failure(ip)
            raise AppError(
                401,
                "wrong_password",
                "That isn't the password set on the server (APP_PASSWORD). Try again.",
            )
        stored_hash = None
    else:
        problem = password_problem(body.password)
        if problem:
            raise AppError(422, "weak_password", problem, extra={"fields": ["password"]})
        stored_hash = await asyncio.to_thread(hash_password, body.password)
    now = state.clock.now()
    async with state.db.write() as tx:
        home = await household_service.household(tx.session)
        if home.onboarded_at is not None:  # someone finished first, a moment ago
            raise AppError(410, "setup_done", "Sunroom is already set up. Sign in instead.")
        meta = await tx.session.get(AppMeta, 1)
        assert meta is not None  # the baseline migration creates it
        if stored_hash is not None:
            meta.password_hash = stored_hash
        home.name = body.household_name
        home.timezone = zone.key
        home.week_starts_on = body.week_starts_on
        home.time_format = body.time_format
        home.theme = body.theme
        home.onboarded_at = now
        home.updated_at = now
        device = await new_device(
            tx.session,
            state,
            request,
            response,
            kind=DeviceKind.KIOSK if body.on_screen else DeviceKind.PHONE,
            paired_via=PairedVia.SETUP,
            label=SCREEN_LABEL
            if body.on_screen
            else device_label(request.headers.get("user-agent")),
            now=now,
        )
        tx.publish("settings.changed", {"area": "setup"})
        out = await session_out(tx.session, state, request, device.id)
    state.household.setup_complete = True
    state.household.password_set = True
    state.household.zone = zone
    state.login_limiter.record_success(ip)
    log.info("setup.done", device=device.id, on_screen=body.on_screen)
    return out
