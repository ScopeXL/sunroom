"""Google's ``recurrence`` lines (PLAN §8.1): RRULE, EXDATE and RDATE read into a series' rule
and recurrence ids, and written back. A New York household; 2026. Synthetic data only."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from sunroom.calendar.synced import SyncedEvent, SyncedSeries
from sunroom.core.lang import t_en
from sunroom.domain.recurrence import RecurrenceError, Timing
from sunroom.domain.timeparts import from_local
from sunroom.plugins.calendar_sync.ical import parse_recurrence_lines, recurrence_lines

NY = ZoneInfo("America/New_York")


def wall(text: str, zone: ZoneInfo = NY) -> datetime:
    return from_local(datetime.fromisoformat(text), zone)


THURSDAYS = Timing(
    all_day=False, start_utc=wall("2026-10-01T09:00:00"), end_utc=wall("2026-10-01T10:00:00")
)
CHRISTMAS = Timing(all_day=True, start_date=date(2015, 12, 25), end_date=date(2015, 12, 26))


def series_of(
    timing: Timing, tzid: str | None, rule: tuple[str | None, tuple[str, ...], tuple[str, ...]]
) -> SyncedSeries:
    rrule, rdates, exdates = rule
    master = SyncedEvent(title="Sample", timing=timing, tzid=tzid)
    return SyncedSeries(uid="sample", master=master, rrule=rrule, rdates=rdates, exdates=exdates)


def test_a_timed_series_reads_dates_from_any_zone_as_its_own() -> None:
    lines = [
        "RRULE:FREQ=WEEKLY;WKST=SU;BYDAY=TH;UNTIL=20261231T235959Z",
        "EXDATE;TZID=Europe/London:20261008T140000",  # 2 PM in London is 9 AM in New York
        "EXDATE:20261015T130000Z",
        "EXDATE;VALUE=DATE:20261126",  # a date on a timed series: that whole day
        "RDATE;TZID=America/New_York:20261021T090000",
    ]
    rule = parse_recurrence_lines(lines, THURSDAYS, "America/New_York", NY)
    assert rule == (
        "FREQ=WEEKLY;BYDAY=TH;WKST=SU;UNTIL=20261231T235959Z",
        ("2026-10-21T09:00:00",),
        ("2026-10-08T09:00:00", "2026-10-15T09:00:00", "2026-11-26"),
    )
    written = recurrence_lines(series_of(THURSDAYS, "America/New_York", rule))
    assert written == [
        "RRULE:FREQ=WEEKLY;BYDAY=TH;WKST=SU;UNTIL=20261231T235959Z",
        "EXDATE;TZID=America/New_York:20261008T090000,20261015T090000",
        "EXDATE;VALUE=DATE:20261126",
        "RDATE;TZID=America/New_York:20261021T090000",
    ]
    assert parse_recurrence_lines(written, THURSDAYS, "America/New_York", NY) == rule


def test_an_all_day_series_has_dates() -> None:
    lines = ["RRULE:FREQ=YEARLY", "EXDATE;VALUE=DATE:20201225", "RDATE;VALUE=DATE:20261224"]
    rule = parse_recurrence_lines(lines, CHRISTMAS, None, NY)
    assert rule == ("FREQ=YEARLY", ("2026-12-24",), ("2020-12-25",))
    written = recurrence_lines(series_of(CHRISTMAS, None, rule))
    assert written == lines
    assert parse_recurrence_lines(written, CHRISTMAS, None, NY) == rule


def test_a_series_in_utc_writes_utc_times() -> None:
    start = wall("2026-10-01T13:00:00", ZoneInfo("UTC"))
    timing = Timing(all_day=False, start_utc=start, end_utc=start + timedelta(hours=1))
    rule = parse_recurrence_lines(
        ["RRULE:FREQ=DAILY;COUNT=5", "EXDATE;TZID=America/New_York:20261003T090000"],
        timing,
        "UTC",
        NY,
    )
    assert rule == ("FREQ=DAILY;COUNT=5", (), ("2026-10-03T13:00:00",))
    written = recurrence_lines(series_of(timing, "UTC", rule))
    assert written == ["RRULE:FREQ=DAILY;COUNT=5", "EXDATE:20261003T130000Z"]
    assert parse_recurrence_lines(written, timing, "UTC", NY) == rule


def test_no_lines_means_no_repeat() -> None:
    assert parse_recurrence_lines([], THURSDAYS, "America/New_York", NY) == (None, (), ())
    assert recurrence_lines(series_of(THURSDAYS, "America/New_York", (None, (), ()))) == []


@pytest.mark.parametrize(
    ("lines", "code"),
    [
        (["RRULE:FREQ=HOURLY"], "rrule_unsupported"),
        (["RRULE:FREQ=WEEKLY", "RRULE:FREQ=DAILY"], "rrule_unsupported"),
        (["RRULE:FREQ=WEEKLY", "EXRULE:FREQ=WEEKLY;BYDAY=TH"], "rrule_unsupported"),
        (["RRULE:FREQ=WEEKLY;COUNT=5000"], "rrule_invalid"),
        (["RRULE:FREQ=WEEKLY", "EXDATE:2026-10-08"], "rrule_invalid"),
        (["RRULE:FREQ=WEEKLY", "EXDATE:20261332T090000Z"], "rrule_invalid"),
        (["not a line"], "rrule_invalid"),
    ],
)
def test_what_sunroom_cant_follow_raises(lines: list[str], code: str) -> None:
    with pytest.raises(RecurrenceError) as raised:
        parse_recurrence_lines(lines, THURSDAYS, "America/New_York", NY)
    assert raised.value.code == code
    assert t_en(raised.value.key)  # a sentence the API can say (ADR 0043)


def test_writing_needs_a_master() -> None:
    with pytest.raises(ValueError, match="main event"):
        recurrence_lines(SyncedSeries(uid="sample", master=None, rrule="FREQ=DAILY"))
