"""Countdowns and birthdays (PLAN §9, §11.3; UX §4 "Countdowns room", §8).

A countdown is a day the family looks forward to. A one-off counts down to its date and leaves
for Recently removed the day after (the hourly ``tidy``); a yearly one counts down to its next
date every year, its ``date`` being the first. Birthdays aren't rows: while the ``birthdays``
setting is on, each person's birthday in Family comes round by itself. The day arithmetic is
domain/countdowns.py, and "today" is the household's.

A countdown with ``show_on_display`` off is a surprise: the wall screen never lists it, and it
stays off the calendar. Every change publishes ``countdowns.changed {id}`` from its write
transaction.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import ColumnElement, delete, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from sunroom.auth.deps import Actor
from sunroom.calendar.schemas import OccurrenceOut
from sunroom.core.errors import AppError
from sunroom.db.types import new_id
from sunroom.domain.countdowns import days_until, next_birthday, next_date, turning, yearly_days
from sunroom.domain.timeparts import to_local
from sunroom.plugins.context import MemberView, PluginContext
from sunroom.plugins.countdowns.models import Countdown
from sunroom.plugins.countdowns.schemas import (
    CountdownIn,
    CountdownOut,
    CountdownPatch,
    RemovedCountdownOut,
    UpcomingListOut,
    UpcomingOut,
)

EVENT = "countdowns.changed"
OVERLAY = "countdowns"
REMOVED_DAYS = 7  # Recently removed, then gone for good
DAY = timedelta(days=1)


def countdown_gone() -> AppError:
    return AppError(404, "not_found", "That countdown isn't here any more.")


def _invalid(message: str, field: str) -> AppError:
    return AppError(422, "invalid", message, extra={"fields": [field]})


def day_passed() -> AppError:
    return _invalid("Pick a day that hasn't passed.", "date")


def not_in_family() -> AppError:
    return _invalid("That person isn't in the family.", "member_id")


# ---- rules -------------------------------------------------------------------------------------


def household_today(ctx: PluginContext) -> date:
    """The household's date now: a countdown's day is the household's, not UTC's."""
    return to_local(ctx.now(), ctx.zone()).date()


def birthdays_on(ctx: PluginContext) -> bool:
    return bool(ctx.settings().get("birthdays", True))


def birthdays_within(ctx: PluginContext) -> int | None:
    """How many days ahead Coming Up shows a birthday (Birthdays in Coming Up, ADR 0032);
    None: any time."""
    value = str(ctx.settings().get("birthdays_within", "30"))
    return None if value == "any" else int(value)


def birthday_title(name: str) -> str:
    return f"{name}'s birthday"


def birthday_next(birthday: date, today: date) -> date:
    """A person's next birthday. One set after today (a baby on the way) first comes round on
    the day itself, never before."""
    return next_birthday(birthday, max(today, birthday))


def days_in(first: date, *, yearly: bool, start: date, end: date) -> list[date]:
    """The days in [start, end) a countdown falls on: a one-off on its own, a yearly one on each
    year's, never before its first."""
    if not yearly:
        return [first] if start <= first < end else []
    return yearly_days(first, start, end)


def _shown_to(actor: Actor) -> ColumnElement[bool]:
    """What a device may list: everything, except that the wall screen never lists a surprise."""
    return Countdown.show_on_display.is_(True) if actor.is_kiosk else true()


async def _active_ids(ctx: PluginContext) -> set[str]:
    """Who can be picked for a countdown: the people in the household now (not archived)."""
    return {member.id for member in await ctx.members.active()}


def _reschedule(row: Countdown, body: CountdownPatch, today: date) -> None:
    """A new day or repeat. A one-off can't move to a day that has passed; one that stops
    repeating, its day sent unchanged or not at all, keeps counting down to the date it showed."""
    yearly = row.repeat_yearly if body.repeat_yearly is None else body.repeat_yearly
    if body.date is not None and body.date != row.date:
        if not yearly and body.date < today:
            raise day_passed()
        row.date = body.date
    elif row.repeat_yearly and not yearly:
        row.date = next_date(row.date, yearly=True, today=today) or row.date
    row.repeat_yearly = yearly


# ---- shapes ------------------------------------------------------------------------------------


def countdown_out(row: Countdown) -> CountdownOut:
    return CountdownOut.model_validate(row, from_attributes=True)


def _countdown_item(row: Countdown, on: date, today: date) -> UpcomingOut:
    return UpcomingOut.model_validate(
        {
            "key": f"countdown:{row.id}",
            "kind": "countdown",
            "countdown_id": row.id,
            "title": row.title,
            "emoji": row.emoji,
            "color": row.color,
            "member_id": row.member_id,
            "date": on,
            "time": row.time,
            "days": days_until(on, today),
            "turning": None,
            "show_on_display": row.show_on_display,
        }
    )


