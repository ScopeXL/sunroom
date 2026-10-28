"""What the chores, rewards and routines services share (ADR 0019, ADR 0025): the plugin's
switches, the household's day, who gets the credit for a tap, the chores as the domain reads
them, and star balances.

Balances and streaks are computed, never stored: domain/points.py adds the stars up and
domain/chores.py walks the rules for a streak.
"""

from __future__ import annotations

import json
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import cast
from zoneinfo import ZoneInfo

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from sunroom.auth.deps import Actor, parent_refusal
from sunroom.core.errors import AppError
from sunroom.domain import points
from sunroom.domain.chores import STREAK_DAYS, Completion, Rule, streak
from sunroom.domain.timeparts import day_bounds, to_local, week_start
from sunroom.plugins.chores.models import (
    Chore,
    ChoreCompletion,
    PointAdjustment,
    Redemption,
    RoutineFinish,
)
from sunroom.plugins.chores.schemas import CompletionOut, StarsOut
from sunroom.plugins.context import MemberView, PluginContext

DAY = timedelta(days=1)
WEEK = timedelta(days=7)
KID = "kid"


# ---- errors ------------------------------------------------------------------------------------


def invalid(message: str, *fields: str) -> AppError:
    return AppError(422, "invalid", message, extra={"fields": list(fields)})


def unknown_member() -> AppError:
    return AppError(422, "unknown_member", "That person isn't in the household.")


def gone(what: str) -> AppError:
    return AppError(404, "not_found", f"That {what} isn't here any more.")


def possessive(name: str) -> str:
    return f"{name}'s"


# ---- the switches and the household's day -----------------------------------------------------


@dataclass(frozen=True, slots=True)
class Switches:
    stars: bool
    rewards: bool
    routines: bool
    approval: bool  # a parent checks finished chores, unless a chore says otherwise


def switches(ctx: PluginContext) -> Switches:
    values = ctx.settings()
    return Switches(
        stars=bool(values.get("stars", True)),
        rewards=bool(values.get("rewards", True)),
        routines=bool(values.get("routines", True)),
        approval=bool(values.get("approval", False)),
    )


@dataclass(frozen=True, slots=True)
class Now:
    """The moment a request is answered, in the household's terms."""

    utc: datetime
    zone: ZoneInfo
    today: date
    clock: str  # the household's wall time, "HH:MM"
    week_starts_on: int  # 0 Monday … 6 Sunday

    @property
    def week_first(self) -> date:
        return week_start(self.today, self.week_starts_on)

    def day_of(self, instant: datetime) -> date:
        """The household day an instant falls on."""
        return to_local(instant, self.zone).date()


async def now_of(ctx: PluginContext) -> Now:
    utc, zone = ctx.now(), ctx.zone()
    local = to_local(utc, zone)
    home = await ctx.household.get()
    return Now(utc, zone, local.date(), local.strftime("%H:%M"), home.week_starts_on)


# ---- who gets the credit -----------------------------------------------------------------------


def credited(actor: Actor, member_id: str | None, members: Sequence[MemberView]) -> MemberView:
    """Who a tap is for (ADR 0025). The wall screen: the person it says tapped, whatever the body
    says. A phone: its person, or anyone a parent's phone names."""
    known = {member.id: member for member in members}
    if actor.is_kiosk:
        tapped = known.get(actor.member_id or "")
        if tapped is None:
            raise AppError(422, "who_needed", "Who did it? Tap a name first.")
        return tapped
    if member_id is not None and member_id != actor.member_id:
        if not actor.is_parent:
            raise parent_refusal(actor)
        named = known.get(member_id)
        if named is None:
            raise unknown_member()
        return named
    person = known.get(actor.member_id or "")
    if person is None:
        raise AppError(422, "who_needed", "Pick who's using this device first.")
    return person


# ---- stored lists ------------------------------------------------------------------------------


def _json_list(raw: str | None) -> list[object]:
    try:
        value: object = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    return cast("list[object]", value) if isinstance(value, list) else []


def member_ids(raw: str | None) -> list[str]:
    return [item for item in _json_list(raw) if isinstance(item, str)]


