"""The core photo store (PLAN §10.1, ADR 0009): WebP files on the volume, EXIF gone, one row
per picture. Every picture here is a synthetic flat color."""

from __future__ import annotations

import io
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest
from fastapi import FastAPI
from PIL import Image

from sunroom.photos.models import PhotoKind
from sunroom.photos.store import PhotoStore, encode_avatar, encode_library
from tests.support import CSRF, picture, state_of

NY = ZoneInfo("America/New_York")


def with_exif(
    *, orientation: int | None = None, taken: str | None = None, offset: str | None = None
) -> bytes:
    image = Image.new("RGB", (40, 20), (10, 120, 200))
    exif = Image.Exif()
    if orientation:
        exif[0x0112] = orientation
    sub = exif.get_ifd(0x8769)
    if taken:
        sub[0x9003] = taken
    if offset:
        sub[0x9011] = offset
    exif[0x8825] = {2: (40.0, 26.0, 0.0)}  # a GPS position, which must never survive
    out = io.BytesIO()
    image.save(out, "JPEG", exif=exif)
    return out.getvalue()


def test_the_camera_rotation_is_applied_and_exif_dropped() -> None:
    encoded = encode_library(with_exif(orientation=6, taken="2026:10:01 18:30:00"), NY)
    with Image.open(io.BytesIO(encoded.main)) as image:
        assert image.format == "WEBP"
        assert image.size == (20, 40)  # rotated upright
        assert not image.getexif()
    assert encoded.taken_at == datetime(2026, 10, 1, 22, 30, tzinfo=UTC)  # 18:30 in New York


def test_an_exif_offset_beats_the_household_zone() -> None:
    encoded = encode_library(with_exif(taken="2026:10:01 18:30:00", offset="+01:00"), NY)
    assert encoded.taken_at == datetime(2026, 10, 1, 17, 30, tzinfo=UTC)


def test_big_pictures_shrink_and_avatars_are_square() -> None:
    library = encode_library(picture((5000, 2500)), NY)
    assert (library.width, library.height) == (2560, 1280)
    assert library.thumb is not None
    with Image.open(io.BytesIO(library.thumb)) as thumb:
        assert max(thumb.size) == 400
    avatar = encode_avatar(picture((900, 600)))
    assert (avatar.width, avatar.height) == (512, 512)


def test_heic_from_iphones_can_be_read() -> None:
    assert ".heic" in Image.registered_extensions()


@pytest.fixture
async def store(app: FastAPI) -> PhotoStore:
    return state_of(app).photos


async def test_the_same_picture_twice_is_one_photo(app: FastAPI, store: PhotoStore) -> None:
    state = state_of(app)
    data = picture((300, 200))
    async with state.db.write() as tx:
        first = await store.ingest(
            tx.session, data, kind=PhotoKind.LIBRARY, zone=NY, now=state.clock.now()
        )
    async with state.db.write() as tx:
        first_row = await tx.session.get(type(first), first.id)
        assert first_row is not None
        first_row.deleted_at = state.clock.now()
    async with state.db.write() as tx:
        again = await store.ingest(
            tx.session, data, kind=PhotoKind.LIBRARY, zone=NY, now=state.clock.now()
        )
        assert again.id == first.id
        assert again.deleted_at is None  # removed, then added again: it's back
    assert store.file("library", first.id).is_file()
    assert store.file("thumbs", first.id).is_file()


async def test_reconcile_hides_rows_without_files_and_quarantines_strays(
    app: FastAPI, store: PhotoStore
) -> None:
    state = state_of(app)
    async with state.db.write() as tx:
        kept = await store.ingest(
            tx.session, picture((30, 30)), kind=PhotoKind.LIBRARY, zone=NY, now=state.clock.now()
        )
        lost = await store.ingest(
            tx.session, picture((31, 30)), kind=PhotoKind.LIBRARY, zone=NY, now=state.clock.now()
        )
    store.file("library", lost.id).unlink()
    stray = store.root / "library" / "01890000-0000-7000-8000-00000000abcd.webp"
    stray.write_bytes(b"orphan")
    async with state.db.write() as tx:
        hidden, moved = await store.reconcile(tx.session)
    assert (hidden, moved) == (1, 1)
    assert not stray.exists()
    assert (store.root / ".orphans" / f"library-{stray.name}").exists()
    assert store.file("library", kept.id).is_file()


