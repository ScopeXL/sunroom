"""Google accounts (ADR 0004, UX §6): a helper (a service account the family makes once, never
called that in the app), a calendar added to it by its ID, and Sign in with Google where Google
allows the way back (an https:// address, or the wall screen at ``localhost``).

The helper's key and a sign-in's refresh token are stored encrypted and never shown again. A
sign-in's state is single-use, lives ten minutes, and is stored only as a hash.
"""

from __future__ import annotations

import hashlib
import json
import secrets as random_secrets
from datetime import timedelta
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import select

from sunroom.core.errors import AppError
from sunroom.plugins.calendar_sync import service
from sunroom.plugins.calendar_sync.engine import SyncEngine, secrets_of
from sunroom.plugins.calendar_sync.models import (
    AccountStatus,
    AuthMode,
    OAuthState,
    Provider,
    RemoteCalendarRow,
    SyncAccount,
)
from sunroom.plugins.calendar_sync.providers.base import ErrorKind, RemoteCalendar, SyncError
from sunroom.plugins.calendar_sync.providers.google import (
    GoogleClient,
    OAuthAuth,
    ServiceAccountAuth,
    authorize_url,
    exchange_code,
    new_pkce,
    parse_service_account_key,
)
from sunroom.plugins.calendar_sync.schemas import AccountOut
from sunroom.plugins.context import PluginContext

STATE_TTL = timedelta(minutes=10)
CALLBACK_PATH = "/api/calendar-sync/google/callback"
NEEDS_KEYS = (
    "Sign in with Google needs your Google app's client ID and secret first: Settings → "
    "Features → Synced Calendars."
)
NEEDS_HTTPS = (
    "Google only signs in to apps at an https:// address. Use Share with a Sunroom helper instead."
)


def redirect_uri(origin: str) -> str:
    return origin.rstrip("/") + CALLBACK_PATH


def sign_in_allowed(origin: str) -> bool:
    """Google accepts a redirect to https, or to localhost (ADR 0004)."""
    parts = urlsplit(origin)
    return parts.scheme == "https" or (parts.hostname or "") in {"localhost", "127.0.0.1"}


def _hash(state: str) -> str:
    return hashlib.sha256(state.encode()).hexdigest()


def _keys(ctx: PluginContext) -> tuple[str, str]:
    settings = ctx.settings()
    client_id = str(settings.get("google_client_id") or "").strip()
    client_secret = str(settings.get("google_client_secret") or "").strip()
    if not client_id or not client_secret:
        raise AppError(422, "needs_keys", NEEDS_KEYS)
    return client_id, client_secret


def auth_for(
    ctx: PluginContext, http: Any, secrets: dict[str, Any]
) -> ServiceAccountAuth | OAuthAuth:
    """The way in for a stored Google account: its helper key, or its sign-in."""
    if "key" in secrets:
        return ServiceAccountAuth(secrets["key"], http, ctx.now)
    if "refresh_token" in secrets:
        settings = ctx.settings()
        client_id = str(settings.get("google_client_id") or "")
        client_secret = str(settings.get("google_client_secret") or "")
        if not client_id or not client_secret:
            raise SyncError(ErrorKind.AUTH, NEEDS_KEYS)
        return OAuthAuth(client_id, client_secret, str(secrets["refresh_token"]), http, ctx.now)
    raise SyncError(ErrorKind.AUTH, "Sunroom needs this Google account connected again.")


def _rows(found: list[RemoteCalendar]) -> list[tuple[str, str, str | None, bool]]:
    return [(c.remote_id, c.name, c.color_hint, c.read_only) for c in found]


async def add_helper(
    ctx: PluginContext,
    engine: SyncEngine | None,
    key_json: str,
    label: str | None,
    actor_member_id: str | None,
) -> AccountOut:
    """Upload the helper's key: checked with Google, kept encrypted, its address shown once."""
    try:
        key = parse_service_account_key(key_json)
    except ValueError as exc:
        raise service.bad(str(exc), "not_a_key") from None
    http = ctx.http()
    client = GoogleClient(http, ServiceAccountAuth(key, http, ctx.now))
    try:
        found = await client.calendar_list()
    except SyncError as exc:
        raise service.failure_message(exc) from None
    email = key["client_email"]
    account_id = await service.save_account(
        ctx,
        provider=Provider.GOOGLE,
        auth_mode=AuthMode.SERVICE_ACCOUNT,
        label=label or "Google",
        server_url=None,
        username=email,
        secrets={"key": key},
        config={"helper_email": email},
        allow_private=False,
        interval_s=service.TOKEN_INTERVAL_S,
        calendars=_rows(found),
        actor_member_id=actor_member_id,
    )
    return await service.get_account(ctx, engine, account_id)