def dates(raw: str | None) -> list[date]:
    found: list[date] = []
    for item in _json_list(raw):
        if isinstance(item, str):
            try:
                found.append(date.fromisoformat(item))
            except ValueError:
                continue
    return found


def weekdays(raw: str | None) -> list[int]:
    return sorted({item for item in _json_list(raw) if isinstance(item, int) and 0 <= item <= 6})


def dates_json(days: Collection[date]) -> str:
    return json.dumps(sorted(day.isoformat() for day in days))


# ---- chores as the domain reads them -----------------------------------------------------------


def rule_of(chore: Chore, active: Collection[str]) -> Rule:
    """A chore as a rule. People no longer in the household drop out of it."""
    return Rule(
        id=chore.id,
        start_date=chore.start_date,
        rrule=chore.rrule,
        mode=chore.assignee_mode,
        assignees=tuple(m for m in member_ids(chore.assignee_member_ids_json) if m in active),
        rotation_index=chore.rotation_index,
        skipped=frozenset(dates(chore.skipped_dates_json)),
    )


@dataclass(frozen=True, slots=True)
class Tick:
    """A completion, read light: the due lists and streaks read thousands of these."""

    id: str
    chore_id: str
    due_date: date
    member_id: str
    completed_at: datetime
    points_awarded: int
    status: str


def completion_out(row: ChoreCompletion | Tick) -> CompletionOut:
    return CompletionOut.model_validate(
        {
            "id": row.id,
            "chore_id": row.chore_id,
            "due_date": row.due_date,
            "member_id": row.member_id,
            "completed_at": row.completed_at,
            "points_awarded": row.points_awarded,
            "status": row.status,
        }
    )


@dataclass(frozen=True, slots=True)
class Book:
    """The chores that are on, in the order they were made, and their completions."""

    chores: list[Chore]
    rules: list[Rule]
    ticks: dict[tuple[str, date, str], Tick]  # by chore, due date and person (UNIQUE)
    completions: list[Completion]

    def tick(self, completion: Completion) -> Tick:
        return self.ticks[completion.chore_id, completion.due_date, completion.member_id]


async def on_chores(session: AsyncSession) -> list[Chore]:
    """Chores that are on (not paused, not removed), in the order they were made."""
    return list(
        await session.scalars(
            select(Chore)
            .where(Chore.deleted_at.is_(None), Chore.active.is_(True))
            .order_by(Chore.created_at, Chore.id)
        )
    )


async def load_book(
    session: AsyncSession, now: Now, active: Collection[str], since: date, until: date
) -> Book:
    """The chores that are on, with the completions of repeating ones due in [since, until) and
    every completion of one-day chores (they carry over until done, from any earlier day)."""
    chores = await on_chores(session)
    rules = [rule_of(chore, active) for chore in chores]
    ticks: dict[tuple[str, date, str], Tick] = {}
    if chores:
        ids = [chore.id for chore in chores]
        one_day = [chore.id for chore in chores if not chore.rrule]
        rows = await session.execute(
            select(
                ChoreCompletion.id,
                ChoreCompletion.chore_id,
                ChoreCompletion.due_date,
                ChoreCompletion.member_id,
                ChoreCompletion.completed_at,
                ChoreCompletion.points_awarded,
                ChoreCompletion.status,
            ).where(
                ChoreCompletion.chore_id.in_(ids),
                or_(
                    and_(ChoreCompletion.due_date >= since, ChoreCompletion.due_date < until),
                    ChoreCompletion.chore_id.in_(one_day),
                ),
            )
        )
        for row_id, chore_id, due_date, member_id, completed_at, awarded, status in rows:
            ticks[chore_id, due_date, member_id] = Tick(
                row_id, chore_id, due_date, member_id, completed_at, awarded, status
            )
    completions = [
        Completion(t.chore_id, t.due_date, t.member_id, now.day_of(t.completed_at), t.status)
        for t in ticks.values()
    ]
    return Book(chores, rules, ticks, completions)


async def streak_book(session: AsyncSession, now: Now, active: Collection[str]) -> Book:
    """Enough of the book for streaks: the last STREAK_DAYS days."""
    return await load_book(session, now, active, now.today - STREAK_DAYS * DAY, now.today + DAY)


