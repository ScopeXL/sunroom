"""The calendar API (PLAN §7, §11.1)."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Query

from sunroom.auth.deps import Actor, ActorDep, ParentDep, parent_required
from sunroom.calendar import service
from sunroom.calendar.occurrences import (
    MAX_DAYS,
    occurrences,
    overlay_occurrences,
    sort_key,
)
from sunroom.calendar.schemas import (
    CalendarCreate,
    CalendarOut,
    CalendarUpdate,
    ChangeOut,
    DescribeOut,
    EventCreate,
    EventFields,
    EventOut,
    EventUpdate,
    MoveIn,
    OccurrencesOut,
    RepeatPartsOut,
    SearchHit,
    UndoIn,
)
from sunroom.calendar.timing import checked_rule, invalid, load_zone, resolve_timing
from sunroom.core.errors import AppError
from sunroom.domain import recurrence
from sunroom.domain.recurrence import RecurrenceError
from sunroom.state import AppState, StateDep

router = APIRouter(prefix="/api/calendar", tags=["calendar"])


def _context(state: AppState, actor: Actor) -> service.Context:
    return service.Context(
        actor=actor,
        now=state.clock.now(),
        zone_key=state.zone().key,
        members=frozenset(state.household.members),
    )


async def _guard_change(state: AppState, actor: Actor) -> None:
    """Kid-safe editing (UX §4): changing or removing an event on the wall screen asks for the
    parent PIN; adding and moving never do."""
    if actor.is_kiosk and not actor.is_parent:
        async with state.db.read() as db:
            if await service.kid_safe_editing(db):
                raise parent_required(actor, state)


# ---- calendars ---------------------------------------------------------------------------------


@router.get("/calendars")
async def get_calendars(
    state: StateDep, actor: ActorDep, include_removed: bool = False
) -> list[CalendarOut]:
    async with state.db.read() as db:
        default_id = await service.default_calendar_id(db)
        rows = await service.list_calendars(db, include_deleted=include_removed)
        return [service.calendar_out(row, default_id) for row in rows]


@router.post("/calendars", status_code=201)
async def post_calendar(body: CalendarCreate, state: StateDep, actor: ParentDep) -> CalendarOut:
    async with state.db.write() as tx:
        calendar = await service.create_calendar(tx, body, _context(state, actor))
        return service.calendar_out(calendar, await service.default_calendar_id(tx.session))


@router.patch("/calendars/{calendar_id}")
async def patch_calendar(
    calendar_id: str, body: CalendarUpdate, state: StateDep, actor: ParentDep
) -> CalendarOut:
    async with state.db.write() as tx:
        calendar = await service.update_calendar(tx, calendar_id, body, _context(state, actor))
        return service.calendar_out(calendar, await service.default_calendar_id(tx.session))


@router.post("/calendars/{calendar_id}/default")
async def make_default_calendar(calendar_id: str, state: StateDep, actor: ParentDep) -> CalendarOut:
    """New events go to this calendar unless another is picked."""
    async with state.db.write() as tx:
        calendar = await service.make_default(tx, calendar_id)
        return service.calendar_out(calendar, await service.default_calendar_id(tx.session))


@router.delete("/calendars/{calendar_id}")
async def delete_calendar(calendar_id: str, state: StateDep, actor: ParentDep) -> CalendarOut:
    async with state.db.write() as tx:
        calendar = await service.remove_calendar(tx, calendar_id, _context(state, actor))
        return service.calendar_out(calendar, await service.default_calendar_id(tx.session))


@router.post("/calendars/{calendar_id}/restore")
async def restore_calendar(calendar_id: str, state: StateDep, actor: ParentDep) -> CalendarOut:
    async with state.db.write() as tx:
        calendar = await service.restore_calendar(tx, calendar_id, _context(state, actor))
        return service.calendar_out(calendar, await service.default_calendar_id(tx.session))


# ---- occurrences -------------------------------------------------------------------------------


@router.get("/occurrences")
async def get_occurrences(
    state: StateDep,
    actor: ActorDep,
    from_date: Annotated[date, Query(alias="from")],
    to_date: Annotated[date, Query(alias="to")],
    calendar_ids: Annotated[list[str] | None, Query()] = None,
    member_ids: Annotated[list[str] | None, Query()] = None,
    overlays: Annotated[list[str] | None, Query()] = None,
    include_cancelled: bool = False,
) -> OccurrencesOut:
    """Every occurrence in [from, to) (household dates, at most 93 days), sorted by start.
    ``member_ids`` keeps events for those people and for Everyone."""
    if to_date <= from_date:
        raise invalid("api.calendar.range_backwards", "to")
    if (to_date - from_date) > timedelta(days=MAX_DAYS):
        raise invalid("api.calendar.range_too_long", "to")
    zone = state.zone()
    async with state.db.read() as db:
        calendars = await service.list_calendars(db)
        if calendar_ids is not None:
            wanted = set(calendar_ids)
            calendars = [c for c in calendars if c.id in wanted]
        elif actor.is_kiosk:
            calendars = [c for c in calendars if c.visible_on_display]
        found = await occurrences(
            db,
            state.calendar,
            calendars,
            from_date,
            to_date,
            zone,
            include_cancelled=include_cancelled,
        )
    if member_ids:
        wanted_people = set(member_ids)
        found = [o for o in found if not o.member_ids or wanted_people & set(o.member_ids)]
    if overlays:
        extra = await overlay_occurrences(state.calendar, overlays, from_date, to_date, zone)
        found = sorted([*found, *extra], key=sort_key)
    return OccurrencesOut(
        from_date=from_date,
        to_date=to_date,
        timezone=zone.key,
        calendar_versions={c.id: c.version for c in calendars},
        occurrences=found,
    )


# ---- events ------------------------------------------------------------------------------------


@router.get("/events/{event_id}")
async def get_event(event_id: str, state: StateDep, actor: ActorDep) -> EventOut:
    async with state.db.read() as db:
        return await service.event_out(db, await service.get_master(db, event_id))


@router.get("/events/{event_id}/occurrences/{recurrence_id}")
async def get_occurrence(
    event_id: str, recurrence_id: str, state: StateDep, actor: ActorDep
) -> EventOut:
    """One occurrence's own words, people and reminders when it was changed on its own (R2)."""
    async with state.db.read() as db:
        return await service.event_at(db, await service.get_master(db, event_id), recurrence_id)


