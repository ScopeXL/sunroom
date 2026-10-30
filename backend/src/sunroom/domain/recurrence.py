"""Recurring events: RFC 5545 rules expanded into occurrences (PLAN §7.2 to §7.4).

A small engine of our own for the part of RFC 5545 a family calendar needs: FREQ from DAILY
to YEARLY, INTERVAL, COUNT or UNTIL, BYDAY (nth weekdays in monthly and yearly rules),
BYMONTHDAY, BYMONTH, BYSETPOS and WKST. It walks a rule one period (a day, week, month or
year) at a time, so a call only ever looks at the periods its window touches: a rule from ten
years ago, or one that matches once a decade or never, costs what a fresh one does. The tests
hold it to python-dateutil and to recurring-ical-events.

Timed series run on naive wall times in their zone, so "9:00 every day" stays 9:00 across
daylight saving; each start becomes an instant with ``from_local`` and keeps the master's
length as an absolute delta. All-day series run on dates. DTSTART is always the first
occurrence and counts toward COUNT, even when the rule itself wouldn't produce it
(RFC 5545 §3.3.10, §3.8.5.3).
"""

from __future__ import annotations

import calendar
import re
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

from sunroom.domain.timeparts import (
    FAR_FUTURE,
    UTC,
    from_local,
    parse_rid,
    rid_date,
    rid_timed,
    to_local,
)

MAX_PER_SERIES = 1000
MAX_COUNT = 1000
MAX_INTERVAL = 9999

_DAYS = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")
_FREQS = ("DAILY", "WEEKLY", "MONTHLY", "YEARLY")
_TOO_OFTEN = ("SECONDLY", "MINUTELY", "HOURLY")
_KNOWN = ("INTERVAL", "COUNT", "UNTIL", "BYDAY", "BYMONTHDAY", "BYMONTH", "BYSETPOS", "WKST")
_UNSUPPORTED = ("BYSECOND", "BYMINUTE", "BYHOUR", "BYYEARDAY", "BYWEEKNO", "RSCALE", "SKIP")
_BYDAY = re.compile(r"([+-]?[0-9]{1,2})?(MO|TU|WE|TH|FR|SA|SU)")
_SIGNED = re.compile(r"[+-]?[0-9]{1,3}")
_UNSIGNED = re.compile(r"[0-9]{1,4}")
_UNTIL = re.compile(r"[0-9]{8}(T[0-9]{6}Z?)?")
_MAX_ORDINAL = date.max.toordinal()
_LAST_INSTANT = datetime.max.replace(tzinfo=UTC)
# Periods one call may walk. Real rules need a few hundred at most; this only stops a rule
# that matches once in centuries from scanning to the year 9999.
_SCAN_LIMIT = 100_000
# How far ahead a new rule must land again to count as repeating, in periods.
_PROBE = {"DAILY": 3000, "WEEKLY": 600, "MONTHLY": 600, "YEARLY": 400}


class RecurrenceError(ValueError):
    """A rule we refuse. ``code`` is ``rrule_invalid`` or ``rrule_unsupported``; ``key`` names
    the sentence for people in ``lang/en.json`` (``api.repeat.*``), which the API says with it
    (ADR 0043). The engine holds keys only, never the English: it stays standard library."""

    code: str
    key: str

    def __init__(self, code: str, key: str) -> None:
        super().__init__(key)
        self.code = code
        self.key = key


@dataclass(frozen=True, slots=True)
class Timing:
    all_day: bool
    start_utc: datetime | None = None  # timed: aware UTC
    end_utc: datetime | None = None
    start_date: date | None = None  # all-day: end exclusive (iCalendar semantics)
    end_date: date | None = None


@dataclass(frozen=True, slots=True)
class Series:
    timing: Timing  # the master's DTSTART/DTEND
    tzid: str  # the zone the rule runs in (timed); ignored for all-day
    rrule: str | None = None  # RFC 5545 RRULE value without the "RRULE:" prefix
    rdates: tuple[str, ...] = ()  # extra occurrences, as recurrence ids
    exdates: frozenset[str] = frozenset()  # recurrence ids removed from the series


@dataclass(frozen=True, slots=True)
class Override:
    recurrence_id: str  # the original occurrence start
    timing: Timing | None  # where it happens now; None = cancelled


@dataclass(frozen=True, slots=True)
class Window:
    start_utc: datetime  # half-open [start, end) for timed occurrences
    end_utc: datetime
    start_date: date  # half-open [start, end) household-zone dates, for all-day occurrences
    end_date: date


@dataclass(frozen=True, slots=True)
class Occurrence:
    recurrence_id: str | None  # None when the series doesn't repeat
    timing: Timing
    is_override: bool


def _invalid(key: str) -> RecurrenceError:
    return RecurrenceError("rrule_invalid", key)


