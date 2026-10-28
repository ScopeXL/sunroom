"""Sign in, add a phone, "Who's using this?", devices, and the parent PIN (PLAN §11.1, §12)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from fastapi import APIRouter, Request, Response
from sqlalchemy import delete, select, update

from sunroom.auth import join
from sunroom.auth.deps import (
    ActorDep,
    ParentDep,
    clear_grant_cookie,
    clear_session_cookie,
    issue_grant,
    parent_required,
)
from sunroom.auth.models import Device, DeviceKind, JoinCode, PairedVia
from sunroom.auth.password import device_form, device_label, hash_pin, verify_pin
from sunroom.auth.ratelimit import SLOW_AFTER
from sunroom.auth.schemas import (
    DeviceLabelIn,
    DeviceOut,
    DeviceUpdate,
    GrantOut,
    JoinCodeOut,
    JoinIn,
    LoginIn,
    MemberChoice,
    PinSetIn,
    PinVerifyIn,
    SessionOut,
    SignOutOthersIn,
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
from sunroom.auth.sessions import DeviceInfo, pin_epoch_of
from sunroom.core.errors import AppError
from sunroom.core.logging import get_logger
from sunroom.household import service as household_service
from sunroom.household.models import Member
from sunroom.state import AppState, StateDep

router = APIRouter(prefix="/api/auth", tags=["auth"])
log = get_logger(__name__)


@router.post("/login")
async def login(body: LoginIn, request: Request, response: Response, state: StateDep) -> SessionOut:
    require_setup(state)
    ip = client_ip(request)
    check_rate(state.login_limiter, ip)
    now = state.clock.now()
    async with state.db.write() as tx:
        if not await password_ok(state, tx.session, body.password):
            state.login_limiter.record_failure(ip)
            log.info("auth.login_failed")
            raise AppError(401, "wrong_password", "That password didn't match. Try again.")
        state.login_limiter.record_success(ip)
        device = await new_device(
            tx.session,
            state,
            request,
            response,
            kind=DeviceKind.PHONE,
            paired_via=PairedVia.PASSWORD,
            label=device_label(request.headers.get("user-agent")),
            now=now,
        )
        tx.publish("devices.changed")
        log.info("auth.login", device=device.id)
        return await session_out(tx.session, state, request, device.id)


@router.post("/join-codes", status_code=201)
async def make_join_code(request: Request, state: StateDep, actor: ActorDep) -> JoinCodeOut:
    """Add a Device: a one-time code another phone, tablet or computer signs in with. On a wall
    screen, which anyone in the house can reach, only a parent may make one."""
    if actor.is_kiosk and not actor.is_parent:
        raise parent_required(actor, state)
    code = join.new_code()
    now = state.clock.now()
    async with state.db.write() as tx:
        await tx.session.execute(
            delete(JoinCode).where(
                JoinCode.created_by_device_id == actor.device_id,
                JoinCode.kind == DeviceKind.PHONE,
                JoinCode.used_at.is_(None),
            )
        )
        tx.session.add(
            JoinCode(
                code_hash=join.code_hash(state.secret, code),
                kind=DeviceKind.PHONE,
                created_by_device_id=actor.device_id,
                created_at=now,
                expires_at=now + join.CODE_TTL,
            )
        )
    log.info("auth.join_code_made", device=actor.device_id)
    return JoinCodeOut(
        code=code,
        display=join.display(code),
        url=f"{advertised_url(state, request)}/join#{code}",
        expires_at=now + join.CODE_TTL,
    )


@router.post("/join")
async def join_with_code(
    body: JoinIn, request: Request, response: Response, state: StateDep
) -> SessionOut:
    """Sign in a new device with a code from a signed-in device. Wrong codes count as wrong
    passwords do, so codes can't be guessed."""
    require_setup(state)
    ip = client_ip(request)
    check_rate(state.login_limiter, ip)
    code = join.normalize(body.code)
    now = state.clock.now()
    async with state.db.write() as tx:
        row = await tx.session.get(JoinCode, join.code_hash(state.secret, code)) if code else None
        maker = row.created_by_device_id if row else None
        if (
            row is not None
            and row.kind == DeviceKind.PHONE
            and row.used_at is None
            and row.expires_at > now
            and maker is not None
            and maker in state.auth.live_device_ids()
        ):
            device = await new_device(
                tx.session,
                state,
                request,
                response,
                kind=DeviceKind.PHONE,
                paired_via=PairedVia.CODE,
                label=device_label(request.headers.get("user-agent")),
                now=now,
            )
            row.used_at = now
            row.used_by_device_id = device.id
            tx.publish("devices.changed")
            log.info("auth.joined", device=device.id, added_by=maker)
            state.login_limiter.record_success(ip)
            return await session_out(tx.session, state, request, device.id)
    state.login_limiter.record_failure(ip)
    log.info("auth.join_failed")
    raise AppError(
        401,
        "join_code_invalid",
        "That code didn't work. A code works once, for 10 minutes. Make a new one on a "
        "signed-in device.",
    )