async def _client(ctx: PluginContext, account_id: str) -> GoogleClient:
    async with ctx.read() as session:
        account = await session.get(SyncAccount, account_id)
        if account is None or account.deleted_at is not None or account.provider != Provider.GOOGLE:
            raise service.not_found()
        stored = secrets_of(ctx, account)
    http = ctx.http()
    try:
        return GoogleClient(http, auth_for(ctx, http, stored))
    except SyncError as exc:
        raise service.failure_message(exc) from None


async def add_calendar(
    ctx: PluginContext, engine: SyncEngine | None, account_id: str, calendar_id: str
) -> AccountOut:
    """A calendar shared with the helper, added by its ID (the Gmail address for someone's
    main calendar); it then waits, unmapped, to be picked."""
    client = await _client(ctx, account_id)
    try:
        await client.insert_calendar(calendar_id.strip())
        found = await client.calendar_list()
    except SyncError as exc:
        raise service.failure_message(exc) from None
    await store_calendars(ctx, account_id, found)
    return await service.get_account(ctx, engine, account_id)


async def store_calendars(ctx: PluginContext, account_id: str, found: list[RemoteCalendar]) -> None:
    now = ctx.now()
    async with ctx.write() as tx:
        rows = {
            row.remote_id: row
            for row in (
                await tx.session.scalars(
                    select(RemoteCalendarRow).where(RemoteCalendarRow.account_id == account_id)
                )
            ).all()
        }
        for remote in found:
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
                row.name, row.read_only = remote.name[:200], remote.read_only
        tx.publish("sync.changed", {"account_id": account_id, "status": "connected"})


async def start(
    ctx: PluginContext, origin: str, device_id: str | None, account_id: str | None
) -> str:
    """Begin Sign in with Google; returns Google's page to send the browser to."""
    if not sign_in_allowed(origin):
        raise AppError(422, "needs_https", NEEDS_HTTPS)
    client_id, _secret = _keys(ctx)
    verifier, challenge = new_pkce()
    state = random_secrets.token_urlsafe(32)
    now = ctx.now()
    async with ctx.write() as tx:
        tx.session.add(
            OAuthState(
                state_hash=_hash(state),
                provider=Provider.GOOGLE,
                code_verifier=verifier,
                device_id=device_id,
                account_id=account_id,
                created_at=now,
                expires_at=now + STATE_TTL,
            )
        )
    return authorize_url(client_id, redirect_uri(origin), state, challenge)


async def callback(
    ctx: PluginContext,
    engine: SyncEngine | None,
    origin: str,
    *,
    code: str | None,
    state: str | None,
    error: str | None,
) -> str:
    """Google sent the browser back: where in Settings to land it, with how it went."""
    if not state:
        return "/settings/calendars?google=failed"
    now = ctx.now()
    async with ctx.write() as tx:
        found = await tx.session.get(OAuthState, _hash(state))
        if found is None or found.used_at is not None:
            return "/settings/calendars?google=expired"
        found.used_at = now
        expired = found.expires_at < now
        verifier, account_id = found.code_verifier, found.account_id
    if expired:
        return "/settings/calendars?google=expired"
    if error or not code:
        return "/settings/calendars?google=denied"
    try:
        client_id, client_secret = _keys(ctx)
        tokens = await exchange_code(
            ctx.http(), client_id, client_secret, code, verifier, redirect_uri(origin)
        )
    except SyncError, AppError:
        return "/settings/calendars?google=failed"
    refresh = str(tokens.get("refresh_token") or "")
    if not refresh:
        return "/settings/calendars?google=failed"
    http = ctx.http()
    client = GoogleClient(http, OAuthAuth(client_id, client_secret, refresh, http, ctx.now))
    try:
        calendars = await client.calendar_list()
    except SyncError:
        return "/settings/calendars?google=failed"
    if account_id is not None:
        async with ctx.write() as tx:
            account = await tx.session.get(SyncAccount, account_id)
            if account is not None and account.deleted_at is None:
                account.credentials_enc = ctx.encrypt(json.dumps({"refresh_token": refresh}))
                account.status = AccountStatus.CONNECTED
                account.consecutive_failures = 0
                account.last_error = None
                account.next_sync_at = now
        await store_calendars(ctx, account_id, calendars)
        if engine is not None:
            engine.start(account_id)
        return "/settings/calendars?google=connected"
    new_id = await service.save_account(
        ctx,
        provider=Provider.GOOGLE,
        auth_mode=AuthMode.OAUTH,
        label="Google",
        server_url=None,
        username=None,
        secrets={"refresh_token": refresh},
        config=None,
        allow_private=False,
        interval_s=service.TOKEN_INTERVAL_S,
        calendars=_rows(calendars),
        actor_member_id=None,
    )
    return f"/settings/calendars?google=connected&account={new_id}"


async def prune_states(ctx: PluginContext) -> None:
    """Sign-ins nobody finished: gone after they expire (PLAN §11.4)."""
    from sqlalchemy import delete

    async with ctx.write() as tx:
        await tx.session.execute(delete(OAuthState).where(OAuthState.expires_at < ctx.now()))
