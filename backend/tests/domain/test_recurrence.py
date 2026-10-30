"""The recurrence engine (PLAN §7.2 to §7.4): rules checked and described, occurrences
expanded across daylight saving, edits split, plus three properties: a split partitions the
series, buckets add up to the whole, and the walk agrees with python-dateutil.

Dates are 2026 unless they say otherwise. New York springs forward on Mar 8 and falls back on
Nov 1; London changes on Mar 29 and Oct 25. Synthetic data only."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from time import perf_counter
from typing import Literal
from zoneinfo import ZoneInfo

import pytest
from dateutil import rrule as du
from hypothesis import assume, given, reject, settings
from hypothesis import strategies as st

from sunroom.core.lang import t_en
from sunroom.domain.recurrence import (
    MAX_PER_SERIES,
    Occurrence,
    Override,
    RecurrenceError,
    Series,
    Timing,
    Window,
    count_before,
    describe,
    expand,
    series_bounds,
    shift_rid,
    split,
    validate_rrule,
)
from sunroom.domain.timeparts import FAR_FUTURE, day_bounds, from_local, rid_timed, to_local

NY_KEY = "America/New_York"
LONDON_KEY = "Europe/London"
NY = ZoneInfo(NY_KEY)


def wall(text: str) -> datetime:
    return datetime.fromisoformat(text)


def utc(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


def timed(start: str, minutes: int = 60, tzid: str = NY_KEY) -> Timing:
    begin = from_local(wall(start), ZoneInfo(tzid))
    return Timing(all_day=False, start_utc=begin, end_utc=begin + timedelta(minutes=minutes))


def all_day(first: str, days: int = 1) -> Timing:
    day = date.fromisoformat(first)
    return Timing(all_day=True, start_date=day, end_date=day + timedelta(days=days))


def window(first: str, last: str) -> Window:
    """[first, last) as New York household dates."""
    start, end = date.fromisoformat(first), date.fromisoformat(last)
    return Window(day_bounds(start, NY)[0], day_bounds(end, NY)[0], start, end)


def repeating(
    timing: Timing,
    rrule: str | None,
    *,
    tzid: str = NY_KEY,
    rdates: tuple[str, ...] = (),
    exdates: tuple[str, ...] = (),
) -> Series:
    return Series(timing, tzid, rrule, rdates, frozenset(exdates))


def rids(found: list[Occurrence]) -> list[str | None]:
    return [occurrence.recurrence_id for occurrence in found]


def starts(found: list[Occurrence], zone: ZoneInfo = NY) -> list[str]:
    """Wall-clock starts of timed occurrences."""
    shown: list[str] = []
    for occurrence in found:
        assert occurrence.timing.start_utc is not None
        shown.append(rid_timed(to_local(occurrence.timing.start_utc, zone)))
    return shown


SOCCER = timed("2026-09-29T16:00:00")  # a Tuesday, 4 to 5 PM
TUE_THU = "FREQ=WEEKLY;BYDAY=TU,TH"
WEEK = window("2026-10-04", "2026-10-11")  # Sunday to Saturday
NEXT_WEEK = window("2026-10-11", "2026-10-18")
YEAR = window("2026-01-01", "2027-01-01")
LESSONS = timed("2026-04-06T16:00:00")  # a Monday


# --- validate_rrule ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("freq=weekly;byday=th,tu", TUE_THU),
        ("RRULE:FREQ=DAILY;INTERVAL=1", "FREQ=DAILY"),
        ("FREQ=DAILY;", "FREQ=DAILY"),
        (" FREQ=DAILY; INTERVAL = 2 ", "FREQ=DAILY;INTERVAL=2"),
        ("COUNT=10;FREQ=WEEKLY;BYDAY=TU", "FREQ=WEEKLY;BYDAY=TU;COUNT=10"),
        ("FREQ=WEEKLY;WKST=MO;BYDAY=TU", "FREQ=WEEKLY;BYDAY=TU"),
        (
            "FREQ=WEEKLY;WKST=SU;INTERVAL=2;BYDAY=SU,TU",
            "FREQ=WEEKLY;INTERVAL=2;BYDAY=TU,SU;WKST=SU",
        ),
        ("FREQ=MONTHLY;BYDAY=+2TU", "FREQ=MONTHLY;BYDAY=2TU"),
        ("FREQ=MONTHLY;BYMONTHDAY=-1,15,1,15", "FREQ=MONTHLY;BYMONTHDAY=1,15,-1"),
        ("FREQ=YEARLY;BYDAY=2SU;BYMONTH=5", "FREQ=YEARLY;BYMONTH=5;BYDAY=2SU"),
        (
            "FREQ=MONTHLY;BYSETPOS=-1;BYDAY=FR,MO,TU,WE,TH",
            "FREQ=MONTHLY;BYDAY=MO,TU,WE,TH,FR;BYSETPOS=-1",
        ),
        (f"{TUE_THU};UNTIL=20261231T235959Z", f"{TUE_THU};UNTIL=20261231T235959Z"),
    ],
)
def test_rules_are_normalized(given: str, expected: str) -> None:
    assert validate_rrule(given, SOCCER, NY_KEY) == expected
    assert validate_rrule(expected, SOCCER, NY_KEY) == expected


@pytest.mark.parametrize(
    ("until", "expected"),
    [
        ("20261231T235959Z", "20261231T235959Z"),
        ("20261231", "20270101T045959Z"),  # a date ends a timed series at the end of that day
        ("20261231T180000", "20261231T230000Z"),  # no Z: wall time in the series' zone
        ("20260701T180000", "20260701T220000Z"),
    ],
)
def test_a_timed_series_ends_at_an_instant_in_utc(until: str, expected: str) -> None:
    timing = timed("2026-01-05T09:00:00")
    normalized = validate_rrule(f"FREQ=DAILY;UNTIL={until}", timing, NY_KEY)
    assert normalized == f"FREQ=DAILY;UNTIL={expected}"


@pytest.mark.parametrize("until", ["20261231", "20261231T235959Z", "20261231T000000"])
def test_an_all_day_series_ends_on_a_date(until: str) -> None:
    normalized = validate_rrule(f"FREQ=WEEKLY;UNTIL={until}", all_day("2026-01-05"), NY_KEY)
    assert normalized == "FREQ=WEEKLY;UNTIL=20261231"


@pytest.mark.parametrize(
    ("rule", "code"),
    [
        ("FREQ=HOURLY", "rrule_unsupported"),
        ("FREQ=MINUTELY;INTERVAL=15", "rrule_unsupported"),
        ("FREQ=SECONDLY", "rrule_unsupported"),
        ("FREQ=DAILY;BYHOUR=9,17", "rrule_unsupported"),
        ("FREQ=DAILY;BYMINUTE=30", "rrule_unsupported"),
        ("FREQ=YEARLY;BYWEEKNO=20", "rrule_unsupported"),
        ("FREQ=YEARLY;BYYEARDAY=100", "rrule_unsupported"),
        ("", "rrule_invalid"),
        ("BYDAY=MO", "rrule_invalid"),
        ("FREQ=FORTNIGHTLY", "rrule_invalid"),
        ("FREQ=DAILY;FOO=1", "rrule_invalid"),
        ("FREQ=DAILY;X-EVOLUTION-ENDDATE=20261231T000000Z", "rrule_invalid"),
        ("FREQ=DAILY;FREQ=WEEKLY", "rrule_invalid"),
        ("FREQ=DAILY;INTERVAL", "rrule_invalid"),
        ("FREQ=WEEKLY;BYDAY=", "rrule_invalid"),
        ("FREQ=WEEKLY;BYDAY=MO,,TU", "rrule_invalid"),
        ("FREQ=DAILY;INTERVAL=0", "rrule_invalid"),
        ("FREQ=DAILY;INTERVAL=-1", "rrule_invalid"),
        ("FREQ=DAILY;INTERVAL=two", "rrule_invalid"),
        ("FREQ=DAILY;INTERVAL=10000", "rrule_invalid"),
        ("FREQ=DAILY;INTERVAL=1,2", "rrule_invalid"),
        ("FREQ=DAILY;COUNT=5,6", "rrule_invalid"),
        ("FREQ=DAILY;COUNT=0", "rrule_invalid"),
        ("FREQ=DAILY;COUNT=1001", "rrule_invalid"),
        ("FREQ=DAILY;COUNT=-1", "rrule_invalid"),
        ("FREQ=DAILY;COUNT=5;UNTIL=20261231T000000Z", "rrule_invalid"),
        ("FREQ=DAILY;UNTIL=20260931T000000Z", "rrule_invalid"),
        ("FREQ=DAILY;UNTIL=2026-12-31", "rrule_invalid"),
        ("FREQ=DAILY;UNTIL=20261231T250000Z", "rrule_invalid"),
        ("FREQ=DAILY;UNTIL=20260929T195959Z", "rrule_invalid"),  # a second before it starts
        ("FREQ=WEEKLY;BYDAY=XX", "rrule_invalid"),
        ("FREQ=WEEKLY;BYDAY=2TU", "rrule_invalid"),
        ("FREQ=DAILY;BYDAY=1MO", "rrule_invalid"),
        ("FREQ=MONTHLY;BYDAY=6TU", "rrule_invalid"),
        ("FREQ=MONTHLY;BYDAY=0TU", "rrule_invalid"),
        ("FREQ=YEARLY;BYDAY=54MO", "rrule_invalid"),
        ("FREQ=MONTHLY;BYMONTHDAY=32", "rrule_invalid"),
        ("FREQ=MONTHLY;BYMONTHDAY=0", "rrule_invalid"),
        ("FREQ=MONTHLY;BYMONTHDAY=-32", "rrule_invalid"),
        ("FREQ=YEARLY;BYMONTH=13", "rrule_invalid"),
        ("FREQ=YEARLY;BYMONTH=0", "rrule_invalid"),
        ("FREQ=YEARLY;BYMONTH=-1", "rrule_invalid"),
        ("FREQ=MONTHLY;BYDAY=MO;BYSETPOS=367", "rrule_invalid"),
        ("FREQ=MONTHLY;BYDAY=MO;BYSETPOS=0", "rrule_invalid"),
        ("FREQ=MONTHLY;BYSETPOS=1", "rrule_invalid"),
        ("FREQ=WEEKLY;BYMONTHDAY=1", "rrule_invalid"),
        ("FREQ=WEEKLY;WKST=XX", "rrule_invalid"),
        # Rules that never land on another day.
        ("FREQ=MONTHLY;BYMONTH=2;BYMONTHDAY=30", "rrule_invalid"),
        ("FREQ=YEARLY;BYMONTH=4;BYMONTHDAY=31", "rrule_invalid"),
        ("FREQ=DAILY;INTERVAL=7;BYDAY=WE", "rrule_invalid"),  # every 7 days from a Tuesday
        ("FREQ=MONTHLY;INTERVAL=12;BYMONTH=2", "rrule_invalid"),  # every September
        ("FREQ=MONTHLY;BYDAY=MO;BYSETPOS=6", "rrule_invalid"),
        ("FREQ=MONTHLY;BYDAY=1MO;BYMONTHDAY=20", "rrule_invalid"),
    ],
)
def test_rules_are_refused_in_plain_words(rule: str, code: str) -> None:
    with pytest.raises(RecurrenceError) as caught:
        validate_rrule(rule, SOCCER, NY_KEY)
    assert caught.value.code == code
    # The engine names its sentence (ADR 0043); the API says the English from lang/en.json.
    key = caught.value.key
    assert str(caught.value) == key and key.startswith("api.repeat.")
    message = t_en(key)
    assert message[0].isupper() and message.endswith(".")
    assert not re.search(r"[A-Z]{4,}|=", message), message  # no rule syntax in front of people


def test_a_refusal_is_a_value_error() -> None:
    assert issubclass(RecurrenceError, ValueError)


# --- expand -----------------------------------------------------------------------------------


def test_a_weekly_rule_expands_into_the_window() -> None:
    found = expand(repeating(SOCCER, TUE_THU), [], WEEK)
    assert found == [
        Occurrence("2026-10-06T16:00:00", timed("2026-10-06T16:00:00"), is_override=False),
        Occurrence("2026-10-08T16:00:00", timed("2026-10-08T16:00:00"), is_override=False),
    ]


def test_nine_oclock_stays_nine_oclock_across_daylight_saving() -> None:
    walk = repeating(timed("2026-03-01T09:00:00", 30), "FREQ=DAILY")
    spring = expand(walk, [], window("2026-03-07", "2026-03-10"))
    autumn = expand(walk, [], window("2026-10-31", "2026-11-03"))
    assert starts(spring) == [
        "2026-03-07T09:00:00",
        "2026-03-08T09:00:00",
        "2026-03-09T09:00:00",
    ]
    assert [o.timing.start_utc for o in spring] == [
        utc("2026-03-07T14:00:00"),
        utc("2026-03-08T13:00:00"),
        utc("2026-03-09T13:00:00"),
    ]
    assert [o.timing.start_utc for o in autumn] == [
        utc("2026-10-31T13:00:00"),
        utc("2026-11-01T14:00:00"),
        utc("2026-11-02T14:00:00"),
    ]
    for occurrence in spring + autumn:
        assert occurrence.timing.start_utc is not None and occurrence.timing.end_utc is not None
        assert occurrence.timing.end_utc - occurrence.timing.start_utc == timedelta(minutes=30)


def test_a_london_series_keeps_london_wall_time() -> None:
    choir = repeating(timed("2026-01-07T19:00:00", 90, LONDON_KEY), "FREQ=WEEKLY", tzid=LONDON_KEY)
    found = expand(choir, [], window("2026-03-23", "2026-04-06"))
    assert rids(found) == ["2026-03-25T19:00:00", "2026-04-01T19:00:00"]
    assert [o.timing.start_utc for o in found] == [
        utc("2026-03-25T19:00:00"),
        utc("2026-04-01T18:00:00"),
    ]


def test_the_length_is_an_absolute_delta() -> None:
    late = repeating(timed("2026-03-06T23:00:00", 240), "FREQ=DAILY;COUNT=3")
    found = expand(late, [], window("2026-03-06", "2026-03-10"))
    ends: list[str] = []
    for occurrence in found:
        assert occurrence.timing.end_utc is not None
        ends.append(rid_timed(to_local(occurrence.timing.end_utc, NY)))
    # Four hours after 11 PM on Mar 7 reads 4 AM: the clocks skipped an hour.
    assert ends == ["2026-03-07T03:00:00", "2026-03-08T04:00:00", "2026-03-09T03:00:00"]


def test_a_time_the_clocks_skip_moves_forward_and_keeps_its_id() -> None:
    night = repeating(timed("2026-03-06T02:30:00", 30), "FREQ=DAILY")
    found = expand(night, [], window("2026-03-08", "2026-03-09"))
    assert rids(found) == ["2026-03-08T02:30:00"]
    assert found[0].timing == Timing(
        all_day=False, start_utc=utc("2026-03-08T07:30:00"), end_utc=utc("2026-03-08T08:00:00")
    )
    assert starts(found) == ["2026-03-08T03:30:00"]


def test_a_time_that_happens_twice_is_the_first() -> None:
    night = repeating(timed("2026-10-30T01:30:00", 30), "FREQ=DAILY")
    found = expand(night, [], window("2026-11-01", "2026-11-02"))
    assert rids(found) == ["2026-11-01T01:30:00"]
    assert found[0].timing.start_utc == utc("2026-11-01T05:30:00")


def test_all_day_spans_keep_their_dates() -> None:
    camp = repeating(all_day("2026-03-06", 3), "FREQ=WEEKLY;COUNT=3")  # Friday to Sunday
    found = expand(camp, [], window("2026-03-08", "2026-03-09"))  # the day the clocks change
    assert found == [Occurrence("2026-03-06", all_day("2026-03-06", 3), is_override=False)]
    assert rids(expand(camp, [], window("2026-03-09", "2026-03-31"))) == [
        "2026-03-13",
        "2026-03-20",
    ]


def test_an_all_day_until_includes_its_day() -> None:
    bins = repeating(all_day("2026-01-05"), "FREQ=WEEKLY;UNTIL=20260126")
    assert rids(expand(bins, [], YEAR)) == ["2026-01-05", "2026-01-12", "2026-01-19", "2026-01-26"]


def test_exdates_remove_occurrences() -> None:
    soccer = repeating(SOCCER, TUE_THU, exdates=("2026-10-06T16:00:00",))
    assert rids(expand(soccer, [], WEEK)) == ["2026-10-08T16:00:00"]


def test_a_date_exdate_on_a_timed_series_removes_that_day() -> None:
    soccer = repeating(SOCCER, TUE_THU, exdates=("2026-10-08",))
    assert rids(expand(soccer, [], WEEK)) == ["2026-10-06T16:00:00"]


def test_an_exdate_that_matches_nothing_changes_nothing() -> None:
    exdates = ("2026-10-07T16:00:00", "2026-10-06T17:00:00", "not an id")
    soccer = repeating(SOCCER, TUE_THU, exdates=exdates)
    assert rids(expand(soccer, [], WEEK)) == ["2026-10-06T16:00:00", "2026-10-08T16:00:00"]


def test_an_override_replaces_its_occurrence() -> None:
    later = Override("2026-10-08T16:00:00", timed("2026-10-08T17:30:00"))
    found = expand(repeating(SOCCER, TUE_THU), [later], WEEK)
    assert [(o.recurrence_id, o.is_override) for o in found] == [
        ("2026-10-06T16:00:00", False),
        ("2026-10-08T16:00:00", True),
    ]
    assert starts(found) == ["2026-10-06T16:00:00", "2026-10-08T17:30:00"]


def test_an_occurrence_moved_into_the_window_appears() -> None:
    to_saturday = Override("2026-10-13T16:00:00", timed("2026-10-10T10:00:00"))
    found = expand(repeating(SOCCER, TUE_THU), [to_saturday], WEEK)
    assert rids(found) == ["2026-10-06T16:00:00", "2026-10-08T16:00:00", "2026-10-13T16:00:00"]
    assert found[-1].is_override


def test_an_occurrence_moved_out_of_the_window_disappears() -> None:
    to_monday = Override("2026-10-06T16:00:00", timed("2026-10-12T16:00:00"))
    soccer = repeating(SOCCER, TUE_THU)
    assert rids(expand(soccer, [to_monday], WEEK)) == ["2026-10-08T16:00:00"]
    assert rids(expand(soccer, [to_monday], NEXT_WEEK)) == [
        "2026-10-06T16:00:00",
        "2026-10-13T16:00:00",
        "2026-10-15T16:00:00",
    ]


def test_a_cancelled_override_removes_its_occurrence() -> None:
    cancelled = Override("2026-10-08T16:00:00", None)
    assert rids(expand(repeating(SOCCER, TUE_THU), [cancelled], WEEK)) == ["2026-10-06T16:00:00"]


def test_an_override_without_its_occurrence_still_shows() -> None:
    stray = Override("2026-10-07T16:00:00", timed("2026-10-07T18:00:00"))
    found = expand(repeating(SOCCER, TUE_THU), [stray], WEEK)
    assert rids(found) == ["2026-10-06T16:00:00", "2026-10-07T16:00:00", "2026-10-08T16:00:00"]


def test_an_exdate_wins_over_an_override() -> None:
    soccer = repeating(SOCCER, TUE_THU, exdates=("2026-10-08T16:00:00",))
    moved = Override("2026-10-08T16:00:00", timed("2026-10-09T16:00:00"))
    assert rids(expand(soccer, [moved], WEEK)) == ["2026-10-06T16:00:00"]


def test_an_override_can_be_all_day_and_all_day_sorts_first() -> None:
    whole_day = Override("2026-10-08T16:00:00", all_day("2026-10-06"))
    found = expand(repeating(SOCCER, TUE_THU), [whole_day], WEEK)
    assert [(o.recurrence_id, o.timing.all_day) for o in found] == [
        ("2026-10-08T16:00:00", True),
        ("2026-10-06T16:00:00", False),
    ]


def test_rdates_add_occurrences_with_the_series_length() -> None:
    piano = repeating(
        timed("2026-09-28T17:00:00", 45),  # Mondays
        "FREQ=WEEKLY",
        rdates=("2026-10-07T18:30:00", "2026-10-05T17:00:00"),  # the second is already there
    )
    found = expand(piano, [], WEEK)
    assert rids(found) == ["2026-10-05T17:00:00", "2026-10-07T18:30:00"]
    assert found[1].timing == timed("2026-10-07T18:30:00", 45)


def test_a_date_rdate_on_a_timed_series_takes_the_series_time() -> None:
    piano = repeating(timed("2026-09-28T17:00:00", 45), "FREQ=WEEKLY", rdates=("2026-10-08",))
    assert rids(expand(piano, [], WEEK)) == ["2026-10-05T17:00:00", "2026-10-08T17:00:00"]


def test_rdates_alone_make_a_series() -> None:
    checkups = repeating(
        timed("2026-02-03T10:00:00"),
        None,
        rdates=("2026-08-04T10:00:00", "2026-05-05T10:00:00"),
        exdates=("2026-08-04T10:00:00",),
    )
    assert rids(expand(checkups, [], YEAR)) == ["2026-02-03T10:00:00", "2026-05-05T10:00:00"]


def test_count_ends_the_series_and_exdates_use_it_up() -> None:
    lessons = repeating(LESSONS, "FREQ=WEEKLY;BYDAY=MO,WE;COUNT=10")
    found = expand(lessons, [], YEAR)
    assert len(found) == 10 and rids(found)[-1] == "2026-05-06T16:00:00"
    skipped = replace(lessons, exdates=frozenset({"2026-04-08T16:00:00"}))
    found = expand(skipped, [], YEAR)
    assert len(found) == 9 and rids(found)[-1] == "2026-05-06T16:00:00"


def test_dtstart_is_the_first_occurrence_even_off_the_rule() -> None:
    monday = repeating(timed("2026-10-05T16:00:00"), f"{TUE_THU};COUNT=3")
    assert rids(expand(monday, [], YEAR)) == [
        "2026-10-05T16:00:00",
        "2026-10-06T16:00:00",
        "2026-10-08T16:00:00",
    ]


def test_until_is_inclusive() -> None:
    exactly = repeating(SOCCER, f"{TUE_THU};UNTIL=20261008T200000Z")  # Oct 8, 4 PM
    just_before = repeating(SOCCER, f"{TUE_THU};UNTIL=20261008T195959Z")
    assert rids(expand(exactly, [], YEAR))[-1] == "2026-10-08T16:00:00"
    assert rids(expand(just_before, [], YEAR))[-1] == "2026-10-06T16:00:00"


def test_monthly_by_nth_weekday() -> None:
    club = repeating(timed("2026-01-13T19:00:00", 90), "FREQ=MONTHLY;BYDAY=2TU")
    pizza = repeating(timed("2026-01-30T18:00:00", 120), "FREQ=MONTHLY;BYDAY=-1FR")
    half = window("2026-01-01", "2026-07-01")
    assert [rid[:10] for rid in starts(expand(club, [], half))] == [
        "2026-01-13",
        "2026-02-10",
        "2026-03-10",
        "2026-04-14",
        "2026-05-12",
        "2026-06-09",
    ]
    assert [rid[:10] for rid in starts(expand(pizza, [], half))] == [
        "2026-01-30",
        "2026-02-27",
        "2026-03-27",
        "2026-04-24",
        "2026-05-29",
        "2026-06-26",
    ]


def test_yearly_rules() -> None:
    brunch = repeating(timed("2024-05-12T11:00:00", 120), "FREQ=YEARLY;BYMONTH=5;BYDAY=2SU")
    birthday = repeating(all_day("2016-02-29"), "FREQ=YEARLY")
    assert rids(expand(brunch, [], window("2026-01-01", "2028-01-01"))) == [
        "2026-05-10T11:00:00",
        "2027-05-09T11:00:00",
    ]
    assert rids(expand(birthday, [], window("2026-01-01", "2033-01-01"))) == [
        "2028-02-29",
        "2032-02-29",
    ]


def test_a_single_event_has_no_recurrence_id() -> None:
    dentist = Series(timed("2026-10-08T14:30:00"), NY_KEY)
    alone = [Occurrence(None, dentist.timing, is_override=False)]
    assert expand(dentist, [], WEEK) == alone
    assert expand(dentist, [], NEXT_WEEK) == []
    assert expand(dentist, [Override("2026-10-08T14:30:00", None)], WEEK) == alone
    assert expand(replace(dentist, exdates=frozenset({"2026-10-08T14:30:00"})), [], WEEK) == alone


@pytest.mark.parametrize(
    ("start", "minutes", "inside"),
    [
        ("2026-10-08T11:00:00", 60, False),  # ends as the window starts
        ("2026-10-08T11:30:00", 60, True),
        ("2026-10-08T12:00:00", 0, True),  # zero length, exactly at the start
        ("2026-10-08T12:59:59", 0, True),
        ("2026-10-08T13:00:00", 0, False),
        ("2026-10-08T13:00:00", 30, False),  # starts as the window ends
    ],
)
def test_windows_are_half_open(start: str, minutes: int, inside: bool) -> None:
    hour = Window(
        utc("2026-10-08T12:00:00"), utc("2026-10-08T13:00:00"), date(2026, 10, 8), date(2026, 10, 9)
    )
    begin = utc(start)
    timing = Timing(all_day=False, start_utc=begin, end_utc=begin + timedelta(minutes=minutes))
    assert bool(expand(Series(timing, "UTC"), [], hour)) is inside
    assert bool(expand(Series(timing, "UTC", "FREQ=DAILY"), [], hour)) is inside


def test_limit_keeps_the_earliest() -> None:
    daily = repeating(timed("2026-10-01T07:00:00", 30), "FREQ=DAILY")
    assert rids(expand(daily, [], WEEK, limit=3)) == [
        "2026-10-04T07:00:00",
        "2026-10-05T07:00:00",
        "2026-10-06T07:00:00",
    ]
    early = Override("2026-10-09T07:00:00", timed("2026-10-04T06:00:00"))
    assert rids(expand(daily, [early], WEEK, limit=2)) == [
        "2026-10-09T07:00:00",
        "2026-10-04T07:00:00",
    ]
    assert expand(daily, [], WEEK, limit=0) == []
    assert len(expand(daily, [], window("2026-10-01", "2030-01-01"))) == MAX_PER_SERIES == 1000


@pytest.mark.parametrize(
    "rule",
    [
        "FREQ=DAILY;INTERVAL=3",
        "FREQ=WEEKLY;INTERVAL=2;BYDAY=SU,WE;WKST=SU",
        "FREQ=WEEKLY;INTERVAL=3;BYDAY=MO,SA;BYSETPOS=-1",
        "FREQ=MONTHLY;INTERVAL=5;BYDAY=-1FR",
        "FREQ=YEARLY;INTERVAL=2;BYMONTH=3,10;BYMONTHDAY=2",
    ],
)
def test_an_old_rule_jumps_to_where_walking_would_land(rule: str) -> None:
    """Without COUNT the walk starts near the window; with COUNT it has to start at DTSTART."""
    start = timed("2020-03-02T08:00:00")
    jumping = expand(repeating(start, rule), [], YEAR)
    walking = expand(repeating(start, f"{rule};COUNT=1000"), [], YEAR)
    assert jumping == walking and jumping


def test_an_old_daily_rule_expands_a_week_in_well_under_a_millisecond() -> None:
    old = repeating(timed("2016-10-09T07:00:00", 30), "FREQ=DAILY")
    assert len(expand(old, [], WEEK)) == 7
    runs = 300
    began = perf_counter()
    for _ in range(runs):
        expand(old, [], WEEK)
    average = (perf_counter() - began) / runs
    assert average < 0.001, f"{average * 1e6:.0f} µs per expansion"


# --- series_bounds ------------------------------------------------------------------------


def test_the_bounds_of_a_single_event() -> None:
    dentist = Series(timed("2026-10-08T14:30:00"), NY_KEY)
    trip = Series(all_day("2026-03-06", 3), "UTC")
    assert series_bounds(dentist) == (utc("2026-10-08T18:30:00"), utc("2026-10-08T19:30:00"))
    # All-day dates widen by a day each side, as UTC midnights.
    assert series_bounds(trip) == (utc("2026-03-05T00:00:00"), utc("2026-03-10T00:00:00"))


def test_a_rule_without_an_end_runs_to_far_future() -> None:
    assert series_bounds(repeating(SOCCER, TUE_THU)) == (utc("2026-09-29T20:00:00"), FAR_FUTURE)


def test_count_and_until_end_at_the_last_occurrence() -> None:
    lessons = repeating(LESSONS, "FREQ=WEEKLY;BYDAY=MO,WE;COUNT=10")
    soccer = repeating(SOCCER, f"{TUE_THU};UNTIL=20261119T235959Z")
    bins = repeating(all_day("2026-01-05"), "FREQ=WEEKLY;UNTIL=20260126")
    assert series_bounds(lessons) == (utc("2026-04-06T20:00:00"), utc("2026-05-06T21:00:00"))
    assert series_bounds(soccer) == (utc("2026-09-29T20:00:00"), utc("2026-11-19T22:00:00"))
    assert series_bounds(bins) == (utc("2026-01-04T00:00:00"), utc("2026-01-28T00:00:00"))


def test_overrides_and_rdates_widen_the_bounds() -> None:
    lessons = repeating(
        LESSONS, "FREQ=WEEKLY;BYDAY=MO,WE;COUNT=10", rdates=("2026-06-01T09:00:00",)
    )
    earlier = Override("2026-04-08T16:00:00", timed("2026-04-01T08:00:00"))
    cancelled = Override("2026-04-13T16:00:00", None)
    assert series_bounds(lessons, [earlier, cancelled]) == (
        utc("2026-04-01T12:00:00"),
        utc("2026-06-01T14:00:00"),
    )
    all_day_later = Override("2026-05-06T16:00:00", all_day("2026-07-04"))
    assert series_bounds(lessons, [all_day_later])[1] == utc("2026-07-06T00:00:00")


def test_a_count_too_sparse_to_walk_is_treated_as_endless() -> None:
    leap_days = repeating(
        timed("2028-02-29T09:00:00"), "FREQ=DAILY;BYMONTH=2;BYMONTHDAY=29;COUNT=999"
    )
    assert series_bounds(leap_days)[1] == FAR_FUTURE


# --- count_before -------------------------------------------------------------------------


def test_count_before() -> None:
    soccer = repeating(
        SOCCER, TUE_THU, rdates=("2026-09-30T08:00:00",), exdates=("2026-10-01T16:00:00",)
    )
    assert count_before(soccer, "2026-09-29T16:00:00") == 0
    assert count_before(soccer, "2026-10-06T15:00:00") == 2  # the exdate counts, the rdate doesn't
    assert count_before(soccer, "2026-10-06T16:00:00") == 2
    assert count_before(soccer, "2026-10-08T16:00:00") == 3
    # A date means that day at the series' time: 14 Tuesdays and 14 Thursdays come before.
    assert count_before(soccer, "2027-01-01") == 28


def test_count_before_counts_an_off_rule_dtstart_and_stops_at_count() -> None:
    monday = repeating(timed("2026-10-05T16:00:00"), f"{TUE_THU};COUNT=3")
    assert count_before(monday, "2026-10-06T16:00:00") == 1
    assert count_before(monday, "2026-12-31T16:00:00") == 3


def test_count_before_without_a_rule() -> None:
    dentist = Series(timed("2026-10-08T14:30:00"), NY_KEY)
    assert count_before(dentist, "2026-10-08T14:30:00") == 0
    assert count_before(dentist, "2026-10-09T09:00:00") == 1
    with pytest.raises(RecurrenceError) as caught:
        count_before(dentist, "next Tuesday")
    assert caught.value.code == "rrule_invalid"


# --- split ------------------------------------------------------------------------------------


def test_split_with_until_or_no_end() -> None:
    soccer = repeating(SOCCER, TUE_THU)
    assert split(soccer, "2026-10-08T16:00:00") == (
        f"{TUE_THU};UNTIL=20261008T195959Z",
        TUE_THU,
    )
    ending = repeating(SOCCER, f"{TUE_THU};UNTIL=20261119T235959Z")
    assert split(ending, "2026-10-08T16:00:00") == (
        f"{TUE_THU};UNTIL=20261008T195959Z",
        f"{TUE_THU};UNTIL=20261119T235959Z",
    )


def test_split_with_count() -> None:
    lessons = repeating(LESSONS, "FREQ=WEEKLY;BYDAY=MO,WE;COUNT=10")
    assert split(lessons, "2026-04-15T16:00:00") == (
        "FREQ=WEEKLY;BYDAY=MO,WE;COUNT=3",
        "FREQ=WEEKLY;BYDAY=MO,WE;COUNT=7",
    )


def test_split_an_all_day_series() -> None:
    bins = repeating(all_day("2026-01-05"), "FREQ=WEEKLY;UNTIL=20260126")
    assert split(bins, "2026-01-19") == ("FREQ=WEEKLY;UNTIL=20260118", "FREQ=WEEKLY;UNTIL=20260126")


def test_split_across_a_clock_change_partitions_the_series() -> None:
    walk = repeating(timed("2026-03-01T09:00:00", 30), "FREQ=DAILY;UNTIL=20260320T235959Z")
    head, tail = split(walk, "2026-03-10T09:00:00")
    assert head == "FREQ=DAILY;UNTIL=20260310T125959Z"  # 9 AM EDT is 13:00 UTC
    month = window("2026-02-01", "2026-04-01")
    whole = expand(walk, [], month)
    pivot = next(o for o in whole if o.recurrence_id == "2026-03-10T09:00:00")
    assert validate_rrule(tail, pivot.timing, NY_KEY) == tail
    before = expand(replace(walk, rrule=head), [], month)
    after = expand(replace(walk, timing=pivot.timing, rrule=tail), [], month)
    assert before + after == whole and len(before) == 9


@pytest.mark.parametrize(
    "rid",
    [
        "2026-09-29T16:00:00",  # the first one: that's "all", not a split
        "2026-10-07T16:00:00",  # a Wednesday
        "2026-10-08T17:00:00",  # the right day, the wrong time
        "2026-10-08",  # an all-day id on a timed series
        "2026-11-24T16:00:00",  # after UNTIL
        "2026-10-08T16:00",
    ],
)
def test_split_refuses_what_isnt_a_later_occurrence(rid: str) -> None:
    soccer = repeating(SOCCER, f"{TUE_THU};UNTIL=20261119T235959Z")
    with pytest.raises(RecurrenceError) as caught:
        split(soccer, rid)
    assert caught.value.code == "rrule_invalid"


def test_split_refuses_a_series_that_doesnt_repeat_by_rule() -> None:
    for series in (
        Series(timed("2026-10-08T14:30:00"), NY_KEY),
        repeating(timed("2026-02-03T10:00:00"), None, rdates=("2026-05-05T10:00:00",)),
    ):
        with pytest.raises(RecurrenceError):
            split(series, "2026-05-05T10:00:00")
    lessons = repeating(LESSONS, "FREQ=WEEKLY;BYDAY=MO,WE;COUNT=10")
    with pytest.raises(RecurrenceError):
        split(lessons, "2026-05-11T16:00:00")  # the eleventh


# --- shift_rid ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("rid", "delta", "expected"),
    [
        ("2026-10-08T16:00:00", timedelta(minutes=90), "2026-10-08T17:30:00"),
        ("2026-10-08T23:30:00", timedelta(hours=1), "2026-10-09T00:30:00"),
        ("2026-10-08T16:00:00", timedelta(hours=-17), "2026-10-07T23:00:00"),
        ("2026-03-08T01:30:00", timedelta(hours=1), "2026-03-08T02:30:00"),  # wall time
        ("2026-10-08", timedelta(days=2), "2026-10-10"),
        ("2026-10-08", timedelta(days=-1), "2026-10-07"),
        ("2026-10-08", timedelta(hours=-2), "2026-10-08"),  # whole days only, toward zero
        ("2026-10-08", timedelta(hours=26), "2026-10-09"),
        ("2026-10-08", timedelta(hours=-26), "2026-10-07"),
    ],
)
def test_shift_rid(rid: str, delta: timedelta, expected: str) -> None:
    assert shift_rid(rid, delta) == expected


def test_shift_rid_refuses_what_isnt_an_id() -> None:
    with pytest.raises(ValueError, match="recurrence id"):
        shift_rid("", timedelta(hours=1))


# --- describe -------------------------------------------------------------------------------

THURSDAY = timed("2026-10-08T16:00:00")
OCT_9 = timed("2026-10-09T16:00:00")


@pytest.mark.parametrize(
    ("rule", "timing", "sentence"),
    [
        ("FREQ=DAILY", THURSDAY, "Every day"),
        ("FREQ=DAILY;INTERVAL=3", THURSDAY, "Every 3 days"),
        ("FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR", THURSDAY, "Every weekday"),
        ("FREQ=DAILY;BYDAY=MO,TU,WE,TH,FR", THURSDAY, "Every weekday"),
        ("FREQ=WEEKLY", THURSDAY, "Every week on Thu"),
        ("FREQ=WEEKLY;BYDAY=TH", THURSDAY, "Every week on Thu"),
        ("FREQ=WEEKLY;BYDAY=TU,TH", THURSDAY, "Every week on Tue and Thu"),
        ("FREQ=WEEKLY;BYDAY=MO,WE,FR", THURSDAY, "Every week on Mon, Wed and Fri"),
        ("FREQ=WEEKLY;BYDAY=SA,SU", THURSDAY, "Every week on Sat and Sun"),
        ("FREQ=WEEKLY;BYDAY=MO,SU;WKST=SU", THURSDAY, "Every week on Sun and Mon"),
        ("FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR,SA,SU", THURSDAY, "Every day"),
        ("FREQ=WEEKLY;INTERVAL=2;BYDAY=TH", THURSDAY, "Every 2 weeks on Thu"),
        ("FREQ=MONTHLY", OCT_9, "Every month on the 9th"),
        ("FREQ=MONTHLY;BYMONTHDAY=9", THURSDAY, "Every month on the 9th"),
        ("FREQ=MONTHLY;BYMONTHDAY=1,15", THURSDAY, "Every month on the 1st and 15th"),
        ("FREQ=MONTHLY;BYMONTHDAY=-1", THURSDAY, "Every month on the last day"),
        ("FREQ=MONTHLY;BYDAY=2TU", THURSDAY, "Every month on the second Tuesday"),
        ("FREQ=MONTHLY;BYDAY=-1FR", THURSDAY, "Every month on the last Friday"),
        ("FREQ=MONTHLY;INTERVAL=3;BYMONTHDAY=1", THURSDAY, "Every 3 months on the 1st"),
        ("FREQ=YEARLY", OCT_9, "Every year on Oct 9"),
        ("FREQ=YEARLY;BYMONTH=10;BYMONTHDAY=9", THURSDAY, "Every year on Oct 9"),
        ("FREQ=YEARLY;INTERVAL=2", OCT_9, "Every 2 years on Oct 9"),
        ("FREQ=YEARLY;BYMONTH=5;BYDAY=2SU", THURSDAY, "Every year on the second Sunday of May"),
        ("FREQ=YEARLY;BYMONTH=9;BYDAY=1MO", THURSDAY, "Every year on the first Monday of Sep"),
        ("FREQ=WEEKLY;BYDAY=TU;COUNT=10", THURSDAY, "Every week on Tue, 10 times"),
        ("FREQ=DAILY;COUNT=1", THURSDAY, "Every day, once"),
        ("FREQ=DAILY;UNTIL=20261231T235959Z", THURSDAY, "Every day, until Dec 31"),
        ("FREQ=DAILY;UNTIL=20270115T235959Z", THURSDAY, "Every day, until Jan 15, 2027"),
        ("FREQ=WEEKLY;UNTIL=20261231", all_day("2026-10-08"), "Every week on Thu, until Dec 31"),
        ("FREQ=MONTHLY;BYDAY=MO,TU,WE,TH,FR;BYSETPOS=-1", THURSDAY, "Repeats on a custom schedule"),
        ("FREQ=MONTHLY;BYMONTH=1,7;BYMONTHDAY=1", THURSDAY, "Repeats on a custom schedule"),
        ("FREQ=DAILY;INTERVAL=2;BYDAY=MO,WE", THURSDAY, "Repeats on a custom schedule"),
        ("FREQ=DAILY;BYMONTHDAY=1", THURSDAY, "Repeats on a custom schedule"),
        ("FREQ=MONTHLY;BYDAY=MO", THURSDAY, "Repeats on a custom schedule"),
        ("FREQ=MONTHLY;BYDAY=1MO,3MO", THURSDAY, "Repeats on a custom schedule"),
        ("FREQ=MONTHLY;BYDAY=-2FR", THURSDAY, "Repeats on a custom schedule"),
        ("FREQ=YEARLY;BYMONTH=1,7", THURSDAY, "Repeats on a custom schedule"),
        ("FREQ=YEARLY;BYMONTHDAY=1", THURSDAY, "Repeats on a custom schedule"),
        (
            "FREQ=MONTHLY;BYDAY=MO,TU,WE,TH,FR;BYSETPOS=-1;COUNT=6",
            THURSDAY,
            "Repeats on a custom schedule, 6 times",
        ),
    ],
)
def test_describe(rule: str, timing: Timing, sentence: str) -> None:
    assert describe(rule, timing, NY_KEY) == sentence


@pytest.mark.parametrize(
    "text",
    ["1st", "2nd", "3rd", "4th", "11th", "12th", "13th", "21st", "22nd", "23rd", "24th", "31st"],
)
def test_describe_ordinals(text: str) -> None:
    day = int(text[:-2])
    sentence = describe(f"FREQ=MONTHLY;BYMONTHDAY={day}", THURSDAY, NY_KEY)
    assert sentence == f"Every month on the {text}"


@pytest.mark.parametrize(
    ("nth", "word"),
    [(1, "first"), (2, "second"), (3, "third"), (4, "fourth"), (5, "fifth"), (-1, "last")],
)
def test_describe_nth_weekdays(nth: int, word: str) -> None:
    sentence = describe(f"FREQ=MONTHLY;BYDAY={nth}WE", THURSDAY, NY_KEY)
    assert sentence == f"Every month on the {word} Wednesday"


def test_until_names_the_last_day_an_occurrence_can_fall_on() -> None:
    head, _ = split(repeating(SOCCER, TUE_THU), "2026-10-08T16:00:00")  # ends at 3:59:59 PM
    assert describe(head, SOCCER, NY_KEY) == "Every week on Tue and Thu, until Oct 7"
    evening = timed("2026-10-08T20:00:00")  # 8 PM is past midnight UTC: Dec 31 can't make it
    assert describe("FREQ=DAILY;UNTIL=20261231T235959Z", evening, NY_KEY) == (
        "Every day, until Dec 30"
    )


def test_describe_refuses_a_broken_rule() -> None:
    with pytest.raises(RecurrenceError):
        describe("FREQ=HOURLY", THURSDAY, NY_KEY)


# --- Properties -----------------------------------------------------------------------------

DAYS = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")
# Times of day with no daylight-saving gap: a series at 2:30 AM can't be split on the day the
# clocks skip 2:30 without its new start moving to 3:30.
CLOCKS = (time(0, 0), time(1, 30), time(6, 45), time(9, 0), time(12, 30), time(16, 0), time(23, 15))
WIDE = window("2024-12-01", "2028-01-01")


@st.composite
def rules(draw: st.DrawFn) -> str:
    freq = draw(st.sampled_from(("DAILY", "WEEKLY", "MONTHLY")))
    parts = [f"FREQ={freq}"]
    interval = draw(st.integers(1, 3))
    if interval > 1:
        parts.append(f"INTERVAL={interval}")
    if freq == "MONTHLY":
        kind = draw(st.sampled_from(("monthday", "nth", "default")))
        if kind == "monthday":
            parts.append(f"BYMONTHDAY={draw(st.sampled_from((*range(1, 29), -1)))}")
        elif kind == "nth":
            nth = draw(st.sampled_from((1, 2, 3, 4, -1)))
            parts.append(f"BYDAY={nth}{draw(st.sampled_from(DAYS))}")
    else:
        size = 4 if freq == "WEEKLY" else 5
        weekdays = draw(st.lists(st.sampled_from(DAYS), unique=True, max_size=size))
        if weekdays:
            parts.append(f"BYDAY={','.join(weekdays)}")
        if freq == "WEEKLY" and draw(st.booleans()):
            parts.append("WKST=SU")
    return ";".join(parts)


@st.composite
def serieses(draw: st.DrawFn) -> Series:
    rule = draw(rules())
    first = draw(st.dates(date(2025, 1, 1), date(2026, 12, 31)))
    timing: Timing
    if draw(st.booleans()):
        timing = all_day(first.isoformat(), draw(st.integers(1, 3)))
    else:
        begin = from_local(datetime.combine(first, draw(st.sampled_from(CLOCKS))), NY)
        minutes = draw(st.sampled_from((0, 30, 60, 240)))
        timing = Timing(all_day=False, start_utc=begin, end_utc=begin + timedelta(minutes=minutes))
    end = draw(st.sampled_from(("none", "count", "until")))
    if end == "count":
        rule += f";COUNT={draw(st.integers(2, 60))}"
    elif end == "until":
        last = first + timedelta(days=draw(st.integers(1, 700)))
        if timing.all_day:
            rule += f";UNTIL={last:%Y%m%d}"
        else:
            cut = from_local(datetime.combine(last, draw(st.sampled_from(CLOCKS))), NY)
            rule += f";UNTIL={cut:%Y%m%dT%H%M%SZ}"
    try:
        return Series(timing, NY_KEY, validate_rrule(rule, timing, NY_KEY))
    except RecurrenceError:
        reject()


def keyed(found: list[Occurrence]) -> list[tuple[str, str]]:
    shown: list[tuple[str, str]] = []
    for occurrence in found:
        timing = occurrence.timing
        start = timing.start_date if timing.all_day else timing.start_utc
        assert start is not None
        shown.append((occurrence.recurrence_id or "", start.isoformat()))
    return sorted(shown)


@settings(max_examples=60, deadline=None)
@given(data=st.data())
def test_a_split_partitions_the_series(data: st.DataObject) -> None:
    """The original's occurrences are exactly the truncated master's plus the new series'."""
    original = data.draw(serieses())
    whole = expand(original, [], WIDE, limit=10_000)
    assume(len(whole) >= 2)
    pivot = data.draw(st.sampled_from(whole[1:]))
    assert pivot.recurrence_id is not None
    head, tail = split(original, pivot.recurrence_id)
    assert validate_rrule(tail, pivot.timing, NY_KEY) == tail
    before = expand(replace(original, rrule=head), [], WIDE, limit=10_000)
    after = expand(replace(original, timing=pivot.timing, rrule=tail), [], WIDE, limit=10_000)
    assert keyed(before + after) == keyed(whole)
    assert before == whole[: len(before)]
    assert after[0] == pivot


