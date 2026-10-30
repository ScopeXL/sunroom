"""The household's photos (PLAN §11.1). The pictures themselves are served from /photos/…
(web/photos.py, signed-in devices only); these routes list, add, hide and remove them.

An upload is one picture as the request body (JPEG, PNG, WebP or HEIC, up to 15 MB): a phone
adding several sends them one after another, which keeps memory flat on a Pi.
"""

from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel
from sqlalchemy import select

from sunroom.auth.deps import ActorDep, ParentDep
from sunroom.core.errors import AppError
from sunroom.photos.models import Photo, PhotoKind
from sunroom.photos.store import MAX_UPLOAD_BYTES
from sunroom.state import StateDep

router = APIRouter(prefix="/api", tags=["photos"])

UPLOADS_PER_HOUR = 60
PAGE_SIZE = 60
LIBRARY_PREFIX = "source:"  # a photo library's photos (the screensaver plugin's sources)


class PhotoOut(BaseModel):
    id: str
    kind: Literal["library", "avatar"]
    url: str
    thumb_url: str
    width: int
    height: int
    taken_at: datetime | None
    created_at: datetime
    hidden: bool
    # Where it came from: "upload", "inbox", or "source:<id>" for a photo library's (ADR 0036).
    source_key: str


class PhotoPage(BaseModel):
    photos: list[PhotoOut]
    next_cursor: str | None


def photo_out(photo: Photo) -> PhotoOut:
    if photo.kind == PhotoKind.AVATAR:
        url = thumb = f"/photos/avatars/{photo.id}.webp"
    else:
        url, thumb = f"/photos/library/{photo.id}.webp", f"/photos/thumbs/{photo.id}.webp"
    return PhotoOut.model_validate(
        {
            "id": photo.id,
            "kind": photo.kind,
            "url": url,
            "thumb_url": thumb,
            "width": photo.width,
            "height": photo.height,
            "taken_at": photo.taken_at,
            "source_key": photo.source_key,
            "created_at": photo.created_at,
            "hidden": photo.hidden,
        }
    )


async def read_upload(request: Request) -> bytes:
    content_type = request.headers.get("content-type", "")
    if not content_type.startswith("image/"):
        raise AppError(415, "not_a_photo", "api.photos.not_a_photo")
    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > MAX_UPLOAD_BYTES:
        raise AppError(413, "too_large", "api.photos.too_big")
    data = bytearray()
    async for chunk in request.stream():
        data += chunk
        if len(data) > MAX_UPLOAD_BYTES:
            raise AppError(413, "too_large", "api.photos.too_big")
    if not data:
        raise AppError(422, "photo_unreadable", "api.photos.unreadable")
    return bytes(data)


def _check_upload_rate(uploads: dict[str, deque[datetime]], device_id: str, now: datetime) -> None:
    recent = uploads.setdefault(device_id, deque())
    while recent and now - recent[0] > timedelta(hours=1):
        recent.popleft()
    if len(recent) >= UPLOADS_PER_HOUR:
        raise AppError(429, "rate_limited", "api.photos.too_many")
    recent.append(now)


@router.get("/photos")
async def list_photos(
    state: StateDep,
    actor: ActorDep,
    kind: Literal["library", "avatar"] = "library",
    source: str | None = None,
    cursor: Annotated[str | None, Query(max_length=40)] = None,
) -> PhotoPage:
    """Newest first, a page at a time; ``cursor`` is the last id of the previous page."""
    async with state.db.read() as db:
        query = select(Photo).where(Photo.kind == kind, Photo.deleted_at.is_(None))
        if source:
            query = query.where(Photo.source_key == source)
        if cursor:
            query = query.where(Photo.id < cursor)
        rows = list(await db.scalars(query.order_by(Photo.id.desc()).limit(PAGE_SIZE + 1)))
    page = rows[:PAGE_SIZE]
    return PhotoPage(
        photos=[photo_out(photo) for photo in page],
        next_cursor=page[-1].id if len(rows) > PAGE_SIZE and page else None,
    )


@router.post("/photos", status_code=201)
async def upload_photo(request: Request, state: StateDep, actor: ActorDep) -> PhotoOut:
    _check_upload_rate(state.uploads, actor.device_id, state.clock.now())
    data = await read_upload(request)
    name = request.headers.get("x-filename")
    # Encoded before the write lock is taken: it's the slow part.
    encoded = await state.photos.encode(data, kind=PhotoKind.LIBRARY, zone=state.zone())
    async with state.db.write() as tx:
        photo = await state.photos.ingest(
            tx.session,
            data,
            kind=PhotoKind.LIBRARY,
            zone=state.zone(),
            now=state.clock.now(),
            original_name=name,
            encoded=encoded,
        )
        tx.publish("photos.changed", {"id": photo.id})
        return photo_out(photo)


@router.get("/photos/{photo_id}")
async def get_photo(photo_id: str, state: StateDep, actor: ActorDep) -> PhotoOut:
    async with state.db.read() as db:
        photo = await db.get(Photo, photo_id)
        if photo is None or photo.deleted_at is not None:
            raise AppError(404, "not_found", "api.photos.not_found")
        return photo_out(photo)


@router.delete("/photos/{photo_id}", status_code=204)
async def delete_photo(photo_id: str, state: StateDep, actor: ParentDep) -> None:
    """Removed with Undo: the row and files stay for 7 days (POST …/restore brings it back). A
    photo library's photo isn't removed one by one (its next pass would bring it back, ADR 0036):
    it's hidden, or the library is changed."""
    async with state.db.write() as tx:
        photo = await tx.session.get(Photo, photo_id)
        if photo is None or photo.deleted_at is not None:
            raise AppError(404, "not_found", "api.photos.not_found")
        if photo.source_key.startswith(LIBRARY_PREFIX):
            raise AppError(409, "from_library", "api.photos.from_library")
        photo.deleted_at = state.clock.now()
        tx.publish("photos.changed", {"id": photo.id})


@router.post("/photos/{photo_id}/restore")
async def restore_photo(photo_id: str, state: StateDep, actor: ParentDep) -> PhotoOut:
    async with state.db.write() as tx:
        photo = await tx.session.get(Photo, photo_id)
        if photo is None:
            raise AppError(404, "not_found", "api.photos.not_found")
        photo.deleted_at = None
        tx.publish("photos.changed", {"id": photo.id})
        return photo_out(photo)


@router.post("/photos/{photo_id}/hide")
async def hide_photo(
    photo_id: str, state: StateDep, actor: ParentDep, hidden: bool = True
) -> PhotoOut:
    """Hide from the screensaver (the display can hide photos but never delete them)."""
    async with state.db.write() as tx:
        photo = await tx.session.get(Photo, photo_id)
        if photo is None or photo.deleted_at is not None:
            raise AppError(404, "not_found", "api.photos.not_found")
        photo.hidden = hidden
        tx.publish("photos.changed", {"id": photo.id})
        return photo_out(photo)
