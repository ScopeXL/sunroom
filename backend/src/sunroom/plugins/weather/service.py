"""The weather (PLAN §9, §11.3, §11.4; ADR 0010): Open-Meteo's forecast for the household's place
(Settings → Household → Location), kept in one cache row so the wall has weather straight after
a restart and keeps the last forecast ("as of 9:10") while Open-Meteo doesn't answer.

``refresh`` runs every 30 minutes and on every settings change. It asks only when the cache is
for another place or other units, or is over an hour old; after a failure it waits five minutes
before asking again (Check now doesn't wait, but asks at most once a minute). Every answer and
every failure publishes ``weather.changed``. ``weather`` reads the cache for the rail block, the
day headers, the screensaver corner and the phone's Today header.

The test server never touches the network: ``fake`` makes up its forecast and places.
"""

from __future__ import annotations

import json
import math
from collections import deque
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx

from sunroom.core.errors import AppError
from sunroom.core.logging import get_logger
from sunroom.core.netguard import OutboundError
from sunroom.domain.timeparts import from_local, to_local
from sunroom.plugins.context import HouseholdView, PluginContext
from sunroom.plugins.weather import fake, open_meteo
from sunroom.plugins.weather.models import WeatherCache
from sunroom.plugins.weather.schemas import (
    ForecastDayOut,
    ForecastHourOut,
    PlaceOut,
    Units,
    WeatherNowOut,
    WeatherOut,
)

log = get_logger(__name__)

Status = Literal["ok", "no_location", "waiting", "error"]
Place = tuple[float, float]  # latitude, longitude

EVENT = "weather.changed"
KEEP_FOR = timedelta(minutes=60)  # a forecast is good for an hour (PLAN §11.4)
RETRY_AFTER = timedelta(minutes=5)  # after a failure
STALE_AFTER = timedelta(hours=3)  # then the wall adds a hint to "as of 9:10"
CHECK_EVERY = timedelta(minutes=1)  # Check now, at most once a minute
SEARCHES = 30  # city searches a minute, for each device: the field searches as you type
SEARCH_WINDOW = timedelta(minutes=1)
HOURS = 24
DAYS = 7

NO_ANSWER = "Open-Meteo didn't answer."
UNREADABLE = "Open-Meteo sent something Sunroom couldn't read."
SEARCH_FAILED = "api.weather.search_failed"

# °F is usual in the United States and its territories, °C everywhere else; "auto" goes by the
# household's time zone. Older names for the same zones are here too.
US_ZONES = frozenset(
    {
        "America/New_York",
        "America/Detroit",
        "America/Chicago",
        "America/Menominee",
        "America/Denver",
        "America/Boise",
        "America/Phoenix",
        "America/Los_Angeles",
        "America/Anchorage",
        "America/Juneau",
        "America/Sitka",
        "America/Yakutat",
        "America/Nome",
        "America/Metlakatla",
        "America/Adak",
        "Pacific/Honolulu",
        "America/Puerto_Rico",
        "America/St_Thomas",
        "Pacific/Guam",
        "Pacific/Saipan",
        "Pacific/Pago_Pago",
        "Pacific/Midway",
        "Pacific/Wake",
        "America/Atka",
        "America/Fort_Wayne",
        "America/Indianapolis",
        "America/Knox_IN",
        "America/Louisville",
        "America/Shiprock",
        "America/Virgin",
        "Navajo",
        "Pacific/Johnston",
        "Pacific/Samoa",
    }
)
US_ZONE_PREFIXES = ("America/Indiana/", "America/Kentucky/", "America/North_Dakota/", "US/")


# ---- rules (pure) ------------------------------------------------------------------------------


def resolve_units(choice: object, zone: ZoneInfo) -> Units:
    """The household's units: the setting, or for "auto" °F in a United States time zone and
    °C anywhere else."""
    if choice == "fahrenheit":
        return "fahrenheit"
    if choice == "celsius":
        return "celsius"
    key = zone.key
    return "fahrenheit" if key in US_ZONES or key.startswith(US_ZONE_PREFIXES) else "celsius"