def moved(timing: Timing, data: st.DataObject) -> Timing:
    if timing.all_day:
        assert timing.start_date is not None and timing.end_date is not None
        days = timedelta(days=data.draw(st.integers(-5, 5)))
        return replace(timing, start_date=timing.start_date + days, end_date=timing.end_date + days)
    assert timing.start_utc is not None and timing.end_utc is not None
    hours = timedelta(hours=data.draw(st.integers(-72, 72)))
    return replace(timing, start_utc=timing.start_utc + hours, end_utc=timing.end_utc + hours)


@settings(max_examples=60, deadline=None)
@given(data=st.data())
def test_buckets_add_up_to_the_whole(data: st.DataObject) -> None:
    """Expanding [a, c) equals expanding [a, b) and [b, c), deduplicated by recurrence id."""
    series = data.draw(serieses())
    first = series.timing.start_date
    if first is None:
        assert series.timing.start_utc is not None
        first = to_local(series.timing.start_utc, NY).date()
    a = first - timedelta(days=data.draw(st.integers(0, 40)))
    c = a + timedelta(days=data.draw(st.integers(1, 200)))
    b = a + timedelta(days=data.draw(st.integers(0, (c - a).days)))
    a_utc, c_utc = day_bounds(a, NY)[0], day_bounds(c, NY)[0]
    seconds = int((c_utc - a_utc).total_seconds())
    b_utc = a_utc + timedelta(seconds=data.draw(st.integers(0, seconds)))
    whole = Window(a_utc, c_utc, a, c)

    known = expand(series, [], whole, limit=10_000)
    picked = data.draw(st.lists(st.sampled_from(known), unique=True, max_size=6)) if known else []
    exdates: set[str] = set()
    overrides: list[Override] = []
    for occurrence in picked:
        assert occurrence.recurrence_id is not None
        action = data.draw(st.sampled_from(("exdate", "cancel", "move")))
        if action == "exdate":
            exdates.add(occurrence.recurrence_id)
        elif action == "cancel":
            overrides.append(Override(occurrence.recurrence_id, None))
        else:
            timing = occurrence.timing
            overrides.append(Override(occurrence.recurrence_id, moved(timing, data)))
    series = replace(series, exdates=frozenset(exdates))

    full = expand(series, overrides, whole, limit=10_000)
    halves = expand(series, overrides, Window(a_utc, b_utc, a, b), limit=10_000)
    halves += expand(series, overrides, Window(b_utc, c_utc, b, c), limit=10_000)
    assert len({o.recurrence_id for o in full}) == len(full)
    assert {o.recurrence_id: o for o in halves} == {o.recurrence_id: o for o in full}


