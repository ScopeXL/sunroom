"""Photo libraries (ADR 0036): connecting an Immich, its people, albums and tags, the picks, the
passes that bring its photos in and keep them in step, and what happens when it refuses its key or
stops answering. The Immich here is a pretend one (``FakeImmichServer``) behind the real guarded
client; its people, albums, tags and pictures are synthetic. No real Immich is ever reached.

Wednesday 2026-10-07 is today (14:00 UTC, 10:00 in New York)."""

from __future__ import annotations

import asyncio
import io
import json
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from PIL import Image
from sqlalchemy import select

from sunroom.app import create_app
from sunroom.core.clock import FakeClock
from sunroom.core.config import Settings
from sunroom.photos.models import Photo
from sunroom.plugins.base import Plugin
from sunroom.plugins.context import PluginContext
from sunroom.plugins.screensaver import libraries, service
from sunroom.plugins.screensaver.models import PhotoSource, PhotoSourceItem
from sunroom.plugins.screensaver.sources.fake import FakeLibrary
from sunroom.plugins.screensaver.sources.immich import ImmichLibrary
from sunroom.plugins.screensaver.sources.registry import library_for
from tests.screensaver.helpers import drop, photo
from tests.support import CSRF, state_of

KEY = "sample-key"
PUBLIC_URL = "http://photos.example.com:2283"
HOME_URL = "http://immich.home:2283"
ADDRESSES = {"photos.example.com": "93.184.216.34", "immich.home": "192.168.1.30"}
NEWEST = datetime(2026, 10, 1, 15, 0, tzinfo=UTC)
GUARD_SAYS = (
    'That address is on your home network. A parent can allow it: tick "This server is on your '
    'home network".'
)


@dataclass
class Asset:
    id: str
    number: int
    people: tuple[str, ...] = ()
    albums: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    kind: str = "IMAGE"
    visibility: str = "timeline"
    trashed: bool = False

    @property
    def taken(self) -> datetime:
        return NEWEST - timedelta(hours=self.number)

    def json(self) -> dict[str, Any]:
        taken = self.taken.isoformat().replace("+00:00", ".000Z")
        return {
            "id": self.id,
            "type": self.kind,
            "fileCreatedAt": taken,
            "localDateTime": taken,
            "visibility": self.visibility,
            "isArchived": self.visibility == "archive",
            "isTrashed": self.trashed,
            "width": 48,
            "height": 32,
        }


