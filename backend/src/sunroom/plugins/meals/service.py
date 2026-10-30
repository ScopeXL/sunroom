"""The week's meals and the saved meals (PLAN §9, §11.3; UX §4 "Meals room", §5 "Meals").

An entry is one meal in one spot: a day, a slot (Dinner unless the family plans more) and a
position (a second dinner the same day is position 1). One live entry holds a spot (a partial
unique index), so whatever takes a spot first moves the one there out: into Recently removed
when a meal replaces it (Undo puts it back), or into the moved one's old spot for Swap days.

Typing a meal keeps it as a saved meal, or counts one more use of the saved meal with that name,
so next week it's one tap; picking a saved meal brings its emoji and recipe link along. Saved
meals carry the ingredients "Add ingredients to Groceries" sends to Lists: the app does that
through the lists API, since a plugin never touches another's tables (ADR 0002).

Every change publishes ``meals.changed {days}`` from its write transaction: the days it touched,
none for a saved meal. Times come from ``ctx.now()``; "today" is the household's.
"""

from __future__ import annotations

import json
from collections.abc import Collection, Iterable, Mapping, Sequence
from datetime import date, datetime, timedelta
from typing import Any, cast
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from sunroom.auth.deps import Actor
from sunroom.calendar.schemas import OccurrenceOut
from sunroom.core.errors import AppError
from sunroom.db.types import new_id
from sunroom.domain.timeparts import to_local, week_start
from sunroom.plugins.context import PluginContext
from sunroom.plugins.meals.models import MealEntry, SavedMeal
from sunroom.plugins.meals.schemas import (
    SLOT_ORDER,
    CopyWeekIn,
    CopyWeekOut,
    EntryIn,
    EntryOut,
    EntrySaved,
    MealMoveIn,
    MealMoveOut,
    MealsRemovedOut,
    MealWeekOut,
    RemovedEntryOut,
    RemovedSavedOut,
    SavedMealIn,
    SavedMealOut,
    SavedMealPatch,
    SlotName,
)

EVENT = "meals.changed"
REMOVED_DAYS = 7  # Recently removed, then gone for good
WEEK_DAYS = 7  # what Copy last week copies
SAVED_MAX = 100  # the most saved meals one answer lists
PARKED = -1  # a position no entry keeps: one waits there while two swap
SLOT_RANK: dict[str, int] = {slot: rank for rank, slot in enumerate(SLOT_ORDER)}
IS_LIVE = MealEntry.deleted_at.is_(None)

Spot = tuple[date, str, int]  # day, slot, position


def entry_gone() -> AppError:
    return AppError(404, "not_found", "api.meals.meal_gone")


def saved_gone() -> AppError:
    return AppError(404, "not_found", "api.meals.saved_gone")


def already_saved() -> AppError:
    return AppError(409, "already_saved", "api.meals.already_saved")


def invalid(key: str, field: str) -> AppError:
    return AppError(422, "invalid", key, extra={"fields": [field]})


# ---- rules (pure) ------------------------------------------------------------------------------


def text_key(text: str) -> str:
    """Two meals (or two ingredients) are the same when their names match, ignoring case and
    outer spaces."""
    return text.strip().casefold()


def planned_slots(settings: Mapping[str, Any]) -> list[SlotName]:
    """The meals the family plans (the setting), in the day's order; Dinner when none are."""
    chosen = settings.get("slots") or ()
    return [slot for slot in SLOT_ORDER if slot in chosen] or ["dinner"]


def spot_order(entry: MealEntry) -> tuple[date, int, int]:
    """By day, then the day's order of meals (breakfast first), then position."""
    return entry.day, SLOT_RANK.get(entry.slot, len(SLOT_ORDER)), entry.position


def free_position(taken: Collection[int], wanted: int) -> int:
    """The first position from ``wanted`` on that no live entry holds."""
    position = wanted
    while position in taken:
        position += 1
    return position


def ingredients_of(raw: str | None) -> list[str]:
    """A saved meal's stored ingredients; anything unreadable reads as none."""
    try:
        value: object = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    items = cast("list[object]", value) if isinstance(value, list) else []
    return [item for item in items if isinstance(item, str)]


