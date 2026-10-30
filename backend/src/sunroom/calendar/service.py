"""Calendars and events: add, change at a scope, remove, move, undo (PLAN §7.4).

Every change writes a revision first (a snapshot of each series it touches), runs in one write
transaction, bumps the calendar's version (the occurrence cache's key) and publishes
``events.changed``.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from sunroom.auth.deps import Actor
from sunroom.calendar import people, revisions
from sunroom.calendar.models import (
    Calendar,
    CalendarKind,
    Event,
    EventMember,
    EventReminder,
    EventRevision,
    EventSource,
    RevisionAction,
)
from sunroom.calendar.schemas import (
    CalendarCreate,
    CalendarOut,
    CalendarUpdate,
    ChangeOut,
    EventCreate,
    EventFields,
    EventOut,
    EventUpdate,
    MoveIn,
    RepeatPartsOut,
    Scope,
    SearchHit,
)
from sunroom.calendar.timing import (
    checked_rule,
    invalid,
    json_list,
    load_zone,
    local_start,
    override_of,
    resolve_timing,
    same_start_day,
    series_of,
    set_timing,
    time_shift,
    timing_of,
)
from sunroom.core.errors import AppError
from sunroom.db.engine import WriteTx
from sunroom.db.types import new_id
from sunroom.domain import recurrence
from sunroom.domain.recurrence import RecurrenceError, Timing, Window
from sunroom.domain.timeparts import day_bounds, parse_rid, to_local
from sunroom.household.models import Household

UNDO_DAYS = 30
REMOVED_DAYS = 7  # Recently removed (PLAN §8.4); Undo and the rows themselves last UNDO_DAYS
SEARCH_LIMIT = 30


@dataclass(frozen=True, slots=True)
class Context:
    """Who is changing what, and when (the service never reads a clock itself)."""

    actor: Actor
    now: datetime
    zone_key: str  # the household's zone: new events' default
    members: frozenset[str]  # active member ids


# ---- calendars ---------------------------------------------------------------------------------


async def default_calendar(session: AsyncSession) -> Calendar:
    """Where new events go: the household's default calendar while it's here and takes events
    (a synced one can be removed with its account, or turn read-only), else the first local
    calendar that does."""
    home = await session.get(Household, 1)
    if home is not None and home.default_calendar_id:
        found = await session.get(Calendar, home.default_calendar_id)
        if found is not None and found.deleted_at is None and not found.read_only:
            return found
    first = (
        await session.scalars(
            select(Calendar)
            .where(
                Calendar.kind == CalendarKind.LOCAL,
                Calendar.deleted_at.is_(None),
                Calendar.read_only.is_(False),
            )
            .order_by(Calendar.sort, Calendar.created_at)
        )
    ).first()
    if first is not None:
        return first
    raise AppError(409, "no_calendar", "api.calendar.no_calendar")


async def list_calendars(session: AsyncSession, *, include_deleted: bool = False) -> list[Calendar]:
    query = select(Calendar).order_by(Calendar.sort, Calendar.created_at)
    if not include_deleted:
        query = query.where(Calendar.deleted_at.is_(None))
    return list((await session.scalars(query)).all())


def calendar_out(calendar: Calendar, default_id: str | None) -> CalendarOut:
    return CalendarOut.model_validate(
        {
            "id": calendar.id,
            "name": calendar.name,
            "color": calendar.color,
            "kind": calendar.kind,
            "owner_member_id": calendar.owner_member_id,
            "read_only": calendar.read_only,
            "visible_on_display": calendar.visible_on_display,
            "version": calendar.version,
            "is_default": calendar.id == default_id,
            "deleted": calendar.deleted_at is not None,
            "source_label": calendar.remote_ref if calendar.kind == CalendarKind.SYNC else None,
        }
    )


async def default_calendar_id(session: AsyncSession) -> str | None:
    try:
        return (await default_calendar(session)).id
    except AppError:
        return None


async def create_calendar(tx: WriteTx, body: CalendarCreate, ctx: Context) -> Calendar:
    _check_member(body.owner_member_id, ctx)
    count = await tx.session.scalar(select(func.count()).select_from(Calendar)) or 0
    calendar = Calendar(
        name=body.name,
        color=body.color,
        owner_member_id=body.owner_member_id,
        visible_on_display=body.visible_on_display,
        sort=count,
        created_at=ctx.now,
        updated_at=ctx.now,
    )
    tx.session.add(calendar)
    await tx.session.flush()
    tx.publish("calendars.changed", {"calendar_id": calendar.id})
    return calendar


async def _local_calendar(session: AsyncSession, calendar_id: str) -> Calendar:
    calendar = await session.get(Calendar, calendar_id)
    if calendar is None:
        raise AppError(404, "not_found", "api.calendar.calendar_not_found")
    if calendar.kind != CalendarKind.LOCAL:
        raise AppError(409, "managed_by_sync", "api.calendar.managed_by_sync")
    return calendar


async def update_calendar(
    tx: WriteTx, calendar_id: str, body: CalendarUpdate, ctx: Context
) -> Calendar:
    calendar = await _local_calendar(tx.session, calendar_id)
    if calendar.deleted_at is not None:
        raise AppError(404, "not_found", "api.calendar.calendar_removed")
    if body.name is not None:
        calendar.name = body.name
    if body.color is not None:
        calendar.color = body.color
    if "owner_member_id" in body.model_fields_set:
        _check_member(body.owner_member_id, ctx)
        calendar.owner_member_id = body.owner_member_id
    if body.visible_on_display is not None:
        calendar.visible_on_display = body.visible_on_display
    calendar.updated_at = ctx.now
    calendar.version += 1
    tx.publish("calendars.changed", {"calendar_id": calendar.id})
    return calendar


async def make_default(tx: WriteTx, calendar_id: str) -> Calendar:
    """The default calendar: new events go here unless another is picked (UX §4). Any calendar
    that takes events can be it, a synced one from an account too."""
    calendar = await tx.session.get(Calendar, calendar_id)
    if calendar is None or calendar.deleted_at is not None:
        raise AppError(404, "not_found", "api.calendar.calendar_not_found")
    if calendar.read_only:
        raise AppError(409, "calendar_read_only", "api.calendar.shows_only")
    home = await tx.session.get(Household, 1)
    if home is not None and home.default_calendar_id != calendar.id:
        home.default_calendar_id = calendar.id
        tx.publish("calendars.changed", {"calendar_id": calendar.id})
    return calendar


async def remove_calendar(tx: WriteTx, calendar_id: str, ctx: Context) -> Calendar:
    calendar = await _local_calendar(tx.session, calendar_id)
    # Sunroom always keeps one calendar of its own (the owner's rule, ADR 0032), so new events
    # have somewhere to go when an account's calendar is the default and then goes.
    others = await tx.session.scalar(
        select(func.count())
        .select_from(Calendar)
        .where(
            Calendar.kind == CalendarKind.LOCAL,
            Calendar.deleted_at.is_(None),
            Calendar.read_only.is_(False),
            Calendar.id != calendar.id,
        )
    )
    if not others:
        raise AppError(409, "last_calendar", "api.calendar.last_calendar")
    if calendar.id == await default_calendar_id(tx.session):
        raise AppError(409, "default_calendar", "api.calendar.default_calendar")
    calendar.deleted_at = ctx.now
    calendar.version += 1
    tx.publish("calendars.changed", {"calendar_id": calendar.id})
    return calendar


async def restore_calendar(tx: WriteTx, calendar_id: str, ctx: Context) -> Calendar:
    calendar = await _local_calendar(tx.session, calendar_id)
    calendar.deleted_at = None
    calendar.updated_at = ctx.now
    calendar.version += 1
    tx.publish("calendars.changed", {"calendar_id": calendar.id})
    return calendar


# ---- reading events ----------------------------------------------------------------------------


async def _members_of(session: AsyncSession, event_id: str) -> list[str]:
    return list(
        (
            await session.scalars(
                select(EventMember.member_id).where(EventMember.event_id == event_id)
            )
        ).all()
    )


async def _reminders_of(session: AsyncSession, event_id: str) -> list[int]:
    return sorted(
        (
            await session.scalars(
                select(EventReminder.minutes_before).where(EventReminder.event_id == event_id)
            )
        ).all()
    )


async def event_out(session: AsyncSession, event: Event) -> EventOut:
    calendar = await session.get(Calendar, event.calendar_id)
    start = end = None
    if not event.all_day:
        zone = load_zone(event.tzid or "UTC")
        assert event.start_utc is not None and event.end_utc is not None
        start, end = to_local(event.start_utc, zone), to_local(event.end_utc, zone)
    repeat_text = repeat = None
    if event.rrule:
        timing, zone = timing_of(event), event.tzid or "UTC"
        try:
            repeat = RepeatPartsOut.of(recurrence.describe_parts(event.rrule, timing, zone))
            repeat_text = recurrence.describe(event.rrule, timing, zone)
        except RecurrenceError:
            repeat_text = repeat = None
    return EventOut.model_validate(
        {
            "id": event.id,
            "calendar_id": event.calendar_id,
            "title": event.title,
            "description": event.description,
            "location": event.location,
            "all_day": event.all_day,
            "start": start,
            "end": end,
            "start_date": event.start_date,
            "end_date": event.end_date,
            "tzid": event.tzid,
            "rrule": event.rrule,
            "repeat_text": repeat_text,
            "repeat": repeat,
            "exdates": json_list(event.exdates_json),
            "member_ids": await _members_of(session, event.id),
            "people_from_title": event.people_from_title,
            "reminders": await _reminders_of(session, event.id),
            "reminders_off": event.reminders_off,
            "color": event.color,
            "status": event.status,
            "source": event.source,
            "pending": event.pending_push or event.pending_delete,
            "read_only": bool(calendar and calendar.read_only),
            "version": event.version,
            "is_override": event.parent_event_id is not None,
            "parent_event_id": event.parent_event_id,
            "recurrence_id": event.recurrence_id,
            "created_by_member_id": event.created_by_member_id,
            "created_at": event.created_at,
            "updated_at": event.updated_at,
            "deleted_at": event.deleted_at,
        }
    )


async def get_master(session: AsyncSession, event_id: str) -> Event:
    event = await session.get(Event, event_id)
    if event is None or event.deleted_at is not None:
        raise AppError(404, "not_found", "api.calendar.event_not_found")
    if event.parent_event_id is not None:
        master = await session.get(Event, event.parent_event_id)
        if master is None or master.deleted_at is not None:
            raise AppError(404, "not_found", "api.calendar.event_not_found")
        return master
    return event


# ---- helpers for changes -----------------------------------------------------------------------


def _check_member(member_id: str | None, ctx: Context) -> None:
    if member_id is not None and member_id not in ctx.members:
        raise invalid("api.calendar.unknown_member", "member_ids", code="unknown_member")


def _check_members(member_ids: list[str] | None, ctx: Context) -> list[str] | None:
    if member_ids is None:
        return None
    unique = list(dict.fromkeys(member_ids))
    for member_id in unique:
        _check_member(member_id, ctx)
    return unique


async def _writable_calendar(session: AsyncSession, calendar_id: str) -> Calendar:
    calendar = await session.get(Calendar, calendar_id)
    if calendar is None or calendar.deleted_at is not None:
        raise invalid("api.calendar.calendar_not_found", "calendar_id", code="unknown_calendar")
    if calendar.read_only:
        if not calendar.remote_ref:
            raise AppError(409, "calendar_read_only", "api.calendar.read_only_account")
        raise AppError(
            409,
            "calendar_read_only",
            "api.calendar.read_only_from",
            params={"source": calendar.remote_ref},
        )
    return calendar


async def _set_people(
    session: AsyncSession,
    row: Event,
    member_ids: list[str] | None,
    reminders: list[int] | None,
    reminders_off: bool | None = None,
) -> None:
    """Who it's for and its reminders, each only when sent. Reminders have three states
    (ADR 0034): its own rows; explicitly none (``reminders_off``); or neither, the household's
    Default reminder, which the wall resolves. Rows sent turn the flag off; the flag sent on
    takes the rows away."""
    if reminders_off and reminders:
        raise invalid("api.calendar.reminders_or_none", "reminders")
    event_id = row.id
    if member_ids is not None:
        for old in (
            await session.scalars(select(EventMember).where(EventMember.event_id == event_id))
        ).all():
            await session.delete(old)
        await session.flush()
        for member_id in member_ids:
            session.add(EventMember(event_id=event_id, member_id=member_id))
    if reminders is not None or reminders_off:
        for old in (
            await session.scalars(select(EventReminder).where(EventReminder.event_id == event_id))
        ).all():
            await session.delete(old)
        await session.flush()
        for minutes in sorted(set(reminders or [])):
            session.add(EventReminder(event_id=event_id, minutes_before=minutes))
    if reminders:
        row.reminders_off = False
    elif reminders_off is not None:
        row.reminders_off = reminders_off


async def _sent_people(
    session: AsyncSession,
    row: Event,
    calendar: Calendar,
    sent: list[str] | None,
    *,
    title_changed: bool,
) -> None:
    """Who ``row`` is for after a change (ADR 0034). People sent that differ from its rows are
    a hand choice: written, and the title stops deciding. Nothing sent, a changed title
    matches again while the title decides. A new title alone never touches a hand choice."""
    if sent is not None:
        if set(sent) != set(await _members_of(session, row.id)):
            row.people_from_title = False
            await _set_people(session, row, sent, None)
        return
    if title_changed and row.people_from_title:
        await people.assign(session, row, calendar, await people.household_people(session))


async def _overrides(session: AsyncSession, master_id: str) -> list[Event]:
    return list(
        (
            await session.scalars(
                select(Event).where(Event.parent_event_id == master_id, Event.deleted_at.is_(None))
            )
        ).all()
    )


async def refresh_window(session: AsyncSession, master: Event) -> None:
    overrides = await _overrides(session, master.id)
    for row in overrides:
        row_start, row_end = recurrence.series_bounds(
            recurrence.Series(timing=timing_of(row), tzid=row.tzid or master.tzid or "UTC")
        )
        row.window_start_utc, row.window_end_utc = row_start, row_end
    master.window_start_utc, master.window_end_utc = recurrence.series_bounds(
        series_of(master), [override_of(o) for o in overrides]
    )


async def bump(tx: WriteTx, calendar_ids: set[str], event_ids: list[str]) -> None:
    for calendar_id in calendar_ids:
        await tx.session.execute(
            update(Calendar).where(Calendar.id == calendar_id).values(version=Calendar.version + 1)
        )
        version = await tx.session.scalar(
            select(Calendar.version).where(Calendar.id == calendar_id)
        )
        tx.publish(
            "events.changed",
            {"calendar_id": calendar_id, "event_ids": event_ids, "calendar_version": version},
        )


async def rematch_people(tx: WriteTx, calendar_ids: Iterable[str] | None = None) -> None:
    """Every event the title decides, matched again and announced (ADR 0034): after a person is
    added, renamed, archived or put back, and once at start."""
    changed = await people.rematch(tx.session, calendar_ids)
    for calendar_id, event_ids in changed.items():
        await bump(tx, {calendar_id}, event_ids[:50])


async def _revision(
    tx: WriteTx,
    ctx: Context,
    series_id: str,
    action: RevisionAction,
    before: str,
    created: list[str] | None = None,
) -> str:
    revision = EventRevision(
        series_id=series_id,
        action=action,
        before_json=before,
        created_ids_json=json.dumps(created or []),
        device_id=ctx.actor.device_id,
        member_id=ctx.actor.member_id,
        created_at=ctx.now,
    )
    tx.session.add(revision)
    ids: list[str] = [series_id, *(created or [])]
    for event_id in dict.fromkeys(ids):
        await _mark_for_push(tx.session, event_id)
    await tx.session.flush()
    return revision.id


def new_uid() -> str:
    """A UID for a series Sunroom creates on a server."""
    return f"{new_id()}@sunroom"


async def _mark_for_push(session: AsyncSession, event_id: str) -> None:
    """A synced series a person changed waits to be pushed (PLAN §8.2); one removed waits to be
    removed from the server, unless it never got there."""
    master = await session.get(Event, event_id)
    if master is None or master.source != EventSource.SYNC or master.parent_event_id is not None:
        return
    if master.deleted_at is not None:
        master.pending_push = False
        master.pending_delete = master.remote_id is not None
        return
    master.pending_delete = False
    master.pending_push = True
    if not master.remote_uid:
        master.remote_uid = new_uid()


def _first_of_series(series: recurrence.Series, rid: str) -> bool:
    """Whether ``rid`` is where the series begins, so "this and the ones after" means all of
    them. An id that isn't a day of this event is a 404, like any occurrence that isn't there."""
    try:
        return recurrence.count_before(series, rid) == 0
    except ValueError:  # RecurrenceError is one
        raise AppError(404, "not_found", "api.calendar.occurrence_not_found") from None


def _occurrence_at(master: Event, overrides: list[Event], rid: str) -> recurrence.Occurrence:
    """The occurrence with this recurrence id as it stands (moved by an override or not)."""
    for row in overrides:
        if row.recurrence_id == rid:
            return recurrence.Occurrence(recurrence_id=rid, timing=timing_of(row), is_override=True)
    try:
        original = parse_rid(rid)
    except ValueError:
        raise AppError(404, "not_found", "api.calendar.occurrence_not_found") from None
    zone = load_zone(master.tzid or "UTC")
    day = original.date() if isinstance(original, datetime) else original
    start_utc, _ = day_bounds(day - timedelta(days=1), zone)
    _, end_utc = day_bounds(day + timedelta(days=1), zone)
    window = Window(start_utc, end_utc, day - timedelta(days=1), day + timedelta(days=2))
    for occurrence in recurrence.expand(series_of(master), [], window):
        if occurrence.recurrence_id == rid:
            return occurrence
    raise AppError(404, "not_found", "api.calendar.occurrence_not_found")


def _apply_text(row: Event, fields: EventFields, *, clear_color: bool = False) -> None:
    if fields.title is not None:
        row.title = fields.title
    if fields.description is not None:
        row.description = fields.description
    if fields.location is not None:
        row.location = fields.location
    if clear_color:
        row.color = None
    elif fields.color is not None:
        row.color = fields.color


def _copy(master: Event, **changes: object) -> Event:
    columns = {
        column.key: getattr(master, column.key)
        for column in Event.__table__.columns
        if column.key not in {"id"}
    }
    columns.update(changes)
    return Event(**columns)


def _shifted(rids: list[str], delta: timedelta) -> list[str]:
    return [recurrence.shift_rid(rid, delta) for rid in rids] if delta else rids


def _rid_start(rid: str) -> datetime:
    parsed = parse_rid(rid)
    return parsed if isinstance(parsed, datetime) else datetime.combine(parsed, datetime.min.time())


# ---- changes -----------------------------------------------------------------------------------


async def create_event(tx: WriteTx, body: EventCreate, ctx: Context) -> ChangeOut:
    calendar = await _writable_calendar(
        tx.session, body.calendar_id or (await default_calendar(tx.session)).id
    )
    timing, tzid = resolve_timing(None, None, body, ctx.zone_key)
    rrule = checked_rule(body.rrule, timing, tzid) if body.rrule else None
    sent = _check_members(body.member_ids, ctx)
    synced = calendar.kind == CalendarKind.SYNC
    if sent is not None:
        # Picked by hand (Everyone included): that's who, and the title doesn't decide.
        members, from_title = sent, False
    else:
        # Nobody picked: the title decides (ADR 0034), as for an imported event, and in a synced
        # calendar with no names its person shows by the read-time fallback.
        members = people.wanted_ids(body.title, calendar, await people.household_people(tx.session))
        from_title = bool(members) or synced
    event = Event(
        calendar_id=calendar.id,
        title=body.title,
        description=body.description or "",
        location=body.location or "",
        rrule=rrule,
        color=body.color,
        source=EventSource.SYNC if synced else EventSource.LOCAL,
        remote_uid=new_uid() if synced else None,
        created_by_member_id=ctx.actor.member_id,
        people_from_title=from_title,
        created_at=ctx.now,
        updated_at=ctx.now,
        window_start_utc=ctx.now,
        window_end_utc=ctx.now,
    )
    set_timing(event, timing, tzid)
    tx.session.add(event)
    await tx.session.flush()
    await _set_people(tx.session, event, members, body.reminders or [], body.reminders_off)
    await refresh_window(tx.session, event)
    revision_id = await _revision(tx, ctx, event.id, RevisionAction.CREATE, "[]", [event.id])
    await bump(tx, {calendar.id}, [event.id])
    return ChangeOut(event=await event_out(tx.session, event), revision_id=revision_id)


async def update_series(
    tx: WriteTx,
    master: Event,
    body: EventUpdate,
    ctx: Context,
    action: RevisionAction = RevisionAction.UPDATE,
) -> ChangeOut:
    """Scope "all": change the series in place. A new time of day shifts its exceptions with
    it; a new first day, a new repeat or switching all-day clears them (reported)."""
    if body.expected_version is not None and body.expected_version != master.version:
        raise AppError(409, "version_conflict", "api.calendar.version_conflict")
    calendar = await _writable_calendar(tx.session, master.calendar_id)
    calendars = {calendar.id}
    to_calendar: Calendar | None = None
    if body.calendar_id is not None and body.calendar_id != master.calendar_id:
        if master.source == EventSource.SYNC:
            raise AppError(409, "synced_stays", "api.calendar.synced_stays")
        to_calendar = await _writable_calendar(tx.session, body.calendar_id)
        calendars.add(to_calendar.id)
    before = await revisions.snapshot(tx.session, [master.id])
    old_timing, old_tzid = timing_of(master), master.tzid
    timing, tzid = resolve_timing(old_timing, old_tzid, body, ctx.zone_key)
    if body.clear_rrule:
        rrule = None
    elif body.rrule is not None:
        rrule = checked_rule(body.rrule, timing, tzid)
    else:
        rrule = checked_rule(master.rrule, timing, tzid) if master.rrule else None
    members = _check_members(body.member_ids, ctx)

    dropped = 0
    overrides = await _overrides(tx.session, master.id)
    zone = load_zone(tzid)
    keep = (
        rrule == master.rrule
        and timing.all_day == old_timing.all_day
        and same_start_day(old_timing, timing, load_zone(old_tzid or tzid))
    )
    if keep:
        delta = time_shift(old_timing, timing, zone)
        master.exdates_json = json.dumps(_shifted(json_list(master.exdates_json), delta))
        if delta:
            for row in overrides:
                row.recurrence_id = recurrence.shift_rid(row.recurrence_id or "", delta)
    else:
        dropped = len(overrides)
        for row in overrides:
            row.deleted_at = ctx.now
        master.exdates_json = "[]"
        master.rdates_json = "[]"

    old_title = master.title
    _apply_text(master, body, clear_color=body.clear_color)
    if to_calendar is not None:
        master.calendar_id = to_calendar.id
        for row in overrides:
            row.calendar_id = to_calendar.id
        if to_calendar.kind == CalendarKind.SYNC:
            master.source = EventSource.SYNC
            master.remote_uid = new_uid()
    set_timing(master, timing, tzid)
    master.rrule = rrule
    master.version += 1
    master.updated_at = ctx.now
    await _sent_people(
        tx.session,
        master,
        to_calendar or calendar,
        members,
        title_changed=master.title != old_title,
    )
    await _set_people(tx.session, master, None, body.reminders, body.reminders_off)
    # All of Them reaches the occurrences changed one by one too (R4): what was sent for the
    # series is theirs as well.
    for row in overrides:
        if row.deleted_at is not None:
            continue
        if members is not None:
            row.people_from_title = master.people_from_title
        await _set_people(tx.session, row, members, body.reminders, body.reminders_off)
    await tx.session.flush()
    await refresh_window(tx.session, master)
    revision_id = await _revision(tx, ctx, master.id, action, before)
    await bump(tx, calendars, [master.id])
    return ChangeOut(
        event=await event_out(tx.session, master),
        revision_id=revision_id,
        dropped_overrides=dropped,
    )


async def update_occurrence(
    tx: WriteTx,
    master: Event,
    rid: str,
    body: EventUpdate,
    ctx: Context,
    action: RevisionAction = RevisionAction.UPDATE,
) -> ChangeOut:
    if body.scope == "all" or not _repeats(master):
        return await update_series(
            tx, master, body.model_copy(update={"scope": "all"}), ctx, action
        )
    series = series_of(master)
    if body.scope == "following" and _first_of_series(series, rid):
        return await update_series(
            tx, master, body.model_copy(update={"scope": "all"}), ctx, action
        )
    if body.expected_version is not None and body.expected_version != master.version:
        raise AppError(409, "version_conflict", "api.calendar.version_conflict")
    calendar = await _writable_calendar(tx.session, master.calendar_id)
    overrides = await _overrides(tx.session, master.id)
    occurrence = _occurrence_at(master, overrides, rid)
    before = await revisions.snapshot(tx.session, [master.id])
    members = _check_members(body.member_ids, ctx)
    master_members = await _members_of(tx.session, master.id)
    master_reminders = await _reminders_of(tx.session, master.id)

    if body.scope == "this":
        if body.rrule is not None or body.clear_rrule:
            raise invalid("api.calendar.occurrence_cant_repeat", "rrule")
        timing, _ = resolve_timing(occurrence.timing, master.tzid, body, ctx.zone_key)
        row = next((o for o in overrides if o.recurrence_id == rid), None)
        old_title = row.title if row is not None else master.title
        if row is None:
            row = _copy(
                master,
                parent_event_id=master.id,
                recurrence_id=rid,
                rrule=None,
                rdates_json="[]",
                exdates_json="[]",
                remote_id=None,
                etag=None,
                version=1,
                created_at=ctx.now,
            )
            tx.session.add(row)
            await tx.session.flush()
            await _set_people(
                tx.session,
                row,
                master_members,
                body.reminders if body.reminders is not None else master_reminders,
                body.reminders_off,
            )
        else:
            await _set_people(tx.session, row, None, body.reminders, body.reminders_off)
        _apply_text(row, body, clear_color=body.clear_color)
        # Its own people and title, by the same rules as a series' (ADR 0034).
        await _sent_people(tx.session, row, calendar, members, title_changed=row.title != old_title)
        set_timing(row, timing, master.tzid)
        row.updated_at = ctx.now
        master.exdates_json = json.dumps([r for r in json_list(master.exdates_json) if r != rid])
        master.version += 1
        master.updated_at = ctx.now
        await tx.session.flush()
        await refresh_window(tx.session, master)
        revision_id = await _revision(tx, ctx, master.id, action, before)
        await bump(tx, {calendar.id}, [master.id])
        return ChangeOut(event=await event_out(tx.session, master), revision_id=revision_id)

    # "This and the ones after": the series ends before this occurrence; a new one starts here.
    try:
        truncated, remaining = recurrence.split(series, rid)
    except RecurrenceError as exc:
        raise invalid(exc.key, "recurrence_id", code=exc.code) from None
    original_start = _rid_start(rid)
    start_timing = recurrence.Occurrence(
        recurrence_id=rid,
        timing=_original_timing(master, rid),
        is_override=False,
    ).timing
    timing, tzid = resolve_timing(start_timing, master.tzid, body, ctx.zone_key)
    if body.clear_rrule:
        rule = None
    elif body.rrule is not None:
        rule = checked_rule(body.rrule, timing, tzid)
    else:
        rule = checked_rule(remaining, timing, tzid)
    zone = load_zone(tzid)
    keep = (
        rule == remaining
        and timing.all_day == start_timing.all_day
        and same_start_day(start_timing, timing, zone)
    )
    later_exdates = [r for r in json_list(master.exdates_json) if _rid_start(r) >= original_start]
    master.exdates_json = json.dumps(
        [r for r in json_list(master.exdates_json) if _rid_start(r) < original_start]
    )
    later_rdates = [r for r in json_list(master.rdates_json) if _rid_start(r) >= original_start]
    master.rdates_json = json.dumps(
        [r for r in json_list(master.rdates_json) if _rid_start(r) < original_start]
    )
    shift = time_shift(start_timing, timing, zone) if keep else timedelta(0)
    dropped = 0
    for row in overrides:
        if row.recurrence_id and _rid_start(row.recurrence_id) >= original_start:
            row.deleted_at = ctx.now
            dropped += 1
    master.rrule = truncated
    master.version += 1
    master.updated_at = ctx.now
    sibling = _copy(
        master,
        rrule=rule,
        rdates_json=json.dumps(_shifted(later_rdates, shift)),
        exdates_json=json.dumps(_shifted(later_exdates, shift) if keep else []),
        remote_uid=None,
        remote_id=None,
        etag=None,
        raw_ical=None,
        pending_push=master.source != "local",
        version=1,
        created_by_member_id=ctx.actor.member_id,
        created_at=ctx.now,
        updated_at=ctx.now,
        deleted_at=None,
    )
    _apply_text(sibling, body, clear_color=body.clear_color)
    if body.calendar_id is not None:
        sibling.calendar_id = (await _writable_calendar(tx.session, body.calendar_id)).id
    set_timing(sibling, timing, tzid)
    tx.session.add(sibling)
    await tx.session.flush()
    await _set_people(
        tx.session,
        sibling,
        master_members,
        body.reminders if body.reminders is not None else master_reminders,
        body.reminders_off,
    )
    sibling_calendar = await tx.session.get(Calendar, sibling.calendar_id) or calendar
    await _sent_people(
        tx.session,
        sibling,
        sibling_calendar,
        members,
        title_changed=sibling.title != master.title,
    )
    await tx.session.flush()
    await refresh_window(tx.session, master)
    await refresh_window(tx.session, sibling)
    revision_id = await _revision(tx, ctx, master.id, action, before, [sibling.id])
    await bump(tx, {calendar.id, sibling.calendar_id}, [master.id, sibling.id])
    return ChangeOut(
        event=await event_out(tx.session, sibling),
        revision_id=revision_id,
        dropped_overrides=dropped,
    )


async def event_at(session: AsyncSession, master: Event, rid: str) -> EventOut:
    """One occurrence as the editor should read it (R2, ADR 0034): the row changed on its own
    when there is one, with its own title, place, notes, people and reminders; else the
    series. 404 for a time that isn't one of the event's occurrences."""
    overrides = await _overrides(session, master.id)
    row = next((o for o in overrides if o.recurrence_id == rid), None)
    if row is not None:
        return await event_out(session, row)
    _occurrence_at(master, overrides, rid)
    return await event_out(session, master)


def _original_timing(master: Event, rid: str) -> Timing:
    """Where this occurrence falls by the rule (before any one-off change)."""
    return _occurrence_at(master, [], rid).timing


def _repeats(master: Event) -> bool:
    return bool(master.rrule) or master.rdates_json not in ("", "[]")


async def remove_series(tx: WriteTx, master: Event, ctx: Context) -> ChangeOut:
    await _writable_calendar(tx.session, master.calendar_id)
    before = await revisions.snapshot(tx.session, [master.id])
    master.deleted_at = ctx.now
    master.updated_at = ctx.now  # a removal is a change, newer than the server's copy
    for row in await _overrides(tx.session, master.id):
        row.deleted_at = ctx.now
    master.version += 1
    revision_id = await _revision(tx, ctx, master.id, RevisionAction.DELETE, before)
    await bump(tx, {master.calendar_id}, [master.id])
    return ChangeOut(event=None, revision_id=revision_id)


async def remove_occurrence(
    tx: WriteTx, master: Event, rid: str, scope: Literal["this", "following", "all"], ctx: Context
) -> ChangeOut:
    if scope == "all" or not _repeats(master):
        return await remove_series(tx, master, ctx)
    series = series_of(master)
    if scope == "following" and _first_of_series(series, rid):
        return await remove_series(tx, master, ctx)
    await _writable_calendar(tx.session, master.calendar_id)
    overrides = await _overrides(tx.session, master.id)
    _occurrence_at(master, overrides, rid)  # 404 unless it is one
    before = await revisions.snapshot(tx.session, [master.id])
    dropped = 0
    if scope == "this":
        exdates = json_list(master.exdates_json)
        if rid not in exdates:
            exdates.append(rid)
        master.exdates_json = json.dumps(sorted(exdates))
        for row in overrides:
            if row.recurrence_id == rid:
                row.deleted_at = ctx.now
    else:
        try:
            truncated, _ = recurrence.split(series, rid)
        except RecurrenceError as exc:
            raise invalid(exc.key, "recurrence_id", code=exc.code) from None
        start = _rid_start(rid)
        master.rrule = truncated
        master.exdates_json = json.dumps(
            [r for r in json_list(master.exdates_json) if _rid_start(r) < start]
        )
        master.rdates_json = json.dumps(
            [r for r in json_list(master.rdates_json) if _rid_start(r) < start]
        )
        for row in overrides:
            if row.recurrence_id and _rid_start(row.recurrence_id) >= start:
                row.deleted_at = ctx.now
                dropped += 1
    master.version += 1
    master.updated_at = ctx.now
    await tx.session.flush()
    await refresh_window(tx.session, master)
    revision_id = await _revision(tx, ctx, master.id, RevisionAction.DELETE, before)
    await bump(tx, {master.calendar_id}, [master.id])
    return ChangeOut(
        event=await event_out(tx.session, master),
        revision_id=revision_id,
        dropped_overrides=dropped,
    )


_WEEKDAYS = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")


def _moved_rule(rule: str | None, days: int) -> str | None:
    """A repeat that follows its first day to a new weekday; refuses rules tied to dates."""
    if not rule or days % 7 == 0:
        return rule
    parts = dict(part.split("=", 1) for part in rule.split(";") if "=" in part)
    if any(key in parts for key in ("BYMONTHDAY", "BYMONTH", "BYYEARDAY", "BYWEEKNO", "BYSETPOS")):
        raise invalid("api.calendar.move_set_dates", "to_date", code="move_unsupported")
    if "BYDAY" in parts:
        days_in = parts["BYDAY"].split(",")
        if any(len(day) != 2 for day in days_in):
            raise invalid("api.calendar.move_set_weekday", "to_date", code="move_unsupported")
        parts["BYDAY"] = ",".join(_WEEKDAYS[(_WEEKDAYS.index(day) + days) % 7] for day in days_in)
    return ";".join(f"{key}={value}" for key, value in parts.items())


def _moved_fields(timing: Timing, days: int, zone: ZoneInfo, scope: Scope) -> EventUpdate:
    """The same time of day and length, ``days`` later (or earlier)."""
    if timing.all_day:
        assert timing.start_date is not None and timing.end_date is not None
        return EventUpdate(
            start_date=timing.start_date + timedelta(days=days),
            end_date=timing.end_date + timedelta(days=days),
            scope=scope,
        )
    assert timing.start_utc is not None and timing.end_utc is not None
    start = local_start(timing, zone) + timedelta(days=days)
    return EventUpdate(start=start, end=start + (timing.end_utc - timing.start_utc), scope=scope)


async def move(tx: WriteTx, master: Event, body: MoveIn, ctx: Context) -> ChangeOut:
    """The drag fast path: the same time of day and length, on another day. Moving all of a
    repeating event's occurrences moves the series by as many days as the dragged one moved."""
    repeats = _repeats(master)
    rid = body.recurrence_id if repeats else None
    scope: Scope = body.scope if rid is not None else "all"
    if rid is not None and scope == "following" and _first_of_series(series_of(master), rid):
        scope = "all"
    overrides = await _overrides(tx.session, master.id)
    current = (
        _occurrence_at(master, overrides, rid).timing if rid is not None else timing_of(master)
    )
    zone = load_zone(master.tzid or ctx.zone_key)
    days = (body.to_date - local_start(current, zone).date()).days
    if scope == "all":
        fields = _moved_fields(timing_of(master), days, zone, "all")
        if repeats:
            rule = _moved_rule(master.rrule, days)
            if rule != master.rrule:
                fields.rrule = rule
        return await update_series(tx, master, fields, ctx, RevisionAction.MOVE)
    assert rid is not None
    fields = _moved_fields(current, days, zone, scope)
    if scope == "following":
        try:
            remaining = recurrence.split(series_of(master), rid)[1]
        except RecurrenceError as exc:
            raise invalid(exc.key, "recurrence_id", code=exc.code) from None
        moved = _moved_rule(remaining, days)
        if moved != remaining:
            fields.rrule = moved
    return await update_occurrence(tx, master, rid, fields, ctx, RevisionAction.MOVE)


