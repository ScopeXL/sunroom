"""Helpers for the screensaver tests. Wednesday 2026-10-07 is today (14:00 UTC, 10:00 in New
York). Every picture is synthetic: a flat color, with made-up EXIF where a test needs some."""

from __future__ import annotations

import asyncio
import io
import os
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI
from PIL import ExifTags, Image
from sqlalchemy import select

from sunroom.plugins.context import PluginContext
from sunroom.plugins.screensaver.models import PhotoSource
from sunroom.plugins.screensaver.plugin import Screensaver
from tests.support import CSRF, state_of

Json = dict[str, Any]
Events = list[tuple[str, dict[str, Any]]]
SETTLED_S = 60  # a file copied a minute ago has finished copying
GONE: dict[str, Any] = {
    "code": "not_found",
    "message": "That photo source isn't here any more.",
    "key": "api.photos.source_gone",
    "params": {},
}


@dataclass(frozen=True, slots=True)
class Family:
    ana: str
    sam: str
    mia: str
    leo: str


def tapped(member_id: str) -> dict[str, str]:
    """A wall-screen request saying who tapped."""
    return CSRF | {"X-Sunroom-Member": member_id}


def error(response: httpx.Response) -> tuple[int, str, str]:
    body = response.json()["error"]
    return response.status_code, body["code"], body["message"]


def photo(
    color: tuple[int, int, int] = (200, 170, 90),
    size: tuple[int, int] = (64, 48),
    *,
    fmt: str = "JPEG",
    taken: str | None = None,
    gps: bool = False,
) -> bytes:
    """A synthetic picture: one color (a different color is a different photo), optionally
    with the EXIF a phone writes: when it was taken, and where (a made-up spot at sea)."""
    exif = Image.Exif()
    if taken:
        exif.get_ifd(ExifTags.IFD.Exif)[ExifTags.Base.DateTimeOriginal] = taken
    if gps:
        where = exif.get_ifd(ExifTags.IFD.GPSInfo)
        where[ExifTags.GPS.GPSLatitudeRef] = "N"
        where[ExifTags.GPS.GPSLatitude] = (1.0, 2.0, 3.0)
        where[ExifTags.GPS.GPSLongitudeRef] = "E"
        where[ExifTags.GPS.GPSLongitude] = (4.0, 5.0, 6.0)
    out = io.BytesIO()
    Image.new("RGB", size, color).save(out, fmt, exif=exif)
    return out.getvalue()


def heic(color: tuple[int, int, int] = (90, 120, 200)) -> bytes | None:
    """An iPhone-style HEIC, when this pillow-heif can write one (None otherwise)."""
    out = io.BytesIO()
    try:
        Image.new("RGB", (64, 48), color).save(out, "HEIF")
    except KeyError, OSError, ValueError:
        return None
    return out.getvalue()


def age(path: Path, seconds: float = SETTLED_S) -> None:
    """Set a file's modified time ``seconds`` ago, by the file system's clock."""
    stamp = time.time() - seconds
    os.utime(path, (stamp, stamp))


def drop(folder: Path, name: str, data: bytes, *, age_s: float = SETTLED_S) -> Path:
    """A file copied into a folder ``age_s`` seconds ago."""
    path = folder / name
    path.write_bytes(data)
    age(path, age_s)
    return path


def names(folder: Path) -> list[str]:
    """What's in a folder, by name (nothing when it isn't there)."""
    return sorted(path.name for path in folder.iterdir()) if folder.is_dir() else []


async def until(check: Callable[[], Awaitable[bool]], within_s: float = 5.0) -> None:
    deadline = asyncio.get_running_loop().time() + within_s
    while not await check():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("that never happened")
        await asyncio.sleep(0.01)


async def started(app: FastAPI, plugin: Screensaver) -> PluginContext:
    """The plugin's context, once it has started and its first look at the inbox (which runs as
    it starts) is done, so a test's own checks never overlap it."""
    state = state_of(app)

    async def ready() -> bool:
        if plugin.ctx is None:
            return False
        async with state.db.read() as session:
            checked = await session.scalar(
                select(PhotoSource.last_scan_at).where(PhotoSource.kind == "inbox")
            )
        return checked is not None

    await until(ready)
    assert plugin.ctx is not None
    return plugin.ctx


async def manifest(client: httpx.AsyncClient, headers: dict[str, str] | None = None) -> Json:
    response = await client.get("/api/screensaver/manifest", headers=headers)
    assert response.status_code == 200, response.text
    found: Json = response.json()
    return found


async def shown(client: httpx.AsyncClient) -> list[str]:
    """The ids the screensaver shows, in its order."""
    return [each["id"] for each in (await manifest(client))["photos"]]


async def all_sources(client: httpx.AsyncClient) -> list[Json]:
    response = await client.get("/api/screensaver/sources")
    assert response.status_code == 200, response.text
    found: list[Json] = response.json()
    return found


async def inbox_source(client: httpx.AsyncClient) -> Json:
    return next(each for each in await all_sources(client) if each["kind"] == "inbox")


async def scan(
    client: httpx.AsyncClient, source_id: str, headers: dict[str, str] = CSRF
) -> httpx.Response:
    return await client.post(f"/api/screensaver/sources/{source_id}/scan", headers=headers)


async def upload(client: httpx.AsyncClient, data: bytes) -> Json:
    """A photo added from a phone (the core photos API)."""
    response = await client.post(
        "/api/photos", content=data, headers=CSRF | {"content-type": "image/jpeg"}
    )
    assert response.status_code == 201, response.text
    added: Json = response.json()
    return added
