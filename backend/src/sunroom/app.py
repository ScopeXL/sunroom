"""The FastAPI application factory."""

from __future__ import annotations

import time
from collections.abc import AsyncGenerator, Callable, Mapping
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Any

import httpx
from fastapi import FastAPI
from sqlalchemy import delete, select
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from sunroom.auth import join as auth_join
from sunroom.auth.kiosk import router as kiosk_router
from sunroom.auth.ratelimit import FailureLimiter
from sunroom.auth.router import router as auth_router
from sunroom.auth.service import load_devices
from sunroom.auth.sessions import AuthState, GrantCodec, SessionCodec, pin_epoch_of
from sunroom.calendar import birthdays as calendar_birthdays
from sunroom.calendar import service as calendar_service
from sunroom.calendar.occurrences import CalendarRuntime
from sunroom.calendar.router import router as calendar_router
from sunroom.core import secretkey
from sunroom.core import updates as core_updates
from sunroom.core.clock import Clock, ShiftableClock, SystemClock
from sunroom.core.config import Settings
from sunroom.core.crypto import plugin_cipher
from sunroom.core.errors import install_error_handlers
from sunroom.core.http import GuardedHttp
from sunroom.core.logging import Redactor, get_logger
from sunroom.core.netguard import NetGuard, Resolver, system_resolve
from sunroom.core.version import build_info
from sunroom.db.backup import BackupService
from sunroom.db.engine import Database, make_database
from sunroom.events.hub import EventHub
from sunroom.events.router import router as events_router
from sunroom.household import screen
from sunroom.household import service as household_service
from sunroom.household.models import AppMeta, NetworkAllowEntry
from sunroom.household.router import router as household_router
from sunroom.meta import feedback as meta_feedback
from sunroom.meta import updates as meta_updates
from sunroom.meta.discover import router as discover_router
from sunroom.meta.restore import router as restore_router
from sunroom.meta.router import router as meta_router
from sunroom.meta.setup import router as setup_router
from sunroom.meta.testing import router as testing_router
from sunroom.photos.models import Photo
from sunroom.photos.router import router as photos_router
from sunroom.photos.store import PhotoStore
from sunroom.plugins.base import Plugin
from sunroom.plugins.context import PluginContext
from sunroom.plugins.manager import PluginManager, PluginRunner
from sunroom.plugins.registry import REGISTRY
from sunroom.plugins.router import mount_plugin_routes
from sunroom.plugins.router import router as plugins_router
from sunroom.problems.router import router as problems_router
from sunroom.state import AppState, HouseholdCache
from sunroom.web.csrf import CSRFGuard
from sunroom.web.forwarded import ForwardedHeaders
from sunroom.web.headers import SecurityHeaders
from sunroom.web.hosts import HostGuard, HostRule
from sunroom.web.photos import router as photo_files_router
from sunroom.web.spa import mount_spa, packaged_static

log = get_logger(__name__)
BACKUP_CHECK_INTERVAL_S = 600
PRUNE_INTERVAL_S = 3600
PHOTOS_RECONCILE_INTERVAL_S = 6 * 3600
AUTH_SYNC_INTERVAL_S = 5
PHOTO_KEEP_REMOVED = timedelta(days=7)