async def undo(tx: WriteTx, series_id: str, revision_id: str | None, ctx: Context) -> ChangeOut:
    """Reverse the newest change to this series from the last 30 days."""
    newest = (
        await tx.session.scalars(
            select(EventRevision)
            .where(
                EventRevision.series_id == series_id,
                EventRevision.undone_at.is_(None),
                EventRevision.created_at >= ctx.now - timedelta(days=UNDO_DAYS),
            )
            .order_by(EventRevision.created_at.desc(), EventRevision.id.desc())
        )
    ).first()
    if newest is None:
        raise AppError(404, "nothing_to_undo", "api.calendar.nothing_to_undo")
    if revision_id is not None and newest.id != revision_id:
        raise AppError(409, "changed_since", "api.calendar.changed_since")
    calendars: set[str] = set()
    created = [str(event_id) for event_id in json.loads(newest.created_ids_json)]
    for event_id in created:
        row = await tx.session.get(Event, event_id)
        if row is None:
            continue
        calendars.add(row.calendar_id)
        if row.source == EventSource.SYNC and row.remote_id is not None:
            # Already on the server: remove it there too, then it goes for good.
            row.deleted_at = ctx.now
            row.updated_at = ctx.now
            for override in await _overrides(tx.session, event_id):
                override.deleted_at = ctx.now
            await _mark_for_push(tx.session, event_id)
        else:
            await revisions.remove_series(tx.session, event_id)
    calendars.update(await revisions.restore(tx.session, newest.before_json))
    newest.undone_at = ctx.now
    restored = await tx.session.get(Event, series_id)
    if restored is not None:
        restored.version += 1
    await tx.session.flush()
    await _mark_for_push(tx.session, series_id)
    await bump(tx, calendars, [series_id, *created])
    event = (
        await event_out(tx.session, restored)
        if restored is not None and restored.deleted_at is None
        else None
    )
    return ChangeOut(event=event, revision_id=newest.id)