def streak_of(book: Book, member_id: str, today: date) -> int:
    """Days in a row (domain/chores.py), walking only the rules that can be theirs."""
    theirs = [rule for rule in book.rules if member_id in rule.assignees]
    return streak(theirs, book.completions, member_id, today) if theirs else 0


# ---- stars -------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Ledger:
    """What people earned and spent, added up per person and status: ``balance`` only adds, so
    one row each stands for all of theirs."""

    earned: list[points.Earned]
    adjustments: list[points.Adjustment]
    spent: list[points.Spent]

    def balance(self, member_id: str) -> int:
        return points.balance(member_id, self.earned, self.adjustments, self.spent)

    def held(self, member_id: str) -> int:
        return points.held(member_id, self.spent)


async def ledger(session: AsyncSession, now: Now, people: Sequence[str]) -> Ledger:
    """Every done chore, finished routine, adjustment and reward of these people, ever."""
    ids = list(people)
    earned = [
        points.Earned(member, int(total or 0), now.today, status)
        for member, status, total in await session.execute(
            select(
                ChoreCompletion.member_id,
                ChoreCompletion.status,
                func.sum(ChoreCompletion.points_awarded),
            )
            .where(ChoreCompletion.member_id.in_(ids))
            .group_by(ChoreCompletion.member_id, ChoreCompletion.status)
        )
    ]
    earned += [
        points.Earned(member, int(total or 0), now.today)
        for member, total in await session.execute(
            select(RoutineFinish.member_id, func.sum(RoutineFinish.points_awarded))
            .where(RoutineFinish.member_id.in_(ids))
            .group_by(RoutineFinish.member_id)
        )
    ]
    adjustments = [
        points.Adjustment(member, int(total or 0))
        for member, total in await session.execute(
            select(PointAdjustment.member_id, func.sum(PointAdjustment.points))
            .where(PointAdjustment.member_id.in_(ids))
            .group_by(PointAdjustment.member_id)
        )
    ]
    spent = [
        points.Spent(member, int(total or 0), status)
        for member, status, total in await session.execute(
            select(Redemption.member_id, Redemption.status, func.sum(Redemption.cost_points))
            .where(Redemption.member_id.in_(ids))
            .group_by(Redemption.member_id, Redemption.status)
        )
    ]
    return Ledger(earned, adjustments, spent)


async def stars_of(
    session: AsyncSession, now: Now, people: Sequence[str], book: Book
) -> list[StarsOut]:
    """Each person's balance, the stars their open asks hold, this week's stars and their
    streak. ``book`` must reach back STREAK_DAYS (``streak_book``)."""
    if not people:
        return []
    ids = list(people)
    totals = await ledger(session, now, ids)
    first = now.week_first
    after = first + WEEK
    start_utc, end_utc = day_bounds(first, now.zone)[0], day_bounds(after, now.zone)[0]
    week = [
        points.Earned(member, awarded, now.day_of(at), status)
        for member, awarded, at, status in await session.execute(
            select(
                ChoreCompletion.member_id,
                ChoreCompletion.points_awarded,
                ChoreCompletion.completed_at,
                ChoreCompletion.status,
            ).where(
                ChoreCompletion.member_id.in_(ids),
                ChoreCompletion.completed_at >= start_utc,
                ChoreCompletion.completed_at < end_utc,
            )
        )
    ]
    week += [
        points.Earned(member, awarded, day)
        for member, awarded, day in await session.execute(
            select(RoutineFinish.member_id, RoutineFinish.points_awarded, RoutineFinish.day).where(
                RoutineFinish.member_id.in_(ids),
                RoutineFinish.day >= first,
                RoutineFinish.day < after,
            )
        )
    ]
    return [
        StarsOut(
            member_id=member,
            balance=totals.balance(member),
            held=totals.held(member),
            week=points.earned_between(member, week, first, after),
            streak=streak_of(book, member, now.today),
        )
        for member in ids
    ]


async def stars_for(
    session: AsyncSession, now: Now, member_id: str, active: Collection[str]
) -> StarsOut:
    """One person's stars, read fresh."""
    book = await streak_book(session, now, active)
    return (await stars_of(session, now, [member_id], book))[0]


def names(members: Sequence[MemberView]) -> Mapping[str, str]:
    return {member.id: member.name for member in members}
