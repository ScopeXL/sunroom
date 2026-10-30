"""Chores, completions and stars (PLAN §11.3, ADR 0019, ADR 0025; UX §4 "Chores room", §6
"Complete a chore on the display").

A chore is a rule; the boxes of a day are computed from the rules and the completions
(domain/chores.py), and balances from what earned and spent (domain/points.py). A completion
credits one person on one day (``common.credited`` says who); Undo deletes it, taking the stamp
and the stars back together. Rewards live in rewards.py and routines in routines.py.
"""

from __future__ import annotations

import json
from collections.abc import Collection, Iterable, Sequence
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sunroom.auth.deps import Actor, parent_refusal
from sunroom.calendar.schemas import RepeatPartsOut
from sunroom.core.errors import AppError
from sunroom.domain.chores import (
    ANY,
    FIXED,
    ROTATE,
    STREAK_DAYS,
    Completion,
    Due,
    Schedule,
    due_days,
    last_due,
    next_due,
    tally,
)
from sunroom.domain.recurrence import (
    RecurrenceError,
    RepeatParts,
    Timing,
    describe,
    describe_parts,
    validate_rrule,
)
from sunroom.plugins.chores import rewards, routines
from sunroom.plugins.chores.common import (
    DAY,
    KID,
    WEEK,
    Book,
    Now,
    Switches,
    completion_out,
    credited,
    dates,
    dates_json,
    gone,
    invalid,
    load_book,
    member_ids,
    now_of,
    on_chores,
    rule_of,
    stars_of,
    streak_book,
    switches,
    unknown_member,
)
from sunroom.plugins.chores.models import Chore, ChoreCompletion, CompletionStatus, PointAdjustment
from sunroom.plugins.chores.schemas import (
    AdjustIn,
    BoxOut,
    ChoreIn,
    ChoreOut,
    ChorePatch,
    ColumnOut,
    CompleteIn,
    CompleteOut,
    CompletionOut,
    DayOut,
    PointsOut,
    RemovedChoreOut,
    WaitingOut,
    WeekCellOut,
    WeekColumnOut,
    WeekOut,
)
from sunroom.plugins.context import MemberView, PluginContext

REMOVED_KEPT = timedelta(days=7)  # Recently removed
FINISHED_LEAVE = timedelta(hours=24)  # a finished task left this long untouched is tidied away
WAITING = timedelta(days=14)  # completions a parent hasn't answered, still shown
COUNTING = (CompletionStatus.DONE, CompletionStatus.PENDING)


def not_due() -> AppError:
    return AppError(409, "not_due", "api.tasks.not_due")


# ---- chores as people see them -----------------------------------------------------------------


def _timing(start: date) -> Timing:
    return Timing(all_day=True, start_date=start, end_date=start + DAY)


def repeat_text(chore: Chore) -> str:
    if not chore.rrule:
        return "Doesn't repeat"
    try:
        return describe(chore.rrule, _timing(chore.start_date), "UTC")
    except RecurrenceError:
        return "Repeats on a custom schedule"


def repeat_parts(chore: Chore) -> RepeatPartsOut | None:
    """The repeat in parts, for the page to word in the family's language (ADR 0043)."""
    if not chore.rrule:
        return None
    try:
        return RepeatPartsOut.of(describe_parts(chore.rrule, _timing(chore.start_date), "UTC"))
    except RecurrenceError:
        return RepeatPartsOut.of(RepeatParts(freq=None))


def chore_out(chore: Chore, next_day: date | None) -> ChoreOut:
    return ChoreOut.model_validate(
        {
            "id": chore.id,
            "title": chore.title,
            "description": chore.description,
            "icon": chore.icon,
            "points": chore.points,
            "rrule": chore.rrule,
            "repeat_text": repeat_text(chore),
            "repeat": repeat_parts(chore),
            "start_date": chore.start_date,
            "due_time": chore.due_time,
            "assignee_mode": chore.assignee_mode,
            "assignee_member_ids": member_ids(chore.assignee_member_ids_json),
            "rotation_index": chore.rotation_index,
            "requires_approval": chore.requires_approval,
            "active": chore.active,
            "next_due": next_day,
        }
    )