async def restore_event(tx: WriteTx, event_id: str, ctx: Context) -> ChangeOut:
    """Recently removed → Put back: the series and the exceptions removed with it."""
    master = await tx.session.get(Event, event_id)
    if master is None or master.parent_event_id is not None or master.deleted_at is None:
        raise AppError(404, "not_found", "api.calendar.not_in_removed")
    await _writable_calendar(tx.session, master.calendar_id)
    before = await revisions.snapshot(tx.session, [master.id])
    removed_at = master.deleted_at
    master.deleted_at = None
    if master.source == EventSource.SYNC and master.remote_id is None:
        # Already removed from the server: it goes back as a new series there.
        master.remote_uid = new_uid()
        master.etag = None
        master.raw_ical = None
    for row in (
        await tx.session.scalars(
            select(Event).where(Event.parent_event_id == master.id, Event.deleted_at == removed_at)
        )
    ).all():
        row.deleted_at = None
    master.version += 1
    master.updated_at = ctx.now
    await tx.session.flush()
    await refresh_window(tx.session, master)
    revision_id = await _revision(tx, ctx, master.id, RevisionAction.RESTORE, before)
    await bump(tx, {master.calendar_id}, [master.id])
    return ChangeOut(event=await event_out(tx.session, master), revision_id=revision_id)


