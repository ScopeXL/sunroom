"""The town search behind Settings → Household → Location (PLAN §11.3, §12.7; ADR 0010): places
from a recorded-style Open-Meteo answer, each named once; ten searches a minute for each device;
parents only; a search that fails says so. Synthetic places only."""

from __future__ import annotations

from typing import Literal

import httpx
import pytest

from sunroom.core.clock import FakeClock
from sunroom.plugins.context import PluginContext
from tests.support import CSRF
from tests.weather.helpers import (
    PUBLIC,
    SEARCH_HOST,
    Family,
    OpenMeteo,
    error,
    tapped,
)

TOO_MANY = (429, "rate_limited", "That's a lot of searches. Try again in a minute.")
FAILED = (502, "unreachable", "The place search didn't answer. Try again in a minute.")


async def search(
    client: httpx.AsyncClient, q: str, headers: dict[str, str] | None = None
) -> httpx.Response:
    return await client.get("/api/weather/geocode", params={"q": q}, headers=headers)


async def test_the_search_names_each_place_once(
    parent: httpx.AsyncClient, ctx: PluginContext, open_meteo: OpenMeteo
) -> None:
    found = await search(parent, "Sample")
    assert found.status_code == 200, found.text
    assert found.json() == [
        {
            "label": "Sample Town, Sample State, United States",
            "latitude": 40.71,
            "longitude": -74.01,
            "timezone": "America/New_York",
        },
        {
            "label": "Sample Village, Sample State, United States",
            "latitude": 41.02,
            "longitude": -73.62,
            "timezone": "America/New_York",
        },
        {  # its region has its name: said once
            "label": "Sampleton, United Kingdom",
            "latitude": 52.0,
            "longitude": 0.5,
            "timezone": "Europe/London",
        },
        {  # no region sent
            "label": "Sample Bay, United Kingdom",
            "latitude": 50.1,
            "longitude": -5.1,
            "timezone": "Europe/London",
        },
        {
            "label": "Sample Harbour, Sample Province, Canada",
            "latitude": 44.6,
            "longitude": -63.6,
            "timezone": "America/Halifax",
        },
    ]
    [request] = open_meteo.requests
    assert (request.headers["host"], request.url.host, request.url.path) == (
        SEARCH_HOST,
        PUBLIC,
        "/v1/search",
    )
    assert dict(request.url.params) == {
        "name": "Sample",
        "count": "5",
        "language": "en",
        "format": "json",
    }


async def test_places_are_named_in_the_households_language(
    parent: httpx.AsyncClient, ctx: PluginContext, open_meteo: OpenMeteo
) -> None:
    """Open-Meteo names places in the language it's asked for (ADR 0043): the household's,
    from Settings → Household → Language."""
    spanish = await parent.patch("/api/settings", json={"language": "es"}, headers=CSRF)
    assert spanish.status_code == 200, spanish.text
    assert (await search(parent, "Sample")).status_code == 200
    [request] = open_meteo.requests
    assert request.url.params["language"] == "es"


async def test_what_is_typed_is_sent_tidied(
    parent: httpx.AsyncClient, ctx: PluginContext, open_meteo: OpenMeteo
) -> None:
    found = await search(parent, "  Sample   Town ")
    assert found.status_code == 200, found.text
    [request] = open_meteo.requests
    assert request.url.params["name"] == "Sample Town"
    assert "name=Sample%20Town" in str(request.url)
    # Spaces around one letter aren't a search: nothing is asked.
    assert (await search(parent, "  a ")).json() == []
    assert len(open_meteo.requests) == 1


async def test_a_search_that_finds_nothing_is_an_empty_list(
    parent: httpx.AsyncClient, ctx: PluginContext, open_meteo: OpenMeteo
) -> None:
    open_meteo.places = {"generationtime_ms": 0.31}  # Open-Meteo leaves "results" out
    found = await search(parent, "Nowhere at all")
    assert (found.status_code, found.json()) == (200, [])


async def test_thirty_searches_a_minute_for_each_device(
    parent: httpx.AsyncClient,
    ctx: PluginContext,
    screen: httpx.AsyncClient,
    family: Family,
    open_meteo: OpenMeteo,
    clock: FakeClock,
) -> None:
    # The field searches as you type (ADR 0030): a name is a few searches, so thirty a minute.
    for _ in range(30):
        assert (await search(parent, "Sample")).status_code == 200
    one_more = await search(parent, "Sample")
    assert error(one_more) == TOO_MANY
    assert one_more.headers["retry-after"] == "60"
    assert len(open_meteo.requests) == 30  # the refused one asked nothing
    # Another device has its own thirty (the wall, a parent while there's no PIN).
    assert (await search(screen, "Sample", tapped(family.sam))).status_code == 200
    clock.advance(seconds=30)
    assert error(await search(parent, "Sample")) == TOO_MANY
    clock.advance(seconds=31)
    assert (await search(parent, "Sample")).status_code == 200


async def test_only_a_parent_searches(
    parent: httpx.AsyncClient,
    ctx: PluginContext,
    screen: httpx.AsyncClient,
    kid_phone: httpx.AsyncClient,
    family: Family,
    open_meteo: OpenMeteo,
) -> None:
    pin = (403, "parent_required", "Only a parent can do that. Enter the parent PIN.")
    assert error(await search(kid_phone, "Sample")) == pin
    assert error(await search(screen, "Sample", tapped(family.ana))) == pin  # a PIN is set
    assert open_meteo.requests == []
    assert (await search(parent, "Sample")).status_code == 200


@pytest.mark.parametrize("failing", ["down", "refused", "html"])
async def test_a_search_that_fails_says_so(
    parent: httpx.AsyncClient,
    ctx: PluginContext,
    open_meteo: OpenMeteo,
    failing: Literal["down", "refused", "html"],
) -> None:
    open_meteo.failing = failing
    assert error(await search(parent, "Sample")) == FAILED


async def test_an_answer_sunroom_cant_read_fails_but_one_odd_place_is_skipped(
    parent: httpx.AsyncClient, ctx: PluginContext, open_meteo: OpenMeteo
) -> None:
    first = open_meteo.places["results"][0]
    open_meteo.places = {"results": "Sample Town"}
    assert error(await search(parent, "Sample")) == FAILED
    open_meteo.places = {"results": [{"name": "Sample Nowhere"}, first]}  # one without a place
    found = await search(parent, "Sample")
    assert found.status_code == 200, found.text
    assert [place["label"] for place in found.json()] == [
        "Sample Town, Sample State, United States"
    ]


async def test_a_search_is_two_to_eighty_letters(
    parent: httpx.AsyncClient, ctx: PluginContext, open_meteo: OpenMeteo
) -> None:
    for q in ("a", "x" * 81):
        assert error(await search(parent, q))[:2] == (422, "invalid")
    missing = await parent.get("/api/weather/geocode", headers=CSRF)
    assert (missing.status_code, missing.json()["error"]["fields"]) == (422, ["q"])
    assert open_meteo.requests == []
    for q in ("ab", "x" * 80):
        assert (await search(parent, q)).status_code == 200
    assert len(open_meteo.requests) == 2
