"""The calendar_sync plugin object: its manifest, routes, jobs and events.

Its tables are its own (models.py); events and calendars live in the core and are reached only
through ``ctx.calendar`` (PLAN §6.2, §7.5).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter

from sunroom.core.lang import t_en
from sunroom.plugins.base import (
    Contributions,
    HubEvent,
    PluginBase,
    PluginManifest,
    Problem,
    SettingsSection,
)
from sunroom.plugins.calendar_sync import service
from sunroom.plugins.calendar_sync.engine import PUSH_S, TICK_S, SyncEngine
from sunroom.plugins.calendar_sync.models import EXPORT_TABLES, TABLES
from sunroom.plugins.calendar_sync.providers.factory import make_factory
from sunroom.plugins.calendar_sync.schemas import AccountOut, ReconnectIn
from sunroom.plugins.context import PluginContext
from sunroom.plugins.spec import ParamField

MANIFEST = PluginManifest(
    id="calendar_sync",
    version="1.0.0",
    name=t_en("plugins.calendar_sync.name"),
    description=t_en("plugins.calendar_sync.description"),
    settings_spec=(
        ParamField(
            "google_client_id",
            t_en("plugins.calendar_sync.settings.google_client_id.label"),
            "string",
            help=t_en("plugins.calendar_sync.settings.google_client_id.help"),
            group="Sign in with Google",
            max_length=200,
        ),
        ParamField(
            "google_client_secret",
            t_en("plugins.calendar_sync.settings.google_client_secret.label"),
            "secret",
            group="Sign in with Google",
            max_length=200,
        ),
    ),
    tables=TABLES,
    export_tables=EXPORT_TABLES,
    export_column_excluded={"sync_accounts": frozenset({"credentials_enc"})},
    contributes=Contributions(
        settings_sections=(
            SettingsSection("accounts", t_en("plugins.calendar_sync.sections.accounts")),
        ),
    ),
    default_enabled=True,
    subscribes=("events.changed",),
)


class CalendarSync(PluginBase):
    def __init__(self) -> None:
        self.manifest = MANIFEST
        self.ctx: PluginContext | None = None
        self.engine: SyncEngine | None = None
        # Providers that bring their own routes and constructors (CalDAV, Google).
        self.extra_providers: dict[str, Any] = {}
        # Google's access tokens last an hour: one way in per account, kept while its stored
        # credentials stay the same.
        self._google_auth: dict[str, tuple[str, Any]] = {}
        self.route_hooks: list[Callable[[APIRouter, Any, Any], None]] = []

    def register_routes(self, router: APIRouter) -> None:
        from sunroom.plugins.calendar_sync.router import build

        build(router, self)

    def register_provider_routes(self, router: APIRouter, ctx: Any, engine: Any) -> None:
        for hook in self.route_hooks:
            hook(router, ctx, engine)

    async def problems(self, ctx: PluginContext) -> list[Problem]:
        """An account that stopped working (Needs Attention, ADR 0034)."""
        return await service.problems(ctx)

    async def on_enable(self, ctx: PluginContext) -> None:
        self.ctx = ctx

        def caldav(account: Any, secrets: dict[str, Any], config: Any, http: Any) -> Any:
            return _caldav(ctx, account, secrets, http)

        def google(account: Any, secrets: dict[str, Any], config: Any, http: Any) -> Any:
            return _google(ctx, self._google_auth, account, secrets)

        self.extra_providers["caldav"] = caldav
        self.extra_providers["google"] = google
        self.engine = SyncEngine(ctx, make_factory(ctx, self.extra_providers))
        ctx.every("tick", TICK_S, self.engine.tick)
        ctx.every("push-sweep", PUSH_S, self.engine.push_sweep)

        async def prune() -> None:
            from sunroom.plugins.calendar_sync.google_accounts import prune_states

            await prune_states(ctx)

        ctx.every("prune", 3600, prune)

    async def on_disable(self, ctx: PluginContext) -> None:
        self.engine = None

    async def on_event(self, ctx: PluginContext, event: HubEvent) -> None:
        if event.type == "events.changed" and self.engine is not None:
            self.engine.push_soon()

    async def reconnect(self, account_id: str, body: ReconnectIn) -> AccountOut:
        assert self.ctx is not None
        ctx = self.ctx

        async def check(password: str) -> None:
            await service.check_caldav(ctx, account_id, password)

        return await service.reconnect(ctx, self.engine, account_id, body, check)


def _caldav(ctx: PluginContext, account: Any, secrets: dict[str, Any], http: Any) -> Any:
    from sunroom.plugins.calendar_sync.providers.base import ErrorKind, SyncError
    from sunroom.plugins.calendar_sync.providers.caldav import CaldavClient
    from sunroom.plugins.calendar_sync.providers.caldav_provider import CaldavProvider

    if "password" not in secrets:
        raise SyncError(ErrorKind.AUTH, "api.sync.password_again")
    client = CaldavClient(
        http, account.server_url or "", account.username or "", str(secrets["password"])
    )
    return CaldavProvider(client, ctx.zone, ctx.now)


PLUGIN = CalendarSync()


def _google(
    ctx: PluginContext, cache: dict[str, tuple[str, Any]], account: Any, secrets: dict[str, Any]
) -> Any:
    import hashlib

    from sunroom.plugins.calendar_sync.google_accounts import auth_for
    from sunroom.plugins.calendar_sync.providers.google import GoogleClient, GoogleProvider

    http = ctx.http()  # Google's hosts are public; never private
    fingerprint = hashlib.sha256((account.credentials_enc or "").encode()).hexdigest()
    cached = cache.get(account.id)
    if cached is not None and cached[0] == fingerprint:
        auth = cached[1]
    else:
        auth = auth_for(ctx, http, secrets)
        cache[account.id] = (fingerprint, auth)
    return GoogleProvider(GoogleClient(http, auth), ctx.zone, ctx.now)