async def prune(session: AsyncSession, now: datetime) -> None:
    """Undo reaches back UNDO_DAYS (PLAN §7.4): older revisions, and events removed before
    then, go for good. People and reminders follow their event (ON DELETE CASCADE)."""
    cutoff = now - timedelta(days=UNDO_DAYS)
    await session.execute(delete(EventRevision).where(EventRevision.created_at < cutoff))
    gone = select(Event.id).where(Event.parent_event_id.is_(None), Event.deleted_at < cutoff)
    await session.execute(delete(Event).where(Event.parent_event_id.in_(gone)))
    await session.execute(delete(Event).where(Event.deleted_at < cutoff))


async def recently_removed(session: AsyncSession, now: datetime) -> list[EventOut]:
    rows = (
        await session.scalars(
            select(Event)
            .where(
                Event.parent_event_id.is_(None),
                Event.deleted_at.is_not(None),
                Event.deleted_at >= now - timedelta(days=REMOVED_DAYS),
            )
            .order_by(Event.deleted_at.desc())
            .limit(100)
        )
    ).all()
    return [await event_out(session, row) for row in rows]


async def search(
    session: AsyncSession, query: str, now: datetime, zone_key: str
) -> list[SearchHit]:
    """Events whose title or location has these words, each with its next (or last) day."""
    words = query.strip()
    if not words:
        return []
    pattern = "%" + words.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    rows = (
        await session.scalars(
            select(Event)
            .join(Calendar, Calendar.id == Event.calendar_id)
            .where(
                Event.parent_event_id.is_(None),
                Event.deleted_at.is_(None),
                Calendar.deleted_at.is_(None),
                or_(
                    Event.title.ilike(pattern, escape="\\"),
                    Event.location.ilike(pattern, escape="\\"),
                ),
            )
            .order_by(Event.window_end_utc.desc())
            .limit(SEARCH_LIMIT)
        )
    ).all()
    zone = load_zone(zone_key)
    hits: list[SearchHit] = []
    today = to_local(now, zone).date()
    for row in rows:
        overrides = await _overrides(session, row.id)
        start_utc, _ = day_bounds(today, zone)
        _, end_utc = day_bounds(today + timedelta(days=400), zone)
        upcoming = recurrence.expand(
            series_of(row),
            [override_of(o) for o in overrides],
            Window(start_utc, end_utc, today, today + timedelta(days=401)),
            limit=1,
        )
        if not upcoming:
            past_start, _ = day_bounds(today - timedelta(days=400), zone)
            earlier = recurrence.expand(
                series_of(row),
                [override_of(o) for o in overrides],
                Window(past_start, start_utc, today - timedelta(days=400), today),
            )
            upcoming = earlier[-1:]
        next_local = next_date = None
        if upcoming:
            timing = upcoming[0].timing
            if timing.all_day:
                next_date = timing.start_date
            else:
                assert timing.start_utc is not None
                next_local = to_local(timing.start_utc, zone)
        hits.append(
            SearchHit(
                event=await event_out(session, row),
                next_start_local=next_local,
                next_start_date=next_date,
            )
        )
    hits.sort(key=_when)
    return hits


def _when(hit: SearchHit) -> str:
    """ISO text sorts dates and wall times together; no day at all sorts last."""
    if hit.next_start_local is not None:
        return hit.next_start_local.isoformat()
    if hit.next_start_date is not None:
        return hit.next_start_date.isoformat()
    return "~"


async def kid_safe_editing(session: AsyncSession) -> bool:
    home = await session.get(Household, 1)
    return bool(home and home.kid_safe_editing)
