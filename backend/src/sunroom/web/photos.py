"""The household's photo files, for signed-in devices only (PLAN §5.1, ADR 0009).

``/photos/{library|thumbs|avatars}/<id>.webp``. A photo's file never changes for its id (a new
picture is a new id), so it is cached for a year, privately: shared caches never keep it.
"""

from __future__ import annotations

import re

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse

from sunroom.auth.deps import read_token
from sunroom.core.errors import AppError
from sunroom.photos.store import FOLDERS
from sunroom.state import StateDep

router = APIRouter(tags=["photos"])
PHOTO_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
CACHE = {"Cache-Control": "private, max-age=31536000, immutable"}


@router.get("/photos/{folder}/{name}", include_in_schema=False)
async def photo_file(folder: str, name: str, request: Request, state: StateDep) -> FileResponse:
    if read_token(request, state) is None:
        raise AppError(401, "signed_out", "api.auth.signed_out")
    photo_id = name.removesuffix(".webp")
    if folder not in FOLDERS or not name.endswith(".webp") or not PHOTO_ID.match(photo_id):
        raise AppError(404, "not_found", "api.photos.file_not_found")
    path = state.photos.file(folder, photo_id)
    if not path.is_file():
        raise AppError(404, "not_found", "api.photos.file_not_found")
    return FileResponse(path, media_type="image/webp", headers=CACHE)