@router.post("/events", status_code=201)
async def post_event(body: EventCreate, state: StateDep, actor: ActorDep) -> ChangeOut:
    async with state.db.write() as tx:
        return await service.create_event(tx, body, _context(state, actor))


@router.patch("/events/{event_id}")
async def patch_event(
    event_id: str, body: EventUpdate, state: StateDep, actor: ActorDep
) -> ChangeOut:
    await _guard_change(state, actor)
    async with state.db.write() as tx:
        master = await service.get_master(tx.session, event_id)
        return await service.update_series(
            tx, master, body.model_copy(update={"scope": "all"}), _context(state, actor)
        )


@router.patch("/events/{event_id}/occurrences/{recurrence_id}")
async def patch_occurrence(
    event_id: str, recurrence_id: str, body: EventUpdate, state: StateDep, actor: ActorDep
) -> ChangeOut:
    await _guard_change(state, actor)
    async with state.db.write() as tx:
        master = await service.get_master(tx.session, event_id)
        return await service.update_occurrence(
            tx, master, recurrence_id, body, _context(state, actor)
        )


@router.delete("/events/{event_id}")
async def delete_event(event_id: str, state: StateDep, actor: ActorDep) -> ChangeOut:
    await _guard_change(state, actor)
    async with state.db.write() as tx:
        master = await service.get_master(tx.session, event_id)
        return await service.remove_series(tx, master, _context(state, actor))


@router.delete("/events/{event_id}/occurrences/{recurrence_id}")
async def delete_occurrence(
    event_id: str,
    recurrence_id: str,
    state: StateDep,
    actor: ActorDep,
    scope: Literal["this", "following", "all"] = "this",
) -> ChangeOut:
    await _guard_change(state, actor)
    async with state.db.write() as tx:
        master = await service.get_master(tx.session, event_id)
        return await service.remove_occurrence(
            tx, master, recurrence_id, scope, _context(state, actor)
        )


@router.post("/events/{event_id}/move")
async def move_event(event_id: str, body: MoveIn, state: StateDep, actor: ActorDep) -> ChangeOut:
    async with state.db.write() as tx:
        master = await service.get_master(tx.session, event_id)
        return await service.move(tx, master, body, _context(state, actor))


@router.post("/events/{event_id}/undo")
async def undo_event(
    event_id: str, state: StateDep, actor: ActorDep, body: UndoIn | None = None
) -> ChangeOut:
    async with state.db.write() as tx:
        return await service.undo(
            tx, event_id, body.revision_id if body else None, _context(state, actor)
        )


@router.post("/events/{event_id}/restore")
async def restore_event(event_id: str, state: StateDep, actor: ActorDep) -> ChangeOut:
    async with state.db.write() as tx:
        return await service.restore_event(tx, event_id, _context(state, actor))


@router.get("/removed")
async def get_removed(state: StateDep, actor: ActorDep) -> list[EventOut]:
    async with state.db.read() as db:
        return await service.recently_removed(db, state.clock.now())


@router.get("/search")
async def get_search(
    state: StateDep,
    actor: ActorDep,
    q: Annotated[str, Query(max_length=100)],
) -> list[SearchHit]:
    async with state.db.read() as db:
        return await service.search(db, q, state.clock.now(), state.zone().key)


@router.get("/rrule/describe")
async def describe_rule(
    state: StateDep,
    actor: ActorDep,
    rrule: Annotated[str, Query(max_length=500)],
    start: datetime | None = None,
    start_date: date | None = None,
    tzid: str | None = None,
) -> DescribeOut:
    """The sentence the editor shows for a repeat ("Every 2 weeks on Thu, until Dec 31")."""
    zone_key = tzid or state.zone().key
    load_zone(zone_key)
    timing, zone_key = resolve_timing(
        None, None, EventFields(start=start, start_date=start_date), zone_key
    )
    normalized = checked_rule(rrule, timing, zone_key)
    try:
        text = recurrence.describe(normalized, timing, zone_key)
        parts = recurrence.describe_parts(normalized, timing, zone_key)
    except RecurrenceError as exc:
        raise AppError(422, exc.code, exc.key) from None
    return DescribeOut(text=text, rrule=normalized, repeat=RepeatPartsOut.of(parts))