def _unsupported(key: str) -> RecurrenceError:
    return RecurrenceError("rrule_unsupported", key)


# --- Parsing -------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Rule:
    freq: str
    interval: int = 1
    count: int | None = None
    until: str | None = None  # as written: YYYYMMDD, YYYYMMDDTHHMMSS or YYYYMMDDTHHMMSSZ
    bymonth: tuple[int, ...] = ()
    bymonthday: tuple[int, ...] = ()
    byday: tuple[tuple[int, int], ...] = ()  # (nth, weekday); nth 0 means every such weekday
    bysetpos: tuple[int, ...] = ()
    wkst: int = 0


def _signed_order(value: int) -> tuple[bool, int]:
    return value < 0, abs(value)


def _numbers(value: str, low: int, high: int, key: str, *, signed: bool) -> tuple[int, ...]:
    pattern = _SIGNED if signed else _UNSIGNED
    found: set[int] = set()
    for item in value.split(","):
        if not pattern.fullmatch(item):
            raise _invalid(key)
        number = int(item)
        if number == 0 or not low <= abs(number) <= high:
            raise _invalid(key)
        found.add(number)
    return tuple(sorted(found, key=_signed_order))


def _number(value: str, low: int, high: int, key: str) -> int:
    if "," in value:
        raise _invalid(key)
    return _numbers(value, low, high, key, signed=False)[0]


def _byday(value: str, freq: str) -> tuple[tuple[int, int], ...]:
    found: set[tuple[int, int]] = set()
    for item in value.split(","):
        match = _BYDAY.fullmatch(item)
        if match is None:
            raise _invalid("api.repeat.bad_weekdays")
        nth = int(match.group(1) or 0)
        if match.group(1) is not None:
            if freq not in ("MONTHLY", "YEARLY"):
                raise _invalid("api.repeat.week_of_month")
            if nth == 0 or abs(nth) > (5 if freq == "MONTHLY" else 53):
                raise _invalid("api.repeat.too_many_weekday")
        found.add((nth, _DAYS.index(match.group(2))))
    return tuple(sorted(found, key=lambda entry: (entry[1], _signed_order(entry[0]))))


def _check_until(value: str) -> str:
    if not _UNTIL.fullmatch(value):
        raise _invalid("api.repeat.bad_end_date")
    try:
        date(int(value[:4]), int(value[4:6]), int(value[6:8]))
        if len(value) > 8:
            time(int(value[9:11]), int(value[11:13]), int(value[13:15]))
    except ValueError:
        raise _invalid("api.repeat.unreal_end_date") from None
    return value


@lru_cache(maxsize=512)
def _parse(text: str) -> _Rule:
    body = text.strip().upper().removeprefix("RRULE:")
    parts: dict[str, str] = {}
    for chunk in body.split(";"):
        if not chunk.strip():
            continue
        name, equals, value = (piece.strip() for piece in chunk.partition("="))
        if not equals or not value:
            raise _invalid("api.repeat.bad_rule")
        if name in parts:
            raise _invalid("api.repeat.said_twice")
        parts[name] = value
    freq = parts.pop("FREQ", None)
    if freq is None:
        raise _invalid("api.repeat.no_freq")
    if freq in _TOO_OFTEN:
        raise _unsupported("api.repeat.too_often")
    if freq not in _FREQS:
        raise _invalid("api.repeat.bad_freq")
    for name in parts:
        if name in _UNSUPPORTED:
            raise _unsupported("api.repeat.unsupported_part")
        if name not in _KNOWN:
            raise _invalid("api.repeat.unknown_part")

    interval = _number(
        parts.get("INTERVAL", "1"),
        1,
        MAX_INTERVAL,
        "api.repeat.bad_interval",
    )
    count = None
    if "COUNT" in parts:
        count = _number(parts["COUNT"], 1, MAX_COUNT, "api.repeat.bad_count")
    until = _check_until(parts["UNTIL"]) if "UNTIL" in parts else None
    if count is not None and until is not None:
        raise _invalid("api.repeat.count_and_until")
    bymonth = (
        _numbers(parts["BYMONTH"], 1, 12, "api.repeat.bad_month", signed=False)
        if "BYMONTH" in parts
        else ()
    )
    bymonthday = (
        _numbers(parts["BYMONTHDAY"], 1, 31, "api.repeat.bad_month_day", signed=True)
        if "BYMONTHDAY" in parts
        else ()
    )
    if bymonthday and freq == "WEEKLY":
        raise _invalid("api.repeat.weekly_month_days")
    byday = _byday(parts["BYDAY"], freq) if "BYDAY" in parts else ()
    bysetpos = (
        _numbers(parts["BYSETPOS"], 1, 366, "api.repeat.bad_position", signed=True)
        if "BYSETPOS" in parts
        else ()
    )
    if bysetpos and not (byday or bymonthday or bymonth):
        raise _invalid("api.repeat.position_alone")
    wkst = parts.get("WKST", "MO")
    if wkst not in _DAYS:
        raise _invalid("api.repeat.bad_week_start")
    return _Rule(
        freq=freq,
        interval=interval,
        count=count,
        until=until,
        bymonth=bymonth,
        bymonthday=bymonthday,
        byday=byday,
        bysetpos=bysetpos,
        wkst=_DAYS.index(wkst),
    )


