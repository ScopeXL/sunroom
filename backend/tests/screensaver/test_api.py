"""The screensaver plugin through its API (PLAN §9, §11.3; UX §4 "Photos room", "Screensaver"):
the manifest the wall shows, the sources a parent looks after, the thumbnail backlog, the Sample
Family's photos, and the plugin switched off. Only this plugin is registered, so it is shown
working with every other plugin off. Synthetic pictures only."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import APIRouter, FastAPI
from fastapi.routing import APIRoute
from PIL import Image
from sqlalchemy import delete, select

from sunroom.photos.models import Photo, PhotoKind
from sunroom.photos.store import PhotoStore
from sunroom.plugins.context import PluginContext
from sunroom.plugins.screensaver import service
from sunroom.plugins.screensaver.models import PhotoSource
from sunroom.plugins.screensaver.plugin import Screensaver
from tests.screensaver.helpers import (
    GONE,
    Events,
    Family,
    Json,
    all_sources,
    drop,
    inbox_source,
    manifest,
    photo,
    shown,
    started,
    tapped,
    until,
    upload,
)
from tests.support import BASE_URL, CSRF, state_of

DEFAULTS = {"start_after_minutes": 15, "every_seconds": 30, "show_clock": True, "shuffle": True}
OFF = {
    "code": "plugin_disabled",
    "message": "Photos & Screensaver is turned off. A parent can turn it on in Settings.",
    "key": "api.plugins.turned_off",
    "params": {"name": "Photos & Screensaver"},
}
PARENT_PIN: dict[str, Any] = {
    "code": "parent_required",
    "message": "Only a parent can do that. Enter the parent PIN.",
    "key": "api.auth.parent_pin",
    "params": {},
    "pin": True,
}


# ---- the manifest ------------------------------------------------------------------------------


async def test_the_manifest_is_every_photo_the_screensaver_may_show_newest_first(
    app: FastAPI, parent: httpx.AsyncClient, ctx: PluginContext, store: PhotoStore
) -> None:
    first, second, third = [
        await upload(parent, photo(color)) for color in ((10, 0, 0), (0, 10, 0), (0, 0, 10))
    ]
    async with state_of(app).db.write() as tx:  # a person's picture isn't for the screensaver
        await store.ingest(
            tx.session,
            photo((0, 0, 0)),
            kind=PhotoKind.AVATAR,
            zone=ctx.zone(),
            now=ctx.now(),
        )
    found = await manifest(parent)
    assert found["settings"] == DEFAULTS
    assert [each["id"] for each in found["photos"]] == [third["id"], second["id"], first["id"]]
    assert found["photos"][0] == {
        "id": third["id"],
        "url": third["url"],
        "thumb_url": third["thumb_url"],
        "width": 64,
        "height": 48,
        "taken_at": None,
    }
    # Hidden from the screensaver, or removed: gone from it.
    hidden = await parent.post(f"/api/photos/{first['id']}/hide", headers=CSRF)
    assert hidden.status_code == 200, hidden.text
    assert (await parent.delete(f"/api/photos/{second['id']}", headers=CSRF)).status_code == 204
    assert await shown(parent) == [third["id"]]


async def test_the_manifest_carries_the_settings_as_the_wall_uses_them(
    parent: httpx.AsyncClient, ctx: PluginContext
) -> None:
    async def choose(**values: object) -> None:
        response = await parent.put(
            "/api/plugins/screensaver/settings", json={"values": values}, headers=CSRF
        )
        assert response.status_code == 200, response.text

    await choose(start_after="never", every="120", show_clock=False, shuffle=False)
    assert (await manifest(parent))["settings"] == {
        "start_after_minutes": None,
        "every_seconds": 120,
        "show_clock": False,
        "shuffle": False,
    }
    await choose(start_after="5", every="15")
    assert (await manifest(parent))["settings"] == DEFAULTS | {
        "start_after_minutes": 5,
        "every_seconds": 15,
    }
    await choose(start_after="60", every="300")
    assert (await manifest(parent))["settings"] == DEFAULTS | {
        "start_after_minutes": 60,
        "every_seconds": 300,
    }
    # Ten minutes was a choice before 0.8.0 and isn't now.
    refused = await parent.put(
        "/api/plugins/screensaver/settings", json={"values": {"start_after": "10"}}, headers=CSRF
    )
    assert refused.status_code == 422, refused.text


async def test_the_manifest_stops_at_5000_photos(
    parent: httpx.AsyncClient, ctx: PluginContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert service.MANIFEST_MAX == 5000
    monkeypatch.setattr(service, "MANIFEST_MAX", 2)
    ids = [(await upload(parent, photo((n, n, n))))["id"] for n in range(3)]
    assert await shown(parent) == [ids[2], ids[1]]


async def test_the_wall_and_every_phone_read_the_manifest(
    app: FastAPI,
    parent: httpx.AsyncClient,
    ctx: PluginContext,
    screen: httpx.AsyncClient,
    kid_phone: httpx.AsyncClient,
    family: Family,
) -> None:
    added = await upload(parent, photo())
    assert await shown(screen) == [added["id"]]
    on_the_wall = await manifest(screen, headers=tapped(family.mia))
    assert [each["id"] for each in on_the_wall["photos"]] == [added["id"]]
    assert await shown(kid_phone) == [added["id"]]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url=BASE_URL
    ) as stranger:
        refused = await stranger.get("/api/screensaver/manifest")
    assert (refused.status_code, refused.json()["error"]["code"]) == (401, "signed_out")


# ---- sources -----------------------------------------------------------------------------------


async def test_the_inbox_is_a_source_from_the_start(
    parent: httpx.AsyncClient, ctx: PluginContext
) -> None:
    [inbox] = await all_sources(parent)
    assert inbox == {
        "id": inbox["id"],
        "kind": "inbox",
        "label": "Photos folder",
        "enabled": True,
        "last_scan_at": "2026-10-07T14:00:00Z",  # it looked as the plugin started
        "last_error": None,
        "items_seen": 0,
        "photo_count": 0,
    }


async def test_sources_are_a_parents_business(
    parent: httpx.AsyncClient,
    ctx: PluginContext,
    screen: httpx.AsyncClient,
    kid_phone: httpx.AsyncClient,
    family: Family,
) -> None:
    source = await inbox_source(parent)
    path = f"/api/screensaver/sources/{source['id']}"
    # With a PIN, the wall screen and a kid's phone are asked for it, whoever tapped.
    for client, headers in ((kid_phone, CSRF), (screen, tapped(family.ana))):
        for method, url, body in (
            ("GET", "/api/screensaver/sources", None),
            ("PATCH", path, {"enabled": False}),
            ("POST", f"{path}/scan", None),
        ):
            response = await client.request(method, url, json=body, headers=headers)
            assert (response.status_code, response.json()["error"]) == (403, PARENT_PIN), url
    assert (await inbox_source(parent))["enabled"] is True


async def test_without_a_pin_the_wall_screen_looks_after_sources(
    parent: httpx.AsyncClient, ctx: PluginContext, screen: httpx.AsyncClient, family: Family
) -> None:
    source = await inbox_source(parent)
    renamed = await screen.patch(
        f"/api/screensaver/sources/{source['id']}",
        json={"label": "Shared folder"},
        headers=tapped(family.sam),
    )
    assert renamed.status_code == 200, renamed.text
    assert (await inbox_source(screen))["label"] == "Shared folder"


async def test_a_parent_renames_a_source_and_switches_it_off(
    parent: httpx.AsyncClient, ctx: PluginContext, events: Events
) -> None:
    source = await inbox_source(parent)
    path = f"/api/screensaver/sources/{source['id']}"
    events.clear()
    renamed = await parent.patch(path, json={"label": "  Shared folder "}, headers=CSRF)
    assert renamed.status_code == 200, renamed.text
    assert renamed.json() == source | {"label": "Shared folder"}
    off = await parent.patch(path, json={"enabled": False}, headers=CSRF)
    assert off.json() == source | {"label": "Shared folder", "enabled": False}
    same = await parent.patch(path, json={"label": "Shared folder"}, headers=CSRF)
    assert same.status_code == 200, same.text
    assert events == [("screensaver.changed", {"source_id": source["id"]})] * 2  # once each
    blank = await parent.patch(path, json={"label": "   "}, headers=CSRF)
    assert (blank.status_code, blank.json()["error"]["code"]) == (422, "invalid")
    gone = await parent.patch("/api/screensaver/sources/nope", json={"enabled": True}, headers=CSRF)
    assert (gone.status_code, gone.json()["error"]) == (404, GONE)
    assert await all_sources(parent) == [source | {"label": "Shared folder", "enabled": False}]


async def test_the_inbox_comes_back_when_its_row_is_gone(
    app: FastAPI, parent: httpx.AsyncClient, ctx: PluginContext
) -> None:
    """A test server's reset empties the plugin's table while it runs."""
    state = state_of(app)

    async def forget() -> None:
        async with state.db.write() as tx:
            await tx.session.execute(delete(PhotoSource))

    await forget()
    [again] = await all_sources(parent)
    assert (again["kind"], again["label"], again["enabled"]) == ("inbox", "Photos folder", True)
    await forget()
    await service.scan_inbox(ctx)
    async with state.db.read() as session:
        rows = list(await session.scalars(select(PhotoSource)))
    assert [(row.kind, row.last_scan_at is not None) for row in rows] == [("inbox", True)]


# ---- the thumbnail backlog ---------------------------------------------------------------------


async def test_the_backlog_makes_lost_thumbnails_again(
    parent: httpx.AsyncClient, ctx: PluginContext, store: PhotoStore, events: Events
) -> None:
    kept, removed = [
        await upload(parent, photo(color, (900, 600))) for color in ((1, 1, 1), (2, 2, 2))
    ]
    assert (await parent.delete(f"/api/photos/{removed['id']}", headers=CSRF)).status_code == 204
    for each in (kept, removed):  # a crash mid-import
        store.file("thumbs", each["id"]).unlink()
    events.clear()
    await service.thumb_backlog(ctx)
    with Image.open(store.file("thumbs", kept["id"])) as thumb:
        assert (thumb.format, thumb.size) == ("WEBP", (400, 267))
    assert not store.file("thumbs", removed["id"]).exists()  # removed photos are left be
    assert events == [("photos.changed", {"thumbs": 1})]
    events.clear()
    await service.thumb_backlog(ctx)
    assert events == []


# ---- the Sample Family -------------------------------------------------------------------------


async def test_the_sample_family_has_eight_calm_photos(
    app: FastAPI,
    parent: httpx.AsyncClient,
    ctx: PluginContext,
    plugin: Screensaver,
    store: PhotoStore,
    family: Family,
    events: Events,
) -> None:
    people = {"Ana": family.ana, "Sam": family.sam, "Mia": family.mia, "Leo": family.leo}
    events.clear()
    await plugin.seed_sample(ctx, people)
    found = (await manifest(parent))["photos"]
    sizes = [(each["width"], each["height"]) for each in found]
    assert sizes == [(1600, 1067)] * 7 + [(1067, 1600)]  # the tall one went in first
    assert len(events) == 8 and {kind for kind, _ in events} == {"photos.changed"}
    async with state_of(app).db.read() as session:
        rows = list(await session.scalars(select(Photo).order_by(Photo.id.desc())))
    assert {row.source_key for row in rows} == {"upload"}
    assert rows[0].original_name == "sunrise.jpg"  # the newest: first with Shuffle off
    assert len({row.sha256 for row in rows}) == 8
    for row in rows:  # painted scenes, not flat colors
        with Image.open(store.file("thumbs", row.id)) as thumb:
            assert len(thumb.convert("RGB").getcolors(maxcolors=1 << 16) or ()) > 40
    # A second seed paints the same pictures and adds nothing.
    events.clear()
    await plugin.seed_sample(ctx, people)
    assert len(await shown(parent)) == 8
    assert events == []


# ---- starting, switched off --------------------------------------------------------------------


async def test_while_photos_start_a_request_asks_to_try_again(
    parent: httpx.AsyncClient, plugin: Screensaver, ctx: PluginContext
) -> None:
    plugin.ctx = None
    try:
        response = await parent.get("/api/screensaver/manifest")
    finally:
        plugin.ctx = ctx
    assert response.status_code == 503
    assert response.json()["error"] == {
        "code": "starting",
        "message": "Photos are still starting. Try again.",
        "key": "api.photos.starting",
        "params": {},
    }


async def test_off_every_route_is_404_and_on_again_everything_is_there(
    app: FastAPI,
    parent: httpx.AsyncClient,
    ctx: PluginContext,
    plugin: Screensaver,
    inbox: Path,
) -> None:
    drop(inbox, "IMG_0001.JPG", photo((70, 80, 90)))
    await service.scan_inbox(ctx)
    source = await inbox_source(parent)
    renamed = await parent.patch(
        f"/api/screensaver/sources/{source['id']}", json={"label": "Shared folder"}, headers=CSRF
    )
    assert renamed.status_code == 200, renamed.text
    before = await manifest(parent)
    off = await parent.post("/api/plugins/screensaver/disable", headers=CSRF)
    assert off.status_code == 200, off.text
    assert off.json()["enabled"] is False
    routes = APIRouter()
    Screensaver().register_routes(routes)
    answered: list[tuple[str, str]] = []
    for route in routes.routes:
        assert isinstance(route, APIRoute)
        path = "/api/screensaver" + route.path.format(source_id=source["id"])
        for method in sorted(route.methods or ()):
            body: Json | None = {} if method in {"POST", "PUT", "PATCH"} else None
            response = await parent.request(method, path, json=body, headers=CSRF)
            assert (response.status_code, response.json()["error"]) == (404, OFF), (method, path)
            answered.append((method, route.path))
    assert len(answered) == 15  # every route the plugin has (11 are photo libraries')
    on = await parent.post("/api/plugins/screensaver/enable", headers=CSRF)
    assert on.status_code == 200, on.text

    async def back() -> bool:
        return plugin.ctx is not ctx and plugin.ctx is not None

    await until(back)
    await started(app, plugin)
    assert await manifest(parent) == before
    assert (await inbox_source(parent))["label"] == "Shared folder"
    assert (await inbox_source(parent))["photo_count"] == 1
