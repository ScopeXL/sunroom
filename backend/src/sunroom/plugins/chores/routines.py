"""Routines (UX §4 "Routine runner", §6 "A kid runs a bedtime routine"): short checklists a kid
runs on their own, morning or bedtime. A check is kept for its day, so a routine starts fresh
each day; finishing one is kept once a day, with the stars it gave. Old checks are pruned; the
finishes stay, because balances count them.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from sunroom.auth.deps import Actor
from sunroom.core.errors import AppError
from sunroom.plugins.chores.common import (
    DAY,
    KID,
    Now,
    credited,
    gone,
    invalid,
    now_of,
    stars_for,
    switches,
    unknown_member,
    weekdays,
)
from sunroom.plugins.chores.models import (
    Routine,
    RoutineCheck,
    RoutineFinish,
    RoutineStep,
)
from sunroom.plugins.chores.schemas import (
    CheckIn,
    FinishIn,
    FinishOut,
    RoutineIn,
    RoutineOut,
    RoutinePatch,
    RoutineRunOut,
    RoutinesOut,
    RoutineStepOut,
    StepIn,
    StepsIn,
)
from sunroom.plugins.context import MemberView, PluginContext

CHECKS_KEPT_DAYS = 60


def routines_off() -> AppError:
    return AppError(409, "routines_off", "api.tasks.routines_off")


def applies(routine: Routine, member: MemberView) -> bool:
    """A routine is its person's, or every kid's when it names nobody."""
    if routine.member_id is None:
        return member.role == KID
    return routine.member_id == member.id


def is_open(start: str, end: str, clock: str) -> bool:
    """Whether "HH:MM" ``clock`` is inside the window; one whose end is before its start runs
    past midnight."""
    if start <= end:
        return start <= clock < end
    return clock >= start or clock < end


def step_out(step: RoutineStep) -> RoutineStepOut:
    return RoutineStepOut(id=step.id, title=step.title, icon=step.icon, position=step.position)


def routine_out(routine: Routine, steps: Sequence[RoutineStep]) -> RoutineOut:
    return RoutineOut(
        id=routine.id,
        title=routine.title,
        member_id=routine.member_id,
        days=weekdays(routine.days_json),
        window_start=routine.window_start,
        window_end=routine.window_end,
        icon=routine.icon,
        points=routine.points,
        active=routine.active,
        steps=[step_out(step) for step in steps],
    )


@dataclass(frozen=True, slots=True)
class Shelf:
    """Routines (in their order) and each one's steps (in theirs)."""

    routines: list[Routine]
    steps: dict[str, list[RoutineStep]] = field(default_factory=dict[str, list[RoutineStep]])

    def steps_of(self, routine_id: str) -> list[RoutineStep]:
        return self.steps.get(routine_id, [])

    def on_day(self, day: date, member: MemberView) -> list[Routine]:
        """The routines that are on and run for ``member`` on ``day``'s weekday."""
        return [
            routine
            for routine in self.routines
            if routine.active
            and day.weekday() in weekdays(routine.days_json)
            and applies(routine, member)
        ]

    def any_on(self, days: Sequence[date], member: MemberView) -> bool:
        return any(self.on_day(day, member) for day in days)


async def load_shelf(session: AsyncSession, *, include_inactive: bool = True) -> Shelf:
    query = select(Routine).where(Routine.deleted_at.is_(None))
    if not include_inactive:
        query = query.where(Routine.active.is_(True))
    routines = list(
        await session.scalars(
            query.order_by(Routine.sort, Routine.window_start, Routine.created_at, Routine.id)
        )
    )
    steps: dict[str, list[RoutineStep]] = {}
    if routines:
        rows = await session.scalars(
            select(RoutineStep)
            .where(RoutineStep.routine_id.in_([routine.id for routine in routines]))
            .order_by(RoutineStep.position, RoutineStep.id)
        )
        for step in rows:
            steps.setdefault(step.routine_id, []).append(step)
    return Shelf(routines, steps)