Frequency = Literal[0, 1, 2, 3]  # dateutil's YEARLY to DAILY
FREQUENCIES: dict[str, Frequency] = {
    "DAILY": du.DAILY,
    "WEEKLY": du.WEEKLY,
    "MONTHLY": du.MONTHLY,
    "YEARLY": du.YEARLY,
}


@dataclass(frozen=True)
class Spec:
    """One rule, as RRULE text and as python-dateutil arguments."""

    text: str
    freq: Frequency
    interval: int
    wkst: int
    bymonth: tuple[int, ...] | None = None
    bymonthday: tuple[int, ...] | None = None
    byweekday: tuple[du.weekday, ...] | None = None
    bysetpos: tuple[int, ...] | None = None

    def dates(self, first: date, last: date) -> list[date]:
        found = du.rrule(
            self.freq,
            dtstart=datetime.combine(first, time()),
            interval=self.interval,
            wkst=self.wkst,
            until=datetime.combine(last, time()),
            bysetpos=self.bysetpos,
            bymonth=self.bymonth,
            bymonthday=self.bymonthday,
            byweekday=self.byweekday,
        )
        return [moment.date() for moment in found]


def csv(values: tuple[int, ...]) -> str:
    return ",".join(str(value) for value in values)


@st.composite
def specs(draw: st.DrawFn) -> Spec:
    name = draw(st.sampled_from(tuple(FREQUENCIES)))
    interval = draw(st.integers(1, 4))
    wkst = draw(st.integers(0, 6))
    text = [f"FREQ={name}", f"INTERVAL={interval}", f"WKST={DAYS[wkst]}"]
    small = st.integers(0, 3)
    bymonth = bymonthday = bysetpos = None
    byweekday = None
    if draw(small) == 0:
        bymonth = tuple(draw(st.lists(st.integers(1, 12), unique=True, min_size=1, max_size=4)))
        text.append(f"BYMONTH={csv(bymonth)}")
    if name != "WEEKLY" and draw(small) == 0:
        monthday = st.integers(-31, 31).filter(bool)
        bymonthday = tuple(draw(st.lists(monthday, unique=True, min_size=1, max_size=3)))
        text.append(f"BYMONTHDAY={csv(bymonthday)}")
    if draw(st.booleans()):
        entries: list[tuple[int, int]]
        if name in ("MONTHLY", "YEARLY") and draw(st.booleans()):
            nth = st.sampled_from((1, 2, 3, 4, -1, -2, 5 if name == "MONTHLY" else 53))
            pairs = st.tuples(nth, st.integers(0, 6))
            entries = draw(st.lists(pairs, unique=True, min_size=1, max_size=2))
        else:
            weekdays = draw(st.lists(st.integers(0, 6), unique=True, min_size=1, max_size=4))
            entries = [(0, weekday) for weekday in weekdays]
        text.append("BYDAY=" + ",".join(f"{nth or ''}{DAYS[day]}" for nth, day in entries))
        byweekday = tuple(du.weekday(day, nth or None) for nth, day in entries)
    if len(text) > 3 and draw(small) == 0:
        positions = st.sampled_from((1, 2, 3, -1, -2))
        bysetpos = tuple(draw(st.lists(positions, unique=True, min_size=1, max_size=2)))
        text.append(f"BYSETPOS={csv(bysetpos)}")
    return Spec(
        ";".join(text),
        FREQUENCIES[name],
        interval,
        wkst,
        bymonth,
        bymonthday,
        byweekday,
        bysetpos,
    )


