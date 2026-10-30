"""iCalendar in and out for synced calendars (PLAN §7.2, §7.5, §8.1, §8.3).

Reading turns a calendar feed or one CalDAV resource into the core's synced series
(``sunroom.calendar.synced``): one series per UID, with its master, its changed occurrences, and
its rule, RDATEs and EXDATEs as recurrence ids in the series' zone. Whatever Sunroom can't show
is refused out loud (a ``Refusal`` a parent can read), never dropped quietly. One broken event
never sinks the calendar: the parser falls back to reading it piece by piece.

Writing goes the other way for a push. With the server's own VCALENDAR (the ``raw_ical`` last
fetched) it changes only what Sunroom changed and keeps everything else (alarms, attendees,
``X-APPLE-*`` properties, other components); without one it builds a new VCALENDAR. Google's
``recurrence`` lines (RRULE, EXDATE, RDATE) are read and written by the same rules.
"""

from __future__ import annotations

import copy
import hashlib
import re
import warnings
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal, cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import x_wr_timezone
from icalendar import Calendar, Component, Event, Timezone
from icalendar.error import GloballyUniqueTZIDGuessed
from icalendar.prop import vDDDLists, vDDDTypes, vDuration, vInt, vRecur, vText

from sunroom.calendar.synced import SyncedEvent, SyncedOverride, SyncedSeries
from sunroom.core.lang import t_en
from sunroom.domain.recurrence import RecurrenceError, Timing, shift_rid, validate_rrule
from sunroom.domain.timeparts import from_local, parse_rid, rid_date, rid_timed, to_local
from sunroom.plugins.calendar_sync.tzmap import named_zone, zone_for

PRODID = "-//Sunroom//Sunroom calendar//EN"
MAX_SERIES = 20_000  # per calendar
TITLE_MAX, LOCATION_MAX, DESCRIPTION_MAX, NAME_MAX = 200, 300, 5000, 80
NO_TITLE = "No title"


@dataclass(frozen=True, slots=True)
class Refusal:
    """An event Sunroom won't show, and why. ``reason`` follows the title: "Sample standup
    repeats every hour, which Sunroom can't show"."""

    uid: str
    title: str
    reason: str  # plain English a parent understands


@dataclass(frozen=True, slots=True)
class ParsedCalendar:
    series: list[SyncedSeries]
    refused: list[Refusal]
    name: str | None  # X-WR-CALNAME (or NAME), if any
    color: str | None  # "#RRGGBB" from X-APPLE-CALENDAR-COLOR or COLOR, if any


NOT_A_CALENDAR = "This isn't a calendar file."
CUT_SHORT = "This calendar file was cut short."

_NO_START = "has no start time, so Sunroom can't place it"
_UNREADABLE = "has a date or time Sunroom can't read"
_TWO_RULES = "repeats in two different ways at once, which Sunroom can't show"
_EXRULE = "skips some of its repeats by a rule, which Sunroom can't show"
_TOO_OFTEN = {"HOURLY": "hour", "MINUTELY": "minute", "SECONDLY": "second"}
_FREQ = re.compile(r"FREQ\s*=\s*([A-Za-z]+)")
_UTC_ZONE = ZoneInfo("UTC")
_MIDNIGHT = time()
_ONE_DAY = timedelta(days=1)


# icalendar warns each time it reads "/mozilla.org/.../America/New_York" as its IANA tail; tzmap
# does the same on purpose, so the warning is only noise.
warnings.filterwarnings("ignore", category=GloballyUniqueTZIDGuessed)


class _UnreadableError(ValueError):
    """A date or time we can't make sense of."""


# --- Reading a calendar -------------------------------------------------------------------------


def parse_calendar(
    data: bytes | str,
    household: ZoneInfo,
    *,
    remote_id: str | None = None,
    etag: str | None = None,
    keep_raw: bool = False,
) -> ParsedCalendar:
    """A whole feed (many UIDs) or one CalDAV resource (one UID). remote_id/etag are copied onto
    every series (for a CalDAV resource; leave None for feeds). keep_raw puts the input text
    in each series' raw_ical (CalDAV: one resource = one series).

    Raises ValueError only when the input isn't a whole VCALENDAR.
    """
    text = _decode(data)
    groups: dict[str, _Group] = {}
    name: str | None = None
    color: str | None = None
    for calendar in _calendars(text):
        timezones = _timezones(calendar)
        calendar = _standard(calendar, household, timezones)
        name = name or _calendar_name(calendar)
        color = color or _calendar_color(calendar)
        context = _Context(household, timezones)
        for component in calendar.subcomponents:
            if isinstance(component, Event):
                group = groups.setdefault(_uid(component), _Group(context))
                if "RECURRENCE-ID" in component:
                    group.instances.append(component)
                else:
                    group.masters.append(component)
    source = _Source(remote_id, etag, text if keep_raw else None)
    series: list[SyncedSeries] = []
    refused: list[Refusal] = []
    over = 0
    for uid, group in groups.items():
        if len(series) >= MAX_SERIES:
            over += 1
            continue
        found = _read_series(uid, group.masters, group.instances, group.context, source)
        if isinstance(found, Refusal):
            refused.append(found)
        elif found is not None:
            series.append(found.series)
    if over:
        refused.append(
            Refusal(
                uid="",
                title=f"{over:,} more events",
                reason=f"go past the {MAX_SERIES:,} one calendar can hold, so Sunroom leaves "
                "them out",
            )
        )
    return ParsedCalendar(series=series, refused=refused, name=name, color=color)


@dataclass(slots=True)
class _Group:
    context: _Context
    masters: list[Event] = field(default_factory=list[Event])
    instances: list[Event] = field(default_factory=list[Event])


@dataclass(frozen=True, slots=True)
class _Source:
    remote_id: str | None
    etag: str | None
    raw: str | None


def _decode(data: bytes | str) -> str:
    if isinstance(data, str):
        return data.removeprefix("\ufeff")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


# --- Reading the text tolerantly ----------------------------------------------------------------


@dataclass(slots=True)
class _Node:
    """One component as text: its own content lines, and its subcomponents."""

    name: str
    lines: list[str] = field(default_factory=list[str])
    children: list[_Node] = field(default_factory=list["_Node"])
    closed: bool = False


_FOLD = re.compile(r"\n[ \t]")


