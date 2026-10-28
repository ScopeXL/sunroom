"""Health, version, diagnostics, backups and export (PLAN §11.1)."""

from __future__ import annotations

import asyncio
import ipaddress
import shutil
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from starlette.types import Receive, Scope, Send

from sunroom.auth.deps import ParentDep
from sunroom.auth.service import check_rate, client_ip, password_ok
from sunroom.core.errors import AppError
from sunroom.core.logging import get_logger
from sunroom.core.version import build_info
from sunroom.db import full_backup, migrate
from sunroom.db.backup import BackupBusyError, BackupError, NoRoomError
from sunroom.db.export import export_data
from sunroom.meta.erase import erase_everything
from sunroom.state import AppState, StateDep
from sunroom.web.hosts import host_name, is_ip_literal

router = APIRouter(prefix="/api", tags=["meta"])
log = get_logger(__name__)


def _phone_can_use(host: str) -> bool:
    """Loopback names reach the server only from the server itself, never from a phone."""
    name = host_name(host)
    if name == "localhost" or name.endswith(".localhost"):
        return False
    return not (is_ip_literal(name) and ipaddress.ip_address(name).is_loopback)


class VersionOut(BaseModel):
    version: str
    revision: str
    created: str | None


class HealthOut(BaseModel):
    status: str


class LiveUpdatesInfo(BaseModel):
    connections: int
    epoch: str


class ClientInfo(BaseModel):
    """How this device reaches Sunroom: About's URL (ADR 0034)."""

    scheme: str
    host: str


class BackupFileOut(BaseModel):
    """One copy on the server (ADR 0034): a nightly one, the one before an upgrade, the one
    Erase everything kept, or the database a restore moved aside."""

    name: str
    kind: Literal["nightly", "pre-migrate", "pre-erase", "pre-restore"]
    made_at: str
    bytes: int


class BackupStatusOut(BaseModel):
    directory: str
    schedule: str
    retention: str
    enabled: bool  # a copy every night (Settings → Backup)
    keep_daily: int
    keep_weekly: int
    busy: bool  # a copy is being written: none can be removed until it's done
    last_success_at: str | None
    last_error: str | None
    stale: bool
    files: list[BackupFileOut]  # newest first


class BackupRunOut(BaseModel):
    file: str
    bytes: int
    seconds: float


class PluginInfo(BaseModel):
    id: str
    status: str
    error: str | None


class StorageInfo(BaseModel):
    free_bytes: int
    total_bytes: int


class DiagnosticsOut(BaseModel):
    version: str
    revision: str
    schema_revision: str | None
    install_kind: str
    timezone: str
    live_updates: LiveUpdatesInfo
    client: ClientInfo
    recent_addresses: list[str]
    backups: BackupStatusOut
    plugins: list[PluginInfo]
    storage: StorageInfo


@router.get("/health", responses={503: {"model": HealthOut}})
async def health(state: StateDep, response: Response) -> HealthOut:
    if not state.started:
        response.status_code = 503
        return HealthOut(status="starting")
    try:
        async with state.db.read() as db:
            await db.execute(text("SELECT 1"))
    except Exception:
        response.status_code = 503
        return HealthOut(status="database unavailable")
    return HealthOut(status="ok")


@router.get("/version")
async def version() -> VersionOut:
    info = build_info()
    return VersionOut(version=info.version, revision=info.revision, created=info.created)


@router.get("/admin/diagnostics")
async def diagnostics(request: Request, state: StateDep, actor: ParentDep) -> DiagnosticsOut:
    info = build_info()
    headers = request.headers
    usage = shutil.disk_usage(state.settings.data_dir)
    return DiagnosticsOut(
        version=info.version,
        revision=info.revision,
        schema_revision=migrate.current_revision(state.settings.db_path),
        install_kind=state.settings.sunroom_install_kind.value,
        timezone=state.zone().key,
        live_updates=LiveUpdatesInfo(connections=state.hub.connection_count, epoch=state.hub.epoch),
        client=ClientInfo(scheme=request.url.scheme, host=headers.get("host", "")),
        recent_addresses=[host for host in reversed(state.recent_hosts) if _phone_can_use(host)],
        backups=BackupStatusOut.model_validate(state.backups.status()),
        plugins=[
            PluginInfo(
                id=plugin_id,
                status=state.plugins.status(plugin_id).value,
                error=state.plugins.error(plugin_id),
            )
            for plugin_id in state.plugins.registry
        ],
        storage=StorageInfo(free_bytes=usage.free, total_bytes=usage.total),
    )