async def runs_for(
    session: AsyncSession, now: Now, shelf: Shelf, day: date, members: Sequence[MemberView]
) -> list[RoutineRunOut]:
    """Each person's routines on ``day``: in household order, then the routines' order."""
    pairs = [(routine, member) for member in members for routine in shelf.on_day(day, member)]
    if not pairs:
        return []
    people = sorted({member.id for _, member in pairs})
    step_ids = sorted({step.id for routine, _ in pairs for step in shelf.steps_of(routine.id)})
    checked: set[tuple[str, str]] = set()
    if step_ids:
        rows = await session.execute(
            select(RoutineCheck.routine_step_id, RoutineCheck.member_id).where(
                RoutineCheck.day == day,
                RoutineCheck.member_id.in_(people),
                RoutineCheck.routine_step_id.in_(step_ids),
            )
        )
        checked = {(step_id, member_id) for step_id, member_id in rows}
    finished = {
        (routine_id, member_id)
        for routine_id, member_id in await session.execute(
            select(RoutineFinish.routine_id, RoutineFinish.member_id).where(
                RoutineFinish.day == day, RoutineFinish.member_id.in_(people)
            )
        )
    }
    return [
        RoutineRunOut(
            routine_id=routine.id,
            member_id=member.id,
            title=routine.title,
            icon=routine.icon,
            points=routine.points,
            window_start=routine.window_start,
            window_end=routine.window_end,
            open_now=day == now.today
            and is_open(routine.window_start, routine.window_end, now.clock),
            steps=[step_out(step) for step in shelf.steps_of(routine.id)],
            checked=[
                step.id for step in shelf.steps_of(routine.id) if (step.id, member.id) in checked
            ],
            finished=(routine.id, member.id) in finished,
        )
        for routine, member in pairs
    ]


# ---- reading -----------------------------------------------------------------------------------


async def routines_view(
    ctx: PluginContext, member_id: str | None, day: date | None, *, include_inactive: bool
) -> RoutinesOut:
    """The routines as made in Settings, and each person's day of them (one person's, when
    asked)."""
    flags = switches(ctx)
    now = await now_of(ctx)
    members = await ctx.members.active()
    when = day or now.today
    people = [m for m in members if m.id == member_id] if member_id is not None else members
    async with ctx.read() as session:
        shelf = await load_shelf(session, include_inactive=include_inactive)
        runs = await runs_for(session, now, shelf, when, people) if flags.routines else []
    return RoutinesOut(
        routines=[routine_out(r, shelf.steps_of(r.id)) for r in shelf.routines], runs=runs
    )


async def _routine(session: AsyncSession, routine_id: str) -> Routine:
    routine = await session.get(Routine, routine_id)
    if routine is None or routine.deleted_at is not None:
        raise gone("api.tasks.routine_gone")
    return routine


async def _steps(session: AsyncSession, routine_id: str) -> list[RoutineStep]:
    return list(
        await session.scalars(
            select(RoutineStep)
            .where(RoutineStep.routine_id == routine_id)
            .order_by(RoutineStep.position, RoutineStep.id)
        )
    )


# ---- making and changing (parents) -------------------------------------------------------------


def _days_json(days: Sequence[int]) -> str:
    chosen = sorted(set(days))
    if not chosen:
        raise invalid("api.tasks.pick_a_day", "days")
    return json.dumps(chosen)


def _check_window(start: str, end: str) -> None:
    if start == end:
        raise invalid("api.tasks.routine_window", "window_end")


async def _check_member(ctx: PluginContext, member_id: str | None) -> None:
    if member_id is not None and member_id not in {m.id for m in await ctx.members.active()}:
        raise unknown_member()


def _place_steps(session: AsyncSession, routine_id: str, steps: Sequence[StepIn]) -> None:
    for position, step in enumerate(steps):
        session.add(
            RoutineStep(routine_id=routine_id, title=step.title, icon=step.icon, position=position)
        )


async def add_routine(ctx: PluginContext, body: RoutineIn) -> RoutineOut:
    await _check_member(ctx, body.member_id)
    _check_window(body.window_start, body.window_end)
    days = _days_json(body.days)
    async with ctx.write() as tx:
        routine = Routine(
            title=body.title,
            member_id=body.member_id,
            days_json=days,
            window_start=body.window_start,
            window_end=body.window_end,
            icon=body.icon,
            points=body.points,
            created_at=ctx.now(),
        )
        tx.session.add(routine)
        await tx.session.flush()
        _place_steps(tx.session, routine.id, body.steps)
        await tx.session.flush()
        tx.publish("routines.changed", {})
        return routine_out(routine, await _steps(tx.session, routine.id))


async def change_routine(ctx: PluginContext, routine_id: str, body: RoutinePatch) -> RoutineOut:
    """Only what's sent changes; ``every_kid`` gives it back to every kid."""
    await _check_member(ctx, body.member_id)
    async with ctx.write() as tx:
        routine = await _routine(tx.session, routine_id)
        if body.title is not None:
            routine.title = body.title
        if body.every_kid:
            routine.member_id = None
        elif body.member_id is not None:
            routine.member_id = body.member_id
        if body.days is not None:
            routine.days_json = _days_json(body.days)
        start = body.window_start or routine.window_start
        end = body.window_end or routine.window_end
        if body.window_start is not None or body.window_end is not None:
            _check_window(start, end)
            routine.window_start, routine.window_end = start, end
        if "icon" in body.model_fields_set:
            routine.icon = body.icon
        if body.points is not None:
            routine.points = body.points
        if body.active is not None:
            routine.active = body.active
        tx.publish("routines.changed", {})
        return routine_out(routine, await _steps(tx.session, routine.id))