class RequestLog:
    """Logs method, path (never the query string), status and duration."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] == "/api/health":
            await self.app(scope, receive, send)
            return
        started = time.perf_counter()
        status = 500

        async def capture(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, capture)
        finally:
            if str(scope["path"]).startswith("/api/"):
                log.info(
                    "http.request",
                    method=scope["method"],
                    path=scope["path"],
                    status=status,
                    ms=round((time.perf_counter() - started) * 1000, 1),
                )


async def load_household(db: Database, settings: Settings) -> tuple[HouseholdCache, AuthState]:
    async with db.read() as session:
        home = await household_service.household(session)
        meta = await session.get(AppMeta, 1)
        members = await household_service.active_members(session)
    cache = HouseholdCache(
        zone=household_service.effective_zone(home, settings),
        setup_complete=home.onboarded_at is not None,
        password_set=settings.app_password is not None or bool(meta and meta.password_hash),
        members={member.id for member in members},
        backups=household_service.backup_policy(home),
    )
    auth = AuthState(
        epoch=meta.auth_epoch if meta else 1,
        has_pin=home.parent_pin_hash is not None,
        pin_epoch=pin_epoch_of(home.parent_pin_hash),
    )
    return cache, auth


def create_app(
    settings: Settings,
    *,
    clock: Clock | None = None,
    secret: str | None = None,
    plugins: Mapping[str, Plugin] | None = None,
    resolver: Resolver = system_resolve,
    http_transport: Callable[[], httpx.AsyncBaseTransport] | None = None,
    ping_interval_s: float = 15.0,
    restart: Callable[[], None] | None = None,
) -> FastAPI:
    """``secret`` comes from boot (APP_SECRET_KEY or the generated key file); tests and the
    OpenAPI dump pass one in or let it resolve from settings."""
    the_clock = clock or (ShiftableClock() if settings.sunroom_test_mode else SystemClock())
    registry: dict[str, Plugin] = dict(REGISTRY if plugins is None else plugins)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        secret_key = secret or secretkey.resolve(settings)
        db = make_database(settings.db_path)
        hub = EventHub(ping_interval_s=ping_interval_s)
        db.publisher = hub.publish
        household, auth = await load_household(db, settings)

        async def allowlist() -> list[str]:
            async with db.read() as session:
                return list(await session.scalars(select(NetworkAllowEntry.target)))

        guard = NetGuard(
            resolver=resolver,
            allowlist=allowlist,
            allow_private_everywhere=settings.sunroom_allow_private_urls,
        )
        http = GuardedHttp(guard, transport_factory=http_transport)
        photos = PhotoStore(settings.photos_dir)
        photos.ensure_folders()
        cipher = plugin_cipher(secret_key)
        redactor = Redactor([*settings.secret_literals(), secret_key])
        holder: dict[str, AppState] = {}
        calendar_runtime = CalendarRuntime()
        # The core's own overlay, on whatever plugins are on (ADR 0028).
        calendar_runtime.overlays[calendar_birthdays.OVERLAY] = calendar_birthdays.provider(db)

        def context_factory(
            plugin_id: str, runner: PluginRunner, settings_of: Callable[[], dict[str, Any]]
        ) -> PluginContext:
            return PluginContext(
                plugin_id=plugin_id,
                clock=the_clock,
                zone_of=lambda: holder["state"].zone(),
                settings_of=settings_of,
                sessions=db,
                publish=hub.publish,
                http=http,
                cipher=cipher,
                runner=runner,
                enabled_of=lambda other: holder["state"].plugins.is_enabled(other),
                photos=photos,
                calendar=calendar_runtime,
                test_mode=settings.sunroom_test_mode,
            )

        manager = PluginManager(
            registry,
            db=db,
            clock=the_clock,
            context_factory=context_factory,
            publish=hub.publish,
            scrub=redactor.scrub_text,
        )
        hub.listeners.append(manager.deliver)
        state = AppState(
            settings=settings,
            clock=the_clock,
            secret=secret_key,
            db=db,
            hub=hub,
            auth=auth,
            codec=SessionCodec(secret_key),
            grants=GrantCodec(secret_key),
            login_limiter=FailureLimiter(the_clock),
            pin_limiter=FailureLimiter(the_clock),
            backups=BackupService(
                db_path=settings.db_path,
                backup_dir=settings.backup_dir,
                zone_of=lambda: holder["state"].zone(),
                clock=the_clock,
                policy_of=lambda: holder["state"].household.backups,
            ),
            http=http,
            photos=photos,
            plugins=manager,
            household=household,
            calendar=calendar_runtime,
        )
        if restart is not None:
            state.restart = restart
        holder["state"] = state
        async with db.read() as session:
            await load_devices(session, state)

        async def prune_expired() -> None:
            now = the_clock.now()
            async with db.write() as tx:
                await auth_join.prune(tx.session, now)
                removed = list(
                    await tx.session.scalars(
                        select(Photo).where(Photo.deleted_at <= now - PHOTO_KEEP_REMOVED)
                    )
                )
                for photo in removed:
                    photos.delete_files(photo)
                if removed:
                    await tx.session.execute(
                        delete(Photo).where(Photo.id.in_([p.id for p in removed]))
                    )
                await calendar_service.prune(tx.session, now)

        async def reconcile_photos() -> None:
            async with db.write() as tx:
                await photos.reconcile(tx.session)

        async def sync_auth_epoch() -> None:
            """`sunroom reset-password` runs in another process: notice its epoch bump."""
            async with db.read() as session:
                meta = await session.get(AppMeta, 1)
            if meta is not None and meta.auth_epoch != state.auth.epoch:
                state.auth.epoch = meta.auth_epoch
                hub.drop_all()
                log.info("auth.epoch_changed", effect="every device signs in again")

        state.jobs.every("nightly-backup", BACKUP_CHECK_INTERVAL_S, state.backups.tick)
        state.jobs.every("prune-expired", PRUNE_INTERVAL_S, prune_expired)
        state.jobs.every("photos-reconcile", PHOTOS_RECONCILE_INTERVAL_S, reconcile_photos)
        state.jobs.every("auth-sync", AUTH_SYNC_INTERVAL_S, sync_auth_epoch)

        async def screen_tick() -> None:
            await screen.tick(state)

        state.jobs.every("screen-schedule", screen.TICK_S, screen_tick)

        async def update_tick() -> None:
            await meta_updates.tick(state)

        state.jobs.every("update-check", core_updates.TICK_S, update_tick)
        hub.listeners.append(lambda event_type, _payload: screen.on_event(state, event_type))
        app.state.sunroom = state
        await manager.boot()
        # Events whose title decides who they're for get their people now, without waiting for
        # a change (0.12.0 flagged synced events with nobody on them; ADR 0034). Writes only
        # what changed.
        async with state.db.write() as tx:
            await calendar_service.rematch_people(tx)
        state.started = True
        log.info("app.started", version=build_info().version, revision=build_info().revision)
        try:
            yield
        finally:
            state.started = False
            hub.close()
            await manager.stop_all()
            await state.jobs.stop()
            await db.dispose()
            log.info("app.stopped")

    app = FastAPI(
        title="Sunroom",
        version="0",
        lifespan=lifespan,
        openapi_url=None,
        docs_url=None,
        redoc_url=None,
    )
    install_error_handlers(app)
    app.include_router(meta_router)
    app.include_router(discover_router)
    app.include_router(meta_updates.router)
    app.include_router(meta_feedback.router)
    app.include_router(restore_router)
    app.include_router(setup_router)
    app.include_router(auth_router)
    app.include_router(kiosk_router)
    app.include_router(household_router)
    app.include_router(screen.router)
    app.include_router(photos_router)
    app.include_router(calendar_router)
    app.include_router(plugins_router)
    app.include_router(problems_router)
    app.include_router(events_router)
    if settings.sunroom_test_mode:
        app.include_router(testing_router)
    mount_plugin_routes(app, registry)
    app.include_router(photo_files_router)
    mount_spa(app, settings.sunroom_static_dir or packaged_static())

    def note_host(host: str) -> None:
        state: AppState | None = getattr(app.state, "sunroom", None)
        if state is not None:
            state.note_host(host)

    # Outermost first: forwarded headers (real scheme, client and host) → request log →
    # security headers → the Host rule → CSRF → the app.
    app.add_middleware(CSRFGuard)
    app.add_middleware(HostGuard, rule=HostRule(settings.app_allowed_hosts), note=note_host)
    app.add_middleware(SecurityHeaders, now_ms=lambda: int(the_clock.now().timestamp() * 1000))
    app.add_middleware(RequestLog)
    app.add_middleware(ForwardedHeaders)
    return app
