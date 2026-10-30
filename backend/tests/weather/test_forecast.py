"""The weather through its API (PLAN §9, §11.3, §11.4; ADR 0010): the forecast rendered from a
recorded-style Open-Meteo answer with sockets off (the PLAN M4 verify item), what is asked for,
the hour-long cache, failures that keep the last forecast until it's stale, the place and the
units following the settings, Check now, who may do what, live events, the job, and the plugin
switched off. Only this plugin is registered, so it is shown working with every other plugin
off. The fake clock reads Wednesday 2026-10-07, 10:00 in New York. Synthetic data only.
"""

from __future__ import annotations

from typing import Any, Literal

import httpx
import pytest
from fastapi import APIRouter, FastAPI
from fastapi.routing import APIRoute

from sunroom.core.clock import FakeClock
from sunroom.household.models import Household
from sunroom.plugins.base import PluginStatus
from sunroom.plugins.context import PluginContext
from sunroom.plugins.weather import open_meteo as client
from sunroom.plugins.weather import service
from sunroom.plugins.weather.plugin import REFRESH_S, Weather
from tests.support import BASE_URL, CSRF, state_of
from tests.weather.helpers import (
    FORECAST_HOST,
    NO_ANSWER,
    PUBLIC,
    UNREADABLE,
    Family,
    Json,
    OpenMeteo,
    TrackedWeather,
    error,
    eventually,
    set_place,
    set_units,
    settled,
    tapped,
    weather,
)

Events = list[tuple[str, dict[str, Any]]]
WEEK = [f"2026-10-{day:02d}" for day in range(7, 14)]


@pytest.fixture
async def placed(
    app: FastAPI, parent: httpx.AsyncClient, ctx: PluginContext, plugin: TrackedWeather
) -> httpx.AsyncClient:
    """Sample Town set as the household's place, and its forecast in."""
    await set_place(parent)
    await settled(app, plugin)
    return parent


def told(events: Events) -> list[dict[str, Any]]:
    return [payload for kind, payload in events if kind == "weather.changed"]


# ---- the forecast ------------------------------------------------------------------------------


async def test_the_forecast_renders_from_open_meteos_answer(placed: httpx.AsyncClient) -> None:
    shown = await weather(placed)
    assert {key: shown[key] for key in ("status", "location_label", "units", "stale")} == {
        "status": "ok",
        "location_label": "Sample Town",
        "units": "fahrenheit",  # a New York household
        "stale": False,
    }
    assert (shown["fetched_at"], shown["message"]) == ("2026-10-07T14:00:00Z", None)
    # Now: 58.5 °F is 59, as people round (Python's round would say 58).
    assert shown["current"] == {
        "time": "2026-10-07T10:00:00",
        "temperature": 59,
        "code": 2,
        "is_day": True,
    }
    # The next 24 hours from this one, in the household's wall time.
    hours = shown["hourly"]
    assert len(hours) == 24
    assert hours[0] == {
        "time": "2026-10-07T10:00:00",
        "temperature": 58,
        "code": 2,
        "precipitation": 6,
    }
    assert hours[5] == {
        "time": "2026-10-07T15:00:00",
        "temperature": 66,
        "code": 2,
        "precipitation": 10,
    }
    assert hours[-1]["time"] == "2026-10-08T09:00:00"
    # Seven days from today.
    days = shown["daily"]
    assert [day["date"] for day in days] == WEEK
    assert [day["code"] for day in days] == [2, 1, 61, 3, 0, 2, 80]
    assert [day["high"] for day in days] == [66, 69, 61, 59, 63, 65, 64]
    assert [day["low"] for day in days] == [52, 54, 55, 49, 46, 50, 53]
    assert [day["precipitation"] for day in days] == [10, 5, 80, 35, 0, 10, 60]
    assert (days[0]["sunrise"], days[0]["sunset"]) == ("2026-10-07T07:06:00", "2026-10-07T18:30:00")


async def test_it_asks_for_the_households_place_units_and_zone(
    placed: httpx.AsyncClient, open_meteo: OpenMeteo
) -> None:
    [request] = open_meteo.requests
    assert request.headers["host"] == FORECAST_HOST
    assert (request.url.scheme, request.url.host, request.url.path) == (
        "https",
        PUBLIC,  # pinned to the address the guard checked
        "/v1/forecast",
    )
    assert request.headers["user-agent"].startswith("Sunroom/")
    assert dict(request.url.params) == {
        "latitude": "40.71",
        "longitude": "-74.01",
        "current": "temperature_2m,weather_code,is_day",
        "hourly": "temperature_2m,weather_code,precipitation_probability",
        "daily": (
            "weather_code,temperature_2m_max,temperature_2m_min,"
            "precipitation_probability_max,sunrise,sunset"
        ),
        "temperature_unit": "fahrenheit",
        "timezone": "America/New_York",
        "forecast_days": "7",
    }