@router.get("/session")
async def get_session(request: Request, state: StateDep, actor: ActorDep) -> SessionOut:
    async with state.db.read() as db:
        return await session_out(db, state, request, actor.device_id)


@router.put("/member")
async def choose_member(
    body: MemberChoice, request: Request, state: StateDep, actor: ActorDep
) -> SessionOut:
    """Who's using this device? A wall screen is everyone's: it picks a person per action."""
    if actor.is_kiosk:
        raise AppError(409, "kiosk_has_no_member", "A paired screen is for everyone.")
    async with state.db.write() as tx:
        if body.member_id is not None:
            member = await tx.session.get(Member, body.member_id)
            if member is None or member.archived_at is not None:
                raise AppError(404, "not_found", "That person isn't in this household.")
        await tx.session.execute(
            update(Device).where(Device.id == actor.device_id).values(member_id=body.member_id)
        )
        old = state.auth.devices[actor.device_id]
        state.auth.devices[actor.device_id] = DeviceInfo(
            old.kind, body.member_id, old.is_kid_device
        )
        tx.publish("devices.changed")
        return await session_out(tx.session, state, request, actor.device_id)


@router.put("/device/label")
async def rename_this_device(
    body: DeviceLabelIn, request: Request, state: StateDep, actor: ActorDep
) -> SessionOut:
    """ "Name this screen" right after pairing, or a phone's own name."""
    async with state.db.write() as tx:
        await tx.session.execute(
            update(Device).where(Device.id == actor.device_id).values(label=body.label)
        )
        tx.publish("devices.changed")
        return await session_out(tx.session, state, request, actor.device_id)


@router.post("/logout", status_code=204)
async def logout(request: Request, response: Response, state: StateDep, actor: ActorDep) -> None:
    await revoke(state, [actor.device_id])
    clear_session_cookie(response, request)
    clear_grant_cookie(response, request)


@router.get("/devices")
async def list_devices(state: StateDep, actor: ParentDep) -> list[DeviceOut]:
    async with state.db.read() as db:
        rows = await db.execute(
            select(Device, Member.name)
            .join(Member, Member.id == Device.member_id, isouter=True)
            .where(Device.revoked_at.is_(None))
            .order_by(Device.kind.desc(), Device.last_seen_at.desc())
        )
        return [
            DeviceOut.model_validate(
                {
                    "id": device.id,
                    "label": device.label,
                    "kind": device.kind,
                    "form": device_form(device.kind, device.label),
                    "member_name": member_name,
                    "is_kid_device": device.is_kid_device,
                    "created_at": device.created_at,
                    "last_seen_at": device.last_seen_at,
                    "is_current": device.id == actor.device_id,
                }
            )
            for device, member_name in rows
        ]


@router.patch("/devices/{device_id}")
async def update_device(
    device_id: str, body: DeviceUpdate, state: StateDep, actor: ParentDep
) -> DeviceOut:
    async with state.db.write() as tx:
        device = await tx.session.get(Device, device_id)
        if device is None or device.revoked_at is not None:
            raise AppError(404, "not_found", "That device isn't signed in.")
        if body.label is not None:
            device.label = body.label
        if body.is_kid_device is not None:
            if device.kind == DeviceKind.KIOSK:
                raise AppError(409, "kiosk_not_kid", "A paired screen is for everyone.")
            if body.is_kid_device and not state.auth.has_pin:
                raise AppError(
                    409,
                    "pin_needed",
                    "Set a parent PIN first, so a parent can still unlock Settings there.",
                )
            device.is_kid_device = body.is_kid_device
            state.auth.devices[device.id] = DeviceInfo(
                device.kind, device.member_id, body.is_kid_device
            )
        member = await tx.session.get(Member, device.member_id) if device.member_id else None
        tx.publish("devices.changed")
        return DeviceOut.model_validate(
            {
                "id": device.id,
                "label": device.label,
                "kind": device.kind,
                "form": device_form(device.kind, device.label),
                "member_name": member.name if member else None,
                "is_kid_device": device.is_kid_device,
                "created_at": device.created_at,
                "last_seen_at": device.last_seen_at,
                "is_current": device.id == actor.device_id,
            }
        )


