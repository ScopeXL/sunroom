"""A pretend Immich for the test server and its screens (ADR 0036): the Sample Family's faces (and
two nobody named), three albums, two tags and twelve photos, all made up and drawn here. It answers
only in test mode, only at ``http://immich.test`` and only to the key ``sample-key``: the repo
never meets a real Immich (the registry picks this one; nothing goes over the network).
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import cache
from urllib.parse import urlsplit

from PIL import Image, ImageDraw, ImageFont

from sunroom.plugins.context import PluginHttp
from sunroom.plugins.screensaver.sources.base import (
    Choice,
    Choices,
    LibraryError,
    LibraryInfo,
    Picks,
    RemotePhoto,
)
from sunroom.plugins.screensaver.sources.immich import AUTH, GONE, KIND, newest_first

FAKE_HOST = "immich.test"
FAKE_URL = "http://immich.test"
FAKE_KEY = "sample-key"
SIZE = (1440, 960)
NEWEST = datetime(2026, 10, 1, 15, 0, tzinfo=UTC)

PEOPLE = (
    ("p-ana", "Ana"),
    ("p-sam", "Sam"),
    ("p-mia", "Mia"),
    ("p-leo", "Leo"),
    ("p-unnamed-1", ""),
    ("p-unnamed-2", ""),
)
ALBUMS = (("a-beach", "Beach 2026"), ("a-street", "Sample Street"), ("a-birthdays", "Birthdays"))
TAGS = (("t-wall", "Wall"), ("t-favorites", "Favorites"))
COLORS = (
    (190, 214, 230),
    (232, 205, 170),
    (200, 222, 196),
    (226, 196, 206),
    (214, 206, 232),
    (236, 222, 182),
    (180, 210, 214),
    (230, 190, 174),
    (204, 214, 180),
    (220, 200, 226),
    (196, 206, 222),
    (238, 214, 196),
)


@dataclass(frozen=True, slots=True)
class FakePhoto:
    id: str
    number: int
    people: tuple[str, ...]
    albums: tuple[str, ...]
    tags: tuple[str, ...]

    @property
    def taken_at(self) -> datetime:
        """A month apart, the newest on October 1."""
        return NEWEST - timedelta(days=30 * (self.number - 1))


PHOTOS = (
    FakePhoto("r-01", 1, ("p-mia", "p-leo"), ("a-beach",), ("t-wall",)),
    FakePhoto("r-02", 2, ("p-mia",), (), ("t-favorites",)),
    FakePhoto("r-03", 3, ("p-ana", "p-sam"), ("a-street",), ()),
    FakePhoto("r-04", 4, ("p-leo",), ("a-beach",), ()),
    FakePhoto("r-05", 5, (), ("a-street",), ("t-wall",)),
    FakePhoto("r-06", 6, ("p-mia", "p-unnamed-1"), ("a-birthdays",), ()),
    FakePhoto("r-07", 7, ("p-sam",), (), ()),
    FakePhoto("r-08", 8, ("p-leo", "p-unnamed-2"), ("a-birthdays",), ("t-favorites",)),
    FakePhoto("r-09", 9, (), ("a-beach",), ()),
    FakePhoto("r-10", 10, ("p-ana",), (), ("t-wall",)),
    FakePhoto("r-11", 11, ("p-mia", "p-leo", "p-sam", "p-ana"), ("a-birthdays",), ()),
    FakePhoto("r-12", 12, (), (), ()),
)


def _jpeg(image: Image.Image) -> bytes:
    out = io.BytesIO()
    image.save(out, format="JPEG", quality=85)
    return out.getvalue()


@cache
def picture(number: int) -> bytes:
    """A flat color with its number in the middle: synthetic, and different every time."""
    image = Image.new("RGB", SIZE, COLORS[(number - 1) % len(COLORS)])
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=320)
    draw.text((SIZE[0] / 2, SIZE[1] / 2), str(number), fill=(70, 70, 80), font=font, anchor="mm")
    return _jpeg(image)


@cache
def face(index: int) -> bytes:
    """A small circle in a color of its own: no one's face."""
    image = Image.new("RGB", (256, 256), (238, 236, 230))
    ImageDraw.Draw(image).ellipse((28, 28, 228, 228), fill=COLORS[(index * 5) % len(COLORS)])
    return _jpeg(image)


def _check_place(url: str, key: str) -> None:
    if (urlsplit(url).hostname or "") != FAKE_HOST:
        raise LibraryError("unreachable", "api.network.not_found")
    if key != FAKE_KEY:
        raise LibraryError("auth", AUTH)


def _count(predicate_id: str, kind: str) -> int:
    return sum(1 for photo in PHOTOS if predicate_id in getattr(photo, kind))


class FakeLibrary:
    kind = KIND

    async def check(self, http: PluginHttp, url: str, key: str) -> LibraryInfo:
        _check_place(url, key)
        return LibraryInfo("Immich", "2.7.5", len(PHOTOS))

    async def choices(self, http: PluginHttp, url: str, key: str) -> Choices:
        _check_place(url, key)
        named = [Choice(pid, name, _count(pid, "people"), True) for pid, name in PEOPLE if name]
        return Choices(
            people=named,
            albums=sorted(
                (Choice(aid, name, _count(aid, "albums"), True) for aid, name in ALBUMS),
                key=lambda c: c.name.casefold(),
            ),
            tags=sorted(
                (Choice(tid, name, None, False) for tid, name in TAGS),
                key=lambda c: c.name.casefold(),
            ),
            unnamed_people=sum(1 for _pid, name in PEOPLE if not name),
        )

    async def find(
        self, http: PluginHttp, url: str, key: str, picks: Picks, limit: int
    ) -> list[RemotePhoto]:
        _check_place(url, key)
        wanted = [
            photo
            for photo in PHOTOS
            if picks.empty
            or set(photo.people) & set(picks.people)
            or set(photo.albums) & set(picks.albums)
            or set(photo.tags) & set(picks.tags)
        ]
        found = [RemotePhoto(p.id, p.taken_at, SIZE[0], SIZE[1]) for p in wanted]
        return newest_first(found)[:limit]

    async def fetch(self, http: PluginHttp, url: str, key: str, photo_id: str) -> bytes:
        _check_place(url, key)
        photo = next((p for p in PHOTOS if p.id == photo_id), None)
        if photo is None:
            raise LibraryError("not_found", GONE)
        return picture(photo.number)

    async def thumb(
        self, http: PluginHttp, url: str, key: str, *, person: str | None, asset: str | None
    ) -> tuple[bytes, str]:
        _check_place(url, key)
        if person is not None:
            index = next((i for i, (pid, _name) in enumerate(PEOPLE) if pid == person), None)
            if index is None:
                raise LibraryError("not_found", GONE)
            return face(index), "image/jpeg"
        photo = next((p for p in PHOTOS if p.id == asset), None)
        if photo is None:
            raise LibraryError("not_found", GONE)
        return picture(photo.number), "image/jpeg"