def ingredients_json(items: Iterable[str]) -> str:
    """Each ingredient once, as first written."""
    kept: dict[str, str] = {}
    for item in items:
        kept.setdefault(text_key(item), item.strip())
    return json.dumps(list(kept.values()))


def household_today(ctx: PluginContext) -> date:
    return to_local(ctx.now(), ctx.zone()).date()


def _given(sent: str | None, fallback: str | None = None) -> str | None:
    """A field a body may send: what it sent ("" for none), else ``fallback``."""
    if sent is None:
        return fallback
    return sent.strip() or None


def _iso(days: Iterable[date]) -> list[str]:
    return sorted({day.isoformat() for day in days})


# ---- shapes ------------------------------------------------------------------------------------


def entry_out(entry: MealEntry, ingredients: Sequence[str] = ()) -> EntryOut:
    return EntryOut.model_validate(
        {
            "id": entry.id,
            "day": entry.day,
            "slot": entry.slot,
            "position": entry.position,
            "text": entry.text,
            "emoji": entry.emoji,
            "recipe_url": entry.recipe_url,
            "note": entry.note,
            "member_id": entry.member_id,
            "saved_meal_id": entry.saved_meal_id,
            "ingredients": list(ingredients),
            "created_by_member_id": entry.created_by_member_id,
            "updated_at": entry.updated_at,
        }
    )


def saved_out(saved: SavedMeal) -> SavedMealOut:
    return SavedMealOut.model_validate(
        {
            "id": saved.id,
            "text": saved.text,
            "emoji": saved.emoji,
            "recipe_url": saved.recipe_url,
            "ingredients": ingredients_of(saved.ingredients_json),
            "use_count": saved.use_count,
            "last_used_at": saved.last_used_at,
        }
    )


async def _entry_out(session: AsyncSession, entry: MealEntry) -> EntryOut:
    """An entry with its saved meal's ingredients (an archived saved meal's too)."""
    saved = await session.get(SavedMeal, entry.saved_meal_id) if entry.saved_meal_id else None
    return entry_out(entry, ingredients_of(saved.ingredients_json) if saved else ())


async def _live_entry(session: AsyncSession, entry_id: str) -> MealEntry:
    entry = await session.get(MealEntry, entry_id)
    if entry is None or entry.deleted_at is not None:
        raise entry_gone()
    return entry


async def _in_spot(
    session: AsyncSession, spot: Spot, *, besides: str | None = None
) -> MealEntry | None:
    """The live entry holding ``spot``, other than ``besides``."""
    day, slot, position = spot
    query = select(MealEntry).where(
        IS_LIVE, MealEntry.day == day, MealEntry.slot == slot, MealEntry.position == position
    )
    if besides is not None:
        query = query.where(MealEntry.id != besides)
    return await session.scalar(query)


async def _live_saved(session: AsyncSession, saved_id: str) -> SavedMeal:
    saved = await session.get(SavedMeal, saved_id)
    if saved is None or saved.deleted_at is not None:
        raise saved_gone()
    return saved


async def _saved_named(
    session: AsyncSession, text: str, *, besides: str | None = None
) -> SavedMeal | None:
    """The live saved meal with this name, other than ``besides``. Matched here rather than in
    SQL, whose lower() folds only ASCII ("Crème brûlée")."""
    key = text_key(text)
    rows = await session.scalars(select(SavedMeal).where(SavedMeal.deleted_at.is_(None)))
    return next((row for row in rows if row.id != besides and text_key(row.text) == key), None)


def _use(saved: SavedMeal, now: datetime) -> None:
    """One more time the family makes it ("made 6 times")."""
    saved.use_count += 1
    saved.last_used_at = now


def _most_used(saved: SavedMeal) -> tuple[int, float, str, str]:
    """Most used first, then the most recently used, then by name."""
    last = saved.last_used_at.timestamp() if saved.last_used_at else float("-inf")
    return -saved.use_count, -last, text_key(saved.text), saved.id


# ---- reading -----------------------------------------------------------------------------------


