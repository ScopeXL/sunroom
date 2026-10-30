"""From the editor's wall times to stored instants and back, and rows to the recurrence
engine's types (PLAN §7.2)."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, date, datetime, time, timedelta
from typing import cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sunroom.calendar.models import Event, EventStatus
from sunroom.calendar.schemas import EventFields
from sunroom.core.errors import AppError
from sunroom.domain import recurrence
from sunroom.domain.recurrence import Override, RecurrenceError, Series, Timing
from sunroom.domain.timeparts import from_local, to_local

DEFAULT_LENGTH = timedelta(hours=1)


def invalid(
    key: str, *fields: str, code: str = "invalid", params: Mapping[str, object] | None = None
) -> AppError:
    return AppError(422, code, key, params=params, extra={"fields": list(fields)})


def load_zone(tzid: str) -> ZoneInfo:
    try:
        return ZoneInfo(tzid)
    except ZoneInfoNotFoundError, ValueError:
        raise invalid("api.calendar.unknown_zone", "tzid") from None


def json_list(raw: str | None) -> list[str]:
    value: object = json.loads(raw or "[]")
    if not isinstance(value, list):
        return []
    return [str(item) for item in cast("list[object]", value)]


def timing_of(row: Event) -> Timing:
    if row.all_day:
        return Timing(all_day=True, start_date=row.start_date, end_date=row.end_date)
    return Timing(all_day=False, start_utc=row.start_utc, end_utc=row.end_utc)


def series_of(master: Event) -> Series:
    return Series(
        timing=timing_of(master),
        tzid=master.tzid or "UTC",
        rrule=master.rrule,
        rdates=tuple(json_list(master.rdates_json)),
        exdates=frozenset(json_list(master.exdates_json)),
    )


def override_of(row: Event) -> Override:
    cancelled = row.status == EventStatus.CANCELLED or row.deleted_at is not None
    return Override(
        recurrence_id=row.recurrence_id or "", timing=None if cancelled else timing_of(row)
    )


def set_timing(row: Event, timing: Timing, tzid: str | None) -> None:
    row.all_day = timing.all_day
    row.start_utc, row.end_utc = timing.start_utc, timing.end_utc
    row.start_date, row.end_date = timing.start_date, timing.end_date
    row.tzid = None if timing.all_day else tzid


def wall_time(value: datetime, zone: ZoneInfo) -> datetime:
    """The editor sends wall times; an aware value is converted to the event's zone."""
    if value.tzinfo is None:
        return value.replace(second=0, microsecond=0)
    return to_local(value.astimezone(UTC), zone).replace(second=0, microsecond=0)


def local_start(timing: Timing, zone: ZoneInfo) -> datetime:
    if timing.all_day:
        assert timing.start_date is not None
        return datetime.combine(timing.start_date, time.min)
    assert timing.start_utc is not None
    return to_local(timing.start_utc, zone)


def resolve_timing(
    current: Timing | None, current_tzid: str | None, fields: EventFields, default_tzid: str
) -> tuple[Timing, str]:
    """The timing after applying ``fields`` to ``current`` (None when creating): a moved start
    keeps the length unless an end is sent; switching between all-day and timed keeps the day."""
    tzid = fields.tzid or current_tzid or default_tzid
    zone = load_zone(tzid)
    old_zone = load_zone(current_tzid) if current_tzid else zone
    # A change keeps the event's kind unless all_day is sent; a new event without a time is
    # all-day.
    if fields.all_day is not None:
        all_day = fields.all_day
    elif current is not None:
        all_day = current.all_day
    else:
        all_day = fields.start is None

    if all_day:
        if fields.start_date is not None:
            start_date = fields.start_date
        elif fields.start is not None:
            start_date = fields.start.date()
        elif current is not None:
            start_date = local_start(current, old_zone).date()
        else:
            raise invalid("api.calendar.pick_day", "start_date")
        span = timedelta(days=1)
        if current is not None and current.all_day:
            assert current.start_date is not None and current.end_date is not None
            span = current.end_date - current.start_date
        end_date = fields.end_date if fields.end_date is not None else start_date + span
        if end_date <= start_date:
            raise invalid("api.calendar.last_before_first", "end_date")
        return Timing(all_day=True, start_date=start_date, end_date=end_date), tzid

    length = DEFAULT_LENGTH
    if current is not None and not current.all_day:
        assert current.start_utc is not None and current.end_utc is not None
        length = current.end_utc - current.start_utc
    if fields.start is not None:
        start = wall_time(fields.start, zone)
    elif current is not None and not current.all_day:
        start = local_start(current, old_zone)
    elif current is not None:
        start = datetime.combine(local_start(current, zone).date(), time(9))
    else:
        raise invalid("api.calendar.pick_time", "start")
    if fields.start_date is not None and fields.start is None:
        start = datetime.combine(fields.start_date, start.time())
    end = wall_time(fields.end, zone) if fields.end is not None else start + length
    start_utc, end_utc = from_local(start, zone), from_local(end, zone)
    if end_utc <= start_utc:
        raise invalid("api.calendar.end_before_start", "end")
    return Timing(all_day=False, start_utc=start_utc, end_utc=end_utc), tzid


def checked_rule(rrule: str, timing: Timing, tzid: str) -> str:
    try:
        return recurrence.validate_rrule(rrule, timing, tzid)
    except RecurrenceError as exc:
        raise invalid(exc.key, "rrule", code=exc.code) from None


def same_start_day(a: Timing, b: Timing, zone: ZoneInfo) -> bool:
    return local_start(a, zone).date() == local_start(b, zone).date()


def time_shift(a: Timing, b: Timing, zone: ZoneInfo) -> timedelta:
    """How far the wall-clock start moved from a to b (zero for all-day)."""
    if a.all_day or b.all_day:
        return timedelta(0)
    return local_start(b, zone) - local_start(a, zone)


def day_of(day: date | datetime) -> date:
    return day.date() if isinstance(day, datetime) else day