def _join(values: Iterable[int]) -> str:
    return ",".join(str(value) for value in values)


def _format(rule: _Rule, until: datetime | date | None) -> str:
    parts = [f"FREQ={rule.freq}"]
    if rule.interval != 1:
        parts.append(f"INTERVAL={rule.interval}")
    if rule.bymonth:
        parts.append(f"BYMONTH={_join(rule.bymonth)}")
    if rule.bymonthday:
        parts.append(f"BYMONTHDAY={_join(rule.bymonthday)}")
    if rule.byday:
        days = (f"{nth}{_DAYS[day]}" if nth else _DAYS[day] for nth, day in rule.byday)
        parts.append(f"BYDAY={','.join(days)}")
    if rule.bysetpos:
        parts.append(f"BYSETPOS={_join(rule.bysetpos)}")
    if rule.wkst:
        parts.append(f"WKST={_DAYS[rule.wkst]}")
    if rule.count is not None:
        parts.append(f"COUNT={rule.count}")
    if until is not None:
        parts.append(f"UNTIL={_until_text(until)}")
    return ";".join(parts)


def _until_text(value: datetime | date) -> str:
    if not isinstance(value, datetime):
        return f"{value.year:04d}{value.month:02d}{value.day:02d}"
    at = value.astimezone(UTC)
    return f"{at.year:04d}{at.month:02d}{at.day:02d}T{at.hour:02d}{at.minute:02d}{at.second:02d}Z"


# --- The series' anchor ----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Anchor:
    zone: ZoneInfo | None  # None for all-day series
    first: date  # DTSTART's (local) date
    at: time  # DTSTART's local time of day; midnight for all-day
    length: timedelta  # absolute for timed series, whole days for all-day ones


def _zone(tzid: str) -> ZoneInfo:
    try:
        return ZoneInfo(tzid)
    except KeyError, ValueError:  # ZoneInfoNotFoundError is a KeyError
        raise ValueError(f"unknown time zone: {tzid!r}") from None


def _clock(value: datetime) -> time:
    return time(value.hour, value.minute, value.second, value.microsecond)


def _anchor(timing: Timing, tzid: str) -> _Anchor:
    if timing.all_day:
        if timing.start_date is None or timing.end_date is None:
            raise ValueError("an all-day timing needs start_date and end_date")
        days = max((timing.end_date - timing.start_date).days, 0)
        return _Anchor(None, timing.start_date, time(), timedelta(days=days))
    if timing.start_utc is None or timing.end_utc is None:
        raise ValueError("a timed timing needs start_utc and end_utc")
    zone = _zone(tzid)
    local = to_local(timing.start_utc, zone)
    length = max(timing.end_utc - timing.start_utc, timedelta(0))
    return _Anchor(zone, local.date(), _clock(local), length)


def _from_local(naive: datetime, zone: ZoneInfo) -> datetime:
    try:
        return from_local(naive, zone)
    except OverflowError:
        return _LAST_INSTANT if naive.year > 1 else datetime.min.replace(tzinfo=UTC)


def _local_day(instant: datetime, zone: ZoneInfo) -> date:
    try:
        return to_local(instant, zone).date()
    except OverflowError:
        return date.max if instant.year > 1 else date.min


def _add_days(day: date, days: int) -> date:
    ordinal = min(max(day.toordinal() + days, 1), _MAX_ORDINAL)
    return date.fromordinal(ordinal)


def _until(rule: _Rule, anchor: _Anchor) -> datetime | date | None:
    """UNTIL as an aware instant (timed series) or a date (all-day series). A date ends a timed
    series at the end of that day in its zone; a time without Z is wall time in the zone."""
    text = rule.until
    if text is None:
        return None
    day = date(int(text[:4]), int(text[4:6]), int(text[6:8]))
    if anchor.zone is None:
        return day
    if len(text) == 8:
        return _from_local(datetime.combine(day, time(23, 59, 59)), anchor.zone)
    clock = time(int(text[9:11]), int(text[11:13]), int(text[13:15]))
    naive = datetime.combine(day, clock)
    if text.endswith("Z"):
        return naive.replace(tzinfo=UTC)
    return _from_local(naive, anchor.zone)