async def week(ctx: PluginContext, start: date | None, days: int) -> MealWeekOut:
    """The live meals of ``days`` days from ``start``: a week for the Meals room, one day for
    Tonight. Without ``start``, this week (from the household's first day of the week)."""
    if start is None:
        home = await ctx.household.get()
        start = week_start(household_today(ctx), home.week_starts_on)
    after = start + timedelta(days=days)
    async with ctx.read() as session:
        rows = await session.execute(
            select(MealEntry, SavedMeal.ingredients_json)
            .outerjoin(SavedMeal, SavedMeal.id == MealEntry.saved_meal_id)
            .where(IS_LIVE, MealEntry.day >= start, MealEntry.day < after)
        )
        found = sorted(((entry, raw) for entry, raw in rows), key=lambda row: spot_order(row[0]))
    return MealWeekOut(
        start=start,
        days=days,
        slots=planned_slots(ctx.settings()),
        entries=[entry_out(entry, ingredients_of(raw)) for entry, raw in found],
    )


async def saved_meals(ctx: PluginContext, q: str | None) -> list[SavedMealOut]:
    """Saved meals, most used first; with ``q``, those whose name has it (ignoring case)."""
    wanted = text_key(q or "")
    async with ctx.read() as session:
        rows = list(await session.scalars(select(SavedMeal).where(SavedMeal.deleted_at.is_(None))))
    if wanted:
        rows = [row for row in rows if wanted in text_key(row.text)]
    rows.sort(key=_most_used)
    return [saved_out(row) for row in rows[:SAVED_MAX]]


async def removed(ctx: PluginContext) -> MealsRemovedOut:
    """Recently removed (7 days), newest first: meals taken off a day (or replaced by another),
    and saved meals archived."""
    since = ctx.now() - timedelta(days=REMOVED_DAYS)
    async with ctx.read() as session:
        entries = await session.scalars(
            select(MealEntry)
            .where(MealEntry.deleted_at >= since)
            .order_by(MealEntry.deleted_at.desc(), MealEntry.id.desc())
        )
        gone = [
            RemovedEntryOut.model_validate(
                {
                    "id": entry.id,
                    "day": entry.day,
                    "slot": entry.slot,
                    "text": entry.text,
                    "deleted_at": entry.deleted_at,
                }
            )
            for entry in entries
        ]
        archived = await session.scalars(
            select(SavedMeal)
            .where(SavedMeal.deleted_at >= since)
            .order_by(SavedMeal.deleted_at.desc(), SavedMeal.id.desc())
        )
        saved = [
            RemovedSavedOut.model_validate(
                {"id": row.id, "text": row.text, "deleted_at": row.deleted_at}
            )
            for row in archived
        ]
    return MealsRemovedOut(entries=gone, saved=saved)


# ---- entries -----------------------------------------------------------------------------------


async def _saved_for(
    session: AsyncSession,
    actor: Actor,
    body: EntryIn,
    entry: MealEntry | None,
    renamed: bool,
    now: datetime,
) -> SavedMeal | None:
    """The saved meal an entry links to after a PUT: the one picked (one archived since may stay
    linked, not be picked anew); for a new or changed text, the live one with that name or a new
    one made from this text, emoji and link; otherwise the link it has."""
    if body.saved_meal_id is not None:
        picked = await session.get(SavedMeal, body.saved_meal_id)
        kept = entry is not None and entry.saved_meal_id == body.saved_meal_id
        if picked is None or (picked.deleted_at is not None and not kept):
            raise saved_gone()
        return picked
    if entry is not None and not renamed:
        # The same meal on another day, with another cook or a note: its link stays.
        if entry.saved_meal_id is None:
            return None
        return await session.get(SavedMeal, entry.saved_meal_id)
    found = await _saved_named(session, body.text)
    if found is not None:
        return found
    made = SavedMeal(
        id=new_id(),
        text=body.text,
        emoji=_given(body.emoji),
        recipe_url=_given(body.recipe_url),
        ingredients_json="[]",
        use_count=0,
        last_used_at=None,
        created_by_member_id=actor.member_id,
        created_at=now,
        updated_at=now,
        deleted_at=None,
    )
    session.add(made)
    await session.flush()  # in the table before an entry points at it
    return made


