"""Helpers shared by sign-in, pairing and setup."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sunroom.auth.deps import grant_expires_at, issue_session
from sunroom.auth.models import Device, DeviceKind, PairedVia
from sunroom.auth.password import env_password_matches, verify_password
from sunroom.auth.ratelimit import FailureLimiter, wait_message
from sunroom.auth.schemas import SessionOut
from sunroom.auth.sessions import DeviceInfo
from sunroom.core.errors import AppError
from sunroom.household import service as household_service
from sunroom.household.models import AppMeta
from sunroom.state import AppState
from sunroom.web.hosts import host_name, is_ip_literal


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def check_rate(limiter: FailureLimiter, key: str) -> None:
    wait = limiter.retry_after_seconds(key)
    if wait is not None:
        raise AppError(429, "rate_limited", wait_message(wait), headers={"Retry-After": str(wait)})


async def password_ok(state: AppState, session: AsyncSession, given: str) -> bool:
    """APP_PASSWORD always wins; otherwise the password chosen in the setup wizard."""
    if state.settings.app_password is not None:
        return env_password_matches(given, state.settings.app_password)
    meta = await session.get(AppMeta, 1)
    if meta is None or meta.password_hash is None:
        return False
    return verify_password(given, meta.password_hash)


def require_setup(state: AppState) -> None:
    if not state.household.setup_complete:
        raise AppError(
            409, "setup_required", "Sunroom isn't set up yet. Open it on a device to set it up."
        )


async def new_device(
    session: AsyncSession,
    state: AppState,
    request: Request,
    response: Response,
    *,
    kind: DeviceKind,
    paired_via: PairedVia,
    label: str,
    now: datetime,
) -> Device:
    """A signed-in device and its cookie."""
    device = Device(label=label, kind=kind.value, paired_via=paired_via.value, created_at=now)
    device.last_seen_at = now
    session.add(device)
    await session.flush()
    state.auth.devices[device.id] = DeviceInfo(kind.value, None, False)
    state.auth.last_seen_written[device.id] = now
    issue_session(response, request, state, device.id)
    return device


async def session_out(
    db: AsyncSession, state: AppState, request: Request, device_id: str
) -> SessionOut:
    device = await db.get(Device, device_id)
    if device is None:
        raise AppError(401, "signed_out", "Please sign in.")
    members = await household_service.active_members(db)
    current = next((m for m in members if m.id == device.member_id), None)
    home = await household_service.household(db)
    info = state.auth.devices.get(device_id)
    expires = grant_expires_at(request, state, device_id)
    is_kiosk = device.kind == DeviceKind.KIOSK
    is_parent = (
        expires is not None
        or (not is_kiosk and not device.is_kid_device)
        or (is_kiosk and not state.auth.has_pin)
    )
    return SessionOut.model_validate(
        {
            "device_id": device_id,
            "device_kind": device.kind,
            "device_label": device.label,
            "member": household_service.member_out(current) if current else None,
            "members": [household_service.member_out(m) for m in members],
            "household_name": home.name,
            "is_parent": is_parent,
            "is_kid_device": info.is_kid_device if info else device.is_kid_device,
            "has_pin": state.auth.has_pin,
            "pin_length": home.pin_length if state.auth.has_pin else None,
            "grant_expires_at": datetime.fromtimestamp(expires, UTC) if expires else None,
        }
    )


async def load_devices(db: AsyncSession, state: AppState) -> None:
    rows = (await db.execute(select(Device))).scalars().all()
    state.auth.devices = {
        row.id: DeviceInfo(row.kind, row.member_id, row.is_kid_device) for row in rows
    }
    state.auth.revoked_devices = {row.id for row in rows if row.revoked_at is not None}


def advertised_url(state: AppState, request: Request) -> str:
    """The address to print on QR codes: the one this request used, unless it came from the
    server's own screen (localhost), where SUNROOM_ADVERTISED_URL says what phones should open."""
    host_header = request.headers.get("host", "")
    name = host_name(host_header)
    loopback = name == "localhost" or (is_ip_literal(name) and name in {"127.0.0.1", "::1"})
    if loopback and state.settings.sunroom_advertised_url:
        return state.settings.sunroom_advertised_url
    return f"{request.url.scheme}://{host_header.strip().lower()}"
