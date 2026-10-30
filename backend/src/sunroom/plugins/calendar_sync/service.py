"""Accounts and their calendars (PLAN §8.1, §11.2, UX §6): add one, map its calendars to people,
sync it now, reconnect it, disconnect it. Secrets are typed on a phone, checked against the
server, stored encrypted, and never shown again.
"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timedelta
from typing import Any, cast

from sqlalchemy import select

from sunroom.core.errors import AppError
from sunroom.core.lang import Words
from sunroom.core.netguard import OutboundError
from sunroom.plugins.base import Problem
from sunroom.plugins.calendar_sync import addresses
from sunroom.plugins.calendar_sync.engine import SyncEngine
from sunroom.plugins.calendar_sync.ical import parse_calendar
from sunroom.plugins.calendar_sync.models import (
    AccountStatus,
    AuthMode,
    Provider,
    RemoteCalendarRow,
    SyncAccount,
    SyncRun,
)
from sunroom.plugins.calendar_sync.providers.base import ErrorKind, SyncError
from sunroom.plugins.calendar_sync.providers.holidays import HolidaysProvider, supported
from sunroom.plugins.calendar_sync.providers.ics import NOT_A_CALENDAR, IcsProvider
from sunroom.plugins.calendar_sync.schemas import (
    AccountOut,
    AccountPatch,
    HolidaysIn,
    IcsIn,
    MappingIn,
    Place,
    ReconnectIn,
    RemoteCalendarOut,
    RunOut,
)
from sunroom.plugins.context import CalendarView, MemberView, PluginContext

SYNC_NOW_EVERY = timedelta(seconds=60)
TOKEN_INTERVAL_S = 300  # CalDAV and Google: cheap token syncs every 5 minutes
HOLIDAYS_INTERVAL_S = 24 * 3600
DEFAULT_COLOR = "sea"
READ_ONLY_PROVIDERS = {Provider.ICS, Provider.HOLIDAYS}
# The allowlist rows a home-network tick writes are named after this feature (ADR 0036).
NETWORK_LABEL = "Calendars & Accounts"


def bad(key: str, code: str = "invalid", **params: object) -> AppError:
    return AppError(422, code, key, params=params)


def not_found() -> AppError:
    return AppError(404, "not_found", "api.sync.account_not_found")


# ---- what needs a parent (Needs Attention, ADR 0034) ---------------------------------------------


def account_name(account: SyncAccount) -> str:
    """What the family calls the account, as the app does (features/sync's sourceName): a
    brand's name, or the one it was given. The holidays have sentences of their own."""
    if account.provider == Provider.GOOGLE:
        return "Google"
    address = account.server_url or ""
    if "icloud.com" in address:
        return "Apple"  # iCloud, which the family knows as Apple
    if "google.com" in address:
        return "Google"
    return account.label


def problem_sentence(account: SyncAccount) -> Words:
    """One sentence for an account that stopped working, by its key (ADR 0043); when it started
    is said apart."""
    if account.status == AccountStatus.NEEDS_RECONNECT:
        if account.provider == Provider.GOOGLE:
            return Words("api.sync.google_signed_out")
        if account.provider == Provider.ICS:
            return Words("api.sync.address_stopped", {"name": account_name(account)})
        return Words("api.sync.needs_password", {"name": account_name(account)})
    if account.provider == Provider.HOLIDAYS:
        return Words("api.sync.holidays_not_answering")
    return Words("api.sync.not_answering", {"name": account_name(account)})


async def problems(ctx: PluginContext) -> list[Problem]:
    """Each live account that needs a new password or address, or hasn't answered three times
    in a row (the engine's ERROR_AFTER), with the page that fixes it."""
    async with ctx.read() as session:
        accounts = (
            await session.scalars(
                select(SyncAccount)
                .where(
                    SyncAccount.deleted_at.is_(None),
                    SyncAccount.status.in_([AccountStatus.NEEDS_RECONNECT, AccountStatus.ERROR]),
                )
                .order_by(SyncAccount.created_at)
            )
        ).all()
    return [_problem(account) for account in accounts]


def _problem(account: SyncAccount) -> Problem:
    said = problem_sentence(account)
    return Problem(
        id=f"sync:{account.id}",
        key=said.key,
        params=said.params,
        detail=account.last_error,
        # Hasn't answered: since it last did. Refused: since the refusal.
        since=(
            account.last_success_at or account.last_error_at
            if account.status == AccountStatus.ERROR
            else account.last_error_at or account.last_success_at
        ),
        page="calendars",
    )


# ---- reading -----------------------------------------------------------------------------------


async def list_accounts(ctx: PluginContext, engine: SyncEngine | None) -> list[AccountOut]:
    members = await ctx.members.active()
    calendars = {c.id: c for c in await ctx.calendar.calendars(include_removed=True)}
    async with ctx.read() as session:
        accounts = (
            await session.scalars(
                select(SyncAccount)
                .where(SyncAccount.deleted_at.is_(None))
                .order_by(SyncAccount.created_at)
            )
        ).all()
        rows = (
            await session.scalars(select(RemoteCalendarRow).order_by(RemoteCalendarRow.created_at))
        ).all()
    by_account: dict[str, list[RemoteCalendarRow]] = {}
    for row in rows:
        by_account.setdefault(row.account_id, []).append(row)
    return [
        _account_out(account, by_account.get(account.id, []), calendars, members, engine)
        for account in accounts
    ]


async def get_account(ctx: PluginContext, engine: SyncEngine | None, account_id: str) -> AccountOut:
    for account in await list_accounts(ctx, engine):
        if account.id == account_id:
            return account
    raise not_found()


def _account_out(
    account: SyncAccount,
    rows: list[RemoteCalendarRow],
    calendars: dict[str, CalendarView],
    members: list[MemberView],
    engine: SyncEngine | None,
) -> AccountOut:
    config = _config(account)
    return AccountOut.model_validate(
        {
            "id": account.id,
            "provider": account.provider,
            "label": account.label,
            "status": account.status,
            "address": account.server_url,
            "owner_member_id": account.owner_member_id,
            "interval_min": max(1, account.interval_s // 60),
            "read_only": account.provider in READ_ONLY_PROVIDERS,
            "syncing": bool(engine and engine.is_running(account.id)),
            "last_sync_at": account.last_sync_at,
            "last_success_at": account.last_success_at,
            "next_sync_at": account.next_sync_at,
            "last_error": account.last_error,
            "last_error_at": account.last_error_at,
            "helper_email": config.get("helper_email"),
            "calendars": [_remote_out(row, calendars, members) for row in rows],
        }
    )


def _remote_out(
    row: RemoteCalendarRow, calendars: dict[str, CalendarView], members: list[MemberView]
) -> RemoteCalendarOut:
    calendar = calendars.get(row.calendar_id or "")
    mapped = row.mapped and calendar is not None and not calendar.deleted
    return RemoteCalendarOut.model_validate(
        {
            "id": row.id,
            "name": row.name,
            "color_hint": row.color_hint,
            "read_only": row.read_only,
            "mapped": mapped,
            "calendar_id": row.calendar_id if mapped else None,
            "color": calendar.color if mapped and calendar else None,
            "owner_member_id": calendar.owner_member_id if mapped and calendar else None,
            "visible_on_display": calendar.visible_on_display if mapped and calendar else True,
            "last_synced_at": row.last_synced_at,
            "last_error": row.last_error,
            "suggested_owner_id": suggest_owner(row.name, members),
        }
    )


def suggest_owner(name: str, members: list[MemberView]) -> str | None:
    """A person named in a calendar's name ("Ana's calendar", "Mia school"), if exactly one."""
    words = set(re.findall(r"[\w']+", name.lower()))
    words |= {word.removesuffix("'s").removesuffix("\u2019s") for word in words}
    found = [m.id for m in members if m.name.lower() in words]
    return found[0] if len(found) == 1 else None


def _config(account: SyncAccount) -> dict[str, Any]:
    raw: object = json.loads(account.config_json or "{}")
    return cast("dict[str, Any]", raw) if isinstance(raw, dict) else {}


async def runs(ctx: PluginContext, account_id: str) -> list[RunOut]:
    async with ctx.read() as session:
        await _account(session, account_id)
        rows = (
            await session.scalars(
                select(SyncRun)
                .where(SyncRun.account_id == account_id)
                .order_by(SyncRun.started_at.desc())
                .limit(50)
            )
        ).all()
        return [RunOut.model_validate(row, from_attributes=True) for row in rows]


def places() -> list[Place]:
    return [Place(country=code, subdivisions=subs) for code, subs in sorted(supported().items())]


async def _account(session: Any, account_id: str) -> SyncAccount:
    account = await session.get(SyncAccount, account_id)
    if account is None or account.deleted_at is not None:
        raise not_found()
    return account


# ---- adding ------------------------------------------------------------------------------------


def source_label(provider: str, url: str | None = None) -> str:
    """How an event's sheet names where it came from: "From Apple · Work" (UX §4)."""
    host = addresses.host_of(url) if url else ""
    if provider == Provider.HOLIDAYS:
        return "Holidays"
    if provider == Provider.GOOGLE or host.endswith("google.com"):
        return "Google"
    if host.endswith("icloud.com"):
        return "Apple"  # iCloud, which the family knows as Apple (ADR 0032)
    if host.endswith(("outlook.com", "office365.com", "live.com")):
        return "Outlook"
    if provider == Provider.CALDAV:
        return host or "the calendar server"
    return "a calendar address"


# The pick order for a calendar everyone shares; the four colors added in 0.12.0 come last.
COLOR_ORDER = (
    "sea",
    "iris",
    "olive",
    "sky",
    "clay",
    "moss",
    "berry",
    "rose",
    "copper",
    "bark",
    "slate",
    "lime",
)


async def pick_color(ctx: PluginContext) -> str:
    """A color for a calendar everyone shares: one no person has, and if possible no other
    calendar either, so its events don't read as someone's."""
    people = {member.color for member in await ctx.members.active()}
    calendars = {calendar.color for calendar in await ctx.calendar.calendars()}
    free = [color for color in COLOR_ORDER if color not in people]
    unused = [color for color in free if color not in calendars]
    return (unused or free or [DEFAULT_COLOR])[0]


async def _check_member(ctx: PluginContext, member_id: str | None) -> MemberView | None:
    if member_id is None:
        return None
    member = await ctx.members.get(member_id)
    if member is None:
        raise bad("api.sync.unknown_member", "unknown_member")
    return member


async def add_ics(
    ctx: PluginContext, engine: SyncEngine | None, body: IcsIn, actor_member_id: str | None
) -> AccountOut:
    """Paste an address: checked, fetched once, and on the board straight away (read-only)."""
    url = addresses.normalize(body.url)
    owner = await _check_member(ctx, body.owner_member_id)
    provider = IcsProvider(ctx.http(allow_private=body.allow_private), url, "", ctx.zone)
    added = await _allow_home(ctx, url, ticked=body.allow_private)
    try:
        _status, content, cursor = await provider.fetch(None)
        parsed = await asyncio.to_thread(parse_calendar, content, ctx.zone())
    except SyncError as exc:
        await _forget_home(ctx, url, added)
        raise AppError.said(422, "address_failed", exc.words) from None
    except OutboundError as exc:
        await _forget_home(ctx, url, added)
        raise AppError.said(422, exc.code, exc.words) from None
    except ValueError:
        await _forget_home(ctx, url, added)
        raise bad(NOT_A_CALENDAR, "not_a_calendar") from None
    name = body.label or parsed.name or addresses.host_of(url) or "Calendar"
    now = ctx.now()
    calendar = await ctx.calendar.create_synced_calendar(
        name=name,
        color=body.color or (owner.color if owner else await pick_color(ctx)),
        owner_member_id=owner.id if owner else None,
        read_only=True,
        visible_on_display=True,
        source_label=source_label(Provider.ICS, url),
    )
    async with ctx.write() as tx:
        account = SyncAccount(
            provider=Provider.ICS,
            auth_mode=AuthMode.NONE,
            label=name,
            server_url=addresses.shown(url),
            credentials_enc=ctx.encrypt(json.dumps({"url": url})),
            allow_private=body.allow_private,
            owner_member_id=owner.id if owner else None,
            interval_s=body.interval_min * 60,
            created_by_member_id=actor_member_id,
            created_at=now,
        )
        tx.session.add(account)
        await tx.session.flush()
        tx.session.add(
            RemoteCalendarRow(
                account_id=account.id,
                remote_id=addresses.feed_id(url),
                name=name,
                read_only=True,
                mapped=True,
                calendar_id=calendar.id,
                sync_token=cursor,
                last_synced_at=now,
                created_at=now,
            )
        )
        account_id = account.id
    await ctx.calendar.upsert_synced(calendar.id, parsed.series, complete=True)
    await _synced_now(ctx, account_id)
    return await get_account(ctx, engine, account_id)


async def add_holidays(
    ctx: PluginContext, engine: SyncEngine | None, body: HolidaysIn, actor_member_id: str | None
) -> AccountOut:
    country = body.country.upper()
    subdivision = body.subdivision.upper() if body.subdivision else None
    places_known = supported()
    if country not in places_known:
        raise bad("api.sync.holidays.no_country", "unknown_country")
    if subdivision and subdivision not in places_known[country]:
        raise bad("api.sync.holidays.no_region", "unknown_region")
    owner = await _check_member(ctx, body.owner_member_id)
    provider = HolidaysProvider(country, subdivision, ctx.now)
    label = "Holidays · " + country + (f"-{subdivision}" if subdivision else "")
    calendar = await ctx.calendar.create_synced_calendar(
        name="Holidays",
        color=body.color or (owner.color if owner else await pick_color(ctx)),
        owner_member_id=owner.id if owner else None,
        read_only=True,
        visible_on_display=True,
        source_label=source_label(Provider.HOLIDAYS),
    )
    now = ctx.now()
    async with ctx.write() as tx:
        account = SyncAccount(
            provider=Provider.HOLIDAYS,
            auth_mode=AuthMode.NONE,
            label=label,
            config_json=json.dumps({"country": country, "subdivision": subdivision}),
            owner_member_id=owner.id if owner else None,
            interval_s=HOLIDAYS_INTERVAL_S,
            created_by_member_id=actor_member_id,
            created_at=now,
        )
        tx.session.add(account)
        await tx.session.flush()
        row = RemoteCalendarRow(
            account_id=account.id,
            remote_id=provider.remote_id(),
            name="Holidays",
            read_only=True,
            mapped=True,
            calendar_id=calendar.id,
            created_at=now,
        )
        tx.session.add(row)
        await tx.session.flush()
        account_id = account.id
    if engine is not None:
        await engine.sync_account(account_id)
    return await get_account(ctx, engine, account_id)


async def _synced_now(ctx: PluginContext, account_id: str) -> None:
    now = ctx.now()
    async with ctx.write() as tx:
        account = await _account(tx.session, account_id)
        account.status = AccountStatus.CONNECTED
        account.last_sync_at = now
        account.last_success_at = now
        account.next_sync_at = now + timedelta(seconds=account.interval_s)
        tx.publish("sync.changed", {"account_id": account_id, "status": account.status})


async def save_account(
    ctx: PluginContext,
    *,
    provider: Provider,
    auth_mode: AuthMode,
    label: str,
    server_url: str | None,
    username: str | None,
    secrets: dict[str, Any],
    config: dict[str, Any] | None,
    allow_private: bool,
    interval_s: int,
    calendars: list[tuple[str, str, str | None, bool]],  # remote id, name, color hint, read-only
    actor_member_id: str | None,
) -> str:
    """Store a newly connected account and its calendars (unmapped until someone picks them)."""
    now = ctx.now()
    async with ctx.write() as tx:
        account = SyncAccount(
            provider=provider,
            auth_mode=auth_mode,
            label=label[:120],
            server_url=server_url,
            username=username,
            credentials_enc=ctx.encrypt(json.dumps(secrets)) if secrets else None,
            config_json=json.dumps(config or {}),
            allow_private=allow_private,
            interval_s=interval_s,
            created_by_member_id=actor_member_id,
            created_at=now,
            next_sync_at=now,
        )
        tx.session.add(account)
        await tx.session.flush()
        for remote_id, name, color_hint, read_only in calendars:
            tx.session.add(
                RemoteCalendarRow(
                    account_id=account.id,
                    remote_id=remote_id,
                    name=name[:200],
                    color_hint=color_hint,
                    read_only=read_only,
                    created_at=now,
                )
            )
        tx.publish("sync.changed", {"account_id": account.id, "status": account.status})
        return account.id


def masked_user(username: str) -> str:
    """ "ana@…" for "ana@example.com": enough to tell two accounts apart."""
    local, _, domain = username.partition("@")
    return f"{local}@…" if domain else username


# ---- mapping, syncing, changing ----------------------------------------------------------------


async def map_calendar(
    ctx: PluginContext, engine: SyncEngine | None, account_id: str, row_id: str, body: MappingIn
) -> AccountOut:
    owner = await _check_member(ctx, body.owner_member_id)
    async with ctx.read() as session:
        account = await _account(session, account_id)
        row = await session.get(RemoteCalendarRow, row_id)
        if row is None or row.account_id != account_id:
            raise AppError(404, "not_found", "api.sync.calendar_not_in_account")
        provider_name, row_name, read_only = account.provider, row.name, row.read_only
        calendar_id, was_mapped = row.calendar_id, row.mapped
    label = source_label(provider_name, account.server_url)
    if body.mapped is True and not was_mapped:
        if calendar_id is not None:
            await ctx.calendar.restore_synced_calendar(calendar_id)
        else:
            created = await ctx.calendar.create_synced_calendar(
                name=row_name,
                color=body.color or (owner.color if owner else await pick_color(ctx)),
                owner_member_id=owner.id if owner else None,
                read_only=read_only or provider_name in READ_ONLY_PROVIDERS,
                visible_on_display=body.visible_on_display is not False,
                source_label=label,
            )
            calendar_id = created.id
        async with ctx.write() as tx:
            stored = await tx.session.get(RemoteCalendarRow, row_id)
            if stored is not None:
                stored.mapped = True
                stored.calendar_id = calendar_id
                stored.sync_token = None  # a full first sync
    elif body.mapped is False and was_mapped:
        if calendar_id is not None:
            await ctx.calendar.remove_synced_calendar(calendar_id)
        async with ctx.write() as tx:
            stored = await tx.session.get(RemoteCalendarRow, row_id)
            if stored is not None:
                stored.mapped = False
    if calendar_id is not None and body.mapped is not False:
        await ctx.calendar.update_synced_calendar(
            calendar_id,
            color=body.color,
            owner_member_id=owner.id if owner else None,
            clear_owner=body.clear_owner,
            visible_on_display=body.visible_on_display,
        )
    if engine is not None and body.mapped is True and not was_mapped:
        engine.start(account_id)
    return await get_account(ctx, engine, account_id)


async def sync_now(ctx: PluginContext, engine: SyncEngine, account_id: str) -> AccountOut:
    async with ctx.read() as session:
        account = await _account(session, account_id)
        last = account.last_sync_at
    if engine.is_running(account_id):
        raise AppError(409, "already_syncing", "api.sync.already_syncing")
    if last is not None and ctx.now() - last < SYNC_NOW_EVERY:
        raise AppError(429, "too_soon", "api.sync.too_soon")
    engine.start(account_id)
    return await get_account(ctx, engine, account_id)


async def patch_account(
    ctx: PluginContext, engine: SyncEngine | None, account_id: str, body: AccountPatch
) -> AccountOut:
    await _check_member(ctx, body.owner_member_id)
    async with ctx.write() as tx:
        account = await _account(tx.session, account_id)
        if body.label is not None:
            account.label = body.label
        if body.interval_min is not None:
            account.interval_s = body.interval_min * 60
            account.next_sync_at = ctx.now() + timedelta(seconds=account.interval_s)
        if body.owner_member_id is not None:
            account.owner_member_id = body.owner_member_id
        ticked = body.allow_private is not None and body.allow_private != account.allow_private
        if body.allow_private is not None:
            account.allow_private = body.allow_private
        host = _host(account.server_url)
        if body.paused is True:
            account.status = AccountStatus.PAUSED
        elif body.paused is False and account.status == AccountStatus.PAUSED:
            account.status = AccountStatus.CONNECTED
            account.next_sync_at = ctx.now()
        account.version += 1
        tx.publish("sync.changed", {"account_id": account_id, "status": account.status})
    if ticked and body.allow_private:
        await _allow_home(ctx, host, ticked=True)
    elif ticked:
        await _release_home(ctx, host)
    return await get_account(ctx, engine, account_id)


async def reconnect(
    ctx: PluginContext,
    engine: SyncEngine | None,
    account_id: str,
    body: ReconnectIn,
    check: Any = None,
) -> AccountOut:
    """A new password (or address) for an account that needs it; checked before it's kept."""
    async with ctx.read() as session:
        account = await _account(session, account_id)
        provider_name = account.provider
    secrets: dict[str, Any]
    if provider_name == Provider.ICS:
        if not body.url:
            raise bad("api.sync.paste_address")
        url = addresses.normalize(body.url)
        probe = IcsProvider(ctx.http(allow_private=account.allow_private), url, "", ctx.zone)
        # A new address on the home network: its host joins the allowlist as the tick says.
        added = await _allow_home(ctx, url, ticked=account.allow_private)
        try:
            _status, content, _cursor = await probe.fetch(None)
            await asyncio.to_thread(parse_calendar, content, ctx.zone())
        except SyncError as exc:
            await _forget_home(ctx, url, added)
            raise AppError.said(422, "address_failed", exc.words) from None
        except ValueError:
            await _forget_home(ctx, url, added)
            raise bad(NOT_A_CALENDAR, "not_a_calendar") from None
        secrets = {"url": url}
        shown = addresses.shown(url)
    else:
        if not body.app_password:
            raise bad("api.sync.type_password")
        if check is not None:
            await check(body.app_password)
        secrets = {"password": body.app_password}
        shown = account.server_url
    async with ctx.write() as tx:
        stored = await _account(tx.session, account_id)
        stored.credentials_enc = ctx.encrypt(json.dumps(secrets))
        stored.server_url = shown
        stored.status = AccountStatus.CONNECTED
        stored.consecutive_failures = 0
        stored.last_error = None
        stored.next_sync_at = ctx.now()
        if provider_name == Provider.ICS:
            # A feed is one calendar, named after its address: the row follows a new address,
            # so its person and color stay and it isn't listed twice.
            rows = (
                await tx.session.scalars(
                    select(RemoteCalendarRow).where(RemoteCalendarRow.account_id == account_id)
                )
            ).all()
            if len(rows) == 1:
                rows[0].remote_id = addresses.feed_id(secrets["url"])
                rows[0].sync_token = None
                rows[0].last_error = None
        tx.publish("sync.changed", {"account_id": account_id, "status": stored.status})
    if engine is not None:
        engine.start(account_id)
    return await get_account(ctx, engine, account_id)


async def disconnect(ctx: PluginContext, account_id: str) -> None:
    """Credentials wiped, calendars off the board (their events kept 30 days), account gone, and
    its host off the allowlist when the tick put it there and no other account needs it."""
    async with ctx.write() as tx:
        account = await _account(tx.session, account_id)
        ticked, host = account.allow_private, _host(account.server_url)
        account.credentials_enc = None
        account.deleted_at = ctx.now()
        rows = (
            await tx.session.scalars(
                select(RemoteCalendarRow).where(RemoteCalendarRow.account_id == account_id)
            )
        ).all()
        calendar_ids = [row.calendar_id for row in rows if row.mapped and row.calendar_id]
        for row in rows:
            row.mapped = False
        tx.publish("sync.changed", {"account_id": account_id, "status": "disconnected"})
    for calendar_id in calendar_ids:
        await ctx.calendar.remove_synced_calendar(calendar_id)
    if ticked:
        await _release_home(ctx, host)


# ---- the home network (PLAN §12.6, ADR 0036) -------------------------------------------------


def _host(address: str | None) -> str:
    """The server an account reaches: from its address, or from what Settings shows of a feed's
    ("nas.lan/…/school.ics")."""
    text = address or ""
    return addresses.host_of(text) if "://" in text else text.split("/", 1)[0].lower()


async def _allow_home(ctx: PluginContext, address: str, *, ticked: bool) -> bool:
    """A parent's "This server is on your home network" tick: the host joins the allowlist
    before the first check (the guard wants both the tick and the row). True when this added
    the row, so a check that fails takes it out again."""
    host = _host(address)
    if not ticked or not host:
        return False
    return await ctx.network.allow(host, NETWORK_LABEL)


async def _forget_home(ctx: PluginContext, address: str, added: bool) -> None:
    if added:
        await ctx.network.disallow(_host(address), NETWORK_LABEL)


async def _release_home(ctx: PluginContext, host: str) -> None:
    """The host leaves the allowlist once no live account here reaches it with the tick."""
    if not host:
        return
    async with ctx.read() as session:
        others = (
            await session.scalars(
                select(SyncAccount.server_url).where(
                    SyncAccount.deleted_at.is_(None), SyncAccount.allow_private.is_(True)
                )
            )
        ).all()
    if any(_host(address) == host for address in others):
        return
    await ctx.network.disallow(host, NETWORK_LABEL)


def failure_message(exc: SyncError) -> AppError:
    code = "auth_failed" if exc.kind == ErrorKind.AUTH else "unreachable"
    return AppError.said(422, code, exc.words)


def fresh(now: datetime, then: datetime | None, within: timedelta) -> bool:
    return then is not None and now - then < within


# ---- iCloud and other CalDAV servers ------------------------------------------------------------


def caldav_client(
    ctx: PluginContext, server_url: str, username: str, password: str, *, private: bool
) -> Any:
    from sunroom.plugins.calendar_sync.providers.caldav import CaldavClient

    return CaldavClient(ctx.http(allow_private=private), server_url, username, password)


async def add_caldav(
    ctx: PluginContext, engine: SyncEngine | None, body: Any, actor_member_id: str | None
) -> AccountOut:
    """Connect with an app-specific password: discovery checks it and lists the calendars,
    which wait, unmapped, for someone to pick them."""
    server_url = addresses.normalize(body.server_url)
    login = (body.username, body.app_password)
    client = caldav_client(ctx, server_url, *login, private=body.allow_private)
    added = await _allow_home(ctx, server_url, ticked=body.allow_private)
    try:
        found = await client.discover()
    except SyncError as exc:
        await _forget_home(ctx, server_url, added)
        raise failure_message(exc) from None
    except OutboundError as exc:
        await _forget_home(ctx, server_url, added)
        raise AppError.said(422, exc.code, exc.words) from None
    icloud = addresses.host_of(server_url).endswith("icloud.com")
    name = "Apple" if icloud else addresses.host_of(server_url)
    label = body.label or f"{name} · {masked_user(body.username)}"
    account_id = await save_account(
        ctx,
        provider=Provider.CALDAV,
        auth_mode=AuthMode.APP_PASSWORD,
        label=label,
        server_url=server_url,
        username=body.username,
        secrets={"password": body.app_password},
        config=None,
        allow_private=body.allow_private,
        interval_s=TOKEN_INTERVAL_S,
        calendars=[(c.remote_id, c.name, c.color_hint, c.read_only) for c in found],
        actor_member_id=actor_member_id,
    )
    return await get_account(ctx, engine, account_id)


async def check_caldav(ctx: PluginContext, account_id: str, password: str) -> None:
    """A reconnect's new password, tried before it's kept."""
    async with ctx.read() as session:
        account = await _account(session, account_id)
        server_url, username, private = (
            account.server_url or "",
            account.username or "",
            account.allow_private,
        )
    try:
        await caldav_client(ctx, server_url, username, password, private=private).discover()
    except SyncError as exc:
        raise failure_message(exc) from None