def dates(first: date, last: date) -> Window:
    """[first, last) for all-day occurrences."""
    zone = ZoneInfo("UTC")
    return Window(day_bounds(first, zone)[0], day_bounds(last, zone)[0], first, last)


@settings(max_examples=150, deadline=None)
@given(specs(), st.dates(date(2024, 1, 1), date(2027, 12, 31)))
def test_the_walk_agrees_with_dateutil(spec: Spec, first: date) -> None:
    """Four years of a rule's days match python-dateutil's (after DTSTART, which RFC 5545
    always counts and dateutil only when the rule lands on it)."""
    timing = all_day(first.isoformat())
    try:
        validate_rrule(spec.text, timing, "UTC")
    except RecurrenceError:
        reject()
    series = Series(timing, "UTC", spec.text)
    horizon = first + timedelta(days=4 * 365)
    # dateutil only stops at a match, so leave out rules that go quiet after the horizon.
    assume(expand(series, [], dates(horizon + timedelta(days=1), date(2080, 1, 1)), limit=1))
    cut = first + timedelta(days=1)
    if spec.freq == du.WEEKLY and spec.bysetpos:
        # dateutil picks positions from a partial first week; RFC 5545 weeks are whole.
        cut = first - timedelta(days=(first.weekday() - spec.wkst) % 7)
        cut += timedelta(weeks=spec.interval)
    ours = expand(series, [], dates(cut, horizon + timedelta(days=1)), limit=10_000)
    try:
        theirs = [day for day in spec.dates(first, horizon) if day >= cut]
    except IndexError:
        # dateutil itself crashes on some yearly rules with a 53rd weekday and BYMONTH
        # ("FREQ=YEARLY;BYMONTH=1,2;BYDAY=1MO,53MO"); the reference can't judge those.
        reject()
    assert [occurrence.timing.start_date for occurrence in ours] == theirs