@router.get("/admin/backups")
async def backups(state: StateDep, actor: ParentDep) -> BackupStatusOut:
    return BackupStatusOut.model_validate(state.backups.status())


@router.post("/admin/backups/run")
async def run_backup(state: StateDep, actor: ParentDep) -> BackupRunOut:
    try:
        result = await state.backups.run_now()
    except Exception as exc:
        raise AppError(500, "backup_failed", f"The backup didn't complete: {exc}") from exc
    return BackupRunOut(file=result.path.name, bytes=result.bytes, seconds=result.seconds)


class FullBackupResponse(StreamingResponse):
    """The zip as the worker writes it. However the response ends (done, failed, or the phone
    gone away), the worker stops and the database copy goes."""

    media_type = "application/zip"

    def __init__(self, download: full_backup.FullBackupStream, filename: str) -> None:
        super().__init__(
            download.chunks(),
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Cache-Control": "no-store",
            },
        )
        self.download = download

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            self.download.close()


class FreshCopyResponse(FileResponse):
    """A copy made for one download (Data Only): it goes however the response ends."""

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            await asyncio.to_thread(Path(self.path).unlink, missing_ok=True)


async def _fresh_copy(state: AppState) -> Path:
    """A verified copy of the database made now, for one download (under backups/.download/)."""
    try:
        return await asyncio.to_thread(
            full_backup.make_database_copy, state.settings.db_path, state.settings.backup_dir
        )
    except NoRoomError as exc:
        raise AppError(
            507,
            "storage_full",
            "There isn't enough free space on the server to make the download. Free some space, "
            "then try again.",
        ) from exc
    except Exception as exc:
        log.error("backup.download_failed", reason=f"{type(exc).__name__}: {exc}")
        raise AppError(
            500, "backup_failed", "The download couldn't be made. Try again in a minute."
        ) from exc


# Before /admin/backups/{name}, which would otherwise take "full.zip" as a name.
@router.get(
    "/admin/backups/full.zip",
    status_code=200,  # FastAPI would look for it in the response class's __init__
    response_class=FullBackupResponse,
    responses={507: {"description": "Not enough free space for the database copy"}},
)
async def download_everything(state: StateDep, actor: ParentDep) -> FullBackupResponse:
    """Download everything (PLAN §13.7): the database, the photos and a manifest in one zip,
    streamed as it is written. Settings → Backup calls it Data & Photos."""
    now = state.clock.now()
    copy = await _fresh_copy(state)
    download = full_backup.FullBackupStream(
        db_copy=copy,
        photos_root=state.photos.root,
        app_version=build_info().version,
        created_at=now,
        zone=state.zone(),
    )
    return FullBackupResponse(download, full_backup.zip_name(now.astimezone(state.zone()).date()))


# Before /admin/backups/{name} too: "data.db" is no copy's name.
@router.get(
    "/admin/backups/data.db",
    status_code=200,
    response_class=FreshCopyResponse,
    responses={507: {"description": "Not enough free space for the database copy"}},
)
async def download_data(state: StateDep, actor: ParentDep) -> FreshCopyResponse:
    """Data Only (Settings → Backup → Download, ADR 0034): a checked copy of the database made
    now, not the newest nightly one, so it holds what was added today."""
    copy = await _fresh_copy(state)
    day = state.clock.now().astimezone(state.zone()).date()
    return FreshCopyResponse(
        copy,
        media_type="application/vnd.sqlite3",
        filename=f"sunroom-{day.isoformat()}.db",
        headers={"Cache-Control": "no-store"},
    )


