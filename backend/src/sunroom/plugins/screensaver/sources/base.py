"""What a photo library is to Sunroom (ADR 0036): the kinds the screens offer, and the five
things every library does. Everything after a photo is fetched (the import into core's store,
the cap, the diff, the status, the problems, the screens) knows nothing of the kind.

A library is reached with the plugin's guarded client (``PluginHttp``), its base address
("http://192.168.1.30:2283") and its key, all passed in on each call: nothing here keeps state.
Its failures are ``LibraryError``s with a plain sentence for a parent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Protocol

from sunroom.core.lang import Words, plain, t_en
from sunroom.plugins.context import PluginHttp

LibraryErrorCode = Literal[
    "auth",  # the key was refused
    "forbidden",  # the key can't read what Sunroom needs
    "not_a_library",  # the address answers, but isn't this kind of server
    "too_old",  # a version Sunroom doesn't work with
    "private_address",  # on the home network, and not allowed (the guard's sentence)
    "unreachable",  # not found, not answering, refused
    "bad_reply",  # an answer Sunroom couldn't read
    "not_found",  # no such person or photo there (any more)
]


class LibraryError(Exception):
    """A library that said no, or couldn't be asked: ``key`` names the sentence for a parent in
    ``lang/en.json`` (ADR 0043), and ``message`` is its English."""

    def __init__(self, code: LibraryErrorCode, key: str, **params: object) -> None:
        self.code: LibraryErrorCode = code
        self.key = key
        self.params = plain(params)
        self.message = t_en(key, **self.params)
        super().__init__(self.message)

    @property
    def words(self) -> Words:
        return Words(self.key, self.params)


@dataclass(frozen=True, slots=True)
class LibraryKind:
    """A kind of library, as the screens offer it."""

    kind: str  # "immich"
    name: str  # "Immich"
    placeholder: str  # an address like the family's own
    address_hint: str  # under the address field
    key_help: str  # under the key field: where the key comes from


@dataclass(frozen=True, slots=True)
class LibraryInfo:
    """What a check found: the server's own name and version, and how many photos it holds
    when it says (None when the key can't ask)."""

    name: str
    version: str
    photo_count: int | None


@dataclass(frozen=True, slots=True)
class Choice:
    """A person, an album or a tag to pick."""

    id: str
    name: str
    count: int | None  # photos in it, when the library says
    has_thumb: bool  # a face or a cover to show beside it


@dataclass(frozen=True, slots=True)
class Choices:
    people: list[Choice] = field(default_factory=list[Choice])
    albums: list[Choice] = field(default_factory=list[Choice])
    tags: list[Choice] = field(default_factory=list[Choice])
    unnamed_people: int = 0  # faces nobody named: not offered


@dataclass(frozen=True, slots=True)
class Picks:
    """What the family picked, by the library's ids. Any pick matches; none means every photo."""

    people: tuple[str, ...] = ()
    albums: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()

    @property
    def empty(self) -> bool:
        return not (self.people or self.albums or self.tags)


@dataclass(frozen=True, slots=True)
class RemotePhoto:
    id: str
    taken_at: datetime | None  # UTC
    width: int | None
    height: int | None


class Library(Protocol):
    kind: LibraryKind

    async def check(self, http: PluginHttp, url: str, key: str) -> LibraryInfo:
        """That the address is this kind of server, new enough, and the key reads photos."""
        ...

    async def choices(self, http: PluginHttp, url: str, key: str) -> Choices:
        """The people, albums and tags to pick from."""
        ...

    async def find(
        self, http: PluginHttp, url: str, key: str, picks: Picks, limit: int
    ) -> list[RemotePhoto]:
        """The photos the picks want: images only, any pick matching, newest first, at most
        ``limit``."""
        ...

    async def fetch(self, http: PluginHttp, url: str, key: str, photo_id: str) -> bytes:
        """One photo, at the size the screensaver needs (a preview, not the original)."""
        ...

    async def thumb(
        self, http: PluginHttp, url: str, key: str, *, person: str | None, asset: str | None
    ) -> tuple[bytes, str]:
        """A person's face or a photo's small picture, with its media type."""
        ...