async def save_entry(ctx: PluginContext, actor: Actor, body: EntryIn) -> EntrySaved:
    """PUT meals/entries: a meal into a spot, new (no ``id``) or changed (its spot may change
    too). A live entry already in that spot is removed and comes back as ``replaced``, for Undo.

    A meal linked to a saved meal anew takes its emoji and recipe link unless the body sends its
    own ("" for none). Making an entry, or changing which meal it is, counts a use; a new day,
    cook or note doesn't. The cook must be someone in the family now (a cook archived since may
    stay on an entry that had them)."""
    now = ctx.now()
    active = {member.id for member in await ctx.members.active()}
    async with ctx.write() as tx:
        session = tx.session
        entry = await _live_entry(session, body.id) if body.id is not None else None
        cook = body.member_id
        if cook is not None and cook not in active and (entry is None or entry.member_id != cook):
            raise invalid("api.meals.not_in_family", "member_id")
        renamed = entry is None or text_key(entry.text) != text_key(body.text)
        saved = await _saved_for(session, actor, body, entry, renamed, now)
        anew = saved is not None and (entry is None or entry.saved_meal_id != saved.id)
        spot: Spot = (body.day, body.slot, body.position)
        replaced = await _in_spot(session, spot, besides=entry.id if entry else None)
        if replaced is not None:
            replaced.deleted_at = now
            replaced.updated_at = now
            await session.flush()  # the spot is free before anything moves into it
        days = {body.day} if entry is None else {body.day, entry.day}
        if entry is None:
            entry = MealEntry(
                id=new_id(),
                source_url=None,
                created_by_member_id=actor.member_id,
                created_at=now,
                deleted_at=None,
            )
            session.add(entry)
        entry.day, entry.slot, entry.position = spot
        entry.text = body.text
        entry.emoji = _given(body.emoji, saved.emoji if saved and anew else None)
        entry.recipe_url = _given(body.recipe_url, saved.recipe_url if saved and anew else None)
        entry.note = _given(body.note)
        entry.member_id = cook
        entry.saved_meal_id = saved.id if saved else None
        entry.updated_at = now
        if saved is not None and renamed:
            _use(saved, now)
        await session.flush()
        tx.publish(EVENT, {"days": _iso(days)})
        return EntrySaved(
            entry=entry_out(entry, ingredients_of(saved.ingredients_json) if saved else ()),
            replaced=await _entry_out(session, replaced) if replaced else None,
        )


async def remove_entry(ctx: PluginContext, entry_id: str) -> None:
    """Off its day, into Recently removed."""
    now = ctx.now()
    async with ctx.write() as tx:
        entry = await _live_entry(tx.session, entry_id)
        entry.deleted_at = now
        entry.updated_at = now
        tx.publish(EVENT, {"days": _iso([entry.day])})


async def restore_entry(ctx: PluginContext, entry_id: str) -> EntryOut:
    """Undo, and Put back in Recently removed: the meal goes back to its spot or, when another
    meal holds it now, to the next free position of that day and meal."""
    now = ctx.now()
    async with ctx.write() as tx:
        entry = await tx.session.get(MealEntry, entry_id)
        if entry is None:
            raise entry_gone()
        if entry.deleted_at is not None:
            taken = set(
                await tx.session.scalars(
                    select(MealEntry.position).where(
                        IS_LIVE, MealEntry.day == entry.day, MealEntry.slot == entry.slot
                    )
                )
            )
            entry.position = free_position(taken, entry.position)
            entry.deleted_at = None
            entry.updated_at = now
        tx.publish(EVENT, {"days": _iso([entry.day])})
        return await _entry_out(tx.session, entry)


async def move_entry(ctx: PluginContext, entry_id: str, body: MealMoveIn) -> MealMoveOut:
    """Move a meal to another day (and meal), keeping its position. One already there swaps into
    the moved one's old spot ("Swap days"): the moved one waits on a parked position meanwhile,
    since two live entries never share a spot, not even inside one transaction."""
    now = ctx.now()
    async with ctx.write() as tx:
        session = tx.session
        entry = await _live_entry(session, entry_id)
        old: Spot = (entry.day, entry.slot, entry.position)
        new: Spot = (body.day, body.slot or entry.slot, entry.position)
        swapped = None
        if new != old:
            swapped = await _in_spot(session, new)
            if swapped is not None:
                entry.position = PARKED
                await session.flush()
                swapped.day, swapped.slot, swapped.position = old
                swapped.updated_at = now
                await session.flush()
            entry.day, entry.slot, entry.position = new
            entry.updated_at = now
            await session.flush()
        tx.publish(EVENT, {"days": _iso([old[0], new[0]])})
        return MealMoveOut(
            moved=await _entry_out(session, entry),
            swapped=await _entry_out(session, swapped) if swapped else None,
        )