def _rid_of(anchor: _Anchor, day: date, at: time) -> str:
    if anchor.zone is None:
        return rid_date(day)
    return rid_timed(datetime.combine(day, at))


def _timing_at(anchor: _Anchor, day: date, at: time) -> Timing:
    if anchor.zone is None:
        return Timing(all_day=True, start_date=day, end_date=_add_days(day, anchor.length.days))
    start = _from_local(datetime.combine(day, at), anchor.zone)
    try:
        end = start + anchor.length
    except OverflowError:
        end = _LAST_INSTANT
    return Timing(all_day=False, start_utc=start, end_utc=end)


def _point(rid: str, anchor: _Anchor) -> tuple[date, time]:
    """A recurrence id as (day, time of day). A date id on a timed series means DTSTART's time
    that day; a timed id on an all-day series means its day."""
    value = parse_rid(rid)
    if isinstance(value, datetime):
        if anchor.zone is None:
            return value.date(), time()
        return value.date(), _clock(value)
    return value, anchor.at


# --- Walking a rule --------------------------------------------------------------------------


def _nth(low: date, high: date, nth: int, weekday: int) -> date | None:
    """The nth (or, counting back, -nth) ``weekday`` in [low, high]."""
    if nth > 0:
        day = low.toordinal() + (weekday - low.weekday()) % 7 + 7 * (nth - 1)
        return date.fromordinal(day) if day <= high.toordinal() else None
    day = high.toordinal() - (high.weekday() - weekday) % 7 + 7 * (nth + 1)
    return date.fromordinal(day) if day >= low.toordinal() else None


def _pick(days: list[date], positions: tuple[int, ...]) -> list[date]:
    size = len(days)
    chosen = {days[pos - 1 if pos > 0 else size + pos] for pos in positions if abs(pos) <= size}
    return sorted(chosen)


