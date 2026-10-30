"""Settings → Backup → Restore from a File (ADR 0034; docs/RESTORE.md).

A parent on a signed-in device sends a backup (a .db, or the zip from Data & Photos), sees what
it holds, and types the household password; Sunroom then says ``server.restarting`` on the live
stream, stops its plugins and jobs, and runs itself again, and boot puts the copy in place
(db/restore.py). Never from a paired screen, which a child can reach: like Erase everything,
it replaces everything, and nothing is urgent about it.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import shutil
from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Any, BinaryIO, Literal
from urllib.parse import unquote

from fastapi import APIRouter, BackgroundTasks, Request
from pydantic import BaseModel, Field

from sunroom.auth.deps import Actor, ParentDep
from sunroom.auth.service import check_rate, client_ip, password_ok
from sunroom.core.errors import AppError
from sunroom.core.logging import get_logger
from sunroom.db import restore
from sunroom.state import AppState, StateDep

router = APIRouter(prefix="/api/admin/restore", tags=["meta"])
log = get_logger(__name__)

WRITE_BYTES = 1024 * 1024  # what arrives is written to the disk a megabyte at a time
RESTART_AFTER_S = 0.2  # the answer and the stream's frame leave first
STOP_WAIT_S = 10.0


class RestoreSummaryOut(BaseModel):
    """What the chosen file holds (Restore from a File?)."""

    file_name: str
    kind: Literal["db", "zip"]
    bytes: int
    app_version: str | None  # the Sunroom that made it, when it says
    schema_revision: str
    needs_upgrade: bool  # older than this Sunroom: brought up to date after the restore
    created_at: str | None  # when a zip was made; a .db doesn't say
    row_counts: dict[str, int]
    photo_files: int


class RestoreOutcomeOut(BaseModel):
    """How the last restore went (it's applied as Sunroom starts again)."""

    ok: bool
    at: str
    file_name: str | None
    problem: str | None
    previous: str | None  # the copy kept of the data from before it
    photos: str | None


class RestoreStateOut(BaseModel):
    staged: RestoreSummaryOut | None
    last: RestoreOutcomeOut | None


class RestoreApplyIn(BaseModel):
    password: Annotated[str, Field(min_length=1, max_length=200)]


class RestoreApplyOut(BaseModel):
    ok: bool = True


def _on_a_device(actor: Actor) -> None:
    if actor.is_kiosk:
        raise AppError(403, "not_on_a_screen", "api.restore.not_on_a_screen")


def _refused(problem: restore.RestoreError) -> AppError:
    if problem.code == "no_room":
        return AppError(507, "storage_full", problem.key, params=problem.params)
    return AppError(422, problem.code, problem.key, params=problem.params)


def _shown_name(header: str | None) -> str:
    """The file's own name, as the phone sent it: no folders, nothing unprintable."""
    name = unquote(header or "").replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(char for char in name if char.isprintable()).strip()
    return name[:120] or "the file"


def _summary(summary: restore.Summary) -> RestoreSummaryOut:
    return RestoreSummaryOut.model_validate(asdict(summary))


@router.get("")
async def restore_state(state: StateDep, actor: ParentDep) -> RestoreStateOut:
    _on_a_device(actor)
    staged = await asyncio.to_thread(restore.staged, state.settings)
    last = await asyncio.to_thread(restore.last_outcome, state.settings)
    return RestoreStateOut(
        staged=_summary(staged) if staged else None,
        last=RestoreOutcomeOut.model_validate(asdict(last)) if last else None,
    )


def _close(handle: BinaryIO) -> None:
    handle.flush()
    os.fsync(handle.fileno())
    handle.close()


async def _receive(request: Request, upload: Path, size: int) -> None:
    """The body, straight to the disk a megabyte at a time: never all of it in memory."""
    await asyncio.to_thread(upload.parent.mkdir, parents=True, exist_ok=True)
    handle = await asyncio.to_thread(upload.open, "wb")
    received = 0
    pending = bytearray()
    try:
        async for chunk in request.stream():
            received += len(chunk)
            if received > size:
                raise AppError(400, "upload_too_long", "api.restore.upload_too_long")
            pending += chunk
            if len(pending) >= WRITE_BYTES:
                await asyncio.to_thread(handle.write, bytes(pending))
                pending.clear()
        if pending:
            await asyncio.to_thread(handle.write, bytes(pending))
        await asyncio.to_thread(_close, handle)
    except BaseException:
        handle.close()
        await asyncio.to_thread(upload.unlink, missing_ok=True)
        raise
    if received != size:
        await asyncio.to_thread(upload.unlink, missing_ok=True)
        raise AppError(400, "upload_incomplete", "api.restore.upload_incomplete")


@router.post(
    "",
    responses={
        411: {"description": "No Content-Length"},
        507: {"description": "Not enough free space"},
    },
)
async def stage_upload(request: Request, state: StateDep, actor: ParentDep) -> RestoreSummaryOut:
    """The file itself is the body (as a photo upload's is), with its name in X-Filename. It is
    checked and kept, ready to restore; nothing changes yet."""
    _on_a_device(actor)
    length = request.headers.get("content-length", "")
    if not length.isdigit():
        raise AppError(411, "length_required", "api.restore.length_required")
    size = int(length)
    free = (await asyncio.to_thread(shutil.disk_usage, state.settings.data_dir)).free
    if free < 2 * size + restore.ROOM_TO_SPARE:
        raise AppError(507, "storage_full", "api.restore.no_room_upload")
    if state.restore_lock.locked():
        raise AppError(409, "restore_busy", "api.restore.busy")
    async with state.restore_lock:
        upload = restore.stage_dir(state.settings) / restore.UPLOAD
        await _receive(request, upload, size)
        name = _shown_name(request.headers.get("x-filename"))
        try:
            summary = await asyncio.to_thread(restore.stage, state.settings, upload, name)
        except restore.RestoreError as problem:
            log.info("restore.refused", code=problem.code)
            raise _refused(problem) from problem
    return _summary(summary)


@router.delete("", status_code=204)
async def discard(state: StateDep, actor: ParentDep) -> None:
    """Keep everything: the file sent is forgotten."""
    _on_a_device(actor)
    async with state.restore_lock:
        await asyncio.to_thread(restore.discard, state.settings)


async def _restart_soon(state: AppState) -> None:
    """After the answer: the health check says "starting" from now on (so a waiting page sees
    the server go), the plugins and jobs stop, and with no write half done Sunroom runs itself
    again (boot.reexec). Boot applies the restore."""
    state.started = False
    await asyncio.sleep(RESTART_AFTER_S)
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(state.plugins.stop_all(), STOP_WAIT_S)
    await state.jobs.stop(timeout_s=STOP_WAIT_S)
    async with state.db.write_lock:
        log.info("restore.restarting")
        state.restart()


@router.post("/apply")
async def apply(
    body: RestoreApplyIn,
    request: Request,
    background: BackgroundTasks,
    state: StateDep,
    actor: ParentDep,
) -> RestoreApplyOut:
    """Restore the file sent, with the household password, checked as at sign-in and as Erase
    everything does (the same bar: what's on the server now survives only as a copy)."""
    _on_a_device(actor)
    ip = client_ip(request)
    check_rate(state.login_limiter, ip)
    async with state.db.read() as db:
        matched = await password_ok(state, db, body.password)
    if not matched:
        state.login_limiter.record_failure(ip)
        log.info("restore.wrong_password")
        raise AppError(403, "wrong_password", "api.auth.wrong_password")
    state.login_limiter.record_success(ip)
    if state.restore_lock.locked():
        raise AppError(409, "restore_busy", "api.restore.busy")
    async with state.restore_lock:
        try:
            await asyncio.to_thread(restore.arm, state.settings, state.clock.now(), actor.device_id)
        except LookupError as exc:
            raise AppError(409, "nothing_staged", "api.restore.nothing_staged") from exc
        except restore.RestoreError as problem:
            raise _refused(problem) from problem
    details: dict[str, Any] = {"reason": "restore"}
    state.hub.publish("server.restarting", details)
    log.info("restore.armed", device=actor.device_id)
    background.add_task(_restart_soon, state)
    return RestoreApplyOut()