async def next_days(
    session: AsyncSession, chores: Sequence[Chore], today: date, active: Collection[str]
) -> dict[str, date | None]:
    """Each chore's next day (domain ``next_due``, ADR 0036), reading the one thing it needs from
    the database: the completions of a one-day chore's own day."""
    one_day = [chore.id for chore in chores if not chore.rrule]
    completions: list[Completion] = []
    if one_day:
        rows = await session.execute(
            select(
                ChoreCompletion.chore_id,
                ChoreCompletion.due_date,
                ChoreCompletion.member_id,
                ChoreCompletion.status,
            ).where(ChoreCompletion.chore_id.in_(one_day))
        )
        completions = [
            Completion(chore_id, due_date, member_id, due_date, status)
            for chore_id, due_date, member_id, status in rows
        ]
    return {chore.id: next_due(rule_of(chore, active), completions, today) for chore in chores}


async def _out(
    session: AsyncSession, chore: Chore, today: date, active: Collection[str]
) -> ChoreOut:
    return chore_out(chore, (await next_days(session, [chore], today, active))[chore.id])


async def list_chores(ctx: PluginContext, *, include_inactive: bool) -> list[ChoreOut]:
    """Every task, soonest first (All Tasks, ADR 0036): by its next day, the finished ones (no
    next day) last, then by title."""
    now = await now_of(ctx)
    active = await _active_ids(ctx)
    query = select(Chore).where(Chore.deleted_at.is_(None))
    if not include_inactive:
        query = query.where(Chore.active.is_(True))
    async with ctx.read() as session:
        chores = list(await session.scalars(query.order_by(Chore.created_at, Chore.id)))
        days = await next_days(session, chores, now.today, active)
    found = [chore_out(chore, days[chore.id]) for chore in chores]
    return sorted(
        found,
        key=lambda c: (c.next_due is None, c.next_due or date.max, c.title.casefold()),
    )


async def removed(ctx: PluginContext) -> list[RemovedChoreOut]:
    """Chores removed in the last 7 days, newest first (Recently removed)."""
    async with ctx.read() as session:
        chores = await session.scalars(
            select(Chore)
            .where(Chore.deleted_at >= ctx.now() - REMOVED_KEPT)
            .order_by(Chore.deleted_at.desc(), Chore.id.desc())
        )
        return [
            RemovedChoreOut(id=chore.id, title=chore.title, deleted_at=chore.deleted_at)
            for chore in chores
            if chore.deleted_at is not None
        ]


# ---- adding and changing -----------------------------------------------------------------------


def _checked_rule(rrule: str, start: date) -> str:
    try:
        return validate_rrule(rrule, _timing(start), "UTC")
    except RecurrenceError as exc:
        raise invalid(exc.key, "rrule") from None


def _checked_people(mode: str, people: Sequence[str]) -> list[str]:
    """Whose chore it is: one person or more for a fixed chore, two or more to take turns, and
    nobody in particular for an anyone chore."""
    if mode == ANY:
        return []
    if len(set(people)) != len(people):
        raise invalid("api.tasks.picked_twice", "assignee_member_ids")
    if mode == FIXED and not people:
        raise invalid("api.tasks.pick_who", "assignee_member_ids")
    if mode == ROTATE and len(people) < 2:
        raise invalid("api.tasks.pick_two", "assignee_member_ids")
    return list(people)


def _all_known(people: Sequence[str], active: Collection[str]) -> None:
    if any(member_id not in active for member_id in people):
        raise unknown_member()


def _turn_index(mode: str, people: Sequence[str], index: int) -> int:
    return index % len(people) if mode == ROTATE and people else 0