class _Walk:
    """One rule anchored at its DTSTART, walked a period at a time."""

    __slots__ = (
        "anchor",
        "base",
        "bymonth",
        "bymonthday",
        "months",
        "negative_days",
        "nth",
        "plain",
        "positive_days",
        "rule",
        "stop",
        "truncated",
        "until",
        "week_offsets",
    )

    def __init__(self, rule: _Rule, anchor: _Anchor) -> None:
        self.rule = rule
        self.anchor = anchor
        first = anchor.first
        byday, bymonthday, bymonth = rule.byday, rule.bymonthday, rule.bymonth
        if not byday and not bymonthday:  # RFC 5545: what the rule leaves out comes from DTSTART
            if rule.freq == "WEEKLY":
                byday = ((0, first.weekday()),)
            elif rule.freq == "MONTHLY":
                bymonthday = (first.day,)
            elif rule.freq == "YEARLY":
                bymonthday = (first.day,)
                bymonth = bymonth or (first.month,)
        self.plain = frozenset(day for nth, day in byday if nth == 0)
        self.nth = tuple((nth, day) for nth, day in byday if nth != 0)
        self.bymonthday = bymonthday
        self.positive_days = frozenset(day for day in bymonthday if day > 0)
        self.negative_days = frozenset(day for day in bymonthday if day < 0)
        self.bymonth = frozenset(bymonth)
        self.months = tuple(sorted(bymonth))
        self.week_offsets = tuple(sorted((day - rule.wkst) % 7 for day in self.plain))
        self.until = _until(rule, anchor)
        self.truncated = False  # the last walk gave up at _SCAN_LIMIT periods
        self.stop: date | None = None  # no occurrence falls after this day
        if isinstance(self.until, datetime):
            assert anchor.zone is not None
            self.stop = _add_days(_local_day(self.until, anchor.zone), 1)
        elif self.until is not None:
            self.stop = self.until
        if rule.freq == "DAILY":
            self.base = first.toordinal()
        elif rule.freq == "WEEKLY":
            self.base = first.toordinal() - (first.weekday() - rule.wkst) % 7
        elif rule.freq == "MONTHLY":
            self.base = first.year * 12 + first.month - 1
        else:
            self.base = first.year

    def period_of(self, day: date) -> int:
        freq, step = self.rule.freq, self.rule.interval
        if freq == "DAILY":
            return (day.toordinal() - self.base) // step
        if freq == "WEEKLY":
            return (day.toordinal() - self.base) // (7 * step)
        if freq == "MONTHLY":
            return (day.year * 12 + day.month - 1 - self.base) // step
        return (day.year - self.base) // step

    def period_start(self, k: int) -> date | None:
        freq, step = self.rule.freq, self.rule.interval
        if freq in ("DAILY", "WEEKLY"):
            ordinal = self.base + k * step * (1 if freq == "DAILY" else 7)
            return date.fromordinal(max(ordinal, 1)) if ordinal <= _MAX_ORDINAL else None
        if freq == "MONTHLY":
            year, month = divmod(self.base + k * step, 12)
            return date(year, month + 1, 1) if year <= 9999 else None
        year = self.base + k * step
        return date(year, 1, 1) if year <= 9999 else None

    def candidates(self, k: int) -> list[date]:
        """The rule's days in period k, BYSETPOS applied, before DTSTART is considered."""
        freq, step = self.rule.freq, self.rule.interval
        found: list[date]
        if freq == "DAILY":
            ordinal = self.base + k * step
            if ordinal > _MAX_ORDINAL:
                return []
            day = date.fromordinal(ordinal)
            found = [day] if self._daily_match(day) else []
        elif freq == "WEEKLY":
            start = self.base + 7 * k * step
            found = []
            for offset in self.week_offsets:
                ordinal = start + offset
                if 1 <= ordinal <= _MAX_ORDINAL:
                    day = date.fromordinal(ordinal)
                    if not self.bymonth or day.month in self.bymonth:
                        found.append(day)
        elif freq == "MONTHLY":
            year, month = divmod(self.base + k * step, 12)
            month += 1
            if year > 9999 or (self.bymonth and month not in self.bymonth):
                return []
            found = self._in_month(year, month, None)
        else:
            year = self.base + k * step
            if year > 9999:
                return []
            found = self._in_year(year)
        if self.rule.bysetpos:
            found = _pick(found, self.rule.bysetpos)
        return found

    def _monthday_match(self, day: date, length: int) -> bool:
        return day.day in self.positive_days or day.day - length - 1 in self.negative_days

    def _weekday_match(self, day: date, low: date, high: date) -> bool:
        weekday = day.weekday()
        if weekday in self.plain:
            return True
        return any(wd == weekday and _nth(low, high, n, wd) == day for n, wd in self.nth)

    def _daily_match(self, day: date) -> bool:
        if self.bymonth and day.month not in self.bymonth:
            return False
        if self.bymonthday and not self._monthday_match(
            day, calendar.monthrange(day.year, day.month)[1]
        ):
            return False
        return not self.plain or day.weekday() in self.plain

    def _weekdays(self, low: date, high: date) -> list[date]:
        found: set[date] = set()
        end = high.toordinal()
        for weekday in self.plain:
            ordinal = low.toordinal() + (weekday - low.weekday()) % 7
            while ordinal <= end:
                found.add(date.fromordinal(ordinal))
                ordinal += 7
        for nth, weekday in self.nth:
            day = _nth(low, high, nth, weekday)
            if day is not None:
                found.add(day)
        return sorted(found)

    def _in_month(self, year: int, month: int, scope: tuple[date, date] | None) -> list[date]:
        """Days of one month; nth weekdays count within ``scope`` (the month by default)."""
        length = calendar.monthrange(year, month)[1]
        low, high = scope or (date(year, month, 1), date(year, month, length))
        if not self.bymonthday:
            return self._weekdays(low, high)
        days = sorted({day if day > 0 else length + 1 + day for day in self.bymonthday})
        found = [date(year, month, day) for day in days if 1 <= day <= length]
        if self.plain or self.nth:
            found = [day for day in found if self._weekday_match(day, low, high)]
        return found

    def _in_year(self, year: int) -> list[date]:
        if self.months:
            return [day for month in self.months for day in self._in_month(year, month, None)]
        scope = (date(year, 1, 1), date(year, 12, 31))
        if self.bymonthday:
            return [day for month in range(1, 13) for day in self._in_month(year, month, scope)]
        return self._weekdays(*scope)

    def before_until(self, day: date) -> bool:
        until = self.until
        if until is None:
            return True
        if isinstance(until, datetime):
            assert self.anchor.zone is not None
            return _from_local(datetime.combine(day, self.anchor.at), self.anchor.zone) <= until
        return day <= until

    def days(self, low: date, high: date) -> Iterator[date]:
        """Occurrence days in [low, high], ascending: DTSTART, then the rule's, within COUNT
        and UNTIL. Without COUNT the walk starts at the period holding ``low``."""
        self.truncated = False
        first = self.anchor.first
        if low <= first <= high:
            yield first
        remaining = None if self.rule.count is None else self.rule.count - 1
        if remaining == 0:
            return
        if self.stop is not None and self.stop < high:
            high = self.stop
        if first >= high:
            return
        k = 0 if remaining is not None else max(self.period_of(low), 0)
        for _ in range(_SCAN_LIMIT):
            start = self.period_start(k)
            if start is None or start > high:
                return
            for day in self.candidates(k):
                if day <= first:
                    continue
                if day > high or not self.before_until(day):
                    return
                if day >= low:
                    yield day
                if remaining is not None:
                    remaining -= 1
                    if remaining == 0:
                        return
            k += 1
        self.truncated = True

    def last(self) -> date | None:
        """The last occurrence day, or None when the rule never ends (or ends past the scan)."""
        first = self.anchor.first
        if self.rule.count is not None:
            found = list(self.days(first, date.max))
            return None if self.truncated else found[-1]
        if self.stop is None:
            return None
        k = self.period_of(self.stop)
        for _ in range(_SCAN_LIMIT):
            if k < 0:
                return first
            for day in reversed(self.candidates(k)):
                if first < day <= self.stop and self.before_until(day):
                    return day
            k -= 1
        return None

    def count_before(self, day: date, at: time) -> int:
        point = (day, at)
        days = self.days(self.anchor.first, day)
        return sum(1 for found in days if (found, self.anchor.at) < point)

    def repeats(self) -> bool:
        """Whether the rule lands on any day after DTSTART within a generous horizon."""
        first = self.anchor.first
        for k in range(_PROBE[self.rule.freq]):
            if self.period_start(k) is None:
                return False
            if any(day > first for day in self.candidates(k)):
                return True
        return False


