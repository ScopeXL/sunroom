"""Open-Meteo (ADR 0010): the forecast and the town search, asked without a key or an account.
Its two hosts are constants, and every request goes through the guarded client (PLAN §12.6).

The forecast request names the household's time zone, so its times come back as the household's
wall time without an offset ("2026-10-07T10:00"). Reading an answer checks it has every array
Sunroom shows, lined up; anything else is an ``UnreadableError``. Nothing here touches the
database.
"""

from __future__ import annotations

import datetime as dt
from typing import Any
from urllib.parse import quote, urlencode

from pydantic import BaseModel, Field, FiniteFloat, ValidationError, model_validator

from sunroom.plugins.weather.schemas import PlaceOut, Units

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
SEARCH_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_MAX_BYTES = 1024 * 1024  # a week of hours is about 10 KB
SEARCH_MAX_BYTES = 256 * 1024
FORECAST_DAYS = 7
PLACES_MAX = 5
CURRENT = ("temperature_2m", "weather_code", "is_day")
HOURLY = ("temperature_2m", "weather_code", "precipitation_probability")
DAILY = (
    "weather_code",
    "temperature_2m_max",
    "temperature_2m_min",
    "precipitation_probability_max",
    "sunrise",
    "sunset",
)


class UnreadableError(Exception):
    """An answer without what Sunroom needs from it."""


# ---- asking ------------------------------------------------------------------------------------


def forecast_url(latitude: float, longitude: float, units: Units, zone: str) -> str:
    """Now, the hours and FORECAST_DAYS days at a place, in ``units``, in the household's
    ``zone`` (an IANA name)."""
    query: dict[str, str | int] = {
        "latitude": _coordinate(latitude),
        "longitude": _coordinate(longitude),
        "current": ",".join(CURRENT),
        "hourly": ",".join(HOURLY),
        "daily": ",".join(DAILY),
        "temperature_unit": units,
        "timezone": zone,
        "forecast_days": FORECAST_DAYS,
    }
    return f"{FORECAST_URL}?{urlencode(query, safe=',/', quote_via=quote)}"


def search_url(name: str, language: str = "en") -> str:
    """Up to PLACES_MAX places called ``name``, named in ``language`` (the household's, a code
    from lang/languages.json; Open-Meteo answers in English, or the place's own name, where it
    has no translation). Open-Meteo matches two characters exactly and three or more loosely,
    which is why the field says "Keep typing…" under three."""
    query: dict[str, str | int] = {
        "name": name,
        "count": PLACES_MAX,
        "language": language.lower(),
        "format": "json",
    }
    return f"{SEARCH_URL}?{urlencode(query, quote_via=quote)}"


def _coordinate(value: float) -> str:
    return str(round(value, 4))  # about 10 m: far finer than any weather model's grid


# ---- the forecast ------------------------------------------------------------------------------


class Current(BaseModel):
    time: dt.datetime
    temperature_2m: FiniteFloat | None
    weather_code: int | None
    is_day: int | None


class Hourly(BaseModel):
    time: list[dt.datetime]
    temperature_2m: list[FiniteFloat | None]
    weather_code: list[int | None]
    precipitation_probability: list[FiniteFloat | None]


class Daily(BaseModel):
    time: list[dt.date]
    weather_code: list[int | None]
    temperature_2m_max: list[FiniteFloat | None]
    temperature_2m_min: list[FiniteFloat | None]
    precipitation_probability_max: list[FiniteFloat | None]
    sunrise: list[dt.datetime | None]
    sunset: list[dt.datetime | None]


class Forecast(BaseModel):
    """The parts of a forecast answer Sunroom shows (the rest is ignored). A value can be null
    (a model without that hour); a missing array can't."""

    timezone: str | None = None  # the zone its times are in: the one asked for
    current: Current
    hourly: Hourly
    daily: Daily

    @model_validator(mode="after")
    def _lined_up(self) -> Forecast:
        hourly, daily = self.hourly, self.daily
        hour_columns = (
            hourly.temperature_2m,
            hourly.weather_code,
            hourly.precipitation_probability,
        )
        day_columns = (
            daily.weather_code,
            daily.temperature_2m_max,
            daily.temperature_2m_min,
            daily.precipitation_probability_max,
            daily.sunrise,
            daily.sunset,
        )
        if any(len(column) != len(hourly.time) for column in hour_columns) or any(
            len(column) != len(daily.time) for column in day_columns
        ):
            raise ValueError("the arrays don't line up")
        times = [self.current.time, *hourly.time, *daily.sunrise, *daily.sunset]
        if any(time is not None and time.tzinfo is not None for time in times):
            raise ValueError("wall times carry no offset")
        return self


def read_forecast(data: Any) -> Forecast:
    """A forecast answer (parsed JSON), checked."""
    try:
        return Forecast.model_validate(data)
    except ValidationError:
        raise UnreadableError("not the forecast Sunroom asked for") from None


# ---- the town search ---------------------------------------------------------------------------


class _Place(BaseModel):
    name: str
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    admin1: str | None = None  # the state or region; empty fields aren't sent at all
    country: str | None = None
    timezone: str | None = None


class _Search(BaseModel):
    results: list[Any] = Field(default_factory=list[Any])  # left out when nothing matched


def read_places(data: Any) -> list[PlaceOut]:
    """A search answer (parsed JSON) as up to PLACES_MAX places. One odd result is skipped
    rather than hiding the others."""
    try:
        search = _Search.model_validate(data)
    except ValidationError:
        raise UnreadableError("not the search answer Sunroom asked for") from None
    places: list[PlaceOut] = []
    for result in search.results:
        try:
            place = _Place.model_validate(result)
        except ValidationError:
            continue
        places.append(
            PlaceOut(
                label=place_label(place.name, place.admin1, place.country),
                latitude=place.latitude,
                longitude=place.longitude,
                timezone=place.timezone or None,
            )
        )
        if len(places) == PLACES_MAX:
            break
    return places


def place_label(*parts: str | None) -> str:
    """The parts there are, joined, each once: "Springfield, Illinois, United States", and
    "Singapore" rather than "Singapore, Singapore"."""
    kept: list[str] = []
    for part in parts:
        text = " ".join((part or "").split())
        if text and text.casefold() not in {seen.casefold() for seen in kept}:
            kept.append(text)
    return ", ".join(kept)