async def _active_ids(ctx: PluginContext) -> set[str]:
    return {member.id for member in await ctx.members.active()}


async def add_chore(ctx: PluginContext, actor: Actor, body: ChoreIn) -> ChoreOut:
    """Anyone may add a chore (adding never asks for the PIN, PLAN §12.4)."""
    now = await now_of(ctx)
    start = body.start_date or now.today
    rrule = _checked_rule(body.rrule, start) if body.rrule and body.rrule.strip() else None
    people = _checked_people(body.assignee_mode, body.assignee_member_ids)
    _all_known(people, await _active_ids(ctx))
    async with ctx.write() as tx:
        chore = Chore(
            title=body.title,
            description=body.description or None,
            icon=body.icon,
            points=body.points,
            rrule=rrule,
            start_date=start,
            due_time=body.due_time,
            assignee_mode=body.assignee_mode,
            assignee_member_ids_json=json.dumps(people),
            rotation_index=_turn_index(body.assignee_mode, people, body.rotation_index),
            requires_approval=body.requires_approval,
            created_by_member_id=actor.member_id,
            created_at=now.utc,
            updated_at=now.utc,
        )
        tx.session.add(chore)
        await tx.session.flush()
        tx.publish("chores.changed", {"chore_id": chore.id})
        return await _out(tx.session, chore, now.today, people)


async def _chore(session: AsyncSession, chore_id: str) -> Chore:
    chore = await session.get(Chore, chore_id)
    if chore is None or chore.deleted_at is not None:
        raise gone("api.tasks.task_gone")
    return chore


async def change_chore(ctx: PluginContext, chore_id: str, body: ChorePatch) -> ChoreOut:
    """Only what's sent changes. A description sent empty, or an icon sent as null, is taken
    off; the rule, the time and the approval have their own clear switches."""
    sent = body.model_fields_set
    now = await now_of(ctx)
    active = await _active_ids(ctx)
    if body.assignee_member_ids is not None:
        _all_known(body.assignee_member_ids, active)
    async with ctx.write() as tx:
        chore = await _chore(tx.session, chore_id)
        if body.title is not None:
            chore.title = body.title
        if body.description is not None or "description" in sent:
            chore.description = body.description or None
        if "icon" in sent:
            chore.icon = body.icon
        if body.points is not None:
            chore.points = body.points
        start = body.start_date or chore.start_date
        if body.clear_rrule:
            chore.rrule = None
        elif body.rrule is not None and body.rrule.strip():
            chore.rrule = _checked_rule(body.rrule, start)
        elif chore.rrule and start != chore.start_date:
            chore.rrule = _checked_rule(chore.rrule, start)
        chore.start_date = start
        if body.clear_due_time:
            chore.due_time = None
        elif body.due_time is not None:
            chore.due_time = body.due_time
        mode = body.assignee_mode or chore.assignee_mode
        people = member_ids(chore.assignee_member_ids_json)
        if body.assignee_mode is not None or body.assignee_member_ids is not None:
            sent_people = body.assignee_member_ids
            people = _checked_people(mode, people if sent_people is None else sent_people)
            chore.assignee_mode = mode
            chore.assignee_member_ids_json = json.dumps(people)
        index = chore.rotation_index if body.rotation_index is None else body.rotation_index
        chore.rotation_index = _turn_index(mode, people, index)
        if body.clear_requires_approval:
            chore.requires_approval = None
        elif body.requires_approval is not None:
            chore.requires_approval = body.requires_approval
        if body.active is not None:
            chore.active = body.active
        chore.updated_at = now.utc
        tx.publish("chores.changed", {"chore_id": chore.id})
        return await _out(tx.session, chore, now.today, active)


async def remove_chore(ctx: PluginContext, chore_id: str) -> None:
    """Into Recently removed for 7 days; its completions (and their stars) stay."""
    async with ctx.write() as tx:
        chore = await _chore(tx.session, chore_id)
        chore.deleted_at = chore.updated_at = ctx.now()
        tx.publish("chores.changed", {"chore_id": chore.id})


