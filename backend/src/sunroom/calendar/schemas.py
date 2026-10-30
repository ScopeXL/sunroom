"""The calendar API's shapes (PLAN §7, §11.1).

Times go in as the household's wall time: a timed event's ``start``/``end`` are naive local
datetimes in its zone (``tzid``, the household's by default); an all-day event has dates with
an exclusive end. Occurrences come back with UTC instants and the household's wall time.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

from sunroom.domain.recurrence import RepeatParts
from sunroom.household.schemas import PersonColor

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
CalendarName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
Reminder = Annotated[int, Field(ge=0, le=7 * 24 * 60)]
Scope = Literal["this", "following", "all"]


class CalendarOut(BaseModel):
    id: str
    name: str
    color: PersonColor
    kind: Literal["local", "sync"]
    owner_member_id: str | None
    read_only: bool
    visible_on_display: bool
    version: int
    is_default: bool
    deleted: bool
    source_label: str | None = None  # a synced calendar's account: "Apple", "Google", …


class CalendarCreate(BaseModel):
    name: CalendarName
    color: PersonColor = "sky"
    owner_member_id: str | None = None
    visible_on_display: bool = True


class CalendarUpdate(BaseModel):
    name: CalendarName | None = None
    color: PersonColor | None = None
    owner_member_id: str | None = None
    visible_on_display: bool | None = None


class EventFields(BaseModel):
    """The editable parts of an event; on an update, only the fields sent change."""

    calendar_id: str | None = None
    title: Title | None = None
    description: Annotated[str, StringConstraints(max_length=5000)] | None = None
    location: Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)] | None = None
    all_day: bool | None = None
    start: datetime | None = None  # timed: naive wall time in tzid
    end: datetime | None = None
    start_date: date | None = None  # all-day: end exclusive
    end_date: date | None = None
    tzid: Annotated[str, StringConstraints(max_length=64)] | None = None
    rrule: Annotated[str, StringConstraints(max_length=500)] | None = None
    member_ids: list[str] | None = None
    reminders: list[Reminder] | None = None
    # True: explicitly no reminder, whatever the household's default (ADR 0034). With no
    # reminders and false, the Default reminder applies.
    reminders_off: bool | None = None
    color: PersonColor | None = None


class EventCreate(EventFields):
    title: Title = Field(...)  # pyright: ignore[reportIncompatibleVariableOverride]


class EventUpdate(EventFields):
    """PATCH a whole series (``scope`` all) or, at an occurrence, ``this`` / ``following``.
    ``clear_rrule``/``clear_color`` say "remove it" (None means "leave it")."""

    scope: Scope = "all"
    expected_version: int | None = None
    clear_rrule: bool = False
    clear_color: bool = False


class MoveIn(BaseModel):
    """The drag fast path: to another day, keeping the time of day and the length."""

    to_date: date
    recurrence_id: str | None = None
    scope: Scope = "all"


class UndoIn(BaseModel):
    revision_id: str | None = None


class RepeatPartsOut(BaseModel):
    """A repeat in parts (``domain.recurrence.RepeatParts``) for the page to word in the
    family's language (ADR 0043); ``repeat_text`` beside it says the same in English."""

    freq: Literal["daily", "weekly", "monthly", "yearly"] | None  # None: a custom schedule
    interval: int
    weekdays: list[int]  # weekly: 0 Monday … 6 Sunday, in the rule's week order
    month_days: list[int]  # monthly: 1…31; yearly: one
    last_day: bool  # monthly: the month's last day
    nth: int | None  # on a weekday: 1…5, or -1 for the last
    weekday: int | None  # that weekday, 0 Monday … 6 Sunday
    month: int | None  # yearly: 1…12
    until: date | None  # the last day an occurrence can fall on
    count: int | None

    @classmethod
    def of(cls, parts: RepeatParts) -> RepeatPartsOut:
        return cls.model_validate(asdict(parts))


class EventOut(BaseModel):
    id: str
    calendar_id: str
    title: str
    description: str
    location: str
    all_day: bool
    start: datetime | None  # wall time in tzid
    end: datetime | None
    start_date: date | None
    end_date: date | None
    tzid: str | None
    rrule: str | None
    repeat_text: str | None  # "Every week on Thu", in English
    repeat: RepeatPartsOut | None = None  # the same in parts, for the family's language
    exdates: list[str]
    member_ids: list[str]
    # The title decides who it's for (ADR 0034): set on import, or by names in a new title; a
    # Who set by hand turns it off.
    people_from_title: bool = False
    reminders: list[int]
    reminders_off: bool = False  # explicitly none; no rows and false: the household's default
    color: PersonColor | None
    status: str
    source: str
    pending: bool = False  # a change waiting to reach its account ("Not synced yet")
    read_only: bool
    version: int
    is_override: bool
    parent_event_id: str | None
    recurrence_id: str | None
    created_by_member_id: str | None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None


class ChangeOut(BaseModel):
    """What a change did: the series now (None when it was removed), the revision Undo
    reverses, and how many one-off changes it had to drop."""

    event: EventOut | None
    revision_id: str
    dropped_overrides: int = 0


class OccurrenceOut(BaseModel):
    key: str  # "<event id>|<recurrence id>"
    event_id: str | None  # None for an overlay
    recurrence_id: str | None
    calendar_id: str | None
    title: str
    location: str
    all_day: bool
    start_utc: datetime | None
    end_utc: datetime | None
    start_local: datetime | None  # the household's wall time
    end_local: datetime | None
    start_date: date | None
    end_date: date | None  # exclusive
    member_ids: list[str]
    color: PersonColor | None
    calendar_color: PersonColor | None
    is_recurring: bool
    is_override: bool
    read_only: bool
    source: str
    pending: bool = False  # a change waiting to reach its account ("Not synced yet")
    status: str
    overlay: str | None
    reminders: list[int]
    reminders_off: bool = False  # explicitly none: the wall's Default reminder doesn't apply
    version: int  # the series' version, for an update's expected_version


class OccurrencesOut(BaseModel):
    from_date: date
    to_date: date
    timezone: str
    calendar_versions: dict[str, int]
    occurrences: list[OccurrenceOut]


class DescribeOut(BaseModel):
    text: str  # in English
    rrule: str  # normalized
    repeat: RepeatPartsOut | None = None  # the same in parts, for the family's language


class SearchHit(BaseModel):
    event: EventOut
    next_start_local: datetime | None  # the next (or last) occurrence, wall time
    next_start_date: date | None
