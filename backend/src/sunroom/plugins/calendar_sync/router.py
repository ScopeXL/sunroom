"""calendar_sync's routes, under /api/calendar-sync (PLAN §11.2). Every route answers 404
plugin_disabled while the plugin is off (the framework gates them)."""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from typing import TYPE_CHECKING

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from sunroom.auth.deps import ActorDep, ParentDep
from sunroom.calendar.synced import SyncedEvent, SyncedSeries
from sunroom.core.errors import AppError
from sunroom.domain.recurrence import Timing
from sunroom.plugins.calendar_sync import google_accounts, service
from sunroom.plugins.calendar_sync.engine import SyncEngine
from sunroom.plugins.calendar_sync.models import AuthMode, Provider
from sunroom.plugins.calendar_sync.providers.base import ErrorKind
from sunroom.plugins.calendar_sync.providers.fake import FAKE_REMOTES, FakeRemote
from sunroom.plugins.calendar_sync.schemas import (
    AccountOut,
    AccountPatch,
    AuthorizeOut,
    CaldavIn,
    FakeScript,
    GoogleCalendarIn,
    GoogleStartIn,
    HelperIn,
    HolidaysIn,
    IcsIn,
    MappingIn,
    Place,
    ReconnectIn,
    RunOut,
)
from sunroom.plugins.context import PluginContext

if TYPE_CHECKING:
    from sunroom.plugins.calendar_sync.plugin import CalendarSync