async def restore_chore(ctx: PluginContext, chore_id: str) -> ChoreOut:
    """Put back. A finished task put back stays a day before the tidy takes it again (its
    ``updated_at``), unless its day changes."""
    now = await now_of(ctx)
    active = await _active_ids(ctx)
    async with ctx.write() as tx:
        chore = await tx.session.get(Chore, chore_id)
        if chore is None:
            raise gone("api.tasks.task_gone")
        if chore.deleted_at is not None:
            chore.deleted_at = None
            chore.updated_at = now.utc
            tx.publish("chores.changed", {"chore_id": chore.id})
        return await _out(tx.session, chore, now.today, active)


async def skip(ctx: PluginContext, chore_id: str, day: date, *, skipped: bool) -> ChoreOut:
    """ "Skip today", and putting it back. A one-day chore has one day, so skipping it from any
    day it shows on skips that day."""
    now = await now_of(ctx)
    active = await _active_ids(ctx)
    async with ctx.write() as tx:
        chore = await _chore(tx.session, chore_id)
        days = set(dates(chore.skipped_dates_json))
        target = day
        if not chore.rrule:
            if day < chore.start_date:
                if skipped:
                    raise not_due()
                return await _out(tx.session, chore, now.today, active)
            target = chore.start_date
        if skipped == (target in days):
            return await _out(tx.session, chore, now.today, active)
        if skipped:
            if not due_days(rule_of(chore, ()), target, target + DAY):
                raise not_due()
            days.add(target)
        else:
            days.discard(target)
        chore.skipped_dates_json = dates_json(days)
        chore.updated_at = now.utc
        tx.publish("chores.changed", {"chore_id": chore.id, "date": target.isoformat()})
        return await _out(tx.session, chore, now.today, active)


# ---- the day and the week ----------------------------------------------------------------------


def _column_ids(
    book: Book,
    shelf: routines.Shelf | None,
    members: Sequence[MemberView],
    days: Sequence[date],
    boxes: Iterable[Due],
    today: date,
) -> list[str | None]:
    """People with a task still ahead of them (it has a next day, ADR 0036) or a box on one of
    these days, or a routine on one of them, in household order; then Anyone, likewise. A
    finished task keeps nobody's column, so once every task is done the room is empty."""
    ahead = [rule for rule in book.rules if next_due(rule, book.completions, today) is not None]
    shown = list(boxes)
    theirs = {member_id for rule in ahead if rule.mode == FIXED for member_id in rule.assignees}
    theirs |= {box.owner_id for box in shown if box.owner_id is not None}
    found: list[str | None] = [
        member.id
        for member in members
        if member.id in theirs or (shelf is not None and shelf.any_on(days, member))
    ]
    if any(rule.mode in (ROTATE, ANY) for rule in ahead) or any(
        box.owner_id is None for box in shown
    ):
        found.append(None)
    return found


def _box_out(box: Due, chore: Chore, book: Book, day: date, approval: bool) -> BoxOut:
    needs = chore.requires_approval if chore.requires_approval is not None else approval
    return BoxOut(
        chore_id=chore.id,
        title=chore.title,
        icon=chore.icon,
        points=chore.points,
        due_time=chore.due_time,
        due_date=box.due_date,
        since=box.due_date if box.due_date < day else None,
        owner_id=box.owner_id,
        turn_id=box.turn_id,
        needs_approval=needs,
        completion=completion_out(book.tick(box.completion)) if box.completion else None,
    )


async def _waiting(session: AsyncSession, now: Now) -> list[WaitingOut]:
    """Completions waiting for a parent's OK from the last two weeks, oldest first."""
    rows = await session.execute(
        select(ChoreCompletion, Chore.title)
        .join(Chore, Chore.id == ChoreCompletion.chore_id)
        .where(
            ChoreCompletion.status == CompletionStatus.PENDING,
            ChoreCompletion.completed_at >= now.utc - WAITING,
            Chore.deleted_at.is_(None),
        )
        .order_by(ChoreCompletion.completed_at, ChoreCompletion.id)
    )
    return [WaitingOut(completion=completion_out(row), title=title) for row, title in rows]


