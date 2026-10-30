"""Pairing a wall screen (PLAN §12.3, UX §4 "Pair this screen").

1. The screen opens /display with no session and asks for a code: ``POST pairings`` returns a
   six-character code, a secret poll token and the address to show as a QR code.
2. It long-polls ``GET pairings/{poll_token}?wait=25`` until the code is claimed or expires.
3. A parent types the code on their phone (``POST pair``), which creates the screen's device
   (kind kiosk, nobody's in particular) and wakes the screen's poll; the poll's response carries
   the screen's session cookie, and the screen reloads into the board.
   Or someone types the household password on the screen itself (``POST pair-with-password``).

The code row is stored like any pair code (hashed, once, 10 minutes); the screen's poll token
is stored hashed beside it, so a poll after a server restart still finds a claimed code.
"""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Query, Request, Response
from sqlalchemy import select

from sunroom.auth import join
from sunroom.auth.deps import ParentDep, issue_session
from sunroom.auth.models import Device, DeviceKind, JoinCode, PairedVia
from sunroom.auth.schemas import (
    KioskPairIn,
    KioskPairingOut,
    KioskPasswordPairIn,
    KioskPollOut,
    SessionOut,
)
from sunroom.auth.service import (
    advertised_url,
    check_rate,
    client_ip,
    new_device,
    password_ok,
    require_setup,
    session_out,
)
from sunroom.auth.sessions import DeviceInfo
from sunroom.core.errors import AppError
from sunroom.core.logging import get_logger
from sunroom.state import AppState, StateDep

router = APIRouter(prefix="/api/auth/kiosk", tags=["auth"])
log = get_logger(__name__)
MAX_WAIT_S = 25


@router.post("/pairings", status_code=201)
async def start_pairing(request: Request, state: StateDep) -> KioskPairingOut:
    require_setup(state)
    ip = client_ip(request)
    check_rate(state.login_limiter, ip)
    code, poll_token = join.new_code(), join.new_poll_token()
    now = state.clock.now()
    async with state.db.write() as tx:
        tx.session.add(
            JoinCode(
                code_hash=join.code_hash(state.secret, code),
                kind=DeviceKind.KIOSK,
                poll_token_hash=join.poll_token_hash(poll_token),
                created_at=now,
                expires_at=now + join.CODE_TTL,
            )
        )
    return KioskPairingOut(
        code=code,
        display=join.display(code),
        poll_token=poll_token,
        expires_in=int(join.CODE_TTL.total_seconds()),
        expires_at=now + join.CODE_TTL,
        pair_url=f"{advertised_url(state, request)}/pair#{code}",
    )


async def _poll_row(state: AppState, token_hash: str) -> JoinCode | None:
    async with state.db.read() as db:
        return await db.scalar(select(JoinCode).where(JoinCode.poll_token_hash == token_hash))


@router.get("/pairings/{poll_token}")
async def poll_pairing(
    poll_token: str,
    request: Request,
    response: Response,
    state: StateDep,
    wait: Annotated[int, Query(ge=0, le=MAX_WAIT_S)] = MAX_WAIT_S,
) -> KioskPollOut:
    token_hash = join.poll_token_hash(poll_token)
    row = await _poll_row(state, token_hash)
    if row is not None and row.used_by_device_id is None and wait > 0:
        waiter = state.pairing_waiters.setdefault(token_hash, asyncio.Event())
        try:
            await asyncio.wait_for(waiter.wait(), timeout=wait)
        except TimeoutError:
            pass
        finally:
            state.pairing_waiters.pop(token_hash, None)
        row = await _poll_row(state, token_hash)
    now = state.clock.now()
    if row is None or (row.used_by_device_id is None and row.expires_at <= now):
        return KioskPollOut(status="expired")
    device_id = row.used_by_device_id
    if device_id is None:
        return KioskPollOut(status="waiting")
    if device_id not in state.auth.live_device_ids():
        return KioskPollOut(status="expired")
    async with state.db.write() as tx:
        claimed = await tx.session.get(JoinCode, row.code_hash)
        if claimed is not None:
            claimed.poll_token_hash = None  # handed over: this token can't sign in again
        issue_session(response, request, state, device_id)
        log.info("auth.kiosk_paired", device=device_id)
        return KioskPollOut(
            status="paired", session=await session_out(tx.session, state, request, device_id)
        )


@router.post("/pair", status_code=201)
async def pair(
    body: KioskPairIn, request: Request, state: StateDep, actor: ParentDep
) -> dict[str, str]:
    """A parent's phone claims the code the screen shows."""
    ip = client_ip(request)
    check_rate(state.login_limiter, ip)
    code = join.normalize(body.code)
    now = state.clock.now()
    async with state.db.write() as tx:
        row = await tx.session.get(JoinCode, join.code_hash(state.secret, code)) if code else None
        if (
            row is None
            or row.kind != DeviceKind.KIOSK
            or row.used_at is not None
            or row.expires_at <= now
        ):
            state.login_limiter.record_failure(ip)
            raise AppError(401, "pair_code_invalid", "api.pairing.code_invalid")
        device = Device(
            label=body.label,
            kind=DeviceKind.KIOSK.value,
            paired_via=PairedVia.KIOSK_CODE.value,
            created_at=now,
            last_seen_at=now,
        )
        tx.session.add(device)
        await tx.session.flush()
        row.used_at = now
        row.used_by_device_id = device.id
        tx.publish("devices.changed")
    state.auth.devices[device.id] = DeviceInfo(DeviceKind.KIOSK.value, None, False)
    state.login_limiter.record_success(ip)
    if row.poll_token_hash and (waiter := state.pairing_waiters.get(row.poll_token_hash)):
        waiter.set()
    log.info("auth.kiosk_claimed", device=device.id, by=actor.device_id)
    return {"device_id": device.id, "label": device.label}


@router.post("/pair-with-password")
async def pair_with_password(
    body: KioskPasswordPairIn, request: Request, response: Response, state: StateDep
) -> SessionOut:
    """Typed on the screen itself, when no phone is at hand."""
    require_setup(state)
    ip = client_ip(request)
    check_rate(state.login_limiter, ip)
    now = state.clock.now()
    async with state.db.write() as tx:
        if not await password_ok(state, tx.session, body.password):
            state.login_limiter.record_failure(ip)
            raise AppError(401, "wrong_password", "api.auth.wrong_password")
        state.login_limiter.record_success(ip)
        device = await new_device(
            tx.session,
            state,
            request,
            response,
            kind=DeviceKind.KIOSK,
            paired_via=PairedVia.PASSWORD,
            label=body.label,
            now=now,
        )
        tx.publish("devices.changed")
        log.info("auth.kiosk_paired_with_password", device=device.id)
        return await session_out(tx.session, state, request, device.id)