def _located(state: AppState, name: str) -> Path:
    copy = state.backups.locate(name)
    if copy is None:
        raise AppError(404, "not_found", "That backup doesn't exist.")
    return copy.path


@router.get("/admin/backups/{name}")
async def download_backup(name: str, state: StateDep, actor: ParentDep) -> FileResponse:
    """One copy on the server, any of the four kinds."""
    return FileResponse(
        _located(state, name),
        media_type="application/vnd.sqlite3",
        filename=name,
        headers={"Cache-Control": "no-store"},
    )


@router.delete("/admin/backups/{name}", status_code=204)
async def remove_backup(name: str, state: StateDep, actor: ParentDep) -> None:
    """Remove one copy (ADR 0034). Never from a paired screen, as Erase everything: it can't be
    undone, it's never urgent, and a parent's grant outlives the parent at the wall."""
    if actor.is_kiosk:
        raise AppError(403, "not_on_a_screen", "Remove backups from a signed-in device.")
    try:
        await state.backups.remove(name)
    except LookupError as exc:
        raise AppError(404, "not_found", "That backup doesn't exist.") from exc
    except BackupBusyError as exc:
        raise AppError(
            409, "backup_busy", "A backup is being written. Try again in a moment."
        ) from exc


class EraseIn(BaseModel):
    password: Annotated[str, Field(min_length=1, max_length=200)]


class EraseOut(BaseModel):
    ok: bool = True


@router.post("/admin/erase")
async def erase(body: EraseIn, request: Request, state: StateDep, actor: ParentDep) -> EraseOut:
    """Erase everything and start over (meta/erase.py, ADR 0029): a parent, on a signed-in
    device, with the household password. Never from a paired screen, which a child can reach.
    The password is checked as at sign-in, wrong tries counting against the same limiter."""
    if actor.is_kiosk:
        raise AppError(
            403, "not_on_a_screen", "Erase everything from a signed-in device, not a paired screen."
        )
    ip = client_ip(request)
    check_rate(state.login_limiter, ip)
    async with state.db.read() as db:
        matched = await password_ok(state, db, body.password)
    if not matched:
        state.login_limiter.record_failure(ip)
        log.info("erase.wrong_password")
        raise AppError(403, "wrong_password", "That password didn't match. Try again.")
    state.login_limiter.record_success(ip)
    try:
        await erase_everything(state)
    except BackupError as exc:
        raise AppError(
            500,
            "backup_failed",
            f"Nothing was erased: the copy to keep first couldn't be made ({exc}).",
        ) from exc
    return EraseOut()


class PasswordCheckIn(BaseModel):
    password: Annotated[str, Field(min_length=1, max_length=200)]


@router.post("/admin/password/check", status_code=204)
async def check_password(
    body: PasswordCheckIn, request: Request, state: StateDep, actor: ParentDep
) -> None:
    """The household password, asked before something that can't be undone happens off this
    server: a wall screen uninstalling Sunroom and the family's data from the computer it runs on
    (This Screen's Uninstall, ADR 0042). A parent's (on a wall, behind the PIN), checked as at
    sign-in, wrong tries counting against the same limiter."""
    ip = client_ip(request)
    check_rate(state.login_limiter, ip)
    async with state.db.read() as db:
        matched = await password_ok(state, db, body.password)
    if not matched:
        state.login_limiter.record_failure(ip)
        log.info("password_check.wrong_password")
        raise AppError(403, "wrong_password", "That password didn't match. Try again.")
    state.login_limiter.record_success(ip)


@router.get("/export")
async def export(state: StateDep, actor: ParentDep) -> dict[str, Any]:
    async with state.db.read() as db:
        return await export_data(
            db,
            plugins=state.plugins.registry,
            app_version=build_info().version,
            schema_revision=migrate.current_revision(state.settings.db_path),
            exported_at=state.clock.now(),
        )