def build(router: APIRouter, plugin: CalendarSync) -> None:
    def ctx() -> PluginContext:
        if plugin.ctx is None:
            raise AppError(503, "starting", "api.sync.starting")
        return plugin.ctx

    def engine() -> SyncEngine:
        if plugin.engine is None:
            raise AppError(503, "starting", "api.sync.starting")
        return plugin.engine

    @router.get("/accounts")
    async def accounts(actor: ActorDep) -> list[AccountOut]:  # pyright: ignore[reportUnusedFunction]
        return await service.list_accounts(ctx(), plugin.engine)

    @router.get("/holidays/places")
    async def holiday_places(actor: ActorDep) -> list[Place]:  # pyright: ignore[reportUnusedFunction]
        return service.places()

    @router.post("/accounts/ics", status_code=201)
    async def add_ics(body: IcsIn, actor: ParentDep) -> AccountOut:  # pyright: ignore[reportUnusedFunction]
        return await service.add_ics(ctx(), plugin.engine, body, actor.member_id)

    @router.post("/accounts/holidays", status_code=201)
    async def add_holidays(body: HolidaysIn, actor: ParentDep) -> AccountOut:  # pyright: ignore[reportUnusedFunction]
        return await service.add_holidays(ctx(), plugin.engine, body, actor.member_id)

    @router.post("/accounts/caldav", status_code=201)
    async def add_caldav(body: CaldavIn, actor: ParentDep) -> AccountOut:  # pyright: ignore[reportUnusedFunction]
        return await service.add_caldav(ctx(), plugin.engine, body, actor.member_id)

    @router.post("/accounts/google/service-account", status_code=201)
    async def add_google_helper(body: HelperIn, actor: ParentDep) -> AccountOut:  # pyright: ignore[reportUnusedFunction]
        return await google_accounts.add_helper(
            ctx(), plugin.engine, body.key_json, body.label, actor.member_id
        )

    @router.post("/accounts/{account_id}/google/add-calendar")
    async def add_google_calendar(  # pyright: ignore[reportUnusedFunction]
        account_id: str, body: GoogleCalendarIn, actor: ParentDep
    ) -> AccountOut:
        return await google_accounts.add_calendar(
            ctx(), plugin.engine, account_id, body.calendar_id
        )

    @router.post("/accounts/google/start")
    async def google_start(  # pyright: ignore[reportUnusedFunction]
        request: Request, body: GoogleStartIn, actor: ParentDep
    ) -> AuthorizeOut:
        url = await google_accounts.start(ctx(), _origin(request), actor.device_id, body.account_id)
        return AuthorizeOut(authorize_url=url)

    @router.get("/google/callback", include_in_schema=False)
    async def google_callback(  # pyright: ignore[reportUnusedFunction]
        request: Request,
        code: str | None = None,
        state: str | None = None,
        error: str | None = None,
    ) -> RedirectResponse:
        target = await google_accounts.callback(
            ctx(), plugin.engine, _origin(request), code=code, state=state, error=error
        )
        return RedirectResponse(target, status_code=303)

    @router.get("/accounts/{account_id}/runs")
    async def account_runs(account_id: str, actor: ParentDep) -> list[RunOut]:  # pyright: ignore[reportUnusedFunction]
        return await service.runs(ctx(), account_id)

    @router.put("/accounts/{account_id}/calendars/{row_id}")
    async def map_calendar(  # pyright: ignore[reportUnusedFunction]
        account_id: str, row_id: str, body: MappingIn, actor: ParentDep
    ) -> AccountOut:
        return await service.map_calendar(ctx(), plugin.engine, account_id, row_id, body)

    @router.post("/accounts/{account_id}/sync")
    async def sync_now(account_id: str, actor: ParentDep) -> AccountOut:  # pyright: ignore[reportUnusedFunction]
        return await service.sync_now(ctx(), engine(), account_id)

    @router.patch("/accounts/{account_id}")
    async def patch_account(  # pyright: ignore[reportUnusedFunction]
        account_id: str, body: AccountPatch, actor: ParentDep
    ) -> AccountOut:
        return await service.patch_account(ctx(), plugin.engine, account_id, body)

    @router.post("/accounts/{account_id}/reconnect")
    async def reconnect(  # pyright: ignore[reportUnusedFunction]
        account_id: str, body: ReconnectIn, actor: ParentDep
    ) -> AccountOut:
        return await plugin.reconnect(account_id, body)

    @router.delete("/accounts/{account_id}", status_code=204)
    async def disconnect(account_id: str, actor: ParentDep) -> None:  # pyright: ignore[reportUnusedFunction]
        await service.disconnect(ctx(), account_id)

    plugin.register_provider_routes(router, ctx, engine)

    # ---- the test server's scripted calendar server ----------------------------------------

    # Like the core's /api/_test routes: open on the test server, absent everywhere else.
    @router.post("/_test/fake", status_code=201)
    async def add_fake() -> AccountOut:  # pyright: ignore[reportUnusedFunction]
        context = ctx()
        if not context.test_mode:
            raise AppError(404, "not_found", "api.testing.not_found")
        account_id = await service.save_account(
            context,
            provider=Provider.FAKE,
            auth_mode=AuthMode.NONE,
            label="Test server",
            server_url="test.invalid",
            username=None,
            secrets={},
            config=None,
            allow_private=False,
            interval_s=service.TOKEN_INTERVAL_S,
            calendars=[],
            actor_member_id=None,
        )
        FAKE_REMOTES[account_id] = FakeRemote()
        return await service.get_account(context, plugin.engine, account_id)

    @router.put("/_test/fake/{account_id}")
    async def script_fake(account_id: str, body: FakeScript) -> dict[str, int]:  # pyright: ignore[reportUnusedFunction]
        context = ctx()
        remote = FAKE_REMOTES.get(account_id)
        if not context.test_mode or remote is None:
            raise AppError(404, "not_found", "api.testing.not_found")
        for remote_id, name, read_only in body.calendars:
            remote.add_calendar(remote_id, name, read_only=read_only)
        for event in body.events:
            remote.put(event.calendar, _fake_series(event))
        for calendar, remote_id in body.removed:
            remote.remove(calendar, remote_id)
        for kind in body.fail_next:
            remote.fail_next(ErrorKind(kind))
        return {"items": sum(len(items) for items in remote.items.values())}


def _origin(request: Request) -> str:
    """This server's address as the browser reached it (scheme and host, behind the proxy's
    forwarded headers when it's trusted)."""
    return str(request.base_url).rstrip("/")


def _fake_series(event: object) -> SyncedSeries:
    from sunroom.plugins.calendar_sync.schemas import FakeEvent

    assert isinstance(event, FakeEvent)
    if event.start_date:
        start = date.fromisoformat(event.start_date)
        end = date.fromisoformat(event.end_date) if event.end_date else start
        timing = Timing(all_day=True, start_date=start, end_date=end)
    else:
        assert event.start is not None and event.end is not None
        timing = Timing(
            all_day=False,
            start_utc=event.start.astimezone(UTC),
            end_utc=event.end.astimezone(UTC),
        )
    master = SyncedEvent(
        title=event.title, timing=timing, tzid=None if timing.all_day else event.tzid
    )
    return SyncedSeries(
        uid=event.uid,
        master=master,
        rrule=event.rrule,
        updated_at=datetime.combine(date(2000, 1, 1), time(), UTC),
    )
