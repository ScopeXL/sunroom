"""The inbox folder (PLAN §11.4 ``screensaver:inbox-scan``, §15 M4 verify; ADR 0009): photos
dropped into $DATA_DIR/photos/inbox come into the library without their EXIF, the originals move
to imported/, and files Sunroom can't read move to unreadable/; a full disk waits; a parent can
check now. A bad file never stops the plugin. Only this plugin is registered. Synthetic pictures
only."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from PIL import ExifTags, Image
from sqlalchemy.ext.asyncio import AsyncSession

from sunroom.core.clock import FakeClock
from sunroom.photos.models import Photo, PhotoKind
from sunroom.photos.store import PhotoStore
from sunroom.plugins.base import PluginStatus
from sunroom.plugins.context import PluginContext
from sunroom.plugins.screensaver import service
from sunroom.plugins.screensaver.models import PhotoSource
from tests.screensaver.helpers import (
    GONE,
    Events,
    Family,
    age,
    all_sources,
    drop,
    error,
    heic,
    inbox_source,
    manifest,
    names,
    photo,
    scan,
    shown,
    tapped,
    until,
)
from tests.support import CSRF, state_of

ONE_UNREADABLE = "1 file wasn't a photo Sunroom could read. It's in the inbox's unreadable folder."
TWO_UNREADABLE = (
    "2 files weren't photos Sunroom could read. They're in the inbox's unreadable folder."
)
ONE_STUCK = (
    "1 file couldn't be moved out of the inbox. "
    "Check that Sunroom is allowed to change files there."
)


async def test_a_photo_dropped_in_the_inbox_shows_without_its_exif(
    parent: httpx.AsyncClient,
    ctx: PluginContext,
    store: PhotoStore,
    inbox: Path,
    clock: FakeClock,
    events: Events,
) -> None:
    """PLAN §15 M4 verify: a JPEG dropped into the inbox appears in the manifest, EXIF gone."""
    original = photo(taken="2026:09:20 17:45:00", gps=True)
    with Image.open(io.BytesIO(original)) as sent:  # the phone's photo says where it was taken
        assert sent.getexif().get_ifd(ExifTags.IFD.GPSInfo)
    drop(inbox, "IMG_0001.JPG", original)
    clock.advance(minutes=5)  # the next check
    events.clear()
    await service.scan_inbox(ctx)

    [found] = (await manifest(parent))["photos"]
    assert found == {
        "id": found["id"],
        "url": f"/photos/library/{found['id']}.webp",
        "thumb_url": f"/photos/thumbs/{found['id']}.webp",
        "width": 64,
        "height": 48,
        "taken_at": "2026-09-20T21:45:00Z",  # 5:45 PM in New York, from the EXIF
    }
    stored = store.file("library", found["id"]).read_bytes()
    with Image.open(io.BytesIO(stored)) as kept:
        assert kept.format == "WEBP"
        assert not kept.getexif()
    assert b"Exif" not in stored and b"EXIF" not in stored
    served = await parent.get(found["url"])
    assert (served.status_code, served.headers["content-type"]) == (200, "image/webp")
    assert (await parent.get(found["thumb_url"])).status_code == 200
    # The original waits in imported/, as it came.
    assert names(inbox) == ["imported"]
    assert (inbox / "imported" / "IMG_0001.JPG").read_bytes() == original
    source = await inbox_source(parent)
    assert source == {
        "id": source["id"],
        "kind": "inbox",
        "label": "Photos folder",
        "enabled": True,
        "last_scan_at": "2026-10-07T14:05:00Z",
        "last_error": None,
        "items_seen": 1,
        "photo_count": 1,
    }
    assert events == [
        ("photos.changed", {"source_id": source["id"], "count": 1}),
        ("screensaver.changed", {"source_id": source["id"]}),
    ]


async def test_a_file_still_being_copied_waits_for_the_next_check(
    parent: httpx.AsyncClient, ctx: PluginContext, inbox: Path, events: Events
) -> None:
    path = drop(inbox, "IMG_0002.JPG", photo(), age_s=0)  # written just now
    events.clear()
    await service.scan_inbox(ctx)
    assert await shown(parent) == []
    assert names(inbox) == ["IMG_0002.JPG"]
    assert events == []  # nothing to tell
    age(path, 11)  # nobody has touched it for over 10 seconds
    await service.scan_inbox(ctx)
    assert len(await shown(parent)) == 1
    assert names(inbox / "imported") == ["IMG_0002.JPG"]


async def test_a_file_that_isnt_a_photo_is_set_aside(
    parent: httpx.AsyncClient, ctx: PluginContext, inbox: Path
) -> None:
    drop(inbox, "notes.jpg", b"a shopping list, not a photo")
    drop(inbox, "IMG_0003.JPG", photo((10, 120, 200)))
    await service.scan_inbox(ctx)
    assert names(inbox / "unreadable") == ["notes.jpg"]
    assert names(inbox / "imported") == ["IMG_0003.JPG"]
    assert len(await shown(parent)) == 1
    source = await inbox_source(parent)
    assert (source["items_seen"], source["last_error"]) == (1, ONE_UNREADABLE)
    # Needs Attention says so, and where it's checked again (ADR 0034).
    listed = (await parent.get("/api/problems")).json()["problems"]
    assert [(p["id"], p["title"], p["page"]) for p in listed] == [
        (f"photos:{source['id']}", ONE_UNREADABLE, "screensaver")
    ]
    # Named by its key, so the page says it in the family's language (ADR 0043).
    assert [(p["key"], p["params"]) for p in listed] == [("api.photos.inbox.unreadable_one", {})]
    # Two more: the line counts them.
    drop(inbox, "receipt.png", b"\x89PNG and then nothing")
    drop(inbox, "scan.heic", b"not a picture either")
    await service.scan_inbox(ctx)
    assert names(inbox / "unreadable") == ["notes.jpg", "receipt.png", "scan.heic"]
    assert (await inbox_source(parent))["last_error"] == TWO_UNREADABLE
    listed = (await parent.get("/api/problems")).json()["problems"]
    assert [(p["title"], p["key"], p["params"]) for p in listed] == [
        (TWO_UNREADABLE, "api.photos.inbox.unreadable", {"count": "2"})
    ]
    # A check that finds nothing keeps the line, so a parent sees it later; Check now says
    # afresh.
    await service.scan_inbox(ctx)
    assert (await inbox_source(parent))["last_error"] == TWO_UNREADABLE
    checked = await scan(parent, source["id"])
    assert checked.status_code == 200, checked.text
    assert checked.json()["source"]["last_error"] is None


async def test_the_same_photo_twice_is_one_photo(
    parent: httpx.AsyncClient, ctx: PluginContext, inbox: Path
) -> None:
    picture = photo((40, 90, 160))
    drop(inbox, "beach.jpg", picture)
    drop(inbox, "beach copy.jpg", picture)
    await service.scan_inbox(ctx)
    [only] = await shown(parent)
    assert names(inbox / "imported") == ["beach copy.jpg", "beach.jpg"]
    assert (await inbox_source(parent))["items_seen"] == 1
    # The same name again: kept beside the first, numbered.
    drop(inbox, "beach.jpg", picture)
    await service.scan_inbox(ctx)
    assert names(inbox / "imported") == ["beach (2).jpg", "beach copy.jpg", "beach.jpg"]
    assert await shown(parent) == [only]
    assert (await inbox_source(parent))["items_seen"] == 1
    # One a parent removed comes back when it's dropped in again.
    assert (await parent.delete(f"/api/photos/{only}", headers=CSRF)).status_code == 204
    drop(inbox, "beach.jpg", picture)
    await service.scan_inbox(ctx)
    assert await shown(parent) == [only]
    assert "beach (3).jpg" in names(inbox / "imported")
    assert (await inbox_source(parent))["items_seen"] == 2


async def test_an_iphone_heic_comes_in(
    parent: httpx.AsyncClient, ctx: PluginContext, store: PhotoStore, inbox: Path
) -> None:
    data = heic()
    if data is None:
        pytest.skip("this pillow-heif can't write HEIC")
    drop(inbox, "IMG_0004.HEIC", data)
    await service.scan_inbox(ctx)
    [found] = (await manifest(parent))["photos"]
    assert (found["width"], found["height"]) == (64, 48)
    with Image.open(store.file("library", found["id"])) as kept:
        assert kept.format == "WEBP"
    assert names(inbox / "imported") == ["IMG_0004.HEIC"]


async def test_only_photo_files_at_the_top_of_the_inbox_come_in(
    parent: httpx.AsyncClient, ctx: PluginContext, inbox: Path
) -> None:
    for name in (".hidden.jpg", "copying.jpg.partial", "notes.txt", "clip.mov"):
        drop(inbox, name, photo((10, 10, 10)))
    (inbox / "album").mkdir()
    drop(inbox / "album", "inside.jpg", photo((20, 20, 20)))
    (inbox / "link.jpg").symlink_to(inbox / "album" / "inside.jpg")
    drop(inbox, "IMG_0005.PNG", photo((30, 30, 30), fmt="PNG"))  # any case, any photo type
    drop(inbox, "IMG_0006.webp", photo((40, 40, 40), fmt="WEBP"))
    await service.scan_inbox(ctx)
    assert len(await shown(parent)) == 2
    assert names(inbox / "imported") == ["IMG_0005.PNG", "IMG_0006.webp"]
    assert names(inbox) == [
        ".hidden.jpg",
        "album",
        "clip.mov",
        "copying.jpg.partial",
        "imported",
        "link.jpg",
        "notes.txt",
    ]
    assert names(inbox / "album") == ["inside.jpg"]


async def test_a_file_over_50_mb_is_set_aside(
    parent: httpx.AsyncClient, ctx: PluginContext, inbox: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert service.MAX_FILE_BYTES == 50 * 1024 * 1024
    monkeypatch.setattr(service, "MAX_FILE_BYTES", 300)
    drop(inbox, "huge.jpg", photo(size=(400, 300)))
    await service.scan_inbox(ctx)
    assert await shown(parent) == []
    assert names(inbox / "unreadable") == ["huge.jpg"]
    assert (await inbox_source(parent))["last_error"] == ONE_UNREADABLE


async def test_a_full_disk_stops_the_check_and_leaves_the_files(
    parent: httpx.AsyncClient, ctx: PluginContext, inbox: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def almost_full(self: PhotoStore) -> int:
        return 1024

    monkeypatch.setattr(PhotoStore, "free_bytes", almost_full)
    drop(inbox, "IMG_0007.JPG", photo((1, 2, 3)))
    drop(inbox, "IMG_0008.JPG", photo((4, 5, 6)))
    await service.scan_inbox(ctx)
    assert await shown(parent) == []
    assert names(inbox) == ["IMG_0007.JPG", "IMG_0008.JPG"]
    source = await inbox_source(parent)
    assert source["last_error"] == (
        "Photos need room. Remove some, or move photos to a bigger disk (About → Storage)."
    )
    assert source["items_seen"] == 0
    # With room again, the next check brings them in.
    monkeypatch.undo()
    await service.scan_inbox(ctx)
    assert len(await shown(parent)) == 2
    source = await inbox_source(parent)
    assert (source["items_seen"], source["last_error"]) == (2, None)


async def test_a_switched_off_inbox_is_left_alone(
    parent: httpx.AsyncClient, ctx: PluginContext, inbox: Path, clock: FakeClock
) -> None:
    source = await inbox_source(parent)
    path = f"/api/screensaver/sources/{source['id']}"
    off = await parent.patch(path, json={"enabled": False}, headers=CSRF)
    assert off.json()["enabled"] is False
    drop(inbox, "IMG_0009.JPG", photo())
    clock.advance(minutes=5)
    await service.scan_inbox(ctx)
    assert names(inbox) == ["IMG_0009.JPG"]
    assert (await inbox_source(parent))["last_scan_at"] == source["last_scan_at"]
    assert error(await scan(parent, source["id"])) == (409, "source_off", "Turn it on first.")
    await parent.patch(path, json={"enabled": True}, headers=CSRF)
    checked = await scan(parent, source["id"])
    assert checked.status_code == 200, checked.text
    assert checked.json()["imported"] == 1


async def test_check_now_says_what_it_found(
    parent: httpx.AsyncClient,
    ctx: PluginContext,
    inbox: Path,
    clock: FakeClock,
    events: Events,
) -> None:
    drop(inbox, "IMG_0010.JPG", photo((9, 9, 9)))
    drop(inbox, "IMG_0011.JPG", photo((11, 11, 11)))
    drop(inbox, "broken.jpg", b"not a photo")
    source = await inbox_source(parent)
    clock.advance(minutes=1)
    events.clear()
    checked = await scan(parent, source["id"])
    assert checked.status_code == 200, checked.text
    assert checked.json() == {
        "source": source
        | {
            "last_scan_at": "2026-10-07T14:01:00Z",
            "last_error": ONE_UNREADABLE,
            "items_seen": 2,
            "photo_count": 2,
        },
        "imported": 2,
        "unreadable": 1,
    }
    assert events == [
        ("photos.changed", {"source_id": source["id"], "count": 2}),
        ("screensaver.changed", {"source_id": source["id"]}),
    ]
    # Nothing new: it says so, and still tells the other screens it looked.
    events.clear()
    again = (await scan(parent, source["id"])).json()
    assert (again["imported"], again["unreadable"], again["source"]["last_error"]) == (0, 0, None)
    assert events == [("screensaver.changed", {"source_id": source["id"]})]


async def test_only_a_parent_checks_now(
    parent: httpx.AsyncClient,
    ctx: PluginContext,
    screen: httpx.AsyncClient,
    kid_phone: httpx.AsyncClient,
    family: Family,
    inbox: Path,
) -> None:
    drop(inbox, "IMG_0012.JPG", photo())
    source = await inbox_source(parent)
    # With a PIN, the wall screen and a kid's phone are asked for it, whoever tapped.
    for refused in (
        await scan(kid_phone, source["id"]),
        await scan(screen, source["id"], headers=tapped(family.ana)),
    ):
        assert refused.status_code == 403
        assert refused.json()["error"] == {
            "code": "parent_required",
            "message": "Only a parent can do that. Enter the parent PIN.",
            "key": "api.auth.parent_pin",
            "params": {},
            "pin": True,
        }
    assert names(inbox) == ["IMG_0012.JPG"]


async def test_sources_are_the_inbox_and_a_library_is_checked_from_its_own_page(
    app: FastAPI, parent: httpx.AsyncClient, ctx: PluginContext, store: PhotoStore
) -> None:
    """A photo library has its own list and its own Check Now (ADR 0036)."""
    async with state_of(app).db.write() as tx:
        album = PhotoSource(kind="immich", label="Family album", created_at=ctx.now())
        tx.session.add(album)
        await tx.session.flush()
        album_id = album.id
        await _ingest(tx.session, store, ctx, photo((50, 60, 70)), f"source:{album_id}")
    listed = await all_sources(parent)
    assert [(each["kind"], each["label"], each["photo_count"]) for each in listed] == [
        ("inbox", "Photos folder", 0),
    ]
    assert error(await scan(parent, album_id)) == (
        409,
        "cant_check",
        "Check a photo library from Photo Libraries.",
    )
    gone = await scan(parent, "nope")
    assert (gone.status_code, gone.json()["error"]) == (404, GONE)


async def test_one_check_at_a_time(
    parent: httpx.AsyncClient, ctx: PluginContext, store: PhotoStore, inbox: Path
) -> None:
    drop(inbox, "IMG_0013.JPG", photo())
    source = await inbox_source(parent)
    service._checking.add(store.inbox)  # a check is running
    try:
        refused = await scan(parent, source["id"])
        await service.scan_inbox(ctx)  # the 5-minute check leaves it to the running one
    finally:
        service._checking.discard(store.inbox)
    assert error(refused) == (409, "already_checking", "It's checking the folder right now.")
    assert names(inbox) == ["IMG_0013.JPG"]


async def test_a_file_that_cant_leave_the_inbox_is_reported(
    parent: httpx.AsyncClient, ctx: PluginContext, inbox: Path
) -> None:
    (inbox / "imported").write_text("a file where the folder should be")
    drop(inbox, "IMG_0014.JPG", photo((14, 14, 14)))
    await service.scan_inbox(ctx)
    assert len(await shown(parent)) == 1  # it came in all the same
    source = await inbox_source(parent)
    assert (source["items_seen"], source["last_error"]) == (1, ONE_STUCK)
    assert (inbox / "IMG_0014.JPG").exists()
    # Next time it's the same photo, not counted twice, and it moves once it can.
    (inbox / "imported").unlink()
    await service.scan_inbox(ctx)
    source = await inbox_source(parent)
    assert (source["items_seen"], source["last_error"]) == (1, None)
    assert names(inbox / "imported") == ["IMG_0014.JPG"]
    assert len(await shown(parent)) == 1


async def test_a_bad_file_never_stops_the_plugin(
    app: FastAPI,
    parent: httpx.AsyncClient,
    ctx: PluginContext,
    inbox: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Its jobs run as it starts: a restart checks the inbox now. A file the image library
    chokes on in a way the store doesn't expect is set aside like any unreadable one."""
    ingest = PhotoStore.ingest

    async def choking(
        self: PhotoStore, session: AsyncSession, data: bytes, **options: Any
    ) -> Photo:
        if options.get("original_name") == "odd.jpg":
            raise SyntaxError("the image library choked")
        return await ingest(self, session, data, **options)

    monkeypatch.setattr(PhotoStore, "ingest", choking)
    drop(inbox, "odd.jpg", photo((1, 1, 1)))
    drop(inbox, "broken.jpg", b"not a photo")
    drop(inbox, "IMG_0015.JPG", photo((15, 15, 15)))
    restarted = await parent.post("/api/plugins/screensaver/restart", headers=CSRF)
    assert restarted.status_code == 200, restarted.text

    async def checked() -> bool:
        return (await inbox_source(parent))["items_seen"] == 1

    await until(checked)
    assert state_of(app).plugins.status("screensaver") is PluginStatus.RUNNING
    assert names(inbox / "unreadable") == ["broken.jpg", "odd.jpg"]
    assert names(inbox / "imported") == ["IMG_0015.JPG"]
    assert (await inbox_source(parent))["last_error"] == TWO_UNREADABLE


async def _ingest(
    session: AsyncSession, store: PhotoStore, ctx: PluginContext, data: bytes, source_key: str
) -> Photo:
    return await store.ingest(
        session,
        data,
        kind=PhotoKind.LIBRARY,
        zone=ctx.zone(),
        now=ctx.now(),
        source_key=source_key,
    )