# --- Public functions --------------------------------------------------------------------------


def validate_rrule(rrule: str, timing: Timing, tzid: str) -> str:
    """The rule in normal form (uppercase, parts in a stable order, UNTIL in UTC for timed
    series and as a date for all-day ones), or RecurrenceError."""
    rule = _parse(rrule)
    anchor = _anchor(timing, tzid)
    walk = _Walk(rule, anchor)
    until = walk.until
    if isinstance(until, datetime):
        assert timing.start_utc is not None
        if until < timing.start_utc:
            raise _invalid("api.repeat.ends_before_start")
    elif until is not None and until < anchor.first:
        raise _invalid("api.repeat.ends_before_start")
    if not walk.repeats():
        raise _invalid("api.repeat.never_again")
    return _format(rule, until)


def _overlaps(timing: Timing, window: Window) -> bool:
    if timing.all_day:
        start, end = timing.start_date, timing.end_date
        if start is None or end is None:
            return False
        if start == end:
            return window.start_date <= start < window.end_date
        return start < window.end_date and end > window.start_date
    instant, finish = timing.start_utc, timing.end_utc
    if instant is None or finish is None:
        return False
    if instant == finish:
        return window.start_utc <= instant < window.end_utc
    return instant < window.end_utc and finish > window.start_utc


def _search_days(anchor: _Anchor, window: Window) -> tuple[date, date]:
    """Local days whose occurrences could touch the window (a day of slack each side)."""
    if anchor.zone is None:
        low = _add_days(window.start_date, -anchor.length.days - 1)
        return low, window.end_date
    try:
        earliest = window.start_utc - anchor.length
    except OverflowError:
        earliest = datetime.min.replace(tzinfo=UTC)
    low = _add_days(_local_day(earliest, anchor.zone), -1)
    return low, _add_days(_local_day(window.end_utc, anchor.zone), 1)


def _sort_key(occurrence: Occurrence) -> tuple[datetime, int, str]:
    timing = occurrence.timing
    if timing.all_day:
        assert timing.start_date is not None
        return datetime.combine(timing.start_date, time(), UTC), 0, occurrence.recurrence_id or ""
    assert timing.start_utc is not None
    return timing.start_utc, 1, occurrence.recurrence_id or ""


def expand(
    series: Series,
    overrides: Sequence[Override],
    window: Window,
    *,
    limit: int = MAX_PER_SERIES,
) -> list[Occurrence]:
    """The series' occurrences that overlap the window, sorted by start, at most ``limit``."""
    if limit <= 0:
        return []
    if not series.rrule and not series.rdates:
        if _overlaps(series.timing, window):
            return [Occurrence(recurrence_id=None, timing=series.timing, is_override=False)]
        return []
    anchor = _anchor(series.timing, series.tzid)
    exdates = series.exdates
    # An EXDATE in the other shape (a date on a timed series, or the reverse) removes that day.
    exdays: set[date] = set()
    for text in exdates:
        try:
            value = parse_rid(text)
        except ValueError:
            continue
        if isinstance(value, datetime) == (anchor.zone is None):
            exdays.add(value.date() if isinstance(value, datetime) else value)
    replaced: dict[str, Override] = {}
    for override in overrides:
        if override.recurrence_id not in exdates:
            replaced[override.recurrence_id] = override
    found: list[Occurrence] = []
    seen: set[str] = set()

    def add(day: date, at: time) -> bool:
        rid = _rid_of(anchor, day, at)
        if rid in seen:
            return False
        seen.add(rid)
        if rid in replaced or rid in exdates or day in exdays:
            return False
        timing = _timing_at(anchor, day, at)
        if not _overlaps(timing, window):
            return False
        found.append(Occurrence(recurrence_id=rid, timing=timing, is_override=False))
        return True

    low, high = _search_days(anchor, window)
    if series.rrule:
        walk = _Walk(_parse(series.rrule), anchor)
        kept = 0
        for day in walk.days(low, high):
            kept += add(day, anchor.at)
            if kept >= limit:
                break
    elif low <= anchor.first <= high:
        add(anchor.first, anchor.at)
    for text in series.rdates:
        try:
            day, at = _point(text, anchor)
        except ValueError:
            continue
        add(day, at)
    for rid, override in replaced.items():
        if override.timing is not None and _overlaps(override.timing, window):
            found.append(Occurrence(recurrence_id=rid, timing=override.timing, is_override=True))
    found.sort(key=_sort_key)
    return found[:limit]