async def copy_week(ctx: PluginContext, actor: Actor, body: CopyWeekIn) -> CopyWeekOut:
    """Copy last week (or any week): each of the seven days' meals goes to the same day of the
    target week, in the same meal and position, unless that spot is filled (counted in
    ``skipped``). A copy keeps the text, emoji, recipe link, cook (if still in the family) and
    saved meal, counting a use; not the note."""
    if body.from_start == body.to_start:
        raise invalid("api.meals.pick_another_week", "to_start")
    now = ctx.now()
    active = {member.id for member in await ctx.members.active()}
    shift = body.to_start - body.from_start
    span = timedelta(days=WEEK_DAYS)
    async with ctx.write() as tx:
        session = tx.session
        source = sorted(
            await session.scalars(
                select(MealEntry).where(
                    IS_LIVE,
                    MealEntry.day >= body.from_start,
                    MealEntry.day < body.from_start + span,
                )
            ),
            key=spot_order,
        )
        filled: set[Spot] = {
            (entry.day, entry.slot, entry.position)
            for entry in await session.scalars(
                select(MealEntry).where(
                    IS_LIVE, MealEntry.day >= body.to_start, MealEntry.day < body.to_start + span
                )
            )
        }
        made: list[MealEntry] = []
        skipped = 0
        for entry in source:
            spot: Spot = (entry.day + shift, entry.slot, entry.position)
            if spot in filled:
                skipped += 1
                continue
            filled.add(spot)
            copy = MealEntry(
                id=new_id(),
                day=spot[0],
                slot=entry.slot,
                position=entry.position,
                text=entry.text,
                emoji=entry.emoji,
                recipe_url=entry.recipe_url,
                note=None,
                member_id=entry.member_id if entry.member_id in active else None,
                saved_meal_id=entry.saved_meal_id,
                source_url=None,
                created_by_member_id=actor.member_id,
                created_at=now,
                updated_at=now,
                deleted_at=None,
            )
            session.add(copy)
            made.append(copy)
        linked = [copy.saved_meal_id for copy in made if copy.saved_meal_id is not None]
        if linked:
            uses = {
                row.id: row
                for row in await session.scalars(select(SavedMeal).where(SavedMeal.id.in_(linked)))
            }
            for saved_id in linked:
                _use(uses[saved_id], now)
        tx.publish(EVENT, {"days": _iso(copy.day for copy in made)})
        return CopyWeekOut(ids=[copy.id for copy in made], skipped=skipped)


# ---- saved meals -------------------------------------------------------------------------------


async def add_saved(ctx: PluginContext, actor: Actor, body: SavedMealIn) -> SavedMealOut:
    """New saved meal (the library's button); a name that's saved already is refused."""
    now = ctx.now()
    async with ctx.write() as tx:
        if await _saved_named(tx.session, body.text) is not None:
            raise already_saved()
        saved = SavedMeal(
            id=new_id(),
            text=body.text,
            emoji=_given(body.emoji),
            recipe_url=_given(body.recipe_url),
            ingredients_json=ingredients_json(body.ingredients),
            use_count=0,
            last_used_at=None,
            created_by_member_id=actor.member_id,
            created_at=now,
            updated_at=now,
            deleted_at=None,
        )
        tx.session.add(saved)
        tx.publish(EVENT, {"days": []})
        return saved_out(saved)


async def change_saved(ctx: PluginContext, saved_id: str, body: SavedMealPatch) -> SavedMealOut:
    """Only what's sent changes; an empty emoji or link clears it. Meals already on a day keep
    their own text, emoji and link."""
    now = ctx.now()
    async with ctx.write() as tx:
        saved = await _live_saved(tx.session, saved_id)
        if body.text is not None:
            if await _saved_named(tx.session, body.text, besides=saved.id) is not None:
                raise already_saved()
            saved.text = body.text
        if body.emoji is not None:
            saved.emoji = _given(body.emoji)
        if body.recipe_url is not None:
            saved.recipe_url = _given(body.recipe_url)
        if body.ingredients is not None:
            saved.ingredients_json = ingredients_json(body.ingredients)
        saved.updated_at = now
        tx.publish(EVENT, {"days": []})
        return saved_out(saved)