async def day_view(ctx: PluginContext, day: date | None) -> DayOut:
    """A day's boxes per person (and Anyone), with routines, stars, asks and approvals."""
    flags = switches(ctx)
    now = await now_of(ctx)
    members = await ctx.members.active()
    by_id = {member.id: member for member in members}
    when = day or now.today
    async with ctx.read() as session:
        book = await load_book(
            session,
            now,
            by_id,
            min(when, now.today) - STREAK_DAYS * DAY,
            max(when, now.today) + DAY,
        )
        shelf = await routines.load_shelf(session) if flags.routines else None
        boxes = Schedule(book.rules, book.completions, when, when + DAY, now.today).due_on(when)
        people = _column_ids(book, shelf, members, [when], boxes, now.today)
        kids_and_more = [by_id[member_id] for member_id in people if member_id is not None]
        runs = (
            await routines.runs_for(session, now, shelf, when, kids_and_more)
            if shelf is not None
            else []
        )
        chores = {chore.id: chore for chore in book.chores}
        columns: list[ColumnOut] = []
        for member_id in people:
            count = tally(boxes, member_id)
            columns.append(
                ColumnOut(
                    member_id=member_id,
                    done=count.done,
                    total=count.total,
                    boxes=[
                        _box_out(box, chores[box.chore_id], book, when, flags.approval)
                        for box in boxes
                        if box.owner_id == member_id
                    ],
                    routines=[run for run in runs if run.member_id == member_id]
                    if member_id is not None
                    else [],
                )
            )
        stars = (
            await stars_of(session, now, [m.id for m in kids_and_more], book) if flags.stars else []
        )
        return DayOut(
            date=when,
            stars_on=flags.stars,
            rewards_on=flags.rewards,
            routines_on=flags.routines,
            columns=columns,
            stars=stars,
            asked=await rewards.asked(session) if flags.rewards else [],
            waiting=await _waiting(session, now),
        )


async def week_view(ctx: PluginContext, start: date | None) -> WeekOut:
    """Seven days of counts per column, the fridge chart."""
    flags = switches(ctx)
    now = await now_of(ctx)
    members = await ctx.members.active()
    first = start or now.week_first
    days = [first + offset * DAY for offset in range(7)]
    async with ctx.read() as session:
        book = await load_book(session, now, {m.id for m in members}, first, first + WEEK)
        shelf = await routines.load_shelf(session) if flags.routines else None
    schedule = Schedule(book.rules, book.completions, first, first + WEEK, now.today)
    boxes = {day: schedule.due_on(day) for day in days}
    columns: list[WeekColumnOut] = []
    shown = [box for day in days for box in boxes[day]]
    for member_id in _column_ids(book, shelf, members, days, shown, now.today):
        cells: list[WeekCellOut] = []
        for day in days:
            count = tally(boxes[day], member_id)
            cells.append(WeekCellOut(date=day, done=count.done, total=count.total))
        columns.append(WeekColumnOut(member_id=member_id, days=cells))
    return WeekOut(start=first, columns=columns)


# ---- ticking a box, and taking it back ---------------------------------------------------------


def _needs_approval(chore: Chore, flags: Switches) -> bool:
    return chore.requires_approval if chore.requires_approval is not None else flags.approval


def _parent_hands(actor: Actor) -> bool:
    """A parent's phone, or a device holding the parent PIN's grant: its ticks need no OK."""
    return (not actor.is_kiosk and not actor.is_kid_device) or actor.has_grant