def whole(value: float) -> int:
    """Rounded as people round, halves away from zero: 58.5 is 59 and -0.5 is -1 (Python's
    ``round`` says 58 and 0). Arithmetic's last-digit noise goes first, so 58.1 °F in °C is
    14.5 and rounds to 15 although the float reads 14.499999999999996."""
    return int(Decimal(repr(round(value, 6))).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def shown(
    forecast: open_meteo.Forecast, *, sent_in: str, units: Units, now: datetime, zone: ZoneInfo
) -> tuple[WeatherNowOut | None, list[ForecastHourOut], list[ForecastDayOut]]:
    """A forecast as the household sees it: now, the next HOURS hours from this one and up to
    DAYS days from today, in whole degrees of ``units`` (converted when the forecast came in
    ``sent_in``, the other ones) and the household's wall time (the forecast was asked in its
    zone; if the zone has changed since, the times move to the new one). An hour or a day
    without its numbers is left out."""
    asked_in = _zone_named(forecast.timezone) or zone

    def wall(at: datetime) -> datetime:
        return at if asked_in.key == zone.key else to_local(from_local(at, asked_in), zone)

    def degrees(value: float) -> int:
        return whole(_convert(value, sent_in, units))

    local = to_local(now, zone)
    this_hour = local.replace(minute=0, second=0, microsecond=0)
    now_in = forecast.current
    current = None
    if now_in.temperature_2m is not None and now_in.weather_code is not None:
        current = WeatherNowOut(
            time=wall(now_in.time),
            temperature=degrees(now_in.temperature_2m),
            code=now_in.weather_code,
            is_day=bool(now_in.is_day),
        )
    hours: list[ForecastHourOut] = []
    hourly = forecast.hourly
    for at, temperature, code, chance in zip(
        hourly.time,
        hourly.temperature_2m,
        hourly.weather_code,
        hourly.precipitation_probability,
        strict=True,
    ):
        time = wall(at)
        if time < this_hour or temperature is None or code is None:
            continue
        hours.append(
            ForecastHourOut(
                time=time,
                temperature=degrees(temperature),
                code=code,
                precipitation=_percent(chance),
            )
        )
        if len(hours) == HOURS:
            break
    days: list[ForecastDayOut] = []
    daily = forecast.daily
    for index, day in enumerate(daily.time):
        code = daily.weather_code[index]
        high, low = daily.temperature_2m_max[index], daily.temperature_2m_min[index]
        if day < local.date() or code is None or high is None or low is None:
            continue
        sunrise, sunset = daily.sunrise[index], daily.sunset[index]
        days.append(
            ForecastDayOut(
                date=day,
                code=code,
                high=degrees(high),
                low=degrees(low),
                precipitation=_percent(daily.precipitation_probability_max[index]),
                sunrise=wall(sunrise) if sunrise else None,
                sunset=wall(sunset) if sunset else None,
            )
        )
        if len(days) == DAYS:
            break
    return current, hours, days


def _convert(value: float, sent_in: str, units: Units) -> float:
    if sent_in == units:
        return value
    return (value - 32) * 5 / 9 if units == "celsius" else value * 9 / 5 + 32


def _percent(value: float | None) -> int | None:
    return None if value is None else whole(value)


def _zone_named(name: str | None) -> ZoneInfo | None:
    if not name:
        return None
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError, ValueError:
        return None


def _place(home: HouseholdView) -> Place | None:
    if home.latitude is None or home.longitude is None:
        return None
    return home.latitude, home.longitude


def _for(row: WeatherCache, place: Place) -> bool:
    """The cache row is for this place."""
    return math.isclose(row.latitude, place[0], abs_tol=1e-6) and math.isclose(
        row.longitude, place[1], abs_tol=1e-6
    )


def _within(start: datetime | None, now: datetime, length: timedelta) -> bool:
    return start is not None and start <= now < start + length


def _nothing_to_ask(row: WeatherCache, place: Place, units: Units, now: datetime) -> bool:
    """The cache has this forecast from the last hour, or asking for it just failed."""
    if not _for(row, place) or row.units != units:
        return False
    fetched, expires = row.fetched_at, row.expires_at
    if row.payload_json is not None and fetched and expires and fetched <= now < expires:
        return True
    return _within(row.last_error_at, now, RETRY_AFTER)


# ---- the forecast ------------------------------------------------------------------------------


async def refresh(ctx: PluginContext, *, force: bool = False) -> None:
    """Ask Open-Meteo for the household's forecast unless there's nothing to ask (``force``
    asks anyway). No place, no request. Never raises for Open-Meteo's sake: a failure keeps the
    last forecast for the place and notes why."""
    place = _place(await ctx.household.get())
    if place is None:
        return
    zone, now = ctx.zone(), ctx.now()
    units = resolve_units(ctx.settings().get("units"), zone)
    async with ctx.read() as session:
        cached = await session.get(WeatherCache, 1)
    if not force and cached is not None and _nothing_to_ask(cached, place, units, now):
        return
    answer, problem = await _ask(ctx, place, units, zone, now)
    async with ctx.write() as tx:
        row = await tx.session.get(WeatherCache, 1)
        if row is None:
            row = WeatherCache(id=1, latitude=place[0], longitude=place[1], units=units)
            tx.session.add(row)
        if answer is not None:
            row.latitude, row.longitude, row.units = place[0], place[1], units
            row.payload_json = answer
            row.fetched_at, row.expires_at = now, now + KEEP_FOR
            row.last_error = row.last_error_at = None
        else:
            if not _for(row, place):
                # What's kept is somewhere else's forecast: nothing to show for this place.
                row.latitude, row.longitude, row.units = place[0], place[1], units
                row.payload_json = row.fetched_at = row.expires_at = None
            row.last_error, row.last_error_at = problem, now
        tx.publish(EVENT)


async def _ask(
    ctx: PluginContext, place: Place, units: Units, zone: ZoneInfo, now: datetime
) -> tuple[str | None, str | None]:
    """Open-Meteo's answer as it's stored (JSON text), or why there's none."""
    latitude, longitude = place
    if ctx.test_mode:
        made_up = fake.forecast(
            now=now, zone=zone, units=units, latitude=latitude, longitude=longitude
        )
        return _stored(made_up), None
    url = open_meteo.forecast_url(latitude, longitude, units, zone.key)
    try:
        result = await ctx.http().get(url, max_bytes=open_meteo.FORECAST_MAX_BYTES)
    except OutboundError as exc:
        return _failed(exc.code, NO_ANSWER)
    except httpx.HTTPError as exc:
        return _failed(type(exc).__name__, NO_ANSWER)
    if result.status != 200:
        return _failed(f"status {result.status}", NO_ANSWER)
    try:
        answer = json.loads(result.content)
        open_meteo.read_forecast(answer)
    except ValueError, open_meteo.UnreadableError:
        return _failed("unreadable", UNREADABLE)
    return _stored(answer), None


def _stored(answer: object) -> str:
    return json.dumps(answer, ensure_ascii=False, separators=(",", ":"))


def _failed(reason: str, problem: str) -> tuple[None, str]:
    log.warning("weather.refresh_failed", reason=reason)  # never the place
    return None, problem


async def weather(ctx: PluginContext) -> WeatherOut:
    """The forecast for every screen: no_location until the household has a place, waiting until
    its first forecast is in, error when there's none and why, else ok (stale after 3 hours)."""
    home = await ctx.household.get()
    zone, now = ctx.zone(), ctx.now()
    units = resolve_units(ctx.settings().get("units"), zone)
    place = _place(home)
    if place is None:
        return _without("no_location", home, units)
    async with ctx.read() as session:
        row = await session.get(WeatherCache, 1)
    if row is None or not _for(row, place):
        return _without("waiting", home, units)  # a new place: refresh follows it
    if row.payload_json is None or row.fetched_at is None:
        if row.last_error:
            return _without("error", home, units, row.last_error)
        return _without("waiting", home, units)
    try:
        forecast = open_meteo.read_forecast(json.loads(row.payload_json))
    except ValueError, open_meteo.UnreadableError:
        return _without("error", home, units, UNREADABLE)
    current, hours, days = shown(forecast, sent_in=row.units, units=units, now=now, zone=zone)
    return WeatherOut(
        status="ok",
        location_label=home.location_label,
        units=units,
        current=current,
        hourly=hours,
        daily=days,
        fetched_at=row.fetched_at,
        stale=now - row.fetched_at > STALE_AFTER,
        message=row.last_error,  # why the last try failed, while the last forecast shows
    )


def _without(
    status: Status, home: HouseholdView, units: Units, message: str | None = None
) -> WeatherOut:
    return WeatherOut(
        status=status,
        location_label=home.location_label,
        units=units,
        current=None,
        hourly=[],
        daily=[],
        fetched_at=None,
        stale=False,
        message=message,
    )


async def check_now(ctx: PluginContext) -> WeatherOut:
    """Check now (a parent): ask again even within the hour, unless any try was under a minute
    ago."""
    if _place(await ctx.household.get()) is not None:
        async with ctx.read() as session:
            row = await session.get(WeatherCache, 1)
        now = ctx.now()
        tries = [at for at in (row.fetched_at, row.last_error_at) if at is not None] if row else []
        last = max(tries, default=None)
        if last is not None and _within(last, now, CHECK_EVERY):
            wait = math.ceil((last + CHECK_EVERY - now).total_seconds())
            raise AppError(
                429, "too_soon", "api.weather.too_soon", headers={"Retry-After": str(wait)}
            )
        await refresh(ctx, force=True)
    return await weather(ctx)


# ---- the city search ---------------------------------------------------------------------------


class SearchLimit:
    """At most SEARCHES city searches a minute for each device (PLAN §12.7): the field searches
    as you type, a few times a name (ADR 0030). Memory is enough: one process serves the API."""

    def __init__(self) -> None:
        self._recent: dict[str, deque[datetime]] = {}

    def check(self, device_id: str, now: datetime) -> None:
        for device in list(self._recent):
            times = self._recent[device]
            while times and now - times[0] >= SEARCH_WINDOW:
                times.popleft()
            if not times:
                del self._recent[device]
        times = self._recent.setdefault(device_id, deque())
        if len(times) >= SEARCHES:
            wait = math.ceil((times[0] + SEARCH_WINDOW - now).total_seconds())
            raise AppError(
                429,
                "rate_limited",
                "api.weather.too_many_searches",
                headers={"Retry-After": str(max(wait, 1))},
            )
        times.append(now)


async def search(ctx: PluginContext, query: str) -> list[PlaceOut]:
    """Cities called ``query``, for Settings → Household → Location and onboarding, named in
    the household's language where Open-Meteo has it."""
    name = " ".join(query.split())
    if len(name) < 2:
        return []
    if ctx.test_mode:
        return fake.places(name)
    language = (await ctx.household.get()).language
    try:
        result = await ctx.http().get(
            open_meteo.search_url(name, language), max_bytes=open_meteo.SEARCH_MAX_BYTES
        )
    except OutboundError as exc:
        raise _search_failed(exc.code) from None
    except httpx.HTTPError as exc:
        raise _search_failed(type(exc).__name__) from None
    if result.status != 200:
        raise _search_failed(f"status {result.status}")
    try:
        return open_meteo.read_places(json.loads(result.content))
    except ValueError, open_meteo.UnreadableError:
        raise _search_failed("unreadable") from None


def _search_failed(reason: str) -> AppError:
    log.warning("weather.search_failed", reason=reason)  # never what was typed
    return AppError(502, "unreachable", SEARCH_FAILED)
