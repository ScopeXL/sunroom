"""Immich, the first photo library (ADR 0036): a self-hosted photo server reached with an API key.

Checked against Immich's OpenAPI spec at the tags **v2.7.5** (the newest 2.x) and **v3.3.4**
(the newest release, 2026-10-20): every path, parameter and field used here is in both. What
differs from the plan's first reading, and why:

* the version comes from ``GET /api/server/version`` (``major``, ``minor``, ``patch``), which
  needs no permission; ``/api/server/about`` needs ``server.about``, which a family's key may lack;
* an album's photos come from the search (``albumIds``), as people's and tags' do: since 3.0,
  ``GET /api/albums/{id}`` no longer carries the album's ``assets``;
* a photo's size is its own ``width`` and ``height`` (EXIF's come only with ``withExif``);
* archived, hidden and locked photos are left out by ``visibility: "timeline"``, and trashed ones
  by ``withDeleted: false`` (the search has no ``isArchived`` or ``isTrashed`` filters);
* the library's photo count is ``GET /api/assets/statistics?visibility=timeline``'s ``images``
  (when the key may ask: ``asset.statistics``); the search's ``total`` counts one page.

Since 3.2.0 the search's flat filters (``personIds``, ``tagIds``, ``albumIds``, ``type``,
``visibility``, ``order``, ``page``) are deprecated in favour of a ``filter`` object and a
``cursor``. They still answer in 3.3.4 and they're all 2.x knows, so they're used here; an Immich
that drops them will need ``filter`` and ``cursor`` instead.

Any pick matches: Immich's own search means "all of these" for several people, so it's asked once
per pick and the answers merged. Every request carries the key as ``x-api-key``, which the
guarded client never lets follow a redirect to another server; nothing here logs it.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, cast
from urllib.parse import urlencode

from sunroom.core.http import FetchResult
from sunroom.core.lang import t_en
from sunroom.core.netguard import OutboundError
from sunroom.plugins.context import PluginHttp
from sunroom.plugins.screensaver.sources.base import (
    Choice,
    Choices,
    LibraryError,
    LibraryInfo,
    LibraryKind,
    Picks,
    RemotePhoto,
)

LIST_BYTES = 20 * 1024 * 1024  # a page of people, albums, tags or search results
PREVIEW_BYTES = 50 * 1024 * 1024  # one preview (about 1440 px; the store re-encodes it)
THUMB_BYTES = 5 * 1024 * 1024  # a face or a small picture
SEARCH_PAGE = 1000  # Immich's most per page
PEOPLE_PAGE = 500
MAX_PAGES = 50  # however many photos are asked for, a pick never walks further
OLDEST_MAJOR = 2
REMOTE_ID = re.compile(r"^[A-Za-z0-9-]{1,100}$")

# What Immich's failures say, by their keys in lang/en.json (ADR 0043).
AUTH = "api.photos.immich.auth"
FORBIDDEN = "api.photos.immich.forbidden"
NOT_IMMICH = "api.photos.immich.not_immich"
BAD_REPLY = "api.photos.immich.bad_reply"
GONE = "api.photos.immich.gone"

KIND = LibraryKind(
    kind="immich",
    name="Immich",
    placeholder="http://192.168.1.30:2283",
    address_hint=t_en("plugins.screensaver.libraries.immich.address_hint"),
    key_help=t_en("plugins.screensaver.libraries.immich.key_help"),
)


def _object(value: object) -> dict[str, Any]:
    return cast(dict[str, Any], value) if isinstance(value, dict) else {}


def _list(value: object) -> list[Any]:
    return cast(list[Any], value) if isinstance(value, list) else []


def _when(value: object) -> datetime | None:
    """An Immich timestamp ("2026-07-04T15:00:00.000Z") as UTC."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _size(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def photo_of(item: object) -> RemotePhoto | None:
    """A search result as a photo the screensaver may show: an image, on the timeline, not in
    the trash. ``fileCreatedAt`` is the moment it was taken, in UTC (``localDateTime`` is the
    same moment's wall time written as if it were UTC)."""
    asset = _object(item)
    photo_id = asset.get("id")
    if not isinstance(photo_id, str) or not REMOTE_ID.match(photo_id):
        return None
    if asset.get("type", "IMAGE") != "IMAGE" or asset.get("isTrashed") is True:
        return None
    if asset.get("isArchived") is True or asset.get("visibility", "timeline") != "timeline":
        return None
    taken = _when(asset.get("fileCreatedAt")) or _when(asset.get("localDateTime"))
    return RemotePhoto(photo_id, taken, _size(asset.get("width")), _size(asset.get("height")))