async def complete(
    ctx: PluginContext, actor: Actor, chore_id: str, body: CompleteIn
) -> CompleteOut:
    flags = switches(ctx)
    now = await now_of(ctx)
    members = await ctx.members.active()
    by_id = {member.id: member for member in members}
    async with ctx.write() as tx:
        chore = await _chore(tx.session, chore_id)
        member = credited(actor, body.member_id, members)
        rule = rule_of(chore, by_id)
        due = (
            bool(due_days(rule, body.due_date, body.due_date + DAY))
            if chore.rrule
            else body.due_date == chore.start_date and chore.start_date not in rule.skipped
        )
        if not chore.active or not due:
            raise not_due()
        rows = list(
            await tx.session.scalars(
                select(ChoreCompletion).where(
                    ChoreCompletion.chore_id == chore.id,
                    ChoreCompletion.due_date == body.due_date,
                )
            )
        )
        if chore.assignee_mode == FIXED:
            if member.id not in rule.assignees:
                raise AppError(
                    409, "not_theirs", "api.tasks.not_their_task", params={"name": member.name}
                )
        else:
            other = next(
                (r for r in rows if r.member_id != member.id and r.status in COUNTING), None
            )
            if other is not None:
                if other.member_id not in by_id:
                    raise AppError(409, "already_done", "api.tasks.someone_did_it")
                raise AppError(
                    409,
                    "already_done",
                    "api.tasks.already_done",
                    params={"name": by_id[other.member_id].name},
                )
        row = next((r for r in rows if r.member_id == member.id), None)
        if row is None or row.status not in COUNTING:
            pending = _needs_approval(chore, flags) and member.role == KID
            if row is None:
                row = ChoreCompletion(
                    chore_id=chore.id, due_date=body.due_date, member_id=member.id
                )
                tx.session.add(row)
            row.completed_at = now.utc
            row.completed_by_device_id = actor.device_id
            row.points_awarded = chore.points if flags.stars else 0
            row.status = (
                CompletionStatus.PENDING
                if pending and not _parent_hands(actor)
                else CompletionStatus.DONE
            )
            row.approved_by_member_id = None
            row.approved_at = None
            await tx.session.flush()
            tx.publish("chores.changed", {"chore_id": chore.id, "date": body.due_date.isoformat()})
            tx.publish("points.changed", {"member_id": member.id})
        completion = completion_out(row)
    # Where the box shows: its own day, or today for a one-day chore done late.
    day = body.due_date if chore.rrule else max(body.due_date, now.today)
    owner = member.id if chore.assignee_mode == FIXED else None
    async with ctx.read() as session:
        book = await load_book(
            session, now, by_id, min(day, now.today) - STREAK_DAYS * DAY, max(day, now.today) + DAY
        )
        boxes = Schedule(book.rules, book.completions, day, day + DAY, now.today).due_on(day)
        stars = (await stars_of(session, now, [member.id], book))[0] if flags.stars else None
    return CompleteOut(completion=completion, stars=stars, all_done=tally(boxes, owner).all_done)


async def undo(ctx: PluginContext, actor: Actor, chore_id: str, body: CompleteIn) -> None:
    """Not done after all: the completion goes, and its stamp and stars with it. Your own, or
    anyone's for a parent. Nothing to take back is fine."""
    member = credited(actor, body.member_id, await ctx.members.active())
    async with ctx.write() as tx:
        chore = await tx.session.get(Chore, chore_id)
        if chore is None:
            raise gone("api.tasks.task_gone")
        rows = list(
            await tx.session.scalars(
                select(ChoreCompletion)
                .where(
                    ChoreCompletion.chore_id == chore.id,
                    ChoreCompletion.due_date == body.due_date,
                    ChoreCompletion.status.in_(COUNTING),
                )
                .order_by(ChoreCompletion.completed_at, ChoreCompletion.id)
            )
        )
        if chore.assignee_mode == FIXED:
            row = next((r for r in rows if r.member_id == member.id), None)
        else:
            row = next(iter(rows), None)
        if row is None:
            return
        if row.member_id != member.id and not actor.is_parent:
            raise parent_refusal(actor)
        await tx.session.delete(row)
        tx.publish("chores.changed", {"chore_id": chore.id, "date": body.due_date.isoformat()})
        tx.publish("points.changed", {"member_id": row.member_id})


