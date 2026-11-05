"""Finding a Sunroom (discovery.py) against pretend servers: new and older ones, what typed
addresses become, the sweep's networks and its cap, the advertised address preferred, and the
re-find by id. No network. Synthetic data only."""

from __future__ import annotations

import ipaddress
from collections.abc import Callable
from typing import Any

import pytest

from sunroom_kiosk.discovery import (
    MOST_HOSTS,
    CheckFailedError,
    Discovery,
    FakeDiscovery,
    candidates,
    check,
    subnets,
    targets,
)
from tests.support import SUNROOM, SUNROOM_ID, FakeSunrooms


def events() -> tuple[list[tuple[str, Any]], Callable[[str, Any], None]]:
    seen: list[tuple[str, Any]] = []

    def publish(kind: str, data: Any) -> None:
        seen.append((kind, data))

    return seen, publish


@pytest.mark.parametrize(
    ("typed", "tries"),
    [
        ("calendar.example.com", ["https://calendar.example.com", "http://calendar.example.com"]),
        ("192.168.1.20:7867", ["http://192.168.1.20:7867", "https://192.168.1.20:7867"]),
        ("sunroom.local:7867/", ["http://sunroom.local:7867", "https://sunroom.local:7867"]),
        ("nas:7867", ["http://nas:7867", "https://nas:7867"]),
        ("https://calendar.example.com/", ["https://calendar.example.com"]),
        ("HTTP://192.168.1.20", ["HTTP://192.168.1.20"]),
        ("ftp://192.168.1.20", []),
        ("two words", []),
        ("", []),
    ],
)
def test_what_a_typed_address_becomes(typed: str, tries: list[str]) -> None:
    assert candidates(typed) == tries


async def test_a_new_and_an_older_sunroom_are_both_recognised(sunrooms: FakeSunrooms) -> None:
    sunrooms.older["http://192.168.1.22:7867"] = "0.11.0"
    async with sunrooms.client() as client:
        new = await check(client, SUNROOM)
        older = await check(client, "192.168.1.22:7867")
    assert (new.id, new.name, new.version, new.older) == (
        SUNROOM_ID,
        "The Sample Family",
        "0.13.0",
        False,
    )
    assert (older.id, older.name, older.version, older.older) == (None, None, "0.11.0", True)


async def test_what_isnt_a_sunroom_is_said_plainly(sunrooms: FakeSunrooms) -> None:
    sunrooms.other.add("http://192.168.1.1")
    async with sunrooms.client() as client:
        with pytest.raises(CheckFailedError, match="isn't a Sunroom"):
            await check(client, "192.168.1.1")
        with pytest.raises(CheckFailedError, match="Can't reach that address from here"):
            await check(client, "calendar.example.com")
        with pytest.raises(CheckFailedError, match="isn't an address"):
            await check(client, "ftp://192.168.1.20")


def test_the_sweep_looks_at_this_screens_networks_only() -> None:
    networks = subnets(
        [
            ("192.168.1.30", 24),
            ("127.0.0.1", 8),  # loopback: never
            ("169.254.10.2", 16),  # link-local: never
            ("10.0.0.5", 8),  # a huge network: the 1024 around this screen
            ("192.168.1.31", 24),  # the same network twice: once
            ("fe80::1", 64),  # IPv6: not swept
        ]
    )
    assert networks == [
        ipaddress.IPv4Network("192.168.1.0/24"),
        ipaddress.IPv4Network("10.0.0.0/22"),
    ]
    assert networks[1].num_addresses == MOST_HOSTS


def test_each_host_is_asked_on_three_ports() -> None:
    bases = targets([ipaddress.IPv4Network("192.168.1.0/30")])
    assert bases == [
        "http://192.168.1.1:7867",
        "http://192.168.1.1",
        "https://192.168.1.1",
        "http://192.168.1.2:7867",
        "http://192.168.1.2",
        "https://192.168.1.2",
    ]


async def test_a_scan_finds_each_sunroom_once_and_says_when_its_done(
    sunrooms: FakeSunrooms,
) -> None:
    sunrooms.older["http://192.168.1.22:7867"] = "0.11.0"
    seen, publish = events()

    async def announced(seconds: float) -> list[str]:
        return [SUNROOM]  # the same server, heard over mDNS too

    discovery = Discovery(
        publish,
        client=sunrooms.client,
        addresses=lambda: [("192.168.1.30", 24)],
        announced=announced,
    )
    found = await discovery.scan()
    assert sorted(f.url for f in found) == [SUNROOM, "http://192.168.1.22:7867"]
    kinds = [kind for kind, _ in seen]
    assert kinds[0] == "discovery.started" and kinds[-1] == "discovery.done"
    assert kinds.count("discovery.found") == 2
    assert discovery.scanning is False


async def test_the_advertised_address_wins_when_it_is_the_same_sunroom(
    sunrooms: FakeSunrooms,
) -> None:
    name = "http://sunroom.local:7867"
    sunrooms.new[SUNROOM]["url"] = name
    sunrooms.new[name] = dict(sunrooms.new[SUNROOM])
    _, publish = events()
    discovery = Discovery(publish, client=sunrooms.client, addresses=lambda: [("192.168.1.30", 24)])
    discovery.announced = _none
    found = await discovery.scan()
    assert [f.url for f in found] == [name]


async def test_an_advertised_address_of_another_server_is_ignored(sunrooms: FakeSunrooms) -> None:
    sunrooms.new[SUNROOM]["url"] = "http://elsewhere.local:7867"
    sunrooms.new["http://elsewhere.local:7867"] = {
        **sunrooms.new[SUNROOM],
        "id": "00000000-0000-7000-8000-0000000000e2",
    }
    _, publish = events()
    discovery = Discovery(publish, client=sunrooms.client, addresses=lambda: [("192.168.1.30", 24)])
    discovery.announced = _none
    assert [f.url for f in await discovery.scan()] == [SUNROOM]


async def test_a_moved_sunroom_is_found_again_by_its_id(sunrooms: FakeSunrooms) -> None:
    moved = "http://192.168.1.44:7867"
    sunrooms.new[moved] = sunrooms.new.pop(SUNROOM)
    _, publish = events()
    discovery = Discovery(publish, client=sunrooms.client, addresses=lambda: [("192.168.1.30", 24)])
    discovery.announced = _none
    again = await discovery.refind(SUNROOM_ID)
    assert again is not None and again.url == moved
    assert await discovery.refind("00000000-0000-7000-8000-0000000000ff") is None


async def test_the_fake_finds_what_it_is_given_and_an_older_one(sunrooms: FakeSunrooms) -> None:
    _, publish = events()
    fake = FakeDiscovery(publish, [SUNROOM])
    fake.client = sunrooms.client
    fake.pause_s = 0
    found = await fake.scan()
    assert [f.url for f in found] == [SUNROOM, "http://198.51.100.21:7867"]
    assert found[1].older and found[1].version == "0.11.0"
    assert (await fake.check("http://198.51.100.21:7867/")).older


async def _none(seconds: float) -> list[str]:
    return []