async def test_without_a_place_nothing_is_asked(
    app: FastAPI,
    parent: httpx.AsyncClient,
    ctx: PluginContext,
    plugin: TrackedWeather,
    open_meteo: OpenMeteo,
) -> None:
    await service.refresh(ctx)
    await service.refresh(ctx, force=True)
    renamed = await parent.patch(
        "/api/settings", json={"household_name": "The Samples"}, headers=CSRF
    )
    assert renamed.status_code == 200, renamed.text
    await settled(app, plugin)
    checked = await parent.post("/api/weather/refresh", headers=CSRF)
    assert checked.status_code == 200, checked.text
    no_location: Json = {
        "status": "no_location",
        "location_label": None,
        "units": "fahrenheit",
        "current": None,
        "hourly": [],
        "daily": [],
        "fetched_at": None,
        "stale": False,
        "message": None,
    }
    assert (checked.json(), await weather(parent)) == (no_location, no_location)
    assert open_meteo.requests == []


async def test_a_forecast_is_kept_for_an_hour_then_asked_for_again(
    app: FastAPI,
    placed: httpx.AsyncClient,
    ctx: PluginContext,
    plugin: TrackedWeather,
    open_meteo: OpenMeteo,
    clock: FakeClock,
) -> None:
    clock.advance(minutes=59)
    await service.refresh(ctx)
    renamed = await placed.patch(
        "/api/settings", json={"household_name": "The Samples"}, headers=CSRF
    )
    assert renamed.status_code == 200, renamed.text
    await settled(app, plugin)
    assert len(open_meteo.asked()) == 1
    clock.advance(minutes=2)
    await service.refresh(ctx)
    assert len(open_meteo.asked()) == 2
    shown = await weather(placed)
    assert (shown["fetched_at"], shown["hourly"][0]["time"]) == (
        "2026-10-07T15:01:00Z",
        "2026-10-07T11:00:00",
    )


async def test_a_failure_keeps_the_last_forecast_until_it_goes_stale(
    placed: httpx.AsyncClient, ctx: PluginContext, open_meteo: OpenMeteo, clock: FakeClock
) -> None:
    open_meteo.failing = "down"
    clock.advance(minutes=61)
    await service.refresh(ctx)
    assert len(open_meteo.asked()) == 2
    shown = await weather(placed)
    assert (shown["status"], shown["stale"], shown["message"]) == ("ok", False, NO_ANSWER)
    assert shown["fetched_at"] == "2026-10-07T14:00:00Z"
    assert shown["current"]["time"] == "2026-10-07T10:00:00"  # what it said then
    assert shown["hourly"][0]["time"] == "2026-10-07T11:00:00"  # from this hour on
    # After a failure it waits five minutes before asking again.
    clock.advance(minutes=4)
    await service.refresh(ctx)
    assert len(open_meteo.asked()) == 2
    # Over three hours on, it's stale ("as of 10:00", with the hint).
    clock.advance(minutes=116)
    await service.refresh(ctx)
    assert len(open_meteo.asked()) == 3
    shown = await weather(placed)
    assert (shown["status"], shown["stale"], shown["fetched_at"]) == (
        "ok",
        True,
        "2026-10-07T14:00:00Z",
    )
    assert [hour["time"] for hour in shown["hourly"][:2]] == [
        "2026-10-07T13:00:00",
        "2026-10-07T14:00:00",
    ]
    assert len(shown["hourly"]) == 24
    # Two days on, the days before today are gone too.
    clock.advance(days=2)
    await service.refresh(ctx)
    shown = await weather(placed)
    assert [day["date"] for day in shown["daily"]] == WEEK[2:]
    assert shown["hourly"][0]["time"] == "2026-10-09T13:00:00"
    # Open-Meteo answers again: fresh, and nothing to say.
    open_meteo.failing = None
    clock.advance(minutes=5)
    await service.refresh(ctx)
    shown = await weather(placed)
    assert (shown["status"], shown["stale"], shown["message"]) == ("ok", False, None)
    assert shown["fetched_at"] == "2026-10-09T17:06:00Z"