async def decide(
    ctx: PluginContext, actor: Actor, completion_id: str, *, approve: bool
) -> CompletionOut:
    """A parent's OK (the stars arrive) or "not done" (the box is due again)."""
    async with ctx.write() as tx:
        row = await tx.session.get(ChoreCompletion, completion_id)
        if row is None:
            raise AppError(404, "not_found", "api.tasks.not_waiting")
        target = CompletionStatus.DONE if approve else CompletionStatus.REJECTED
        if row.status == target:
            return completion_out(row)
        if approve and row.status != CompletionStatus.PENDING:
            raise AppError(409, "not_waiting", "api.tasks.not_waiting")
        row.status = target
        row.approved_by_member_id = actor.member_id if approve else None
        row.approved_at = ctx.now() if approve else None
        tx.publish("chores.changed", {"chore_id": row.chore_id, "date": row.due_date.isoformat()})
        tx.publish("points.changed", {"member_id": row.member_id})
        return completion_out(row)


# ---- stars ---------------------------------------------------------------------------------------


async def stars_view(ctx: PluginContext) -> PointsOut:
    now = await now_of(ctx)
    members = await ctx.members.active()
    ids = [member.id for member in members]
    async with ctx.read() as session:
        book = await load_book(session, now, ids, now.today - STREAK_DAYS * DAY, now.today + DAY)
        return PointsOut(stars=await stars_of(session, now, ids, book))


async def adjust(ctx: PluginContext, actor: Actor, body: AdjustIn) -> PointsOut:
    """A parent gives or takes stars, with a reason: to one child or several at once, a ledger
    row each in one transaction (ADR 0034). Answers their stars, in the order asked."""
    if body.points == 0:
        raise invalid("api.tasks.give_or_take", "points")
    now = await now_of(ctx)
    active = await _active_ids(ctx)
    ids = list(dict.fromkeys(body.member_ids))
    if any(member_id not in active for member_id in ids):
        raise unknown_member()
    async with ctx.write() as tx:
        for member_id in ids:
            tx.session.add(
                PointAdjustment(
                    member_id=member_id,
                    points=body.points,
                    reason=body.reason,
                    by_member_id=actor.member_id,
                    created_at=now.utc,
                )
            )
            tx.publish("points.changed", {"member_id": member_id})
    async with ctx.read() as session:
        book = await streak_book(session, now, active)
        return PointsOut(stars=await stars_of(session, now, ids, book))


# ---- housekeeping --------------------------------------------------------------------------------


async def tidy(ctx: PluginContext) -> None:
    """A finished task leaves for Recently removed the day after its last day, as a past
    countdown does (ADR 0036): a one-day task that's done, or a repeating one whose rule has
    ended, untouched for a day (so one just added, changed or put back stays a while). Its
    completions, stars and streaks stay: they're history. Paused tasks are left alone."""
    now = await now_of(ctx)
    active = await _active_ids(ctx)
    async with ctx.write() as tx:
        chores = await on_chores(tx.session)
        days = await next_days(tx.session, chores, now.today, active)
        for chore in chores:
            if days[chore.id] is not None or chore.updated_at > now.utc - FINISHED_LEAVE:
                continue
            last = last_due(rule_of(chore, active))
            if last is None or last >= now.today:
                continue
            chore.deleted_at = chore.updated_at = now.utc
            tx.publish("chores.changed", {"chore_id": chore.id})


async def prune(ctx: PluginContext) -> None:
    """Hourly. Finished tasks leave (``tidy``) and old routine checks go; chores, completions
    and asks are history (balances count them) and stay."""
    await tidy(ctx)
    await routines.prune(ctx)