def _tree(text: str) -> tuple[list[_Node], bool]:
    """The components' outline, and whether it was tidy (every END closed the component that
    was open). An END for a component that isn't open is ignored."""
    unfolded = _FOLD.sub("", text.replace("\r\n", "\n").replace("\r", "\n"))
    roots: list[_Node] = []
    stack: list[_Node] = []
    tidy = True
    for line in unfolded.split("\n"):
        if not line.strip():
            continue
        head, _, value = line.partition(":")
        word = head.strip().upper()
        if word == "BEGIN":
            node = _Node(value.strip().upper())
            (stack[-1].children if stack else roots).append(node)
            stack.append(node)
        elif word == "END":
            name = value.strip().upper()
            tidy = tidy and bool(stack) and stack[-1].name == name
            if any(node.name == name for node in stack):
                while stack:
                    node = stack.pop()
                    if node.name == name:
                        node.closed = True
                        break
        elif stack:
            stack[-1].lines.append(line)
        else:
            tidy = False
    return roots, tidy and not stack


def _calendars(text: str) -> list[Calendar]:
    """The VCALENDARs in the text. icalendar reads a tidy file in one go; anything it can't is
    read component by component, and property by property where needed, leaving out only the
    pieces that can't be read."""
    roots, tidy = _tree(text)
    nodes = [node for node in roots if node.name == "VCALENDAR"]
    if not nodes:
        raise ValueError(NOT_A_CALENDAR)
    if not all(node.closed for node in nodes):
        raise ValueError(CUT_SHORT)  # a feed cut off mid-download: never read it as complete
    if tidy:
        whole = _parse_many(text)
        if len(whole) == len(nodes):
            return whole
    rebuilt = [_rebuild(node) for node in nodes]
    return [calendar for calendar in rebuilt if isinstance(calendar, Calendar)]


def _parse_many(text: str) -> list[Calendar]:
    try:
        found = Component.from_ical(text.encode(), multiple=True)
    except Exception:  # whatever icalendar can't read in one go is read piece by piece
        return []
    return [component for component in found if isinstance(component, Calendar)]


def _parse_one(text: str) -> Component | None:
    try:
        return Component.from_ical(text.encode())
    except Exception:  # a piece icalendar can't read is left out
        return None


def _render(name: str, lines: Sequence[str], children: Sequence[_Node] = ()) -> str:
    parts = [f"BEGIN:{name}", *lines]
    parts += [_render(child.name, child.lines, child.children).rstrip("\r\n") for child in children]
    parts.append(f"END:{name}")
    return "\r\n".join(parts) + "\r\n"


def _rebuild(node: _Node) -> Component | None:
    whole = _parse_one(_render(node.name, node.lines, node.children))
    if whole is not None:
        return whole
    component = _parse_one(_render(node.name, node.lines))
    if component is None:
        component = _parse_one(_render(node.name, []))
        if component is None:
            return None
        for line in node.lines:
            single = _parse_one(_render(node.name, [line]))
            if single is not None:
                for key in _names(single):
                    _add(component, key, single[key])
    for child in node.children:
        rebuilt = _rebuild(child)
        if rebuilt is not None:
            component.add_component(rebuilt)
    return component


# --- Calendar-wide properties -------------------------------------------------------------------


def _timezones(calendar: Calendar) -> dict[str, Timezone]:
    found: dict[str, Timezone] = {}
    for component in calendar.subcomponents:
        if isinstance(component, Timezone):
            tzid = _clean_tzid(_text(component, "TZID"))
            if tzid:
                found.setdefault(tzid, component)
    return found


def _standard(calendar: Calendar, household: ZoneInfo, timezones: dict[str, Timezone]) -> Calendar:
    """Google's feeds write UTC times and name the calendar's zone in X-WR-TIMEZONE; move those
    times into that zone, so a weekly 9:00 stays 9:00 across daylight saving."""
    name = _clean_tzid(_text(calendar, "X-WR-TIMEZONE"))
    if not name:
        return calendar
    zone, _ = zone_for(name, timezones.get(name), household)
    try:
        return x_wr_timezone.to_standard(calendar, timezone=zone)
    except Exception:  # a calendar the converter can't walk is read as written
        return calendar


def _calendar_name(calendar: Calendar) -> str | None:
    for key in ("X-WR-CALNAME", "NAME"):
        text = " ".join((_text(calendar, key) or "").split())
        if text:
            return text[:NAME_MAX]
    return None


def _calendar_color(calendar: Calendar) -> str | None:
    for key in ("X-APPLE-CALENDAR-COLOR", "COLOR"):
        color = _color(_text(calendar, key))
        if color:
            return color
    return None


_HEX = re.compile(r"[0-9a-f]{3,8}")


def _color(text: str | None) -> str | None:
    """A color as "#RRGGBB", from "#RGB", "#RRGGBB" or "#RRGGBBAA" (Apple's). RFC 7986's color
    names are left out: a calendar's color is only a hint, and feeds send hex."""
    value = (text or "").strip().lower()
    digits = value[1:] if value.startswith("#") else ""
    if not _HEX.fullmatch(digits):
        return None
    if len(digits) in (3, 4):
        digits = "".join(digit * 2 for digit in digits[:3])
    elif len(digits) in (6, 8):
        digits = digits[:6]
    else:
        return None
    return f"#{digits.upper()}"


# --- Dates and times as written ---------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _When:
    """A date or date-time as a calendar wrote it."""

    kind: Literal["date", "utc", "zoned", "floating"]
    value: date | datetime  # a date, or a naive wall time (UTC's for "utc")
    zone: ZoneInfo | None = None  # "zoned" and "utc"
    label: str | None = None  # "zoned": the TZID as written

    def wall(self) -> datetime:
        if not isinstance(self.value, datetime):
            raise _UnreadableError("a date has no time of day")
        return self.value

    def instant(self, household: ZoneInfo) -> datetime:
        """The UTC instant of a date-time; a floating one is the household's wall time."""
        wall = self.wall()
        if self.kind == "utc":
            return wall.replace(tzinfo=UTC)
        return from_local(wall, self.zone if self.kind == "zoned" and self.zone else household)