async def archive_saved(ctx: PluginContext, saved_id: str) -> None:
    """Archive: off the library, into Recently removed. Meals on a day keep their link (and
    ingredients) until it's gone for good."""
    now = ctx.now()
    async with ctx.write() as tx:
        saved = await _live_saved(tx.session, saved_id)
        saved.deleted_at = now
        saved.updated_at = now
        tx.publish(EVENT, {"days": []})


async def restore_saved(ctx: PluginContext, saved_id: str) -> SavedMealOut:
    """Back into the library, unless a meal with its name was saved meanwhile."""
    now = ctx.now()
    async with ctx.write() as tx:
        saved = await tx.session.get(SavedMeal, saved_id)
        if saved is None:
            raise saved_gone()
        if saved.deleted_at is not None:
            if await _saved_named(tx.session, saved.text) is not None:
                raise already_saved()
            saved.deleted_at = None
            saved.updated_at = now
        tx.publish(EVENT, {"days": []})
        return saved_out(saved)


# ---- the calendar overlay ----------------------------------------------------------------------


def _occurrence(entry: MealEntry) -> OccurrenceOut:
    """A meal as an all-day chip at the top of its day, in the cook's color."""
    return OccurrenceOut(
        key=f"meals|{entry.id}",
        event_id=None,
        recurrence_id=None,
        calendar_id=None,
        title=f"{entry.emoji} {entry.text}" if entry.emoji else entry.text,
        location="",
        all_day=True,
        start_utc=None,
        end_utc=None,
        start_local=None,
        end_local=None,
        start_date=entry.day,
        end_date=entry.day + timedelta(days=1),
        member_ids=[entry.member_id] if entry.member_id else [],
        color=None,
        calendar_color=None,
        is_recurring=False,
        is_override=False,
        read_only=True,
        source="meals",
        status="confirmed",
        overlay="meals",
        reminders=[],
        version=0,
    )


async def overlay(
    ctx: PluginContext, start: date, end: date, zone: ZoneInfo
) -> list[OccurrenceOut]:
    """``occurrences?overlays=meals``: each live meal in [start, end) of the kinds the family
    shows on the calendar ("Show dinner on the calendar", one switch per meal it plans); none
    by default. A meal the family no longer plans isn't drawn, whatever was chosen before."""
    settings = ctx.settings()
    chosen: Sequence[str] = settings.get("calendar_slots") or ()
    shown = [slot for slot in planned_slots(settings) if slot in chosen]
    if not shown:
        return []
    async with ctx.read() as session:
        meals = await session.scalars(
            select(MealEntry)
            .where(
                IS_LIVE,
                MealEntry.slot.in_(shown),
                MealEntry.day >= start,
                MealEntry.day < end,
            )
            .order_by(MealEntry.day, MealEntry.position, MealEntry.id)
        )
        return [_occurrence(entry) for entry in meals]


# ---- the job (hourly) --------------------------------------------------------------------------


async def prune(ctx: PluginContext) -> None:
    """Gone for good: meals removed more than REMOVED_DAYS ago, and saved meals archived that
    long ago (meals still on a day keep their text, emoji and link; only the link to the saved
    meal goes)."""
    before = ctx.now() - timedelta(days=REMOVED_DAYS)
    async with ctx.write() as tx:
        session = tx.session
        days = set(
            await session.scalars(select(MealEntry.day).where(MealEntry.deleted_at < before))
        )
        archived = list(
            await session.scalars(select(SavedMeal.id).where(SavedMeal.deleted_at < before))
        )
        if not days and not archived:
            return
        await session.execute(delete(MealEntry).where(MealEntry.deleted_at < before))
        if archived:
            linked = MealEntry.saved_meal_id.in_(archived)
            days |= set(await session.scalars(select(MealEntry.day).where(IS_LIVE, linked)))
            await session.execute(update(MealEntry).where(linked).values(saved_meal_id=None))
            await session.execute(delete(SavedMeal).where(SavedMeal.id.in_(archived)))
        tx.publish(EVENT, {"days": _iso(days)})