def _span(timing: Timing) -> tuple[datetime, datetime] | None:
    """A timing as UTC instants; all-day dates widen by a day each side, so any household
    zone's day is covered."""
    if timing.all_day:
        if timing.start_date is None or timing.end_date is None:
            return None
        start = datetime.combine(_add_days(timing.start_date, -1), time(), UTC)
        return start, datetime.combine(_add_days(timing.end_date, 1), time(), UTC)
    if timing.start_utc is None or timing.end_utc is None:
        return None
    return timing.start_utc, timing.end_utc


def series_bounds(series: Series, overrides: Sequence[Override] = ()) -> tuple[datetime, datetime]:
    """(window_start_utc, window_end_utc) for indexed range queries: from the earliest start to
    the latest end over the whole series, overrides and RDATEs included; FAR_FUTURE when the
    rule never ends. Never narrower than the occurrences (an EXDATE doesn't shrink it)."""
    own = _span(series.timing)
    if own is None:
        raise ValueError("the series' timing is incomplete")
    if not series.rrule and not series.rdates:
        return own
    anchor = _anchor(series.timing, series.tzid)
    spans = [own]
    endless = False
    if series.rrule:
        last = _Walk(_parse(series.rrule), anchor).last()
        if last is None:
            endless = True
        else:
            spans.append(_span(_timing_at(anchor, last, anchor.at)) or own)
    for text in series.rdates:
        try:
            day, at = _point(text, anchor)
        except ValueError:
            continue
        spans.append(_span(_timing_at(anchor, day, at)) or own)
    for override in overrides:
        if override.timing is not None:
            spans.append(_span(override.timing) or own)
    start = min(span[0] for span in spans)
    return start, FAR_FUTURE if endless else max(span[1] for span in spans)


def count_before(series: Series, rid: str) -> int:
    """How many occurrences the rule generates before ``rid``'s original start. DTSTART counts
    and EXDATEs count (as for COUNT); RDATEs don't."""
    anchor = _anchor(series.timing, series.tzid)
    try:
        day, at = _point(rid, anchor)
    except ValueError:
        raise _invalid("api.repeat.not_a_day") from None
    if not series.rrule:
        return 1 if (anchor.first, anchor.at) < (day, at) else 0
    return _Walk(_parse(series.rrule), anchor).count_before(day, at)


def last_day(series: Series) -> date | None:
    """The local day the rule's last occurrence starts on (its UNTIL or COUNT; EXDATEs and
    RDATEs aside), the first day for a series without a rule, or None when it never ends."""
    anchor = _anchor(series.timing, series.tzid)
    if not series.rrule:
        return anchor.first
    return _Walk(_parse(series.rrule), anchor).last()


def split(series: Series, rid: str) -> tuple[str, str]:
    """Rules for "this and the ones after" at occurrence ``rid`` (never the first): one that
    ends the series just before it, and one for a new series that starts at it."""
    if not series.rrule:
        raise _invalid("api.repeat.not_repeating")
    rule = _parse(series.rrule)
    anchor = _anchor(series.timing, series.tzid)
    walk = _Walk(rule, anchor)
    try:
        value = parse_rid(rid)
    except ValueError:
        raise _invalid("api.repeat.not_a_day") from None
    if isinstance(value, datetime) != (anchor.zone is not None):
        raise _invalid("api.repeat.not_a_day")
    day, at = _point(rid, anchor)
    if _rid_of(anchor, day, anchor.at) != rid or day not in walk.days(day, day):
        raise _invalid("api.repeat.not_a_day")
    if day == anchor.first:
        raise _invalid("api.repeat.first_time")
    if rule.count is not None:
        before = walk.count_before(day, at)
        return (
            _format(replace(rule, count=before), None),
            _format(replace(rule, count=rule.count - before), None),
        )
    cut: datetime | date
    if anchor.zone is None:
        cut = _add_days(day, -1)
    else:
        cut = from_local(datetime.combine(day, at), anchor.zone) - timedelta(seconds=1)
    return _format(rule, cut), _format(rule, walk.until)


