"""Who is asking: the dependencies every protected route uses (PLAN §11, §12.2 to §12.4).

``ActorDep`` (A in the API tables) is any signed-in device. ``ParentDep`` (P) is a parent:
a phone not marked as a kid's, or any device holding a parent-PIN grant; while the household has
no PIN, the wall screen counts as a parent too (the PIN is optional, ADR 0006). A wall screen may
say who tapped (``X-Sunroom-Member``, K in the tables); phones ignore the header and act as the
person using them. A kid tapping a parent's avatar still can't do parent things.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Annotated

from fastapi import Depends, Request, Response
from sqlalchemy import update

from sunroom.auth.models import Device, DeviceKind
from sunroom.auth.sessions import (
    GRANT_SECONDS,
    MAX_AGE_SECONDS,
    REISSUE_AFTER_DAYS,
    GrantToken,
    SessionToken,
    day_number,
    grant_cookie_name,
    session_cookie_name,
)
from sunroom.core.errors import AppError
from sunroom.state import AppState, StateDep

LAST_SEEN_EVERY = timedelta(hours=1)
MEMBER_HEADER = "x-sunroom-member"


@dataclass(frozen=True, slots=True)
class Actor:
    device_id: str
    epoch: int
    kind: str
    member_id: str | None  # a phone's person, or the person a wall screen says tapped
    is_kid_device: bool
    is_parent: bool
    has_grant: bool

    @property
    def is_kiosk(self) -> bool:
        return self.kind == DeviceKind.KIOSK


def is_https(request: Request) -> bool:
    return request.url.scheme == "https"


def set_session_cookie(response: Response, request: Request, value: str) -> None:
    https = is_https(request)
    response.set_cookie(
        session_cookie_name(https),
        value,
        max_age=MAX_AGE_SECONDS,
        path="/",
        secure=https,
        httponly=True,
        samesite="lax",
    )


def clear_session_cookie(response: Response, request: Request) -> None:
    https = is_https(request)
    response.delete_cookie(
        session_cookie_name(https), path="/", secure=https, httponly=True, samesite="lax"
    )


def set_grant_cookie(response: Response, request: Request, value: str) -> None:
    https = is_https(request)
    response.set_cookie(
        grant_cookie_name(https),
        value,
        max_age=GRANT_SECONDS,
        path="/",
        secure=https,
        httponly=True,
        samesite="strict",
    )


def clear_grant_cookie(response: Response, request: Request) -> None:
    https = is_https(request)
    response.delete_cookie(
        grant_cookie_name(https), path="/", secure=https, httponly=True, samesite="strict"
    )


def issue_session(response: Response, request: Request, state: AppState, device_id: str) -> None:
    token = SessionToken(device_id, state.auth.epoch, day_number(state.clock.now()))
    set_session_cookie(response, request, state.codec.encode(token))


def issue_grant(response: Response, request: Request, state: AppState, device_id: str) -> int:
    """A 10-minute parent grant for this device. Returns when it ends (unix seconds)."""
    expires = int(state.clock.now().timestamp()) + GRANT_SECONDS
    token = GrantToken(device_id, expires, state.auth.pin_epoch)
    set_grant_cookie(response, request, state.grants.encode(token))
    return expires


def read_token(request: Request, state: AppState) -> SessionToken | None:
    token = state.codec.decode(request.cookies.get(session_cookie_name(is_https(request))))
    if token is None or not state.auth.is_valid(token):
        return None
    return token


def grant_expires_at(request: Request, state: AppState, device_id: str) -> int | None:
    """When this device's parent grant ends (unix seconds), or None if it holds none."""
    if not state.auth.has_pin:
        return None
    token = state.grants.decode(request.cookies.get(grant_cookie_name(is_https(request))))
    if (
        token is None
        or token.device_id != device_id
        or token.pin_epoch != state.auth.pin_epoch
        or token.expires_at <= int(state.clock.now().timestamp())
    ):
        return None
    return token.expires_at


async def current_actor(request: Request, response: Response, state: StateDep) -> Actor:
    token = read_token(request, state)
    if token is None:
        raise AppError(401, "signed_out", "api.auth.signed_out")
    now = state.clock.now()
    today = day_number(now)
    if today - token.issued_day >= REISSUE_AFTER_DAYS:
        renewed = SessionToken(token.device_id, token.epoch, today)
        set_session_cookie(response, request, state.codec.encode(renewed))
    last = state.auth.last_seen_written.get(token.device_id)
    if last is None or now - last >= LAST_SEEN_EVERY:
        state.auth.last_seen_written[token.device_id] = now
        async with state.db.write() as tx:
            await tx.session.execute(
                update(Device).where(Device.id == token.device_id).values(last_seen_at=now)
            )
    info = state.auth.devices[token.device_id]
    has_grant = grant_expires_at(request, state, token.device_id) is not None
    member_id = info.member_id
    if info.kind == DeviceKind.KIOSK:
        tapped = request.headers.get(MEMBER_HEADER)
        member_id = tapped if tapped in state.household.members else None
    is_parent = (
        has_grant
        or (info.kind == DeviceKind.PHONE and not info.is_kid_device)
        or (info.kind == DeviceKind.KIOSK and not state.auth.has_pin)
    )
    return Actor(
        device_id=token.device_id,
        epoch=token.epoch,
        kind=info.kind,
        member_id=member_id,
        is_kid_device=info.is_kid_device,
        is_parent=is_parent,
        has_grant=has_grant,
    )


ActorDep = Annotated[Actor, Depends(current_actor)]


def parent_required(actor: Actor, state: AppState) -> AppError:
    """The refusal for a parent-only action. The display and kids' phones can unlock it with
    the PIN."""
    if state.auth.has_pin and (actor.is_kiosk or actor.is_kid_device):
        return AppError(403, "parent_required", "api.auth.parent_pin", extra={"pin": True})
    return AppError(403, "parent_required", "api.auth.parent_only", extra={"pin": False})


def parent_refusal(actor: Actor) -> AppError:
    """``parent_required`` for code that can't see the app's state (plugins). A device that
    isn't a parent's is a wall screen or a kid's phone only while the household has a PIN, so
    the PIN is on offer exactly then."""
    if actor.is_kiosk or actor.is_kid_device:
        return AppError(403, "parent_required", "api.auth.parent_pin", extra={"pin": True})
    return AppError(403, "parent_required", "api.auth.parent_only", extra={"pin": False})


async def current_parent(actor: ActorDep, state: StateDep) -> Actor:
    if not actor.is_parent:
        raise parent_required(actor, state)
    return actor


ParentDep = Annotated[Actor, Depends(current_parent)]
