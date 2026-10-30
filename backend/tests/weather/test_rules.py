"""The weather's rules without the app: units by time zone, rounding, place labels, what is asked,
reading Open-Meteo's answers, the forecast as shown, and the test server's made-up week."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from sunroom.plugins.weather import fake, service
from sunroom.plugins.weather import open_meteo as client
from tests.weather.helpers import fixture

NOW = datetime(2026, 10, 7, 14, 0, tzinfo=UTC)  # 10:00 in New York
NEW_YORK = ZoneInfo("America/New_York")


# ---- units and rounding ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("zone", "units"),
    [
        ("America/New_York", "fahrenheit"),
        ("America/Chicago", "fahrenheit"),
        ("America/Indiana/Indianapolis", "fahrenheit"),
        ("America/Kentucky/Louisville", "fahrenheit"),
        ("America/North_Dakota/Center", "fahrenheit"),
        ("America/Phoenix", "fahrenheit"),
        ("America/Anchorage", "fahrenheit"),
        ("Pacific/Honolulu", "fahrenheit"),
        ("America/Puerto_Rico", "fahrenheit"),
        ("Pacific/Guam", "fahrenheit"),
        ("US/Eastern", "fahrenheit"),
        ("America/Toronto", "celsius"),
        ("America/Mexico_City", "celsius"),
        ("Europe/London", "celsius"),
        ("Australia/Sydney", "celsius"),
        ("UTC", "celsius"),
    ],
)
def test_usual_units_go_by_the_households_time_zone(zone: str, units: str) -> None:
    assert service.resolve_units("auto", ZoneInfo(zone)) == units


def test_chosen_units_win() -> None:
    assert service.resolve_units("celsius", NEW_YORK) == "celsius"
    assert service.resolve_units("fahrenheit", ZoneInfo("Europe/London")) == "fahrenheit"
    assert service.resolve_units(None, NEW_YORK) == "fahrenheit"  # unset is usual


@pytest.mark.parametrize(
    ("value", "rounded"),
    [
        (58.5, 59),
        (58.49, 58),
        (62.5, 63),
        (61.5, 62),
        (-0.5, -1),
        (-1.5, -2),
        (-0.4, 0),
        (0.0, 0),
        (99.95, 100),
        (14.722222222222221, 15),
        ((58.1 - 32) * 5 / 9, 15),  # exactly 14.5, though the float falls just short
    ],
)
def test_degrees_round_as_people_round(value: float, rounded: int) -> None:
    assert service.whole(value) == rounded


def test_a_place_is_named_by_its_parts_each_once() -> None:
    label = client.place_label
    assert label("Sample Town", "Sample State", "United States") == (
        "Sample Town, Sample State, United States"
    )
    assert label("Sampleton", "sampleton", "Sampleland") == "Sampleton, Sampleland"
    assert label("Sample Bay", None, "Sampleland") == "Sample Bay, Sampleland"
    assert label("  Sample   Bay ", "", "Sampleland") == "Sample Bay, Sampleland"


def test_the_requests_say_what_they_ask() -> None:
    assert client.forecast_url(40.71234, -74.00987, "celsius", "Europe/London") == (
        "https://api.open-meteo.com/v1/forecast?latitude=40.7123&longitude=-74.0099"
        "&current=temperature_2m,weather_code,is_day"
        "&hourly=temperature_2m,weather_code,precipitation_probability"
        "&daily=weather_code,temperature_2m_max,temperature_2m_min,"
        "precipitation_probability_max,sunrise,sunset"
        "&temperature_unit=celsius&timezone=Europe/London&forecast_days=7"
    )
    assert client.search_url("Sample Town") == (
        "https://geocoding-api.open-meteo.com/v1/search"
        "?name=Sample%20Town&count=5&language=en&format=json"
    )
    assert client.search_url("Sample Town", "es") == (
        "https://geocoding-api.open-meteo.com/v1/search"
        "?name=Sample%20Town&count=5&language=es&format=json"
    )


# ---- reading answers ---------------------------------------------------------------------------


def broken_answers() -> list[Any]:
    def changed(change: Callable[[dict[str, Any]], object]) -> dict[str, Any]:
        answer = fixture("forecast.json")
        change(answer)
        return answer

    return [
        None,
        [],
        changed(lambda a: a.pop("daily")),
        changed(lambda a: a.pop("current")),
        changed(lambda a: a["hourly"].pop("precipitation_probability")),
        changed(lambda a: a["hourly"]["temperature_2m"].pop()),  # one short
        changed(lambda a: a["daily"]["sunset"].append("2026-10-14T18:19")),  # one over
        changed(lambda a: a["hourly"]["time"].__setitem__(0, "2026-10-07T00:00-04:00")),
        changed(lambda a: a["current"].__setitem__("temperature_2m", float("nan"))),
        changed(lambda a: a["daily"]["weather_code"].__setitem__(0, "cloudy")),
        changed(lambda a: a["daily"]["time"].__setitem__(0, "Wednesday")),
    ]


def test_a_forecast_has_every_array_lined_up() -> None:
    forecast = client.read_forecast(fixture("forecast.json"))
    assert (len(forecast.hourly.time), len(forecast.daily.time)) == (168, 7)
    assert forecast.timezone == "America/New_York"
    for answer in broken_answers():
        with pytest.raises(client.UnreadableError):
            client.read_forecast(answer)


def test_a_search_answer_has_up_to_five_places() -> None:
    assert client.read_places({"generationtime_ms": 0.3}) == []
    many = {
        "results": [
            {"name": f"Sample {n}", "latitude": 40 + n / 10, "longitude": -74.0} for n in range(8)
        ]
    }
    assert [place.label for place in client.read_places(many)] == [f"Sample {n}" for n in range(5)]
    odd = {"results": [{"name": "Sample Pole", "latitude": 91.0, "longitude": 0.0}]}
    assert client.read_places(odd) == []
    with pytest.raises(client.UnreadableError):
        client.read_places([])


# ---- the forecast as shown ---------------------------------------------------------------------


def test_hours_and_days_without_their_numbers_are_left_out() -> None:
    answer = fixture("forecast.json")
    answer["current"]["temperature_2m"] = None
    answer["hourly"]["temperature_2m"][11] = None  # 11 AM
    answer["hourly"]["weather_code"][12] = None  # noon
    answer["hourly"]["precipitation_probability"][13] = None  # 1 PM: shown, chance unknown
    answer["daily"]["temperature_2m_max"][1] = None  # Thursday
    answer["daily"]["precipitation_probability_max"][2] = None
    answer["daily"]["sunrise"][3] = None
    current, hours, days = service.shown(
        client.read_forecast(answer),
        sent_in="fahrenheit",
        units="fahrenheit",
        now=NOW,
        zone=NEW_YORK,
    )
    assert current is None
    assert [(hour.time.hour, hour.precipitation) for hour in hours[:3]] == [
        (10, 6),
        (13, None),
        (14, 10),
    ]
    assert len(hours) == 24
    assert [day.date.day for day in days] == [7, 9, 10, 11, 12, 13]
    assert (days[1].precipitation, days[2].sunrise) == (None, None)


def test_a_forecast_in_the_other_units_is_converted() -> None:
    forecast = client.read_forecast(fixture("forecast.json"))
    current, hours, days = service.shown(
        forecast, sent_in="fahrenheit", units="celsius", now=NOW, zone=NEW_YORK
    )
    assert current is not None
    assert (current.temperature, hours[0].temperature) == (15, 15)  # 14.7 °C, exactly 14.5 °C
    assert [(day.high, day.low) for day in days[:2]] == [(19, 11), (21, 12)]


# ---- the test server's week --------------------------------------------------------------------


def test_the_test_servers_week_is_the_same_every_time() -> None:
    def week(now: datetime = NOW, units: service.Units = "fahrenheit") -> dict[str, Any]:
        return fake.forecast(now=now, zone=NEW_YORK, units=units, latitude=40.71, longitude=-74.01)

    made = week()
    assert made == week()
    assert json.loads(json.dumps(made)) == made  # as it's stored
    forecast = client.read_forecast(made)
    assert (len(forecast.hourly.time), len(forecast.daily.time)) == (168, 7)
    assert forecast.timezone == "America/New_York"
    assert forecast.hourly.time[0] == datetime(2026, 10, 7, 0, 0)  # noqa: DTZ001 - wall time
    assert (forecast.daily.sunrise[0], forecast.daily.sunset[0]) == (
        datetime(2026, 10, 7, 7, 5),  # noqa: DTZ001 - wall time
        datetime(2026, 10, 7, 18, 30),  # noqa: DTZ001 - wall time
    )
    assert (made["current"]["time"], made["current"]["is_day"]) == ("2026-10-07T10:00", 1)
    # October-ish, in either units.
    in_celsius = week(units="celsius")
    assert in_celsius["daily"]["temperature_2m_max"] == [18.4, 19.6, 16.1, 14.7, 17.2, 19.0, 17.8]
    assert made["daily"]["temperature_2m_max"] == [
        round(value * 9 / 5 + 32, 1) for value in in_celsius["daily"]["temperature_2m_max"]
    ]
    assert all(45 <= value <= 68 for value in made["hourly"]["temperature_2m"])
    # Now is the quarter hour it's in; after sunset the sun is down.
    assert week(datetime(2026, 10, 7, 14, 20, tzinfo=UTC))["current"]["time"] == "2026-10-07T10:15"
    evening = week(datetime(2026, 10, 8, 1, 0, tzinfo=UTC))["current"]  # 9 PM in New York
    assert (evening["time"], evening["is_day"]) == ("2026-10-07T21:00", 0)