async def test_upload_list_hide_remove_and_restore(parent: httpx.AsyncClient) -> None:
    uploaded = await parent.post(
        "/api/photos",
        content=picture((800, 600)),
        headers=CSRF | {"content-type": "image/jpeg", "x-filename": "beach.jpg"},
    )
    assert uploaded.status_code == 201, uploaded.text
    photo = uploaded.json()
    assert photo["kind"] == "library"
    assert photo["url"] == f"/photos/library/{photo['id']}.webp"
    assert (await parent.get(photo["thumb_url"])).status_code == 200
    page = (await parent.get("/api/photos")).json()
    assert [p["id"] for p in page["photos"]] == [photo["id"]]
    assert page["next_cursor"] is None
    hidden = await parent.post(f"/api/photos/{photo['id']}/hide", headers=CSRF)
    assert hidden.json()["hidden"] is True
    assert (await parent.delete(f"/api/photos/{photo['id']}", headers=CSRF)).status_code == 204
    assert (await parent.get("/api/photos")).json()["photos"] == []
    restored = await parent.post(f"/api/photos/{photo['id']}/restore", headers=CSRF)
    assert restored.status_code == 200
    assert len((await parent.get("/api/photos")).json()["photos"]) == 1


async def test_a_photo_library_s_photo_is_hidden_never_removed_one_by_one(
    app: FastAPI, parent: httpx.AsyncClient, store: PhotoStore
) -> None:
    """Its library's next pass would bring it back (ADR 0036): hide it, or change the library."""
    state = state_of(app)
    async with state.db.write() as tx:
        photo = await store.ingest(
            tx.session,
            picture((60, 40)),
            kind=PhotoKind.LIBRARY,
            zone=NY,
            now=state.clock.now(),
            source_key="source:01890000-0000-7000-8000-00000000beef",
            taken_at=datetime(2026, 7, 4, 15, 0, tzinfo=UTC),
        )
    listed = (await parent.get("/api/photos")).json()["photos"]
    assert [(p["id"], p["source_key"]) for p in listed] == [
        (photo.id, "source:01890000-0000-7000-8000-00000000beef")
    ]
    # Dated from the library's record: the picture itself has no EXIF.
    assert listed[0]["taken_at"] == "2026-07-04T15:00:00Z"
    refused = await parent.delete(f"/api/photos/{photo.id}", headers=CSRF)
    assert refused.status_code == 409
    assert refused.json()["error"] == {
        "code": "from_library",
        "message": "This photo comes from a photo library. Hide it from the screensaver "
        "instead, or take it out of the library.",
        "key": "api.photos.from_library",
        "params": {},
    }
    hidden = await parent.post(f"/api/photos/{photo.id}/hide", headers=CSRF)
    assert hidden.status_code == 200 and hidden.json()["hidden"] is True


async def test_uploads_are_capped_per_device(
    parent: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("sunroom.photos.router.UPLOADS_PER_HOUR", 2)
    for size in ((10, 10), (11, 10)):
        response = await parent.post(
            "/api/photos", content=picture(size), headers=CSRF | {"content-type": "image/png"}
        )
        assert response.status_code == 201
    third = await parent.post(
        "/api/photos", content=picture((12, 10)), headers=CSRF | {"content-type": "image/png"}
    )
    assert third.status_code == 429


async def test_a_full_disk_says_so(
    parent: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def almost_full(self: PhotoStore) -> int:
        return 1024

    monkeypatch.setattr(PhotoStore, "free_bytes", almost_full)
    response = await parent.post(
        "/api/photos", content=picture(), headers=CSRF | {"content-type": "image/jpeg"}
    )
    assert response.status_code == 507
    assert response.json()["error"]["message"].startswith("Photos need room.")