@dataclass(frozen=True, slots=True)
class _Frame:
    """How a series writes its times: dates (all-day), or wall times in the zone its rule runs
    in (UTC, a named zone, or the household's for floating times)."""

    kind: Literal["date", "utc", "zoned", "floating"]
    zone: ZoneInfo = _UTC_ZONE
    label: str | None = None  # "zoned": the TZID to write
    at: time = _MIDNIGHT  # DTSTART's time of day

    @property
    def all_day(self) -> bool:
        return self.kind == "date"

    def rid(self, when: _When, household: ZoneInfo, *, original: bool = False) -> str:
        """A value as a recurrence id in this frame. A date on a timed series stays a date id,
        except as a RECURRENCE-ID (``original``), where it means DTSTART's time that day."""
        value = when.value
        if self.all_day:
            if not isinstance(value, datetime):
                return rid_date(value)
            if when.kind == "utc":
                return rid_date(to_local(value.replace(tzinfo=UTC), household).date())
            return rid_date(value.date())
        if not isinstance(value, datetime):
            return rid_timed(datetime.combine(value, self.at)) if original else rid_date(value)
        if when.kind == "floating" or (when.zone is not None and when.zone.key == self.zone.key):
            return rid_timed(value)
        return rid_timed(to_local(when.instant(household), self.zone))

    def when(self, rid: str) -> _When:
        """A recurrence id as a value to write in this frame."""
        value = parse_rid(rid)
        if not isinstance(value, datetime):
            return _When("date", value)
        if self.all_day:
            return _When("date", value.date())
        return self.wall(value)

    def at_instant(self, instant: datetime) -> _When:
        return self.wall(to_local(instant, self.zone))

    def wall(self, value: datetime) -> _When:
        if self.kind == "utc":
            return _When("utc", value, _UTC_ZONE)
        if self.kind == "floating":
            return _When("floating", value)
        return _When("zoned", value, self.zone, self.label or self.zone.key)


def _frame_of(start: _When, household: ZoneInfo) -> _Frame:
    """The frame a series' DTSTART sets."""
    if start.kind == "date":
        return _Frame("date")
    at = start.wall().time()
    if start.kind == "floating":
        return _Frame("floating", household, at=at)
    if start.kind == "utc" or start.zone is None:
        return _Frame("utc", _UTC_ZONE, at=at)
    return _Frame("zoned", start.zone, start.label, at=at)


@dataclass(slots=True)
class _Context:
    """What reading one calendar needs: the household's zone and the calendar's VTIMEZONEs."""

    household: ZoneInfo
    timezones: dict[str, Timezone]
    zones: dict[tuple[str, int], ZoneInfo] = field(default_factory=dict[tuple[str, int], ZoneInfo])

    def zone(self, tzid: str, year: int) -> ZoneInfo:
        key = (tzid, year)
        found = self.zones.get(key)
        if found is None:
            vtimezone = self.timezones.get(_clean_tzid(tzid))
            found, _ = zone_for(tzid, vtimezone, self.household, year=year)
            self.zones[key] = found
        return found

    def when(self, value: object, tzid: str | None) -> _When:
        """A parsed date or date-time (with its property's TZID) as written."""
        if isinstance(value, tuple):  # an RDATE period: its start
            value = cast("tuple[object, object]", value)[0]
        if isinstance(value, datetime):
            wall = value.replace(tzinfo=None)
            if tzid:
                zone = self.zone(tzid, value.year)
                if zone.key == "UTC":
                    return _When("utc", wall, _UTC_ZONE)
                return _When("zoned", wall, zone, tzid)
            if value.tzinfo is None:
                return _When("floating", wall)
            if isinstance(value.tzinfo, ZoneInfo) and value.tzinfo.key != "UTC":
                return _When("zoned", wall, value.tzinfo, value.tzinfo.key)
            return _When("utc", value.astimezone(UTC).replace(tzinfo=None), _UTC_ZONE)
        if isinstance(value, date):
            return _When("date", value)
        raise _UnreadableError("not a date or a time")

    def moment(self, prop: object) -> _When:
        """DTSTART, DTEND or RECURRENCE-ID as written."""
        if isinstance(prop, vDDDTypes):
            return self.when(prop.dt, _param(prop.params.get("TZID")))
        if isinstance(prop, vDDDLists) and len(prop.dts) == 1:
            return self.when(prop.dts[0].dt, _param(prop.params.get("TZID")))
        raise _UnreadableError("not a date or a time")

    def moments(self, prop: object) -> list[_When]:
        """The values of one EXDATE or RDATE line."""
        if isinstance(prop, vDDDLists):
            tzid = _param(prop.params.get("TZID"))
            return [
                self.when(item.dt, tzid or _param(item.params.get("TZID"))) for item in prop.dts
            ]
        if isinstance(prop, vDDDTypes):
            return [self.moment(prop)]
        raise _UnreadableError("not a list of dates")


# --- Reading one series -------------------------------------------------------------------------


@dataclass(slots=True)
class _Reading:
    """A series as read, with the components it came from (a push edits those)."""

    series: SyncedSeries
    master: Event
    frame: _Frame
    orphan: bool = False
    # changed occurrences by recurrence id, cancelled ones included (for an orphan: the others)
    instances: dict[str, tuple[Event, SyncedEvent]] = field(
        default_factory=dict[str, tuple[Event, SyncedEvent]]
    )


def _read_series(
    uid: str, masters: list[Event], instances: list[Event], context: _Context, source: _Source
) -> _Reading | Refusal | None:
    """One UID's components as a series; None when there's nothing to show (cancelled)."""
    first = _latest(masters) if masters else instances[0]
    title = _title(first)
    try:
        if masters:
            return _read_master(uid, first, instances, context, source)
        return _read_orphans(uid, instances, context, source)
    except _RefusedError as refused:
        return Refusal(uid, title, refused.reason)
    except _UnreadableError:
        return Refusal(uid, title, _UNREADABLE)