@pytest.mark.parametrize(
    ("failing", "message"),
    [
        ("down", NO_ANSWER),
        ("refused", NO_ANSWER),
        ("html", UNREADABLE),
        ("garbage", UNREADABLE),
        ("huge", NO_ANSWER),
    ],
)
async def test_with_nothing_to_show_the_weather_says_why(
    app: FastAPI,
    parent: httpx.AsyncClient,
    ctx: PluginContext,
    plugin: TrackedWeather,
    open_meteo: OpenMeteo,
    monkeypatch: pytest.MonkeyPatch,
    failing: Literal["down", "refused", "html", "garbage", "huge"],
    message: str,
) -> None:
    if failing == "huge":
        monkeypatch.setattr(client, "FORECAST_MAX_BYTES", 1000)  # the fixture is about 7 KB
    else:
        open_meteo.failing = failing
    await set_place(parent)
    await settled(app, plugin)
    assert len(open_meteo.asked()) == 1
    shown = await weather(parent)
    assert {key: shown[key] for key in ("status", "message", "fetched_at", "current")} == {
        "status": "error",
        "message": message,
        "fetched_at": None,
        "current": None,
    }
    assert (shown["hourly"], shown["daily"], shown["location_label"]) == ([], [], "Sample Town")
    assert state_of(app).plugins.status("weather") is PluginStatus.RUNNING


async def test_a_new_place_is_asked_for_when_the_settings_change(
    app: FastAPI,
    placed: httpx.AsyncClient,
    ctx: PluginContext,
    plugin: TrackedWeather,
    open_meteo: OpenMeteo,
) -> None:
    await set_place(placed, latitude=41.02, longitude=-73.62, location_label="Sample Village")
    await settled(app, plugin)
    assert [(asked["latitude"], asked["longitude"]) for asked in open_meteo.asked()] == [
        ("40.71", "-74.01"),
        ("41.02", "-73.62"),
    ]
    shown = await weather(placed)
    assert (shown["status"], shown["location_label"]) == ("ok", "Sample Village")
    # A place the cache hasn't caught up with yet is waiting (moved here without telling the
    # plugin)…
    async with state_of(app).db.write() as tx:
        home = await tx.session.get(Household, 1)
        assert home is not None
        home.latitude, home.longitude = 51.48, 0.0
    assert (await weather(placed))["status"] == "waiting"
    # …and one Open-Meteo doesn't answer for says so, never showing somewhere else's weather.
    open_meteo.failing = "down"
    await service.refresh(ctx)
    shown = await weather(placed)
    assert (shown["status"], shown["message"], shown["daily"]) == ("error", NO_ANSWER, [])
    assert open_meteo.asked()[-1]["latitude"] == "51.48"


async def test_units_follow_the_setting_or_the_households_time_zone(
    app: FastAPI, placed: httpx.AsyncClient, plugin: TrackedWeather, open_meteo: OpenMeteo
) -> None:
    async def units_now(expected_asks: int) -> tuple[str, str, int, list[int]]:
        await settled(app, plugin)
        assert len(open_meteo.asked()) == expected_asks
        shown = await weather(placed)
        last = open_meteo.asked()[-1]
        return (
            shown["units"],
            last["temperature_unit"],
            shown["current"]["temperature"],
            [day["high"] for day in shown["daily"]],
        )

    highs_f = [66, 69, 61, 59, 63, 65, 64]
    highs_c = [19, 21, 16, 15, 17, 19, 18]
    assert await units_now(1) == ("fahrenheit", "fahrenheit", 59, highs_f)
    await set_units(placed, "celsius")
    assert await units_now(2) == ("celsius", "celsius", 15, highs_c)
    await set_units(placed, "fahrenheit")
    assert await units_now(3) == ("fahrenheit", "fahrenheit", 59, highs_f)
    # Chosen °F stays °F in London; "Usual for where you live" there is °C.
    moved = await placed.patch("/api/settings", json={"timezone": "Europe/London"}, headers=CSRF)
    assert moved.status_code == 200, moved.text
    assert await units_now(3) == ("fahrenheit", "fahrenheit", 59, highs_f)
    await set_units(placed, "auto")
    assert await units_now(4) == ("celsius", "celsius", 15, highs_c)
    assert open_meteo.asked()[-1]["timezone"] == "Europe/London"