def shift_rid(rid: str, delta: timedelta) -> str:
    """Move a recurrence id with its series: a timed id by ``delta`` of wall time, an all-day id
    by the whole days in ``delta`` (toward zero)."""
    value = parse_rid(rid)
    if isinstance(value, datetime):
        return rid_timed(value + delta)
    days = delta.days if delta >= timedelta(0) else -(-delta).days
    return rid_date(value + timedelta(days=days))


# --- Describing a rule --------------------------------------------------------------------------

_SHORT_DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_LONG_DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_NTH = {1: "first", 2: "second", 3: "third", 4: "fourth", 5: "fifth", -1: "last"}
_UNITS = {"DAILY": "day", "WEEKLY": "week", "MONTHLY": "month", "YEARLY": "year"}
_CUSTOM = "Repeats on a custom schedule"


def _ordinal(number: int) -> str:
    suffix = {1: "st", 2: "nd", 3: "rd"}.get(number % 10, "th")
    return f"{number}{'th' if 11 <= number % 100 <= 13 else suffix}"


def _listing(items: Sequence[str]) -> str:
    if len(items) == 1:
        return items[0]
    return f"{', '.join(items[:-1])} and {items[-1]}"


def _every(interval: int, unit: str) -> str:
    return f"Every {unit}" if interval == 1 else f"Every {interval} {unit}s"


def _weekly(days: Sequence[int], interval: int, wkst: int) -> str:
    if interval == 1 and len(set(days)) == 7:
        return "Every day"
    if interval == 1 and set(days) == {0, 1, 2, 3, 4}:
        return "Every weekday"
    ordered = sorted(set(days), key=lambda day: (day - wkst) % 7)
    return f"{_every(interval, 'week')} on {_listing([_SHORT_DAYS[day] for day in ordered])}"


def _monthly_on(rule: _Rule, first: date) -> str | None:
    if rule.byday:
        if rule.bymonthday or len(rule.byday) != 1 or rule.byday[0][0] not in _NTH:
            return None
        nth, weekday = rule.byday[0]
        return f"the {_NTH[nth]} {_LONG_DAYS[weekday]}"
    days = rule.bymonthday or (first.day,)
    if all(day > 0 for day in days):
        return f"the {_listing([_ordinal(day) for day in days])}"
    return "the last day" if days == (-1,) else None


def _phrase(rule: _Rule, first: date) -> str | None:
    if rule.bysetpos:
        return None
    plain = [day for nth, day in rule.byday if nth == 0]
    if rule.freq in ("DAILY", "WEEKLY"):
        if rule.bymonth or rule.bymonthday or len(plain) != len(rule.byday):
            return None
        if rule.freq == "DAILY":
            if not plain:
                return _every(rule.interval, "day")
            return _weekly(plain, 1, rule.wkst) if rule.interval == 1 else None
        return _weekly(plain or [first.weekday()], rule.interval, rule.wkst)
    every = _every(rule.interval, _UNITS[rule.freq])
    if rule.freq == "MONTHLY":
        on = None if rule.bymonth else _monthly_on(rule, first)
        return f"{every} on {on}" if on else None
    months = rule.bymonth or (() if rule.byday or rule.bymonthday else (first.month,))
    if len(months) != 1:
        return None
    month = _MONTHS[months[0] - 1]
    if rule.byday:
        if rule.bymonthday or len(rule.byday) != 1 or rule.byday[0][0] not in _NTH:
            return None
        nth, weekday = rule.byday[0]
        return f"{every} on the {_NTH[nth]} {_LONG_DAYS[weekday]} of {month}"
    days = rule.bymonthday or (first.day,)
    if len(days) != 1 or days[0] < 0:
        return None
    return f"{every} on {month} {days[0]}"


def _last_day(until: datetime | date, anchor: _Anchor) -> date:
    """The last day an occurrence can fall on, given UNTIL."""
    if not isinstance(until, datetime):
        return until
    assert anchor.zone is not None
    day = _local_day(until, anchor.zone)
    if _from_local(datetime.combine(day, anchor.at), anchor.zone) > until:
        day = _add_days(day, -1)
    return day


def describe(rrule: str, timing: Timing, tzid: str) -> str:
    """The rule as a sentence: "Every 2 weeks on Thu, until Dec 31"."""
    rule = _parse(rrule)
    anchor = _anchor(timing, tzid)
    sentence = _phrase(rule, anchor.first) or _CUSTOM
    if rule.count is not None:
        return f"{sentence}, once" if rule.count == 1 else f"{sentence}, {rule.count} times"
    until = _until(rule, anchor)
    if until is None:
        return sentence
    day = _last_day(until, anchor)
    when = f"{_MONTHS[day.month - 1]} {day.day}"
    if day.year != anchor.first.year:
        when = f"{when}, {day.year}"
    return f"{sentence}, until {when}"