def _birthday_item(member: MemberView, birthday: date, today: date) -> UpcomingOut:
    on = birthday_next(birthday, today)
    return UpcomingOut.model_validate(
        {
            "key": f"birthday:{member.id}",
            "kind": "birthday",
            "countdown_id": None,
            "title": birthday_title(member.name),
            "emoji": None,
            "color": None,  # the person's own
            "member_id": member.id,
            "date": on,
            "time": None,
            "days": days_until(on, today),
            "turning": turning(birthday, on),
            "show_on_display": True,
        }
    )


def _soonest(item: UpcomingOut) -> tuple[date, bool, str, str]:
    """By day; on the same day birthdays first, then by title."""
    return item.date, item.kind != "birthday", item.title.casefold(), item.key


def _occurrence(
    of: str, on: date, title: str, member_id: str | None, color: str | None
) -> OccurrenceOut:
    return OccurrenceOut.model_validate(
        {
            "key": f"{OVERLAY}|{of}|{on.isoformat()}",
            "event_id": None,
            "recurrence_id": None,
            "calendar_id": None,
            "title": title,
            "location": "",
            "all_day": True,
            "start_utc": None,
            "end_utc": None,
            "start_local": None,
            "end_local": None,
            "start_date": on,
            "end_date": on + DAY,
            "member_ids": [member_id] if member_id else [],
            "color": color,
            "calendar_color": None,
            "is_recurring": False,
            "is_override": False,
            "read_only": True,
            "source": OVERLAY,
            "status": "confirmed",
            "overlay": OVERLAY,
            "reminders": [],
            "version": 0,
        }
    )


async def _listed(session: AsyncSession, actor: Actor) -> Sequence[Countdown]:
    """The live countdowns this device may list."""
    query = select(Countdown).where(Countdown.deleted_at.is_(None), _shown_to(actor))
    return (await session.scalars(query)).all()


async def _live(session: AsyncSession, countdown_id: str) -> Countdown:
    row = await session.get(Countdown, countdown_id)
    if row is None or row.deleted_at is not None:
        raise countdown_gone()
    return row


# ---- reading -----------------------------------------------------------------------------------


async def upcoming(
    ctx: PluginContext,
    actor: Actor,
    *,
    day: date | None = None,
    limit: int | None = None,
    include_birthdays: bool = True,
    coming_up: bool = False,
) -> UpcomingListOut:
    """What's coming up from ``day`` (the household's today), soonest first: the countdowns
    still to come, and each person's next birthday while the setting is on. For the Today
    panel's Coming Up (``coming_up``) a birthday shows only within Birthdays in Coming Up's
    window, while a countdown always does: someone chose to count down to it (ADR 0032). The
    Countdowns room asks without it, and lists every birthday."""
    today = day or household_today(ctx)
    async with ctx.read() as session:
        rows = await _listed(session, actor)
    items: list[UpcomingOut] = []
    for row in rows:
        on = next_date(row.date, yearly=row.repeat_yearly, today=today)
        if on is not None:
            items.append(_countdown_item(row, on, today))
    if include_birthdays and birthdays_on(ctx):
        window = birthdays_within(ctx) if coming_up else None
        for member in await ctx.members.active():
            if member.birthday is not None:
                item = _birthday_item(member, member.birthday, today)
                if window is None or item.days <= window:
                    items.append(item)
    items.sort(key=_soonest)
    return UpcomingListOut(today=today, items=items if limit is None else items[:limit])


async def all_countdowns(ctx: PluginContext, actor: Actor) -> list[CountdownOut]:
    """Every live countdown, soonest next date first. A one-off whose day has passed, until the
    hourly tidy takes it, comes last."""
    today = household_today(ctx)
    async with ctx.read() as session:
        rows = await _listed(session, actor)

    def soonest(row: Countdown) -> tuple[bool, date, str, str]:
        on = next_date(row.date, yearly=row.repeat_yearly, today=today)
        return on is None, on or row.date, row.title.casefold(), row.id

    return [countdown_out(row) for row in sorted(rows, key=soonest)]


async def removed(ctx: PluginContext, actor: Actor) -> list[RemovedCountdownOut]:
    """Recently removed (7 days), newest first."""
    since = ctx.now() - timedelta(days=REMOVED_DAYS)
    async with ctx.read() as session:
        rows = await session.scalars(
            select(Countdown)
            .where(Countdown.deleted_at >= since, _shown_to(actor))
            .order_by(Countdown.deleted_at.desc(), Countdown.id.desc())
        )
        return [
            RemovedCountdownOut(
                id=row.id, title=row.title, date=row.date, deleted_at=row.deleted_at
            )
            for row in rows
            if row.deleted_at is not None
        ]


# ---- adding and changing -----------------------------------------------------------------------


