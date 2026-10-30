"""Calendar addresses as pasted and as shown (UX §2), and the offline holidays (PLAN §8.1).
Synthetic addresses only (example.com and a made-up secret)."""

from __future__ import annotations

from datetime import UTC, date, datetime

from sunroom.plugins.calendar_sync.addresses import feed_id, normalize, shown
from sunroom.plugins.calendar_sync.providers.base import RemoteCalendar
from sunroom.plugins.calendar_sync.providers.holidays import (
    HolidaysProvider,
    holiday_language,
    supported,
)

SECRET_FEED = (
    "https://calendar.example.com/calendar/ical/family%40group.example.com/"
    "private-3f9a8b7c6d5e4f3a2b1c/basic.ics"
)


def test_webcal_and_bare_hosts_become_https() -> None:
    assert normalize(" webcal://calendar.example.com/team.ics ") == (
        "https://calendar.example.com/team.ics"
    )
    assert normalize("webcals://example.com/a.ics") == "https://example.com/a.ics"
    assert normalize("example.com/school.ics") == "https://example.com/school.ics"
    assert normalize("http://example.com/a.ics") == "http://example.com/a.ics"


def test_a_secret_address_shows_with_its_secret_hidden() -> None:
    assert shown(SECRET_FEED) == "calendar.example.com/…/private-3f9a…/basic.ics"
    assert shown("https://example.com/school.ics") == "example.com/school.ics"
    assert shown("https://example.com/feeds/team.ics?token=abcdef") == ("example.com/…/team.ics")
    assert "3f9a8b7c" not in shown(SECRET_FEED)


def test_feed_ids_say_nothing_about_the_address() -> None:
    assert feed_id(SECRET_FEED).startswith("feed-")
    assert "private" not in feed_id(SECRET_FEED)
    assert feed_id(SECRET_FEED) == feed_id(SECRET_FEED)


def test_places_include_countries_and_their_regions() -> None:
    places = supported()
    assert "US" in places and "CA" in places["US"]
    assert all(len(code) == 2 for code in places)


async def test_holidays_cover_last_year_to_two_ahead_and_refresh_yearly() -> None:
    now = datetime(2026, 10, 7, 14, tzinfo=UTC)
    provider = HolidaysProvider("us", None, lambda: now)
    calendar = RemoteCalendar(provider.remote_id(), "Holidays", read_only=True)
    changes = await provider.changes(calendar, None, {})
    assert changes.complete
    days = {s.master.timing.start_date for s in changes.series if s.master}
    assert date(2025, 12, 25) in days and date(2028, 12, 25) in days
    assert date(2029, 1, 1) not in days
    new_year = [s for s in changes.series if s.master and s.master.title == "New Year's Day"]
    assert all(s.master and s.master.timing.all_day for s in new_year)
    assert len({s.uid for s in changes.series}) == len(changes.series)
    # Nothing to do until the year turns.
    again = await provider.changes(calendar, changes.cursor, {})
    assert again.series == [] and not again.complete


def test_the_holidays_speak_the_households_language_where_the_country_has_it() -> None:
    assert holiday_language("ES", "en") == "en_US"  # Spain's, in English
    assert holiday_language("es", "es") is None  # Spain's own words
    assert holiday_language("US", "es") is None  # no Spanish for the United States
    assert holiday_language("US", "en") is None  # the country speaks it already
    assert holiday_language("GB", "en") is None  # so British English stays British
    assert holiday_language("ZZ", "en") is None
    assert holiday_language("ES", None) is None


async def test_a_new_language_makes_the_holidays_again() -> None:
    now = datetime(2026, 10, 7, 14, tzinfo=UTC)
    language = "en"

    async def household() -> str:
        return language

    provider = HolidaysProvider("es", None, lambda: now, language_of=household)
    calendar = RemoteCalendar(provider.remote_id(), "Holidays", read_only=True)
    english = await provider.changes(calendar, None, {})
    titles = {s.master.title for s in english.series if s.master}
    assert "New Year's Day" in titles
    assert (await provider.changes(calendar, english.cursor, {})).series == []
    language = "es"
    spanish = await provider.changes(calendar, english.cursor, {})
    assert spanish.complete and spanish.cursor != english.cursor
    assert "Año Nuevo" in {s.master.title for s in spanish.series if s.master}