class _RefusedError(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _read_master(
    uid: str, master: Event, instances: list[Event], context: _Context, source: _Source
) -> _Reading | None:
    if _status(master) == "CANCELLED":
        return None
    start_prop = _first(master, "DTSTART")
    if start_prop is None:
        raise _RefusedError(_NO_START)
    start = context.moment(start_prop)
    event = _event(master, start, context)
    frame = _frame_of(start, context.household)
    rrule = _rule(master, event)
    rdates = _dates(master, "RDATE", frame, context)
    exdates = _dates(master, "EXDATE", frame, context)

    found: dict[str, list[tuple[int, Event]]] = {}
    for index, component in enumerate(instances):
        original = context.moment(_first(component, "RECURRENCE-ID"))
        rid = frame.rid(original, context.household, original=True)
        found.setdefault(rid, []).append((index, component))
    changed: dict[str, tuple[Event, SyncedEvent]] = {}
    for rid, candidates in sorted(found.items()):
        _, component = max(candidates, key=lambda item: _rank(item[1], item[0]))
        changed[rid] = (component, _instance(component, frame.when(rid), event, context))
    series = SyncedSeries(
        uid=uid,
        master=event,
        rrule=rrule,
        rdates=rdates,
        exdates=exdates,
        overrides=tuple(SyncedOverride(rid, ev) for rid, (_, ev) in changed.items()),
        remote_id=source.remote_id,
        etag=source.etag,
        updated_at=_updated([master, *(c for c, _ in changed.values())]),
        sequence=_sequence(master),
        raw_ical=source.raw,
    )
    return _Reading(series, master, frame, instances=changed)


def _read_orphans(
    uid: str, instances: list[Event], context: _Context, source: _Source
) -> _Reading | None:
    """Occurrences of a series whose master isn't here (an invitation to one of them): the
    earliest is the master, without a rule; any others are its extra dates, as changed."""
    latest: dict[tuple[datetime, str], tuple[int, Event, _When]] = {}
    for index, component in enumerate(instances):
        original = context.moment(_first(component, "RECURRENCE-ID"))
        key = _order(original, context.household)
        if key not in latest or _rank(component, index) > _rank(latest[key][1], latest[key][0]):
            latest[key] = (index, component, original)
    live = sorted(
        (
            (key, component, original)
            for key, (_, component, original) in latest.items()
            if _status(component) != "CANCELLED"
        ),
        key=lambda item: item[0],
    )
    if not live:
        return None
    _, master, master_original = live[0]
    start_prop = _first(master, "DTSTART")
    start = context.moment(start_prop) if start_prop is not None else master_original
    event = _event(master, start, context)
    frame = _frame_of(start, context.household)
    others: dict[str, tuple[Event, SyncedEvent]] = {}
    for _, component, original in live[1:]:
        rid = frame.rid(original, context.household, original=True)
        others[rid] = (component, _instance(component, frame.when(rid), event, context))
    others = dict(sorted(others.items()))
    series = SyncedSeries(
        uid=uid,
        master=event,
        rdates=tuple(others),
        overrides=tuple(SyncedOverride(rid, ev) for rid, (_, ev) in others.items()),
        remote_id=source.remote_id,
        etag=source.etag,
        updated_at=_updated([master, *(c for c, _ in others.values())]),
        sequence=_sequence(master),
        raw_ical=source.raw,
    )
    return _Reading(series, master, frame, orphan=True, instances=others)


def _order(when: _When, household: ZoneInfo) -> tuple[datetime, str]:
    if when.kind == "date":
        return datetime.combine(when.value, _MIDNIGHT, UTC), "date"
    return when.instant(household), "time"


def _rank(component: Event, index: int) -> tuple[int, datetime, int]:
    """Which of two copies of one event wins: the higher SEQUENCE, then the later
    LAST-MODIFIED, then the later one in the file."""
    modified = _stamp(component, "LAST-MODIFIED") or datetime.min.replace(tzinfo=UTC)
    return _sequence(component) or 0, modified, index


def _latest(components: list[Event]) -> Event:
    return max(enumerate(components), key=lambda item: _rank(item[1], item[0]))[1]


def _event(
    component: Event, start: _When, context: _Context, *, length: Timing | None = None
) -> SyncedEvent:
    timing, tzid, floating = _timing(component, start, context, length=length)
    return SyncedEvent(
        title=_title(component),
        timing=timing,
        tzid=tzid,
        floating=floating,
        description=_long_text(component, "DESCRIPTION", DESCRIPTION_MAX),
        location=_long_text(component, "LOCATION", LOCATION_MAX),
        cancelled=_status(component) == "CANCELLED",
    )


def _instance(
    component: Event, original: _When, master: SyncedEvent, context: _Context
) -> SyncedEvent:
    """A changed occurrence; ``original`` is its original start in the series' frame. Without
    its own DTSTART it starts there and keeps the master's length."""
    start_prop = _first(component, "DTSTART")
    if start_prop is not None:
        return _event(component, context.moment(start_prop), context)
    return _event(component, original, context, length=master.timing)


def _timing(
    component: Event, start: _When, context: _Context, *, length: Timing | None = None
) -> tuple[Timing, str | None, bool]:
    """(timing, tzid, floating) from DTSTART and DTEND or DURATION. Without either, a timed
    event has no length and an all-day one lasts a day (RFC 5545), unless ``length`` (the
    master's) says otherwise."""
    end_prop = _first(component, "DTEND")
    duration = _duration(_first(component, "DURATION"))
    if start.kind == "date":
        day = cast("date", start.value)
        last: date | None = None
        if end_prop is not None:
            end = context.moment(end_prop)
            if end.kind == "date":
                last = cast("date", end.value)
            else:
                wall = end.wall()
                last = wall.date() + (_ONE_DAY if wall.time() != _MIDNIGHT else timedelta(0))
        elif duration is not None:
            last = day + timedelta(days=max(1, -(-duration // _ONE_DAY)))
        elif length is not None and length.all_day and length.start_date and length.end_date:
            last = day + (length.end_date - length.start_date)
        if last is None or last <= day:
            last = day + _ONE_DAY
        return Timing(all_day=True, start_date=day, end_date=last), None, False

    begin = start.instant(context.household)
    finish = begin
    if end_prop is not None:
        end = context.moment(end_prop)
        if end.kind == "date":  # a DATE end on a timed event: midnight that day
            end = _When(
                start.kind, datetime.combine(cast("date", end.value), _MIDNIGHT), start.zone
            )
        finish = end.instant(context.household)
    elif duration is not None:
        # Whole days are calendar days (the same wall time); the rest is exact (RFC 5545).
        days = timedelta(days=duration.days)
        wall = _When(start.kind, start.wall() + days, start.zone, start.label)
        finish = wall.instant(context.household) + (duration - days)
    elif length is not None and not length.all_day and length.start_utc and length.end_utc:
        finish = begin + (length.end_utc - length.start_utc)
    if start.kind == "floating":
        tzid = context.household.key
    else:
        tzid = start.zone.key if start.zone is not None else "UTC"
    timing = Timing(all_day=False, start_utc=begin, end_utc=max(finish, begin))
    return timing, tzid, start.kind == "floating"


def _duration(prop: object) -> timedelta | None:
    if isinstance(prop, vDuration):
        return prop.td
    if isinstance(prop, vDDDTypes) and isinstance(prop.dt, timedelta):
        return prop.dt
    return None


def _rule(component: Event, event: SyncedEvent) -> str | None:
    rules = _props(component, "RRULE")
    if len(rules) > 1:
        raise _RefusedError(_TWO_RULES)
    if _props(component, "EXRULE"):
        raise _RefusedError(_EXRULE)
    if not rules:
        return None
    text = _rule_text(rules[0])
    try:
        return validate_rrule(text, event.timing, event.tzid or "UTC")
    except RecurrenceError as exc:
        raise _RefusedError(_rule_reason(exc, text)) from None


def _rule_text(prop: object) -> str:
    if isinstance(prop, vRecur):
        return prop.to_ical().decode()
    return str(prop)


def _rule_reason(exc: RecurrenceError, rule: str) -> str:
    match = _FREQ.search(rule)
    unit = _TOO_OFTEN.get(match.group(1).upper()) if match else None
    if unit is not None:
        return f"repeats every {unit}, which Sunroom can't show"
    if exc.code == "rrule_unsupported":
        return "repeats in a way Sunroom can't show"
    detail = t_en(exc.key).rstrip(".")
    return f"has a repeat Sunroom can't follow ({detail[:1].lower()}{detail[1:]})"


def _dates(component: Event, name: str, frame: _Frame, context: _Context) -> tuple[str, ...]:
    found = {
        frame.rid(when, context.household)
        for prop in _props(component, name)
        for when in context.moments(prop)
    }
    return tuple(sorted(found))


# --- Reading properties -------------------------------------------------------------------------


def _add(component: Component, name: str, value: object) -> None:
    """Add a property value as it is (icalendar's signature here is partly untyped)."""
    component.add(name, value, encode=False)  # pyright: ignore[reportUnknownMemberType]


def _names(component: Component) -> list[str]:
    return [str(key) for key in cast("Iterable[object]", component.keys())]


def _props(component: Component, name: str) -> list[object]:
    value: object = component.get(name)
    if value is None:
        return []
    if isinstance(value, list):
        return list(cast("list[object]", value))
    return [value]


def _first(component: Component, name: str) -> object | None:
    found = _props(component, name)
    return found[0] if found else None


def _text(component: Component, name: str) -> str | None:
    value = _first(component, name)
    return str(value) if isinstance(value, str) else None


def _param(value: object) -> str | None:
    if isinstance(value, list) and value:
        value = cast("list[object]", value)[0]
    text = str(value).strip() if isinstance(value, str) else ""
    return text or None


def _clean_tzid(tzid: str | None) -> str:
    return (tzid or "").strip().strip('"').strip()


def _title(component: Component) -> str:
    return " ".join((_text(component, "SUMMARY") or "").split())[:TITLE_MAX] or NO_TITLE


def _long_text(component: Component, name: str, limit: int) -> str:
    return (_text(component, name) or "").strip()[:limit]


def _status(component: Component) -> str:
    return (_text(component, "STATUS") or "").strip().upper()


def _sequence(component: Component) -> int | None:
    value = _first(component, "SEQUENCE")
    if isinstance(value, int) and not isinstance(value, bool):
        return int(value)
    return None


def _stamp(component: Component, name: str) -> datetime | None:
    value = _first(component, name)
    if not isinstance(value, vDDDTypes):
        return None
    moment = value.dt
    if isinstance(moment, datetime):
        return moment.astimezone(UTC) if moment.tzinfo else moment.replace(tzinfo=UTC)
    if isinstance(moment, date):
        return datetime.combine(moment, _MIDNIGHT, UTC)
    return None


def _updated(components: Sequence[Component]) -> datetime | None:
    """When the series last changed on the server: its latest LAST-MODIFIED."""
    stamps = [stamp for c in components if (stamp := _stamp(c, "LAST-MODIFIED")) is not None]
    return max(stamps, default=None)


def _uid(component: Event) -> str:
    """The UID, or for an event without one, one made from what it says (so it's the same in
    every fetch while the event doesn't change)."""
    uid = (_text(component, "UID") or "").strip()
    if uid:
        return uid
    parts: list[str] = []
    for name in ("DTSTART", "RECURRENCE-ID"):
        for prop in _props(component, name):
            if isinstance(prop, vDDDTypes) and isinstance(prop.dt, date):
                moment = prop.dt
                plain = moment.replace(tzinfo=None) if isinstance(moment, datetime) else moment
                parts.append(f"{name}:{plain.isoformat()}:{_param(prop.params.get('TZID')) or ''}")
            else:
                parts.append(f"{name}:{prop}")
    parts.append(f"SUMMARY:{_text(component, 'SUMMARY') or ''}")
    parts += [f"RRULE:{_rule_text(prop)}" for prop in _props(component, "RRULE")]
    digest = hashlib.sha256("\n".join(parts).encode()).hexdigest()[:32]
    return f"sunroom-no-uid-{digest}"


# --- Writing a calendar -------------------------------------------------------------------------


def build_calendar(series: SyncedSeries, *, base: str | None = None, now: datetime) -> str:
    """The VCALENDAR text to PUT. With `base` (the raw_ical last fetched): patch the server's
    own components and keep everything Sunroom doesn't model (X-APPLE-* properties, VALARM,
    ATTENDEE, ORGANIZER, CATEGORIES, URL, unknown X- properties, other VTIMEZONEs). Without
    `base`: a new VCALENDAR (PRODID, VERSION:2.0, a VTIMEZONE for the zone, one VEVENT per
    master and override). `now` stamps DTSTAMP and LAST-MODIFIED; SEQUENCE goes up by one when
    the time or the rule changed."""
    if series.master is None:
        raise ValueError("A series needs its main event to be written out.")
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    stamp = now.astimezone(UTC).replace(microsecond=0)
    household = _stand_in(series)
    calendar: Calendar | None = None
    reading: _Reading | None = None
    context = _Context(household, {})
    if base is not None:
        calendar, reading, context = _read_base(base, series.uid, household)
    if calendar is None or reading is None:
        calendar = Calendar()
        _add(calendar, "PRODID", vText(PRODID))
        _add(calendar, "VERSION", vText("2.0"))
        _add(calendar, "CALSCALE", vText("GREGORIAN"))
        reading = None
        context = _Context(household, {})
    _Writer(calendar, context, stamp).write(series, reading)
    return calendar.to_ical(sorted=False).decode()


def _stand_in(series: SyncedSeries) -> ZoneInfo:
    """The zone floating times in the base were read in: the series' own (it was the
    household's when it was read)."""
    events = [series.master, *(o.event for o in series.overrides)]
    for event in events:
        if event is not None and not event.timing.all_day and event.tzid:
            return _load_zone(event.tzid)
    return _UTC_ZONE


def _load_zone(tzid: str) -> ZoneInfo:
    try:
        return ZoneInfo(tzid)
    except ZoneInfoNotFoundError, ValueError:
        raise ValueError(f"unknown time zone: {tzid!r}") from None


def _read_base(
    base: str, uid: str, household: ZoneInfo
) -> tuple[Calendar | None, _Reading | None, _Context]:
    """The server's calendar (in standard form) and the series as Sunroom read it from there."""
    try:
        calendars = _calendars(base)
    except ValueError:
        calendars = []
    if not calendars:
        return None, None, _Context(household, {})
    calendar = calendars[0]
    timezones = _timezones(calendar)
    calendar = _standard(calendar, household, timezones)
    context = _Context(household, timezones)
    events = [c for c in calendar.subcomponents if isinstance(c, Event)]
    mine = [e for e in events if (_text(e, "UID") or "").strip() in (uid, "")]
    masters = [e for e in mine if "RECURRENCE-ID" not in e]
    instances = [e for e in mine if "RECURRENCE-ID" in e]
    if not masters and not instances:
        return calendar, None, context
    found = _read_series(uid, masters, instances, context, _Source(None, None, None))
    return calendar, found if isinstance(found, _Reading) else None, context


# Properties a new changed occurrence doesn't copy from its master.
_OWN = frozenset(
    {
        "UID",
        "DTSTAMP",
        "CREATED",
        "LAST-MODIFIED",
        "SEQUENCE",
        "DTSTART",
        "DTEND",
        "DURATION",
        "RRULE",
        "RDATE",
        "EXDATE",
        "EXRULE",
        "RECURRENCE-ID",
        "SUMMARY",
        "LOCATION",
        "DESCRIPTION",
        "STATUS",
    }
)


@dataclass(slots=True)
class _Writer:
    """Writes one series into a calendar: patches the components it was read from, adds what's
    new, drops what went, and adds a VTIMEZONE for each zone it names."""

    calendar: Calendar
    context: _Context
    stamp: datetime
    tzids: set[str] = field(default_factory=set[str])  # TZIDs written, which need a VTIMEZONE
    years: set[int] = field(default_factory=set[int])

    def write(self, after: SyncedSeries, reading: _Reading | None) -> None:
        master = after.master
        assert master is not None
        before = reading.series if reading is not None else None
        if reading is None:
            component = Event()
            _add(component, "UID", vText(after.uid))
            self.calendar.add_component(component)
        else:
            component = reading.master
        frame = self.frame(master, component if reading is not None else None)
        changed, significant = self.event(
            component, before.master if before else None, master, frame
        )
        if reading is None or not reading.orphan:
            rules_changed = self.rules(component, reading, after, frame)
            changed, significant = changed or rules_changed, significant or rules_changed
        sequence = self.finish(
            component, changed, significant, new=reading is None, sequence=after.sequence
        )
        shift = _shift(before.master, master) if before is not None and before.master else None
        self.instances(component, reading, after, frame, sequence, shift)
        self.add_timezones()

    def frame(self, event: SyncedEvent, component: Event | None) -> _Frame:
        """How to write this event's times: its zone, under the TZID the server already uses
        for it when that names the same zone."""
        if event.timing.all_day:
            return _Frame("date")
        assert event.timing.start_utc is not None
        zone = _load_zone(event.tzid or "UTC")
        at = to_local(event.timing.start_utc, zone).time()
        if event.floating:
            return _Frame("floating", zone, at=at)
        if zone.key == "UTC":
            return _Frame("utc", zone, at=at)
        label = zone.key
        written = self.label(component)
        if written and (named_zone(written) or self.context.timezones.get(written)):
            year = to_local(event.timing.start_utc, zone).year
            if self.context.zone(written, year).key == zone.key:
                label = written
        return _Frame("zoned", zone, label, at=at)

    @staticmethod
    def label(component: Event | None) -> str | None:
        if component is None:
            return None
        start = _first(component, "DTSTART")
        if isinstance(start, vDDDTypes):
            return _clean_tzid(_param(start.params.get("TZID"))) or None
        return None

    def event(
        self, component: Event, before: SyncedEvent | None, after: SyncedEvent, frame: _Frame
    ) -> tuple[bool, bool]:
        """Write what differs from ``before`` (everything when None); (changed, significant)."""
        changed = significant = False
        for name, old, new in (
            ("SUMMARY", before.title if before else None, after.title),
            ("LOCATION", before.location if before else None, after.location),
            ("DESCRIPTION", before.description if before else None, after.description),
        ):
            if old != new:
                if new:
                    component[name] = vText(new)
                else:
                    component.pop(name, None)
                changed = True
        when = (after.timing, after.tzid, after.floating)
        if before is None or (before.timing, before.tzid, before.floating) != when:
            self.times(component, after, frame)
            changed = significant = True
        if (before.cancelled if before else False) != after.cancelled:
            if after.cancelled:
                component["STATUS"] = vText("CANCELLED")
            else:
                component.pop("STATUS", None)
            changed = significant = True
        return changed, significant

    def times(self, component: Event, event: SyncedEvent, frame: _Frame) -> None:
        component.pop("DURATION", None)
        timing = event.timing
        if timing.all_day:
            assert timing.start_date is not None and timing.end_date is not None
            self.put(component, "DTSTART", _When("date", timing.start_date))
            self.put(component, "DTEND", _When("date", timing.end_date))
            return
        assert timing.start_utc is not None and timing.end_utc is not None
        self.put(component, "DTSTART", frame.at_instant(timing.start_utc))
        if timing.end_utc > timing.start_utc:
            self.put(component, "DTEND", frame.at_instant(timing.end_utc))
        else:
            component.pop("DTEND", None)  # no end: it lasts no time (RFC 5545)
        self.years.add(timing.start_utc.year)

    def put(self, component: Component, name: str, when: _When) -> None:
        """Set one date property, keeping its place among the others."""
        prop = vDDDTypes(_python_value(when))
        if when.kind == "zoned" and when.label:
            prop.params["TZID"] = when.label
            self.tzids.add(when.label)
        component[name] = prop

    def rules(
        self, component: Event, reading: _Reading | None, after: SyncedSeries, frame: _Frame
    ) -> bool:
        """RRULE, RDATE and EXDATE: rewrite what changed, keep the rest as the server wrote it.
        A cancelled occurrence counts as an EXDATE either way."""
        before = reading.series if reading is not None else None
        changed = False
        if before is None or before.rrule != after.rrule:
            component.pop("RRULE", None)
            if after.rrule:
                _add(component, "RRULE", vRecur.from_ical(after.rrule))
            changed = before is not None or after.rrule is not None
        old_rdates = set(before.rdates) if before else set[str]()
        changed |= self.dates(component, "RDATE", reading, old_rdates, set(after.rdates), frame)
        old_exdates = set(before.exdates) if before else set[str]()
        if reading is not None:
            old_exdates |= {rid for rid, (_, ev) in reading.instances.items() if ev.cancelled}
        new_exdates = set(after.exdates) | {
            o.recurrence_id for o in after.overrides if o.event.cancelled
        }
        changed |= self.dates(component, "EXDATE", reading, old_exdates, new_exdates, frame)
        return changed

    def dates(
        self,
        component: Event,
        name: str,
        reading: _Reading | None,
        old: set[str],
        new: set[str],
        frame: _Frame,
    ) -> bool:
        if old == new:
            return False
        gone = old - new
        if gone and reading is not None:
            kept: list[object] = []
            for prop in _props(component, name):
                if isinstance(prop, vDDDLists):
                    tzid = _param(prop.params.get("TZID"))
                    items = [
                        item
                        for item in prop.dts
                        if reading.frame.rid(
                            self.context.when(item.dt, tzid), self.context.household
                        )
                        not in gone
                    ]
                    if not items:
                        continue
                    if len(items) != len(prop.dts):
                        trimmed = vDDDLists(items)
                        trimmed.params = prop.params
                        prop = trimmed
                kept.append(prop)
            component.pop(name, None)
            for prop in kept:
                _add(component, name, prop)
        added = sorted(new - old)
        groups: dict[tuple[str, str | None], list[_When]] = {}
        for rid in added:
            when = frame.when(rid)
            groups.setdefault((when.kind, when.label), []).append(when)
        for (kind, label), whens in groups.items():
            prop = vDDDLists([_python_value(when) for when in whens])
            if kind == "date":
                prop.params["VALUE"] = "DATE"
            elif kind == "zoned" and label:
                prop.params["TZID"] = label
                self.tzids.add(label)
            _add(component, name, prop)
        return True

    def instances(
        self,
        master: Event,
        reading: _Reading | None,
        after: SyncedSeries,
        frame: _Frame,
        sequence: int,
        shift: timedelta | None,
    ) -> None:
        """Changed occurrences: patch the server's, add new ones, drop the ones that went. When
        the series' time of day moved (``shift``), its changed occurrences moved with it: the
        server's own components follow, under their new RECURRENCE-ID."""
        live = {o.recurrence_id: o for o in after.overrides if not o.event.cancelled}
        excluded = set(after.exdates) | {
            o.recurrence_id for o in after.overrides if o.event.cancelled
        }
        found = reading.instances if reading is not None else {}
        targets = {rid: rid for rid in found if rid in live}
        if shift is not None:
            for rid in found:
                moved = shift_rid(rid, shift)
                if rid not in targets and moved in live and moved not in targets.values():
                    targets[rid] = moved
        for rid, (component, before) in found.items():
            target = targets.get(rid)
            if target is not None:
                if target != rid:
                    self.put(component, "RECURRENCE-ID", frame.when(target))
                event = live[target].event
                changed, significant = self.event(
                    component, before, event, self.frame(event, component)
                )
                moved = target != rid
                self.finish(
                    component, changed or moved, significant or moved, new=False, sequence=None
                )
            elif not (before.cancelled and rid in excluded):
                self.calendar.subcomponents = [
                    c for c in self.calendar.subcomponents if c is not component
                ]
        done = set(targets.values())
        for rid, override in sorted(live.items()):
            if rid not in done:
                self.calendar.add_component(
                    self.new_instance(master, rid, override, frame, sequence)
                )

    def new_instance(
        self, master: Event, rid: str, override: SyncedOverride, frame: _Frame, sequence: int
    ) -> Event:
        """A new changed occurrence: the master's other properties and alarms, its own time."""
        component = Event()
        _add(component, "UID", vText(_text(master, "UID") or ""))
        for key in _names(master):
            if key.upper() not in _OWN:
                component[key] = master[key]
        for sub in master.subcomponents:
            if sub.name == "VALARM":
                alarm = copy.deepcopy(sub)
                alarm.pop("UID", None)
                alarm.pop("X-WR-ALARMUID", None)
                component.add_component(alarm)
        self.put(component, "RECURRENCE-ID", frame.when(rid))
        self.event(component, None, override.event, self.frame(override.event, master))
        self.finish(component, True, True, new=True, sequence=sequence)
        return component

    def finish(
        self, component: Event, changed: bool, significant: bool, *, new: bool, sequence: int | None
    ) -> int:
        """Stamp a changed component; its SEQUENCE goes up when its time or rule changed."""
        current = _sequence(component)
        if new or significant:
            current = sequence or 0 if new else (current or 0) + 1
            component["SEQUENCE"] = vInt(current)
        if new or changed:
            component["DTSTAMP"] = vDDDTypes(self.stamp)
            component["LAST-MODIFIED"] = vDDDTypes(self.stamp)
        if new and "CREATED" not in component:
            component["CREATED"] = vDDDTypes(self.stamp)
        return current or 0

    def add_timezones(self) -> None:
        """A VTIMEZONE for each zone written by its IANA name that the calendar lacks."""
        have = set(_timezones(self.calendar))
        missing = sorted(tzid for tzid in self.tzids if tzid not in have and named_zone(tzid))
        if not missing:
            return
        first = min(self.years, default=self.stamp.year)
        last = max([*self.years, self.stamp.year]) + 10
        components = self.calendar.subcomponents
        at = next((i for i, c in enumerate(components) if not isinstance(c, Timezone)), 0)
        for tzid in missing:
            zone = named_zone(tzid)
            if zone is None or zone.key != tzid:
                continue
            vtimezone = Timezone.from_tzinfo(
                zone, tzid=tzid, first_date=date(first, 1, 1), last_date=date(last, 1, 1)
            )
            vtimezone.pop("COMMENT", None)
            components.insert(at, vtimezone)
            at += 1


def _shift(before: SyncedEvent, after: SyncedEvent) -> timedelta | None:
    """How far a timed series' time of day moved on its first day (the core moves its changed
    occurrences and EXDATEs with it), or None."""
    if before.timing.all_day or after.timing.all_day or before.tzid != after.tzid:
        return None
    assert before.timing.start_utc is not None and after.timing.start_utc is not None
    zone = _load_zone(after.tzid or "UTC")
    old = to_local(before.timing.start_utc, zone)
    new = to_local(after.timing.start_utc, zone)
    return new - old if old.date() == new.date() and new != old else None


def _python_value(when: _When) -> date | datetime:
    if when.kind == "utc":
        return when.wall().replace(tzinfo=UTC)
    return when.value


# --- Google's recurrence lines ------------------------------------------------------------------

_LINE = re.compile(r"(?P<name>[A-Za-z-]+)(?P<params>(?:;[^:]*)?):(?P<value>.*)")
_MOMENT = re.compile(r"([0-9]{8})(?:T([0-9]{6})(Z?))?")


def parse_recurrence_lines(
    lines: Sequence[str], timing: Timing, tzid: str | None, household: ZoneInfo
) -> tuple[str | None, tuple[str, ...], tuple[str, ...]]:
    """Google's `recurrence` array (["RRULE:...", "EXDATE;TZID=Europe/London:20261008T090000",
    "RDATE;VALUE=DATE:20261224"]) as (rrule normalized via validate_rrule, rdates, exdates),
    with dates as recurrence ids in the series' zone. Raises RecurrenceError for an unsupported
    rule (as validate_rrule does)."""
    context = _Context(household, {})
    if timing.all_day:
        frame = _Frame("date")
        rule_zone = "UTC"
    else:
        assert timing.start_utc is not None
        zone = context.zone(tzid, timing.start_utc.year) if tzid else household
        at = to_local(timing.start_utc, zone).time()
        frame = (
            _Frame("utc", _UTC_ZONE, at=at) if zone.key == "UTC" else _Frame("zoned", zone, at=at)
        )
        rule_zone = zone.key
    rules: list[str] = []
    rdates: set[str] = set()
    exdates: set[str] = set()
    for line in lines:
        match = _LINE.fullmatch(line.strip())
        if match is None:
            raise RecurrenceError("rrule_invalid", "api.repeat.bad_rule")
        name = match.group("name").upper()
        if name == "RRULE":
            rules.append(match.group("value"))
        elif name == "EXRULE":
            raise RecurrenceError("rrule_unsupported", "api.repeat.exrule")
        elif name in ("RDATE", "EXDATE"):
            params = _line_params(match.group("params"))
            target = rdates if name == "RDATE" else exdates
            for text in match.group("value").split(","):
                when = context.when(_moment_value(text), params.get("TZID"))
                target.add(frame.rid(when, household))
    if len(rules) > 1:
        raise RecurrenceError("rrule_unsupported", "api.repeat.one_way")
    rrule = validate_rrule(rules[0], timing, rule_zone) if rules else None
    return rrule, tuple(sorted(rdates)), tuple(sorted(exdates))


def _line_params(text: str) -> dict[str, str]:
    params: dict[str, str] = {}
    for chunk in text.split(";"):
        key, equals, value = chunk.partition("=")
        if equals:
            params[key.strip().upper()] = value.strip().strip('"')
    return params


def _moment_value(text: str) -> date | datetime:
    """One EXDATE or RDATE value: a date, a wall time, or a UTC time (a period's start)."""
    match = _MOMENT.fullmatch(text.strip().split("/")[0])
    if match is None:
        raise RecurrenceError("rrule_invalid", "api.repeat.bad_date")
    digits, clock, utc = match.groups()
    try:
        day = date(int(digits[:4]), int(digits[4:6]), int(digits[6:]))
        if clock is None:
            return day
        moment = datetime.combine(day, time(int(clock[:2]), int(clock[2:4]), int(clock[4:])))
    except ValueError:
        raise RecurrenceError("rrule_invalid", "api.repeat.unreal_date") from None
    return moment.replace(tzinfo=UTC) if utc else moment


def recurrence_lines(series: SyncedSeries) -> list[str]:
    """The reverse: RRULE, EXDATE and RDATE lines for Google, with TZID for timed series."""
    master = series.master
    if master is None:
        raise ValueError("A series needs its main event to be written out.")
    lines = [f"RRULE:{series.rrule}"] if series.rrule else []
    for name, rids in (("EXDATE", series.exdates), ("RDATE", series.rdates)):
        days: set[str] = set()
        times: set[str] = set()
        for rid in rids:
            value = parse_rid(rid)
            if isinstance(value, datetime) and not master.timing.all_day:
                times.add(value.strftime("%Y%m%dT%H%M%S"))
            else:
                day = value.date() if isinstance(value, datetime) else value
                days.add(day.strftime("%Y%m%d"))
        if times:
            tzid = master.tzid or "UTC"
            if tzid == "UTC":
                lines.append(f"{name}:" + ",".join(f"{t}Z" for t in sorted(times)))
            else:
                lines.append(f"{name};TZID={tzid}:" + ",".join(sorted(times)))
        if days:
            lines.append(f"{name};VALUE=DATE:" + ",".join(sorted(days)))
    return lines