async def test_a_forecast_in_the_other_units_is_converted_until_the_new_one_comes(
    app: FastAPI, placed: httpx.AsyncClient, plugin: TrackedWeather, open_meteo: OpenMeteo
) -> None:
    open_meteo.failing = "down"
    await set_units(placed, "celsius")
    await settled(app, plugin)
    assert open_meteo.asked()[-1]["temperature_unit"] == "celsius"
    shown = await weather(placed)
    assert (shown["status"], shown["units"], shown["message"]) == ("ok", "celsius", NO_ANSWER)
    # 58.5 °F is 14.7 °C; 66.4 °F, the first high, is 19.1 °C; 46.4 °F, a low, is 8 °C.
    assert shown["current"]["temperature"] == 15
    assert (shown["daily"][0]["high"], shown["daily"][4]["low"]) == (19, 8)


async def test_a_new_time_zone_moves_the_forecasts_times_until_it_is_asked_again(
    app: FastAPI,
    placed: httpx.AsyncClient,
    ctx: PluginContext,
    plugin: TrackedWeather,
    open_meteo: OpenMeteo,
    clock: FakeClock,
) -> None:
    moved = await placed.patch("/api/settings", json={"timezone": "America/Chicago"}, headers=CSRF)
    assert moved.status_code == 200, moved.text
    await settled(app, plugin)
    assert len(open_meteo.asked()) == 1  # the same place and units, within the hour
    shown = await weather(placed)
    assert shown["current"]["time"] == "2026-10-07T09:00:00"
    assert shown["hourly"][0] == {
        "time": "2026-10-07T09:00:00",  # 10 AM in New York
        "temperature": 58,
        "code": 2,
        "precipitation": 6,
    }
    assert shown["daily"][0]["sunrise"] == "2026-10-07T06:06:00"
    clock.advance(minutes=61)
    await service.refresh(ctx)
    assert open_meteo.asked()[-1]["timezone"] == "America/Chicago"
    assert (await weather(placed))["current"]["time"] == "2026-10-07T10:00:00"


# ---- Check now ---------------------------------------------------------------------------------


async def test_check_now_asks_again_at_most_once_a_minute(
    placed: httpx.AsyncClient, open_meteo: OpenMeteo, clock: FakeClock
) -> None:
    too_soon = await placed.post("/api/weather/refresh", headers=CSRF)
    assert error(too_soon) == (429, "too_soon", "It just checked. Try again in a minute.")
    assert too_soon.headers["retry-after"] == "60"
    clock.advance(seconds=61)
    checked = await placed.post("/api/weather/refresh", headers=CSRF)
    assert checked.status_code == 200, checked.text
    assert (checked.json()["status"], checked.json()["fetched_at"]) == (
        "ok",
        "2026-10-07T14:01:01Z",
    )
    assert len(open_meteo.asked()) == 2  # asked within the hour, because a parent asked
    assert (await placed.post("/api/weather/refresh", headers=CSRF)).status_code == 429
    # A check that fails counts as a check too, and says why over the last forecast.
    open_meteo.failing = "down"
    clock.advance(seconds=61)
    failed = await placed.post("/api/weather/refresh", headers=CSRF)
    assert failed.status_code == 200, failed.text
    assert (failed.json()["status"], failed.json()["message"]) == ("ok", NO_ANSWER)
    assert (await placed.post("/api/weather/refresh", headers=CSRF)).status_code == 429
    assert len(open_meteo.asked()) == 3


# ---- who may do what ---------------------------------------------------------------------------


async def test_the_wall_and_a_kids_phone_read_it_but_only_a_parent_checks_again(
    placed: httpx.AsyncClient,
    screen: httpx.AsyncClient,
    kid_phone: httpx.AsyncClient,
    family: Family,
) -> None:
    on_the_wall = await weather(screen, headers=tapped(family.mia))
    assert (on_the_wall["status"], on_the_wall["current"]["temperature"]) == ("ok", 59)
    assert await weather(kid_phone) == on_the_wall
    pin = (403, "parent_required", "Only a parent can do that. Enter the parent PIN.")
    # With a PIN set, neither the wall (whoever tapped) nor a kid's phone is a parent.
    assert error(await screen.post("/api/weather/refresh", headers=tapped(family.ana))) == pin
    assert error(await kid_phone.post("/api/weather/refresh", headers=CSRF)) == pin


async def test_without_a_pin_the_wall_checks_again(
    placed: httpx.AsyncClient,
    screen: httpx.AsyncClient,
    family: Family,
    open_meteo: OpenMeteo,
    clock: FakeClock,
) -> None:
    clock.advance(seconds=61)
    checked = await screen.post("/api/weather/refresh", headers=tapped(family.leo))
    assert checked.status_code == 200, checked.text
    assert len(open_meteo.asked()) == 2