async def remove_routine(ctx: PluginContext, routine_id: str) -> None:
    async with ctx.write() as tx:
        routine = await _routine(tx.session, routine_id)
        routine.deleted_at = ctx.now()
        tx.publish("routines.changed", {})


async def replace_steps(ctx: PluginContext, routine_id: str, body: StepsIn) -> RoutineOut:
    """The steps in their new order: a step sent with its id keeps it (and today's checks),
    one without is new, and one left out goes, with its checks."""
    async with ctx.write() as tx:
        routine = await _routine(tx.session, routine_id)
        existing = {step.id: step for step in await _steps(tx.session, routine.id)}
        kept: set[str] = set()
        for position, sent in enumerate(body.steps):
            step = existing.get(sent.id or "")
            if step is None or step.id in kept:
                tx.session.add(
                    RoutineStep(
                        routine_id=routine.id, title=sent.title, icon=sent.icon, position=position
                    )
                )
                continue
            step.title, step.icon, step.position = sent.title, sent.icon, position
            kept.add(step.id)
        dropped = [step for step_id, step in existing.items() if step_id not in kept]
        if dropped:
            await tx.session.execute(
                delete(RoutineCheck).where(
                    RoutineCheck.routine_step_id.in_([step.id for step in dropped])
                )
            )
            for step in dropped:
                await tx.session.delete(step)
        await tx.session.flush()
        tx.publish("routines.changed", {})
        return routine_out(routine, await _steps(tx.session, routine.id))


# ---- running one (anyone) ----------------------------------------------------------------------


def _theirs(routine: Routine, member: MemberView, day: date) -> None:
    if not applies(routine, member):
        raise AppError(
            409, "not_theirs", "api.tasks.not_their_routine", params={"name": member.name}
        )
    if day.weekday() not in weekdays(routine.days_json):
        raise AppError(409, "not_due", "api.tasks.routine_not_due")


async def check(
    ctx: PluginContext, actor: Actor, routine_id: str, step_id: str, body: CheckIn
) -> RoutineRunOut:
    """Tick a step (or untick it) for one person on one day."""
    if not switches(ctx).routines:
        raise routines_off()
    now = await now_of(ctx)
    members = await ctx.members.active()
    member = credited(actor, body.member_id, members)
    async with ctx.write() as tx:
        routine = await _routine(tx.session, routine_id)
        if not routine.active:
            raise gone("api.tasks.routine_gone")
        step = await tx.session.get(RoutineStep, step_id)
        if step is None or step.routine_id != routine.id:
            raise AppError(404, "not_found", "api.tasks.step_gone")
        _theirs(routine, member, body.date)
        found = await tx.session.get(RoutineCheck, (step.id, member.id, body.date))
        if body.checked and found is None:
            tx.session.add(
                RoutineCheck(
                    routine_step_id=step.id, member_id=member.id, day=body.date, checked_at=now.utc
                )
            )
            tx.publish("routines.changed", {})
        elif not body.checked and found is not None:
            await tx.session.delete(found)
            tx.publish("routines.changed", {})
        await tx.session.flush()
        shelf = Shelf([routine], {routine.id: await _steps(tx.session, routine.id)})
        [run] = await runs_for(tx.session, now, shelf, body.date, [member])
    return run


async def finish(ctx: PluginContext, actor: Actor, routine_id: str, body: FinishIn) -> FinishOut:
    """The last step done: stars once a day, when the routine gives them."""
    flags = switches(ctx)
    if not flags.routines:
        raise routines_off()
    now = await now_of(ctx)
    members = await ctx.members.active()
    member = credited(actor, body.member_id, members)
    awarded = 0
    async with ctx.write() as tx:
        routine = await _routine(tx.session, routine_id)
        if not routine.active:
            raise gone("api.tasks.routine_gone")
        _theirs(routine, member, body.date)
        if await tx.session.get(RoutineFinish, (routine.id, member.id, body.date)) is None:
            awarded = routine.points if flags.stars else 0
            tx.session.add(
                RoutineFinish(
                    routine_id=routine.id,
                    member_id=member.id,
                    day=body.date,
                    finished_at=now.utc,
                    points_awarded=awarded,
                )
            )
            tx.publish("routines.changed", {})
            if awarded:
                tx.publish("points.changed", {"member_id": member.id})
    stars = None
    if flags.stars:
        async with ctx.read() as session:
            stars = await stars_for(session, now, member.id, {m.id for m in members})
    return FinishOut(points_awarded=awarded, stars=stars)


async def prune(ctx: PluginContext) -> None:
    """Checks older than CHECKS_KEPT_DAYS go; finishes stay (balances count them)."""
    now = await now_of(ctx)
    async with ctx.write() as tx:
        await tx.session.execute(
            delete(RoutineCheck).where(RoutineCheck.day < now.today - CHECKS_KEPT_DAYS * DAY)
        )