async def add_countdown(ctx: PluginContext, actor: Actor, body: CountdownIn) -> CountdownOut:
    """Anyone may add one. It's made by the phone's person, or whoever tapped on the wall."""
    if not body.repeat_yearly and body.date < household_today(ctx):
        raise day_passed()
    if body.member_id is not None and body.member_id not in await _active_ids(ctx):
        raise not_in_family()
    now = ctx.now()
    async with ctx.write() as tx:
        row = Countdown(
            id=new_id(),
            title=body.title,
            emoji=body.emoji or None,
            color=body.color,
            date=body.date,
            time=body.time,
            repeat_yearly=body.repeat_yearly,
            member_id=body.member_id,
            show_on_display=body.show_on_display,
            created_by_member_id=actor.member_id,
            created_at=now,
            updated_at=now,
            deleted_at=None,
        )
        tx.session.add(row)
        tx.publish(EVENT, {"id": row.id})
        return countdown_out(row)


async def change_countdown(
    ctx: PluginContext, countdown_id: str, body: CountdownPatch
) -> CountdownOut:
    """Only what's sent changes; an empty emoji and the clear switches take things off. What's
    sent unchanged isn't checked again (an editor sends the whole form): someone archived since
    stays on their countdown, but can't be picked anew."""
    picked = None if body.clear_member else body.member_id
    active = await _active_ids(ctx) if picked is not None else set[str]()
    today = household_today(ctx)
    async with ctx.write() as tx:
        row = await _live(tx.session, countdown_id)
        if picked is not None and picked != row.member_id and picked not in active:
            raise not_in_family()
        _reschedule(row, body, today)
        if body.title is not None:
            row.title = body.title
        if body.emoji is not None:
            row.emoji = body.emoji or None
        if body.clear_color:
            row.color = None
        elif body.color is not None:
            row.color = body.color
        if body.clear_time:
            row.time = None
        elif body.time is not None:
            row.time = body.time
        if body.clear_member:
            row.member_id = None
        elif picked is not None:
            row.member_id = picked
        if body.show_on_display is not None:
            row.show_on_display = body.show_on_display
        row.updated_at = ctx.now()
        tx.publish(EVENT, {"id": row.id})
        return countdown_out(row)


async def remove_countdown(ctx: PluginContext, countdown_id: str) -> None:
    """Into Recently removed for 7 days."""
    async with ctx.write() as tx:
        row = await _live(tx.session, countdown_id)
        row.deleted_at = row.updated_at = ctx.now()
        tx.publish(EVENT, {"id": row.id})


async def restore_countdown(ctx: PluginContext, countdown_id: str) -> CountdownOut:
    """Undo and Put back. One whose day has passed leaves again at the next tidy."""
    async with ctx.write() as tx:
        row = await tx.session.get(Countdown, countdown_id)
        if row is None:
            raise countdown_gone()
        if row.deleted_at is not None:
            row.deleted_at = None
            row.updated_at = ctx.now()
            tx.publish(EVENT, {"id": row.id})
        return countdown_out(row)


# ---- the calendar and the hourly job ----------------------------------------------------------


async def overlay(
    ctx: PluginContext, start: date, end: date, zone: ZoneInfo
) -> list[OccurrenceOut]:
    """The calendar's countdowns (PLAN §7.6), all day and read only: each one not kept off the
    wall, on its days in [start, end). Birthdays are the core's own overlay (calendar/birthdays.py,
    ADR 0028): Countdowns counts them down but doesn't draw them, so nothing shows twice."""
    async with ctx.read() as session:
        rows = (
            await session.scalars(
                select(Countdown).where(
                    Countdown.deleted_at.is_(None),
                    Countdown.show_on_display.is_(True),
                    Countdown.date < end,  # nothing comes round before its first date
                    or_(Countdown.repeat_yearly.is_(True), Countdown.date >= start),
                )
            )
        ).all()
    return [
        _occurrence(row.id, on, row.title, row.member_id, row.color)
        for row in rows
        for on in days_in(row.date, yearly=row.repeat_yearly, start=start, end=end)
    ]


async def tidy(ctx: PluginContext) -> None:
    """Hourly: a one-off whose day has passed leaves for Recently removed ("the next day", UX
    §4), and what was removed over 7 days ago is gone for good."""
    now = ctx.now()
    today = household_today(ctx)
    async with ctx.write() as tx:
        passed = (
            await tx.session.scalars(
                select(Countdown).where(
                    Countdown.deleted_at.is_(None),
                    Countdown.repeat_yearly.is_(False),
                    Countdown.date < today,
                )
            )
        ).all()
        for row in passed:
            row.deleted_at = row.updated_at = now
        stale = Countdown.deleted_at < now - timedelta(days=REMOVED_DAYS)
        gone = list((await tx.session.scalars(select(Countdown.id).where(stale))).all())
        if gone:
            await tx.session.execute(delete(Countdown).where(Countdown.id.in_(gone)))
        for countdown_id in sorted({row.id for row in passed} | set(gone)):
            tx.publish(EVENT, {"id": countdown_id})