@router.delete("/devices/{device_id}", status_code=204)
async def sign_out_device(
    device_id: str, request: Request, response: Response, state: StateDep, actor: ParentDep
) -> None:
    if device_id not in state.auth.live_device_ids():
        raise AppError(404, "not_found", "That device isn't signed in.")
    await revoke(state, [device_id])
    if device_id == actor.device_id:
        clear_session_cookie(response, request)


@router.post("/devices/sign-out-others", status_code=204)
async def sign_out_others(body: SignOutOthersIn, state: StateDep, actor: ParentDep) -> None:
    others = [
        device_id
        for device_id in state.auth.live_device_ids()
        if device_id != actor.device_id
        and (body.include_kiosks or state.auth.devices[device_id].kind != DeviceKind.KIOSK)
    ]
    await revoke(state, others)


async def revoke(state: AppState, device_ids: list[str]) -> None:
    if not device_ids:
        return
    now = state.clock.now()
    async with state.db.write() as tx:
        await tx.session.execute(
            update(Device)
            .where(Device.id.in_(device_ids), Device.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        tx.publish("devices.changed")
    state.auth.revoked_devices.update(device_ids)
    state.hub.drop_devices(set(device_ids))
    log.info("auth.devices_signed_out", count=len(device_ids))


# ---- the parent PIN (PLAN §12.3) -------------------------------------------------------------


@router.put("/pin", status_code=204)
async def set_pin(body: PinSetIn, state: StateDep, actor: ParentDep) -> None:
    """Set or change the PIN. Where the PIN is what made this device a parent (the wall screen, a
    child's phone), changing it asks for the current one; a parent's own phone doesn't need it, so
    a forgotten PIN can always be reset from there."""
    now = state.clock.now()
    async with state.db.write() as tx:
        home = await household_service.household(tx.session)
        unlocked_by_pin = actor.is_kiosk or actor.is_kid_device
        if (
            home.parent_pin_hash
            and unlocked_by_pin
            and not (body.current_pin and verify_pin(body.current_pin, home.parent_pin_hash))
        ):
            raise AppError(403, "wrong_pin", "That PIN didn't match. Try again.")
        home.parent_pin_hash = await asyncio.to_thread(hash_pin, body.pin)
        home.pin_length = len(body.pin)
        home.pin_updated_at = now
        tx.publish("settings.changed", {"area": "pin"})
    state.auth.has_pin = True
    state.auth.pin_epoch = pin_epoch_of(home.parent_pin_hash)


@router.delete("/pin", status_code=204)
async def remove_pin(state: StateDep, actor: ParentDep) -> None:
    now = state.clock.now()
    async with state.db.write() as tx:
        home = await household_service.household(tx.session)
        home.parent_pin_hash = None
        home.pin_length = None
        home.pin_updated_at = now
        tx.publish("settings.changed", {"area": "pin"})
    state.auth.has_pin = False
    state.auth.pin_epoch = pin_epoch_of(None)


@router.post("/pin/verify")
async def verify_parent_pin(
    body: PinVerifyIn, request: Request, response: Response, state: StateDep, actor: ActorDep
) -> GrantOut:
    """A correct PIN unlocks parent things on this device for 10 minutes (no sliding)."""
    if not state.auth.has_pin:
        raise AppError(409, "no_pin", "There's no parent PIN yet. Set one in Settings → Family.")
    check_rate(state.pin_limiter, actor.device_id)
    async with state.db.read() as db:
        home = await household_service.household(db)
        stored = home.parent_pin_hash
    matched = stored is not None and await asyncio.to_thread(verify_pin, body.pin, stored)
    if not matched:
        if state.pin_limiter.recent_failures(actor.device_id) >= SLOW_AFTER - 1:
            await asyncio.sleep(1)
        state.pin_limiter.record_failure(actor.device_id)
        raise AppError(403, "wrong_pin", "That PIN didn't match. Try again.")
    state.pin_limiter.record_success(actor.device_id)
    expires = issue_grant(response, request, state, actor.device_id)
    log.info("auth.parent_grant", device=actor.device_id)
    return GrantOut(expires_at=datetime.fromtimestamp(expires, UTC))


@router.post("/pin/lock", status_code=204)
async def lock(request: Request, response: Response, actor: ActorDep) -> None:
    """End this device's parent grant now (the display's Lock button)."""
    clear_grant_cookie(response, request)