def newest_first(photos: list[RemotePhoto]) -> list[RemotePhoto]:
    """Newest first, the undated last; the id breaks ties so the order is the same every time."""
    floor = datetime.min.replace(tzinfo=UTC)
    return sorted(photos, key=lambda p: (p.taken_at or floor, p.id), reverse=True)


def _safe(remote_id: str | None) -> str:
    if remote_id is None or not REMOTE_ID.match(remote_id):
        raise LibraryError("not_found", GONE)
    return remote_id


class ImmichLibrary:
    kind = KIND

    async def _call(
        self,
        http: PluginHttp,
        method: str,
        url: str,
        key: str,
        path: str,
        *,
        query: Mapping[str, object] | None = None,
        body: dict[str, object] | None = None,
        max_bytes: int = LIST_BYTES,
        accept: str = "application/json",
    ) -> FetchResult:
        address = f"{url}/api{path}" + (f"?{urlencode(query)}" if query else "")
        headers = {"x-api-key": key, "Accept": accept}
        content: bytes | None = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            content = json.dumps(body).encode()
        try:
            result = await http.request(
                method, address, headers=headers, content=content, max_bytes=max_bytes
            )
        except OutboundError as exc:
            # The guard's own sentence: a home address not allowed, not found, no answer.
            code = "private_address" if exc.code == "private_address" else "unreachable"
            raise LibraryError(code, exc.key, **exc.params) from None
        if result.status == 401:
            raise LibraryError("auth", AUTH)
        if result.status == 403:
            raise LibraryError("forbidden", FORBIDDEN)
        return result

    async def _json(
        self,
        http: PluginHttp,
        method: str,
        url: str,
        key: str,
        path: str,
        *,
        query: Mapping[str, object] | None = None,
        body: dict[str, object] | None = None,
    ) -> object:
        result = await self._call(http, method, url, key, path, query=query, body=body)
        if result.status == 404:
            raise LibraryError("not_found", GONE)
        if not result.ok:
            raise LibraryError("bad_reply", BAD_REPLY)
        try:
            return json.loads(result.content)
        except ValueError:
            raise LibraryError("bad_reply", BAD_REPLY) from None

    async def check(self, http: PluginHttp, url: str, key: str) -> LibraryInfo:
        ping = await self._call(http, "GET", url, key, "/server/ping")
        try:
            pong = _object(json.loads(ping.content)).get("res") if ping.ok else None
        except ValueError:
            pong = None
        if pong != "pong":
            raise LibraryError("not_a_library", NOT_IMMICH)
        try:
            version = _object(await self._json(http, "GET", url, key, "/server/version"))
        except LibraryError as exc:
            if exc.code == "not_found":  # an Immich so old it answers elsewhere
                raise LibraryError("not_a_library", NOT_IMMICH) from None
            raise
        parts = [version.get(part) for part in ("major", "minor", "patch")]
        if not all(isinstance(part, int) for part in parts):
            raise LibraryError("bad_reply", BAD_REPLY)
        major, minor, patch = cast(list[int], parts)
        if major < OLDEST_MAJOR:
            raise LibraryError("too_old", "api.photos.immich.too_old", version=f"{major}.{minor}")
        # The key reads photos: one search, one photo (401 and 403 say what's wrong).
        await self._json(
            http, "POST", url, key, "/search/metadata", body={"type": "IMAGE", "size": 1}
        )
        count: int | None = None
        try:
            stats = _object(
                await self._json(
                    http, "GET", url, key, "/assets/statistics", query={"visibility": "timeline"}
                )
            )
            count = _size(stats.get("images"))
        except LibraryError:
            count = None  # a key without asset.statistics still works
        return LibraryInfo("Immich", f"{major}.{minor}.{patch}", count)

    async def choices(self, http: PluginHttp, url: str, key: str) -> Choices:
        people: list[Choice] = []
        unnamed = 0
        for page in range(1, MAX_PAGES + 1):
            query: dict[str, object] = {"withHidden": "false", "page": page, "size": PEOPLE_PAGE}
            answer = _object(await self._json(http, "GET", url, key, "/people", query=query))
            for item in _list(answer.get("people")):
                person = _object(item)
                person_id, name = person.get("id"), person.get("name")
                if not isinstance(person_id, str) or not REMOTE_ID.match(person_id):
                    continue
                if person.get("isHidden") is True:
                    continue
                if isinstance(name, str) and name.strip():
                    has_face = bool(person.get("thumbnailPath"))
                    people.append(Choice(person_id, name.strip(), None, has_face))
                else:
                    unnamed += 1
            if answer.get("hasNextPage") is not True:
                break
        albums: list[Choice] = []
        for item in _list(await self._json(http, "GET", url, key, "/albums")):
            album = _object(item)
            album_id, name = album.get("id"), album.get("albumName")
            if isinstance(album_id, str) and REMOTE_ID.match(album_id) and isinstance(name, str):
                count = album.get("assetCount")
                albums.append(
                    Choice(
                        album_id,
                        name.strip() or "An album with no name",
                        count if isinstance(count, int) else None,
                        bool(album.get("albumThumbnailAssetId")),
                    )
                )
        tags: list[Choice] = []
        for item in _list(await self._json(http, "GET", url, key, "/tags")):
            tag = _object(item)
            tag_id, value = tag.get("id"), tag.get("value") or tag.get("name")
            if isinstance(tag_id, str) and REMOTE_ID.match(tag_id) and isinstance(value, str):
                tags.append(Choice(tag_id, value, None, False))
        return Choices(
            people=people,
            albums=sorted(albums, key=lambda c: c.name.casefold()),
            tags=sorted(tags, key=lambda c: c.name.casefold()),
            unnamed_people=unnamed,
        )

    async def _images(
        self, http: PluginHttp, url: str, key: str, picked: dict[str, object], limit: int
    ) -> list[RemotePhoto]:
        """One search, paged, newest first, until ``limit`` photos or the last page."""
        found: list[RemotePhoto] = []
        for page in range(1, MAX_PAGES + 1):
            body: dict[str, object] = {
                **picked,
                "type": "IMAGE",
                "visibility": "timeline",
                "withDeleted": False,
                "order": "desc",
                "page": page,
                "size": min(SEARCH_PAGE, limit),
            }
            answer = _object(
                await self._json(http, "POST", url, key, "/search/metadata", body=body)
            )
            assets = _object(answer.get("assets"))
            items = _list(assets.get("items"))
            found.extend(photo for photo in map(photo_of, items) if photo is not None)
            if len(found) >= limit or not items or not assets.get("nextPage"):
                break
        return found[:limit]

    async def find(
        self, http: PluginHttp, url: str, key: str, picks: Picks, limit: int
    ) -> list[RemotePhoto]:
        if picks.empty:
            return newest_first(await self._images(http, url, key, {}, limit))[:limit]
        searches: list[dict[str, object]] = [
            *({"personIds": [_safe(person)]} for person in picks.people),
            *({"albumIds": [_safe(album)]} for album in picks.albums),
            *({"tagIds": [_safe(tag)]} for tag in picks.tags),
        ]
        found: dict[str, RemotePhoto] = {}
        for picked in searches:
            for photo in await self._images(http, url, key, picked, limit):
                found.setdefault(photo.id, photo)
        return newest_first(list(found.values()))[:limit]

    async def fetch(self, http: PluginHttp, url: str, key: str, photo_id: str) -> bytes:
        result = await self._call(
            http,
            "GET",
            url,
            key,
            f"/assets/{_safe(photo_id)}/thumbnail",
            query={"size": "preview"},
            max_bytes=PREVIEW_BYTES,
            accept="image/*",
        )
        if result.status == 404:
            raise LibraryError("not_found", GONE)
        if not result.ok or not result.content:
            raise LibraryError("bad_reply", BAD_REPLY)
        return result.content

    async def thumb(
        self, http: PluginHttp, url: str, key: str, *, person: str | None, asset: str | None
    ) -> tuple[bytes, str]:
        if person is not None:
            path, query = f"/people/{_safe(person)}/thumbnail", None
        else:
            path, query = f"/assets/{_safe(asset)}/thumbnail", {"size": "thumbnail"}
        result = await self._call(
            http, "GET", url, key, path, query=query, max_bytes=THUMB_BYTES, accept="image/*"
        )
        if result.status == 404:
            raise LibraryError("not_found", GONE)
        if not result.ok or not result.content:
            raise LibraryError("bad_reply", BAD_REPLY)
        media = result.headers.get("content-type", "").split(";")[0].strip()
        return result.content, media if media.startswith("image/") else "image/jpeg"