def picture(number: int) -> bytes:
    """A small flat picture in a color of its own. PNG, so every asset's bytes differ (flat JPEG
    colors a step apart can encode alike, and the store would take them for one photo)."""
    out = io.BytesIO()
    color = (number % 256, number // 256 % 256, 160)
    Image.new("RGB", (48, 32), color).save(out, "PNG")
    return out.getvalue()


@dataclass
class FakeImmichServer:
    """A pretend Immich 2.x: the routes Sunroom calls, with synthetic people and pictures."""

    key: str = KEY
    version: tuple[int, int, int] = (2, 7, 5)
    assets: list[Asset] = field(default_factory=list[Asset])
    refuse: int | None = None  # every request after the ping answers this status
    broken: set[str] = field(default_factory=set[str])  # assets whose preview fails
    not_immich: bool = False
    requests: list[httpx.Request] = field(default_factory=list[httpx.Request])
    people: list[dict[str, Any]] = field(
        default_factory=lambda: [
            {"id": "p-mia", "name": "Mia", "isHidden": False, "thumbnailPath": "/t/mia.jpeg"},
            {"id": "p-leo", "name": "Leo", "isHidden": False, "thumbnailPath": "/t/leo.jpeg"},
            {"id": "p-x", "name": "", "isHidden": False, "thumbnailPath": "/t/x.jpeg"},
            {"id": "p-y", "name": " ", "isHidden": False, "thumbnailPath": ""},
            {"id": "p-sam", "name": "Sam", "isHidden": True, "thumbnailPath": "/t/sam.jpeg"},
        ]
    )

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if self.not_immich:
            return httpx.Response(200, text="<html>A router's page</html>")
        if path == "/api/server/ping":
            return httpx.Response(200, json={"res": "pong"})
        if request.headers.get("x-api-key") != self.key or self.refuse == 401:
            return httpx.Response(
                401, json={"message": "Invalid API key", "error": "Unauthorized", "statusCode": 401}
            )
        if self.refuse is not None:
            return httpx.Response(self.refuse, json={"message": "No", "statusCode": self.refuse})
        major, minor, patch = self.version
        if path == "/api/server/version":
            return httpx.Response(200, json={"major": major, "minor": minor, "patch": patch})
        if path == "/api/assets/statistics":
            visibility = request.url.params.get("visibility")
            images = sum(
                1
                for a in self.assets
                if a.kind == "IMAGE" and not a.trashed and visibility in (None, a.visibility)
            )
            return httpx.Response(200, json={"images": images, "videos": 0, "total": images})
        if path == "/api/people":
            return self._people(request)
        if path == "/api/albums":
            return httpx.Response(
                200,
                json=[
                    {
                        "id": "a-beach",
                        "albumName": "Beach 2026",
                        "assetCount": 3,
                        "albumThumbnailAssetId": "r-001",
                    },
                    {
                        "id": "a-zoo",
                        "albumName": "Zoo day",
                        "assetCount": 1,
                        "albumThumbnailAssetId": None,
                    },
                ],
            )
        if path == "/api/tags":
            return httpx.Response(
                200,
                json=[
                    {"id": "t-wall", "name": "Wall", "value": "Wall"},
                    {"id": "t-fav", "name": "Favorites", "value": "Family/Favorites"},
                ],
            )
        if path == "/api/search/metadata" and request.method == "POST":
            return self._search(json.loads(request.content))
        if path.startswith("/api/assets/") and path.endswith("/thumbnail"):
            asset_id = path.split("/")[3]
            asset = next((a for a in self.assets if a.id == asset_id), None)
            if asset is None:
                return httpx.Response(404, json={"message": "Not found"})
            if asset_id in self.broken:
                return httpx.Response(500, json={"message": "Broken"})
            return httpx.Response(
                200, content=picture(asset.number), headers={"content-type": "image/png"}
            )
        if path.startswith("/api/people/") and path.endswith("/thumbnail"):
            person = path.split("/")[3]
            if not any(p["id"] == person for p in self.people):
                return httpx.Response(404, json={"message": "Not found"})
            return httpx.Response(200, content=picture(999), headers={"content-type": "image/jpeg"})
        return httpx.Response(404, json={"message": "Not found"})

    def _people(self, request: httpx.Request) -> httpx.Response:
        page = int(request.url.params.get("page", "1"))
        size = int(request.url.params.get("size", "500"))
        shown = [
            p
            for p in self.people
            if request.url.params.get("withHidden") != "false" or not p["isHidden"]
        ]
        chunk = shown[(page - 1) * size : page * size]
        return httpx.Response(
            200,
            json={
                "people": chunk,
                "total": len(shown),
                "hidden": 1,
                "hasNextPage": page * size < len(shown),
            },
        )

    def _search(self, body: dict[str, Any]) -> httpx.Response:
        found = [
            a
            for a in self.assets
            if (body.get("type") is None or a.kind == body["type"])
            and (body.get("visibility") is None or a.visibility == body["visibility"])
            and (body.get("withDeleted") or not a.trashed)
            and all(p in a.people for p in body.get("personIds", []))
            and all(t in a.tags for t in body.get("tagIds", []))
            and all(al in a.albums for al in body.get("albumIds", []))
        ]
        found.sort(key=lambda a: a.taken, reverse=body.get("order", "desc") == "desc")
        page, size = int(body.get("page", 1)), int(body.get("size", 250))
        chunk = found[(page - 1) * size : page * size]
        more = page * size < len(found)
        return httpx.Response(
            200,
            json={
                "assets": {
                    "items": [a.json() for a in chunk],
                    "total": len(chunk),
                    "count": len(chunk),
                    "facets": [],
                    "nextPage": str(page + 1) if more else None,
                },
                "albums": {"items": [], "total": 0, "count": 0, "facets": []},
            },
        )

    def searches(self) -> list[dict[str, Any]]:
        return [
            json.loads(r.content) for r in self.requests if r.url.path == "/api/search/metadata"
        ]


def family_album() -> list[Asset]:
    """Twelve photos: Mia's, Leo's, the beach album's, the wall tag's, and ones nobody picks;
    an archived photo, a trashed one and a video, which never come in."""
    return [
        Asset("r-001", 1, ("p-mia", "p-leo"), ("a-beach",)),
        Asset("r-002", 2, ("p-mia",), (), ("t-wall",)),
        Asset("r-003", 3, ("p-leo",)),
        Asset("r-004", 4, (), ("a-beach",)),
        Asset("r-005", 5, (), (), ("t-wall",)),
        Asset("r-006", 6),
        Asset("r-007", 7, ("p-mia",), ("a-beach",)),
        Asset("r-008", 8),
        Asset("r-009", 9, ("p-mia",), visibility="archive"),
        Asset("r-010", 10, ("p-mia",), trashed=True),
        Asset("r-011", 11, ("p-mia",), kind="VIDEO"),
        Asset("r-012", 12, ("p-leo",), ("a-zoo",)),
    ]


async def resolve(host: str, port: int) -> list[str]:
    if host in ADDRESSES:
        return [ADDRESSES[host]]
    raise OSError("not found")


@pytest.fixture
def immich() -> FakeImmichServer:
    return FakeImmichServer(assets=family_album())


@pytest.fixture(autouse=True)
def _no_pause(monkeypatch: pytest.MonkeyPatch) -> None:
    """A pass with work left starts the next at once here (2 s on a real server)."""
    monkeypatch.setattr(libraries, "NEXT_PASS_S", 0.0)


@pytest.fixture
async def app(
    settings: Settings, clock: FakeClock, plugins: dict[str, Plugin], immich: FakeImmichServer
) -> AsyncIterator[FastAPI]:
    application = create_app(
        settings,
        clock=clock,
        plugins=plugins,
        ping_interval_s=0.05,
        resolver=resolve,
        http_transport=lambda: httpx.MockTransport(immich.handler),
    )
    async with application.router.lifespan_context(application):
        yield application


async def connect(
    parent: httpx.AsyncClient, url: str = PUBLIC_URL, key: str = KEY, **extra: Any
) -> httpx.Response:
    body = {"kind": "immich", "url": url, "api_key": key, **extra}
    return await parent.post("/api/screensaver/libraries", json=body, headers=CSRF)


async def settled(source_id: str) -> None:
    """Until the passes a change started have finished."""
    for _tick in range(500):
        if not libraries.checking(source_id):
            return
        await asyncio.sleep(0.01)
    raise AssertionError("the library never stopped checking")


async def connected(parent: httpx.AsyncClient, **extra: Any) -> dict[str, Any]:
    response = await connect(parent, **extra)
    assert response.status_code == 201, response.text
    library: dict[str, Any] = response.json()
    await settled(library["id"])
    return library


async def library_of(parent: httpx.AsyncClient, source_id: str) -> dict[str, Any]:
    response = await parent.get(f"/api/screensaver/libraries/{source_id}")
    assert response.status_code == 200, response.text
    found: dict[str, Any] = response.json()
    return found


async def pick(parent: httpx.AsyncClient, source_id: str, **picks: list[str]) -> dict[str, Any]:
    body = {"picks": {"people": [], "albums": [], "tags": [], **picks}}
    response = await parent.patch(
        f"/api/screensaver/libraries/{source_id}", json=body, headers=CSRF
    )
    assert response.status_code == 200, response.text
    await settled(source_id)
    return await library_of(parent, source_id)


async def shown_names(app: FastAPI, source_id: str) -> list[str]:
    """The library's photos the screensaver shows, by their name in the library, newest first."""
    async with state_of(app).db.read() as session:
        rows = await session.execute(
            select(Photo.original_name)
            .where(service.VISIBLE, Photo.source_key == f"source:{source_id}")
            .order_by(Photo.taken_at.desc())
        )
        return [str(name).removesuffix(".jpg") for (name,) in rows]


async def allowlist(parent: httpx.AsyncClient) -> list[tuple[str, str]]:
    response = await parent.get("/api/network-allowlist")
    return [(row["target"], row["label"]) for row in response.json()]


def error(response: httpx.Response) -> tuple[int, str, str]:
    body = response.json()["error"]
    return response.status_code, body["code"], body["message"]


# ---- connecting --------------------------------------------------------------------------------


async def test_immich_is_the_kind_on_offer(parent: httpx.AsyncClient) -> None:
    kinds = (await parent.get("/api/screensaver/library-kinds")).json()
    assert [(k["kind"], k["name"]) for k in kinds] == [("immich", "Immich")]
    assert kinds[0]["key_help"].startswith("In Immich: Account Settings → API Keys")


async def test_connecting_keeps_it_fetches_its_choices_and_brings_every_photo_in(
    app: FastAPI, parent: httpx.AsyncClient, ctx: PluginContext, immich: FakeImmichServer
) -> None:
    response = await connect(parent, url=f"{PUBLIC_URL}/api/")
    assert response.status_code == 201, response.text
    library = response.json()
    assert (library["name"], library["url"], library["status"]) == (
        "Immich",
        PUBLIC_URL,
        "connected",
    )
    assert (library["version"], library["library_photos"]) == ("2.7.5", 9)
    assert library["picks"] == {"people": [], "albums": [], "tags": []}
    assert library["limit"] == 500
    await settled(library["id"])
    # Every image on the timeline came in, newest first; not the archived, trashed or video.
    names = await shown_names(app, library["id"])
    assert names == [
        "r-001",
        "r-002",
        "r-003",
        "r-004",
        "r-005",
        "r-006",
        "r-007",
        "r-008",
        "r-012",
    ]
    after = await library_of(parent, library["id"])
    assert (after["photo_count"], after["pending"], after["checking"]) == (9, 0, False)
    assert after["last_scan_at"] is not None and after["last_error"] is None
    manifest = (await parent.get("/api/screensaver/manifest")).json()["photos"]
    assert len(manifest) == 9
    # Dated from Immich's record (a preview has no EXIF), sized by the store.
    async with state_of(app).db.read() as session:
        first = await session.scalar(select(Photo).where(Photo.original_name == "r-001.jpg"))
    assert first is not None and first.source_key == f"source:{library['id']}"
    assert first.taken_at == NEWEST - timedelta(hours=1)
    assert (first.width, first.height) == (48, 32)
    # The key went to that server only, as x-api-key, and is never kept in the clear.
    assert {r.headers.get("x-api-key") for r in immich.requests} == {KEY}
    async with state_of(app).db.read() as session:
        source = await session.get(PhotoSource, library["id"])
    assert source is not None and source.credentials_enc and KEY not in source.credentials_enc
    assert KEY not in source.config_json
    # The choices are cached: the named people (not the hidden, nor the unnamed), albums, tags.
    choices = (await parent.get(f"/api/screensaver/libraries/{library['id']}/choices")).json()
    assert [(c["id"], c["name"]) for c in choices["people"]] == [("p-mia", "Mia"), ("p-leo", "Leo")]
    assert choices["unnamed_people"] == 2
    assert [(c["name"], c["count"]) for c in choices["albums"]] == [
        ("Beach 2026", 3),
        ("Zoo day", 1),
    ]
    assert [c["name"] for c in choices["tags"]] == ["Family/Favorites", "Wall"]
    assert choices["fetched_at"] is not None


async def test_a_home_address_needs_the_tick_which_allows_it_until_the_library_goes(
    parent: httpx.AsyncClient,
) -> None:
    refused = await connect(parent, url=HOME_URL)
    assert error(refused) == (422, "private_address", GUARD_SAYS)
    assert (await parent.get("/api/screensaver/libraries")).json() == []
    assert await allowlist(parent) == []
    library = await connected(parent, url=HOME_URL, allow_private=True)
    assert library["allow_private"] is True
    assert await allowlist(parent) == [("immich.home", "Photos & Screensaver")]
    gone = await parent.delete(f"/api/screensaver/libraries/{library['id']}", headers=CSRF)
    assert gone.status_code == 204
    assert await allowlist(parent) == []


def a_wrong_key(server: FakeImmichServer) -> None:
    server.key = "another-key"


def a_key_that_cant_read(server: FakeImmichServer) -> None:
    server.refuse = 403


def not_immich(server: FakeImmichServer) -> None:
    server.not_immich = True


def too_old(server: FakeImmichServer) -> None:
    server.version = (1, 106, 4)


@pytest.mark.parametrize(
    ("setup", "code", "message"),
    [
        (
            a_wrong_key,
            "auth",
            "Immich said that key isn't right. Make a new API key in Immich and connect again.",
        ),
        (
            a_key_that_cant_read,
            "forbidden",
            "That key can't read photos. In Immich, make a key that can read photos, albums, "
            "people and tags.",
        ),
        (
            not_immich,
            "not_a_library",
            "That address isn't an Immich server.",
        ),
        (
            too_old,
            "too_old",
            "Sunroom works with Immich 2.0 and newer; this one is 1.106.",
        ),
    ],
    ids=["a wrong key", "a key that can't read", "not immich", "too old"],
)
async def test_a_check_that_fails_says_why_and_keeps_nothing(
    parent: httpx.AsyncClient,
    immich: FakeImmichServer,
    setup: Callable[[FakeImmichServer], None],
    code: str,
    message: str,
) -> None:
    setup(immich)
    response = await connect(parent)
    assert error(response) == (422, code, message)
    assert response.json()["error"]["fields"] == ["api_key"]
    assert (await parent.get("/api/screensaver/libraries")).json() == []


async def test_an_address_that_cant_be_reached_says_the_guard_s_words(
    parent: httpx.AsyncClient,
) -> None:
    response = await connect(parent, url="http://nowhere.example.com")
    assert error(response) == (
        422,
        "unreachable",
        "That server couldn't be found. Check the address.",
    )
    bad = await connect(parent, url="ftp://photos.example.com")
    assert error(bad)[:2] == (422, "bad_address")


async def test_immich_3_answers_the_same(
    app: FastAPI, parent: httpx.AsyncClient, immich: FakeImmichServer
) -> None:
    immich.version = (3, 3, 4)
    library = await connected(parent)
    assert library["version"] == "3.3.4"
    assert len(await shown_names(app, library["id"])) == 9


# ---- the picks ---------------------------------------------------------------------------------


async def test_any_pick_matches_newest_first_up_to_keep_up_to(
    app: FastAPI, parent: httpx.AsyncClient, immich: FakeImmichServer
) -> None:
    library = await connected(parent)
    after = await pick(parent, library["id"], people=["p-leo"], albums=["a-beach"], tags=["t-wall"])
    assert after["picks"] == {"people": ["p-leo"], "albums": ["a-beach"], "tags": ["t-wall"]}
    # Leo's (1, 3, 12), the beach album (1, 4, 7) and the wall tag (2, 5), each once.
    assert await shown_names(app, library["id"]) == [
        "r-001",
        "r-002",
        "r-003",
        "r-004",
        "r-005",
        "r-007",
        "r-012",
    ]
    # One search per pick: Immich's own "personIds: [a, b]" would mean both at once.
    asked = [
        s for s in immich.searches() if any(k in s for k in ("personIds", "albumIds", "tagIds"))
    ]
    assert {
        json.dumps(s.get("personIds") or s.get("albumIds") or s.get("tagIds")) for s in asked
    } >= {
        '["p-leo"]',
        '["a-beach"]',
        '["t-wall"]',
    }
    assert all(s["visibility"] == "timeline" and s["type"] == "IMAGE" for s in asked)
    limited = await parent.patch(
        f"/api/screensaver/libraries/{library['id']}", json={"limit": 100}, headers=CSRF
    )
    assert limited.status_code == 200
    assert (
        await parent.patch(
            f"/api/screensaver/libraries/{library['id']}", json={"limit": 300}, headers=CSRF
        )
    ).status_code == 422


async def test_a_pick_taken_away_leaves_and_comes_back_without_a_fetch_and_hidden_stays_hidden(
    app: FastAPI, parent: httpx.AsyncClient, immich: FakeImmichServer
) -> None:
    library = await connected(parent)
    await pick(parent, library["id"], people=["p-mia"])
    assert await shown_names(app, library["id"]) == ["r-001", "r-002", "r-007"]
    async with state_of(app).db.read() as session:
        seven = await session.scalar(select(Photo).where(Photo.original_name == "r-007.jpg"))
    assert seven is not None
    hidden = await parent.post(f"/api/photos/{seven.id}/hide", headers=CSRF)
    assert hidden.status_code == 200
    assert await shown_names(app, library["id"]) == ["r-001", "r-002"]
    fetched = len([r for r in immich.requests if r.url.path.endswith("/thumbnail")])
    # Leo instead: Mia's leave (removed softly), Leo's come.
    await pick(parent, library["id"], people=["p-leo"])
    assert await shown_names(app, library["id"]) == ["r-001", "r-003", "r-012"]
    async with state_of(app).db.read() as session:
        two = await session.scalar(select(Photo).where(Photo.original_name == "r-002.jpg"))
    assert two is not None and two.deleted_at is not None
    # Mia again within the week: back without fetching them again, and 7 still hidden. (Every
    # photo came in when it was connected, with nothing picked: each pick since is a return.)
    await pick(parent, library["id"], people=["p-mia"])
    assert await shown_names(app, library["id"]) == ["r-001", "r-002"]
    after_back = len([r for r in immich.requests if r.url.path.endswith("/thumbnail")])
    assert after_back == fetched
    async with state_of(app).db.read() as session:
        seven = await session.scalar(select(Photo).where(Photo.original_name == "r-007.jpg"))
    assert seven is not None and seven.hidden and seven.deleted_at is None


async def test_switched_off_its_photos_stay_and_the_screensaver_shows_none(
    app: FastAPI, parent: httpx.AsyncClient
) -> None:
    library = await connected(parent)
    off = await parent.patch(
        f"/api/screensaver/libraries/{library['id']}", json={"enabled": False}, headers=CSRF
    )
    assert off.status_code == 200 and off.json()["enabled"] is False
    assert (await parent.get("/api/screensaver/manifest")).json()["photos"] == []
    assert len(await shown_names(app, library["id"])) == 9  # kept
    assert error(
        await parent.post(f"/api/screensaver/libraries/{library['id']}/scan", headers=CSRF)
    ) == (409, "source_off", "Turn it on first.")
    on = await parent.patch(
        f"/api/screensaver/libraries/{library['id']}", json={"enabled": True}, headers=CSRF
    )
    assert on.status_code == 200
    await settled(library["id"])
    assert len((await parent.get("/api/screensaver/manifest")).json()["photos"]) == 9


# ---- passes ------------------------------------------------------------------------------------


async def test_a_pass_brings_in_200_and_the_next_follows_by_itself(
    app: FastAPI, parent: httpx.AsyncClient, ctx: PluginContext, immich: FakeImmichServer
) -> None:
    immich.assets = [Asset(f"r-{n:03d}", n) for n in range(1, 231)]
    response = await connect(parent)
    assert response.status_code == 201, response.text
    library = response.json()
    await settled(library["id"])
    assert len(await shown_names(app, library["id"])) == 230
    async with state_of(app).db.read() as session:
        source = await session.get(PhotoSource, library["id"])
    assert source is not None and source.items_seen == 230
    # One pass alone stops at 200 and says there's more.
    immich.assets.extend(Asset(f"s-{n:03d}", 300 + n) for n in range(1, 211))
    assert (
        await parent.patch(
            f"/api/screensaver/libraries/{library['id']}", json={"limit": 1000}, headers=CSRF
        )
    ).status_code == 200
    await settled(library["id"])
    assert len(await shown_names(app, library["id"])) == 440
    count = await parent.patch(
        f"/api/screensaver/libraries/{library['id']}", json={"limit": 2000}, headers=CSRF
    )
    assert count.status_code == 200
    await settled(library["id"])
    immich.assets.extend(Asset(f"t-{n:03d}", 600 + n) for n in range(1, 211))
    assert await libraries.run_pass(ctx, library["id"]) is True
    assert len(await shown_names(app, library["id"])) == 640
    assert await libraries.run_pass(ctx, library["id"]) is False
    assert len(await shown_names(app, library["id"])) == 650


async def test_a_photo_that_wont_come_is_tried_three_times_and_left_out(
    app: FastAPI, parent: httpx.AsyncClient, ctx: PluginContext, immich: FakeImmichServer
) -> None:
    immich.broken = {"r-004"}
    library = await connected(parent)
    assert "r-004" not in await shown_names(app, library["id"])
    after = await library_of(parent, library["id"])
    assert (after["status"], after["last_error"], after["pending"]) == ("connected", None, 1)
    for _try in range(2):
        assert await libraries.run_pass(ctx, library["id"]) is False
    async with state_of(app).db.read() as session:
        row = await session.scalar(
            select(PhotoSourceItem).where(PhotoSourceItem.remote_id == "r-004")
        )
    assert row is not None and row.fetch_failures == 3 and row.dropped_at is not None
    assert (await library_of(parent, library["id"]))["pending"] == 0
    # Left out for good: a later pass doesn't ask again.
    asked = len([r for r in immich.requests if "/r-004/" in r.url.path])
    await libraries.run_pass(ctx, library["id"])
    assert len([r for r in immich.requests if "/r-004/" in r.url.path]) == asked


async def test_a_key_refused_midway_asks_for_it_again_and_the_inbox_keeps_going(
    app: FastAPI,
    parent: httpx.AsyncClient,
    ctx: PluginContext,
    immich: FakeImmichServer,
) -> None:
    library = await connected(parent)
    immich.refuse = 401
    assert await libraries.run_pass(ctx, library["id"]) is False
    after = await library_of(parent, library["id"])
    assert after["status"] == "needs_reconnect"
    assert after["last_error"].startswith("Immich said that key isn't right.")
    assert len(await shown_names(app, library["id"])) == 9  # its photos stay
    problems = (await parent.get("/api/problems")).json()["problems"]
    mine = [p for p in problems if p["id"] == f"photos:{library['id']}"]
    assert [(p["title"], p["page"]) for p in mine] == [
        ("Immich needs its key again.", "screensaver")
    ]
    assert [(p["key"], p["params"]) for p in mine] == [
        ("api.photos.library_needs_key", {"name": "Immich"})
    ]
    # The inbox doesn't notice.
    store = state_of(app).photos
    drop(store.inbox, "IMG_0001.JPG", photo((10, 120, 30)))
    await service.scan_inbox(ctx)
    inbox = (await parent.get("/api/screensaver/sources")).json()[0]
    assert (inbox["kind"], inbox["photo_count"]) == ("inbox", 1)
    # A new key: checked, kept, and the library is back.
    immich.refuse = None
    immich.key = "a-new-key"
    wrong = await parent.post(
        f"/api/screensaver/libraries/{library['id']}/reconnect",
        json={"api_key": "still-wrong"},
        headers=CSRF,
    )
    assert error(wrong)[:2] == (422, "auth")
    back = await parent.post(
        f"/api/screensaver/libraries/{library['id']}/reconnect",
        json={"api_key": "a-new-key"},
        headers=CSRF,
    )
    assert back.status_code == 200, back.text
    await settled(library["id"])
    after = await library_of(parent, library["id"])
    assert (after["status"], after["last_error"]) == ("connected", None)
    assert [
        p
        for p in (await parent.get("/api/problems")).json()["problems"]
        if p["id"] == f"photos:{library['id']}"
    ] == []


async def test_a_server_that_stops_answering_keeps_its_photos_showing(
    app: FastAPI, parent: httpx.AsyncClient, ctx: PluginContext, immich: FakeImmichServer
) -> None:
    library = await connected(parent)
    immich.refuse = 502
    await libraries.run_pass(ctx, library["id"])
    after = await library_of(parent, library["id"])
    assert (after["status"], after["last_error"]) == (
        "error",
        "Immich sent a reply Sunroom couldn't read.",
    )
    problems = (await parent.get("/api/problems")).json()["problems"]
    assert [p["title"] for p in problems if p["id"] == f"photos:{library['id']}"] == [
        "Immich hasn't answered. Showing the photos it had."
    ]
    assert len((await parent.get("/api/screensaver/manifest")).json()["photos"]) == 9


async def test_one_check_at_a_time(parent: httpx.AsyncClient, ctx: PluginContext) -> None:
    library = await connected(parent)
    assert libraries.start_pass(ctx, library["id"]) is True
    busy = await parent.post(f"/api/screensaver/libraries/{library['id']}/scan", headers=CSRF)
    assert error(busy) == (409, "already_checking", "It's checking that library right now.")
    await settled(library["id"])
    again = await parent.post(f"/api/screensaver/libraries/{library['id']}/scan", headers=CSRF)
    assert again.status_code == 200 and again.json()["checking"] is True
    await settled(library["id"])


async def test_a_key_wiped_by_a_new_secret_key_asks_for_it_again(
    app: FastAPI, parent: httpx.AsyncClient, ctx: PluginContext
) -> None:
    library = await connected(parent)
    async with state_of(app).db.write() as tx:
        source = await tx.session.get(PhotoSource, library["id"])
        assert source is not None
        source.credentials_enc = None  # what boot does when the secret key changes
        source.status = "needs_reconnect"
    assert await libraries.run_pass(ctx, library["id"]) is False
    after = await library_of(parent, library["id"])
    assert (after["status"], after["last_error"]) == (
        "needs_reconnect",
        "Sunroom can't read this library's saved key any more. Connect it again.",
    )


async def test_removing_it_removes_its_photos_and_what_it_kept(
    app: FastAPI, parent: httpx.AsyncClient, events: list[tuple[str, dict[str, Any]]]
) -> None:
    library = await connected(parent)
    gone = await parent.delete(f"/api/screensaver/libraries/{library['id']}", headers=CSRF)
    assert gone.status_code == 204
    assert (await parent.get("/api/screensaver/libraries")).json() == []
    assert (await parent.get("/api/screensaver/manifest")).json()["photos"] == []
    async with state_of(app).db.read() as session:
        items = (await session.scalars(select(PhotoSourceItem))).all()
        source = await session.get(PhotoSource, library["id"])
        removed = (
            await session.scalars(
                select(Photo).where(Photo.source_key == f"source:{library['id']}")
            )
        ).all()
    assert items == []
    assert source is not None and source.credentials_enc is None and source.deleted_at is not None
    assert len(removed) == 9 and all(p.deleted_at is not None for p in removed)
    assert ("photos.changed", {"source_id": library["id"]}) in events
    assert (await parent.get(f"/api/screensaver/libraries/{library['id']}")).status_code == 404


async def test_faces_come_through_sunroom_and_the_choices_refresh_when_asked(
    parent: httpx.AsyncClient, immich: FakeImmichServer
) -> None:
    library = await connected(parent)
    base = f"/api/screensaver/libraries/{library['id']}"
    face = await parent.get(f"{base}/thumb", params={"person": "p-mia"})
    assert face.status_code == 200
    assert face.headers["content-type"] == "image/jpeg"
    assert face.headers["cache-control"] == "private, max-age=3600"
    assert (await parent.get(f"{base}/thumb", params={"person": "p-nobody"})).status_code == 404
    assert (await parent.get(f"{base}/thumb", params={"person": "../server"})).status_code == 404
    assert (await parent.get(f"{base}/thumb")).status_code == 404
    immich.people.append({"id": "p-ana", "name": "Ana", "isHidden": False, "thumbnailPath": "/a"})
    cached = (await parent.get(f"{base}/choices")).json()
    assert [c["name"] for c in cached["people"]] == ["Mia", "Leo"]
    fresh = (await parent.get(f"{base}/choices", params={"refresh": "true"})).json()
    assert [c["name"] for c in fresh["people"]] == ["Mia", "Leo", "Ana"]
    immich.refuse = 401
    refused = await parent.get(f"{base}/choices", params={"refresh": "true"})
    assert error(refused)[:2] == (422, "auth")


async def test_libraries_are_a_parents_business(
    parent: httpx.AsyncClient, third: httpx.AsyncClient
) -> None:
    from tests.support import PASSWORD, set_pin

    await set_pin(parent)
    paired = await third.post(
        "/api/auth/kiosk/pair-with-password", json={"password": PASSWORD}, headers=CSRF
    )
    assert paired.status_code == 200, paired.text
    for method, path in [
        ("GET", "/api/screensaver/libraries"),
        ("GET", "/api/screensaver/library-kinds"),
        ("POST", "/api/screensaver/libraries"),
    ]:
        response = await third.request(
            method, path, json={} if method == "POST" else None, headers=CSRF
        )
        assert response.status_code == 403, (method, path)


def test_the_pretend_immich_answers_only_on_the_test_server() -> None:
    assert isinstance(library_for("immich", "http://immich.test", test_mode=True), FakeLibrary)
    assert isinstance(library_for("immich", "http://immich.test", test_mode=False), ImmichLibrary)
    assert isinstance(library_for("immich", PUBLIC_URL, test_mode=True), ImmichLibrary)
    assert library_for("nextcloud", PUBLIC_URL, test_mode=True) is None


async def test_the_test_route_is_absent_off_the_test_server(parent: httpx.AsyncClient) -> None:
    response = await parent.post("/api/screensaver/_test/library", json={}, headers=CSRF)
    assert response.status_code == 404