async def test_weather_needs_a_signed_in_device(app: FastAPI, parent: httpx.AsyncClient) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as stranger:
        response = await stranger.get("/api/weather")
    assert error(response)[:2] == (401, "signed_out")


# ---- live events, the job, starting, switched off ----------------------------------------------


async def test_every_screen_hears_of_a_new_forecast_and_of_a_failure(
    app: FastAPI,
    parent: httpx.AsyncClient,
    ctx: PluginContext,
    plugin: TrackedWeather,
    open_meteo: OpenMeteo,
    clock: FakeClock,
    events: Events,
) -> None:
    await set_place(parent)
    await settled(app, plugin)
    assert told(events) == [{}]
    await weather(parent)
    await service.refresh(ctx)  # nothing to ask
    assert told(events) == [{}]  # reading tells nobody
    open_meteo.failing = "down"
    clock.advance(minutes=61)
    await service.refresh(ctx)
    assert told(events) == [{}, {}]
    clock.advance(minutes=1)
    await service.refresh(ctx)  # waits after a failure: nothing asked, nothing to tell
    assert told(events) == [{}, {}]
    assert len(open_meteo.asked()) == 2


async def test_the_refresh_job_runs_as_weather_starts_and_every_half_hour(
    app: FastAPI,
    placed: httpx.AsyncClient,
    plugin: TrackedWeather,
    open_meteo: OpenMeteo,
    clock: FakeClock,
) -> None:
    manager = state_of(app).plugins
    runner = manager._live["weather"].runner
    assert runner is not None
    assert (list(runner.jobs), REFRESH_S) == (["refresh"], 30 * 60)
    job = runner.jobs["refresh"]
    await job()  # within the hour: nothing to ask
    assert len(open_meteo.asked()) == 1
    clock.advance(minutes=61)
    await job()
    assert len(open_meteo.asked()) == 2
    # Open-Meteo failing never stops the plugin, however it's woken (a restart asks at once).
    open_meteo.failing = "down"
    clock.advance(minutes=61)
    restarted = await placed.post("/api/plugins/weather/restart", headers=CSRF)
    assert restarted.status_code == 200, restarted.text
    await eventually(lambda: len(open_meteo.asked()) == 3)
    await eventually(lambda: manager.status("weather") is PluginStatus.RUNNING)
    await settled(app, plugin)
    assert (manager.status("weather"), manager.error("weather")) == (PluginStatus.RUNNING, None)
    assert (await weather(placed))["message"] == NO_ANSWER


async def test_while_weather_starts_a_request_asks_to_try_again(
    placed: httpx.AsyncClient, plugin: TrackedWeather
) -> None:
    ctx, plugin.ctx = plugin.ctx, None
    try:
        response = await placed.get("/api/weather")
    finally:
        plugin.ctx = ctx
    assert error(response) == (503, "starting", "Weather is still starting. Try again.")


async def test_off_every_route_is_404_and_on_again_the_forecast_is_there(
    app: FastAPI, placed: httpx.AsyncClient, plugin: TrackedWeather, open_meteo: OpenMeteo
) -> None:
    before: Json = await weather(placed)
    off = await placed.post("/api/plugins/weather/disable", headers=CSRF)
    assert off.status_code == 200, off.text
    assert off.json()["enabled"] is False
    routes = APIRouter()
    Weather().register_routes(routes)
    answered: list[tuple[str, str]] = []
    for route in routes.routes:
        assert isinstance(route, APIRoute)
        for method in sorted(route.methods or ()):
            response = await placed.request(method, f"/api/weather{route.path}", headers=CSRF)
            assert response.status_code == 404, (method, route.path)
            assert response.json()["error"] == {
                "code": "plugin_disabled",
                "message": "Weather is turned off. A parent can turn it on in Settings.",
                "key": "api.plugins.turned_off",
                "params": {"name": "Weather"},
            }
            answered.append((method, route.path))
    assert sorted(answered) == [("GET", ""), ("GET", "/geocode"), ("POST", "/refresh")]
    on = await placed.post("/api/plugins/weather/enable", headers=CSRF)
    assert on.status_code == 200, on.text
    manager = state_of(app).plugins
    await eventually(lambda: manager.status("weather") is PluginStatus.RUNNING)
    await settled(app, plugin)
    assert await weather(placed) == before
    assert len(open_meteo.asked()) == 1  # still fresh: nothing asked on the way back
