"""Lists and their items (PLAN §9, §11.3; UX §4 "Lists room", §5 "Lists").

An item is **open** (still to get or do), **done** (checked: struck, under Done), **cleared**
(Clear done hid it: Undo brings it back, and the list keeps it as history for its Usuals) or
**removed** (``deleted_at``: Recently removed shows it for 7 days). Removing a list leaves its
items as they are, so putting the list back brings them all back.

Every change publishes ``lists.changed {list_id}`` from its write transaction; the hourly jobs
publish one per list they touched. Times come from ``ctx.now()``; "today" is the household's.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import and_, case, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from sunroom.auth.deps import Actor, parent_refusal
from sunroom.core.errors import AppError
from sunroom.db.types import new_id
from sunroom.domain.timeparts import to_local
from sunroom.plugins.context import PluginContext
from sunroom.plugins.lists.models import ListItem, ListKind, ShoppingList
from sunroom.plugins.lists.schemas import (
    ClearedOut,
    ItemOut,
    ItemPatch,
    ItemsAdded,
    ItemsIn,
    LastChange,
    ListDetailOut,
    ListIn,
    ListOut,
    ListPatch,
    RemovedItemOut,
    RemovedListOut,
    RemovedOut,
    TodoItemOut,
    TodoOut,
)

EVENT = "lists.changed"
REMOVED_DAYS = 7  # Recently removed, then gone for good
HISTORY_DAYS = 180  # how far back Usuals look; cleared items are kept this long
USUALS_MAX = 12
STAPLES_UP_TO = 8  # a grocery list's Usuals are topped up with staples to this many
STAPLES = ("Milk", "Eggs", "Bread", "Bananas", "Apples", "Butter", "Cheese", "Yogurt")

# What a list's name says it is, checked in this order ("Packing to do" is packing).
KIND_WORDS: tuple[tuple[ListKind, tuple[str, ...]], ...] = (
    (ListKind.PACKING, ("pack",)),
    (ListKind.TODO, ("to do", "todo", "to-do", "errand")),
    (ListKind.GROCERY, ("grocer", "shopping", "costco", "pharmacy", "market", "store")),
)

IS_OPEN = and_(
    ListItem.deleted_at.is_(None), ListItem.cleared_at.is_(None), ListItem.checked_at.is_(None)
)
IS_DONE = and_(
    ListItem.deleted_at.is_(None), ListItem.cleared_at.is_(None), ListItem.checked_at.is_not(None)
)
OPEN_ORDER = (ListItem.position, ListItem.created_at, ListItem.id)
DONE_ORDER = (ListItem.checked_at.desc(), ListItem.id.desc())  # the latest check first


def list_gone() -> AppError:
    return AppError(404, "not_found", "That list isn't here any more.")


def item_gone() -> AppError:
    return AppError(404, "not_found", "That item isn't here any more.")


# ---- rules (pure) ------------------------------------------------------------------------------


def guess_kind(name: str) -> ListKind:
    """What a new list is from its name: "Packing: beach", "Errands", "Costco"."""
    folded = name.casefold()
    for kind, words in KIND_WORDS:
        if any(word in folded for word in words):
            return kind
    return ListKind.CUSTOM


def item_key(text: str) -> str:
    """Two items are the same thing when their text matches, ignoring case and outer spaces."""
    return text.strip().casefold()


@dataclass(slots=True)
class _Usual:
    count: int
    last_at: datetime
    text: str


def usuals(history: Iterable[tuple[str, datetime]], open_now: set[str], kind: str) -> list[str]:
    """The Usuals strip (UX §4): what the list had at least twice (``history`` is its items added
    in the last HISTORY_DAYS, oldest first), in the spelling used last, most often first, then
    most recent; never what's on the list now. A grocery list is topped up with staples."""
    found: dict[str, _Usual] = {}
    for text, at in history:
        key = item_key(text)
        if key in open_now:
            continue
        usual = found.get(key)
        if usual is None:
            found[key] = _Usual(1, at, text.strip())
            continue
        usual.count += 1
        if at >= usual.last_at:
            usual.last_at, usual.text = at, text.strip()
    often = sorted(
        (usual for usual in found.values() if usual.count >= 2),
        key=lambda usual: (usual.count, usual.last_at),
        reverse=True,
    )
    shown = [usual.text for usual in often[:USUALS_MAX]]
    if kind == ListKind.GROCERY:
        taken = open_now | {item_key(text) for text in shown}
        for staple in STAPLES:
            if len(shown) >= STAPLES_UP_TO:
                break
            if item_key(staple) not in taken:
                shown.append(staple)
    return shown


def household_today(ctx: PluginContext) -> date:
    """The household's date now: "due today" is the household's today, not UTC's."""
    return to_local(ctx.now(), ctx.zone()).date()


# ---- who may remove what -----------------------------------------------------------------------


def _kids_phone(actor: Actor) -> bool:
    """A kid's phone, without a parent's PIN grant."""
    return actor.is_kid_device and not actor.is_kiosk and not actor.is_parent


def _theirs(actor: Actor, created_by: str | None) -> bool:
    return actor.member_id is not None and actor.member_id == created_by


def _check_list_rights(actor: Actor, row: ShoppingList) -> None:
    """Removing a list (or putting it back) is a parent's call, except that a kid's phone may
    for a list its own person made."""
    if not actor.is_parent and not (
        _kids_phone(actor) and _theirs(actor, row.created_by_member_id)
    ):
        raise parent_refusal(actor)


def _check_item_rights(actor: Actor, item: ListItem) -> None:
    """A kid's phone removes (and puts back) only what its person added. The wall screen and
    parents' phones may remove anything: Undo and Recently removed cover mistakes."""
    if _kids_phone(actor) and not _theirs(actor, item.created_by_member_id):
        raise parent_refusal(actor)


async def _check_people(ctx: PluginContext, wanted: Sequence[tuple[str, str | None]]) -> None:
    """Each (field, member id) names someone in the household now (not archived)."""
    asked = [(field, member_id) for field, member_id in wanted if member_id is not None]
    if not asked:
        return
    active = {member.id for member in await ctx.members.active()}
    for field, member_id in asked:
        if member_id not in active:
            raise AppError(
                422, "invalid", "That person isn't in the household.", extra={"fields": [field]}
            )


# ---- shapes ------------------------------------------------------------------------------------


def item_out(item: ListItem) -> ItemOut:
    return ItemOut.model_validate(item, from_attributes=True)


def _blank(value: str) -> str | None:
    return value.strip() or None


def _touch(item: ListItem, now: datetime) -> None:
    item.version += 1
    item.updated_at = now


def _fields(item: ListItem) -> tuple[object, ...]:
    """What a change can touch, to tell whether it did."""
    return (
        item.text,
        item.note,
        item.quantity,
        item.due_date,
        item.assigned_member_id,
        item.checked_at,
        item.checked_by_member_id,
        item.position,
    )


async def _counts(
    session: AsyncSession, ids: Sequence[str], day: date
) -> dict[str, tuple[int, int, int]]:
    """Each list's open, done and due-by-``day`` counts."""
    rows = await session.execute(
        select(
            ListItem.list_id,
            func.count(case((IS_OPEN, 1))),
            func.count(case((IS_DONE, 1))),
            func.count(case((and_(IS_OPEN, ListItem.due_date <= day), 1))),
        )
        .where(ListItem.list_id.in_(ids), ListItem.deleted_at.is_(None))
        .group_by(ListItem.list_id)
    )
    return {list_id: (open_, done, due) for list_id, open_, done, due in rows}


async def _latest(
    session: AsyncSession,
    ids: Sequence[str],
    at: InstrumentedAttribute[datetime | None],
    by: InstrumentedAttribute[str | None],
) -> dict[str, tuple[str, str | None, datetime]]:
    """Each list's newest item by ``at`` (added, or checked): its text, who, and when. Removed
    items don't count; cleared ones do (Clear done isn't news, the check before it was)."""
    ranked = (
        select(
            ListItem.list_id.label("list_id"),
            ListItem.text.label("text"),
            by.label("member_id"),
            at.label("at"),
            func.row_number()
            .over(partition_by=ListItem.list_id, order_by=(at.desc(), ListItem.id.desc()))
            .label("rank"),
        )
        .where(ListItem.list_id.in_(ids), ListItem.deleted_at.is_(None), at.is_not(None))
        .subquery()
    )
    rows = await session.execute(
        select(ranked.c.list_id, ranked.c.text, ranked.c.member_id, ranked.c.at).where(
            ranked.c.rank == 1
        )
    )
    return {list_id: (text, member_id, when) for list_id, text, member_id, when in rows}


def _last_change(
    added: tuple[str, str | None, datetime] | None,
    checked: tuple[str, str | None, datetime] | None,
) -> LastChange | None:
    """A tile's last line: the newest add or check ("Mia added Milk · 2:10 PM"); a check made
    the same instant as an add is the newer."""
    if checked is not None and (added is None or checked[2] >= added[2]):
        text, member_id, at = checked
        return LastChange(action="checked", text=text, member_id=member_id, at=at)
    if added is not None:
        text, member_id, at = added
        return LastChange(action="added", text=text, member_id=member_id, at=at)
    return None


async def _list_outs(
    session: AsyncSession, rows: Sequence[ShoppingList], day: date
) -> list[ListOut]:
    ids = [row.id for row in rows]
    if not ids:
        return []
    counts = await _counts(session, ids, day)
    added = await _latest(session, ids, ListItem.created_at, ListItem.created_by_member_id)
    checked = await _latest(session, ids, ListItem.checked_at, ListItem.checked_by_member_id)
    out: list[ListOut] = []
    for row in rows:
        open_count, done_count, due_count = counts.get(row.id, (0, 0, 0))
        out.append(
            ListOut.model_validate(
                {
                    "id": row.id,
                    "name": row.name,
                    "kind": row.kind,
                    "sort": row.sort,
                    "open_count": open_count,
                    "done_count": done_count,
                    "due_count": due_count,
                    "last_change": _last_change(added.get(row.id), checked.get(row.id)),
                    "created_by_member_id": row.created_by_member_id,
                }
            )
        )
    return out


async def _list_out(session: AsyncSession, row: ShoppingList, day: date) -> ListOut:
    [out] = await _list_outs(session, [row], day)
    return out


async def _live_list(session: AsyncSession, list_id: str) -> ShoppingList:
    row = await session.get(ShoppingList, list_id)
    if row is None or row.deleted_at is not None:
        raise list_gone()
    return row


async def _live_item(session: AsyncSession, list_id: str, item_id: str) -> ListItem:
    """An item on the list now, open or done (not cleared, not removed), of a list that's here."""
    await _live_list(session, list_id)
    item = await session.get(ListItem, item_id)
    if (
        item is None
        or item.list_id != list_id
        or item.deleted_at is not None
        or item.cleared_at is not None
    ):
        raise item_gone()
    return item


# ---- reading -----------------------------------------------------------------------------------


async def all_lists(ctx: PluginContext) -> list[ListOut]:
    async with ctx.read() as session:
        rows = (
            await session.scalars(
                select(ShoppingList)
                .where(ShoppingList.deleted_at.is_(None))
                .order_by(ShoppingList.sort, ShoppingList.created_at, ShoppingList.id)
            )
        ).all()
        return await _list_outs(session, rows, household_today(ctx))


async def list_detail(ctx: PluginContext, list_id: str) -> ListDetailOut:
    since = ctx.now() - timedelta(days=HISTORY_DAYS)
    async with ctx.read() as session:
        row = await _live_list(session, list_id)
        summary = await _list_out(session, row, household_today(ctx))
        on_list = (
            await session.scalars(
                select(ListItem).where(ListItem.list_id == list_id, IS_OPEN).order_by(*OPEN_ORDER)
            )
        ).all()
        done = (
            await session.scalars(
                select(ListItem).where(ListItem.list_id == list_id, IS_DONE).order_by(*DONE_ORDER)
            )
        ).all()
        history = await session.execute(
            select(ListItem.text, ListItem.created_at)
            .where(
                ListItem.list_id == list_id,
                ListItem.deleted_at.is_(None),
                ListItem.created_at >= since,
            )
            .order_by(ListItem.created_at, ListItem.id)
        )
        open_now = {item_key(item.text) for item in on_list}
        return ListDetailOut(
            list=summary,
            items=[item_out(item) for item in on_list],
            done=[item_out(item) for item in done],
            usuals=usuals(history, open_now, row.kind),
        )


async def todo(ctx: PluginContext, day: date | None) -> TodoOut:
    """The Today panel's To do: open items due on ``day`` (the household's today) or before."""
    on = day or household_today(ctx)
    async with ctx.read() as session:
        rows = await session.execute(
            select(ListItem, ShoppingList.name, ShoppingList.kind)
            .join(ShoppingList, ShoppingList.id == ListItem.list_id)
            .where(IS_OPEN, ListItem.due_date <= on, ShoppingList.deleted_at.is_(None))
            .order_by(ListItem.due_date, *OPEN_ORDER)
        )
        items = [
            TodoItemOut.model_validate(
                {**item_out(item).model_dump(), "list_name": name, "list_kind": kind}
            )
            for item, name, kind in rows
        ]
    return TodoOut(date=on, items=items)


async def removed(ctx: PluginContext) -> RemovedOut:
    """Recently removed (7 days), newest first. An item removed from a list that's removed too
    comes back with its list, so it shows only there."""
    since = ctx.now() - timedelta(days=REMOVED_DAYS)
    async with ctx.read() as session:
        gone = (
            await session.scalars(
                select(ShoppingList)
                .where(ShoppingList.deleted_at >= since)
                .order_by(ShoppingList.deleted_at.desc(), ShoppingList.id.desc())
            )
        ).all()
        held: dict[str, int] = {}
        if gone:
            counted = await session.execute(
                select(ListItem.list_id, func.count())
                .where(
                    ListItem.list_id.in_([row.id for row in gone]),
                    ListItem.deleted_at.is_(None),
                    ListItem.cleared_at.is_(None),
                )
                .group_by(ListItem.list_id)
            )
            held = dict(counted.all())
        items = await session.execute(
            select(ListItem, ShoppingList.name)
            .join(ShoppingList, ShoppingList.id == ListItem.list_id)
            .where(ListItem.deleted_at >= since, ShoppingList.deleted_at.is_(None))
            .order_by(ListItem.deleted_at.desc(), ListItem.id.desc())
        )
        return RemovedOut(
            lists=[
                RemovedListOut.model_validate(
                    {
                        "id": row.id,
                        "name": row.name,
                        "item_count": held.get(row.id, 0),
                        "deleted_at": row.deleted_at,
                    }
                )
                for row in gone
            ],
            items=[
                RemovedItemOut.model_validate(
                    {
                        "id": item.id,
                        "list_id": item.list_id,
                        "list_name": name,
                        "text": item.text,
                        "deleted_at": item.deleted_at,
                    }
                )
                for item, name in items
            ],
        )


# ---- lists -------------------------------------------------------------------------------------


async def create_list(ctx: PluginContext, actor: Actor, body: ListIn) -> ListOut:
    """A new list goes last; its kind comes from its name unless the family picked one."""
    now = ctx.now()
    async with ctx.write() as tx:
        last = await tx.session.scalar(select(func.max(ShoppingList.sort)))
        row = ShoppingList(
            id=new_id(),
            name=body.name,
            kind=body.kind or guess_kind(body.name).value,
            icon=None,
            sort=0 if last is None else last + 1,
            created_by_member_id=actor.member_id,
            created_at=now,
            updated_at=now,
            deleted_at=None,
        )
        tx.session.add(row)
        tx.publish(EVENT, {"list_id": row.id})
        return await _list_out(tx.session, row, household_today(ctx))


async def update_list(ctx: PluginContext, list_id: str, body: ListPatch) -> ListOut:
    now = ctx.now()
    async with ctx.write() as tx:
        row = await _live_list(tx.session, list_id)
        if body.name is not None:
            row.name = body.name
        if body.kind is not None:
            row.kind = body.kind
        row.updated_at = now
        tx.publish(EVENT, {"list_id": list_id})
        return await _list_out(tx.session, row, household_today(ctx))


async def order_lists(ctx: PluginContext, ids: Sequence[str]) -> None:
    """The lists in the order the family dragged them: each one's sort is its place in ``ids``.
    A list that isn't here any more is skipped."""
    now = ctx.now()
    wanted = list(dict.fromkeys(ids))
    async with ctx.write() as tx:
        rows = {
            row.id: row
            for row in (
                await tx.session.scalars(
                    select(ShoppingList).where(
                        ShoppingList.id.in_(wanted), ShoppingList.deleted_at.is_(None)
                    )
                )
            ).all()
        }
        for index, list_id in enumerate(wanted):
            row = rows.get(list_id)
            if row is None:
                continue
            if row.sort != index:
                row.sort = index
                row.updated_at = now
            tx.publish(EVENT, {"list_id": list_id})


async def remove_list(ctx: PluginContext, actor: Actor, list_id: str) -> None:
    """Into Recently removed; its items stay as they are and come back with it."""
    now = ctx.now()
    async with ctx.write() as tx:
        row = await _live_list(tx.session, list_id)
        _check_list_rights(actor, row)
        row.deleted_at = now
        row.updated_at = now
        tx.publish(EVENT, {"list_id": list_id})


async def restore_list(ctx: PluginContext, actor: Actor, list_id: str) -> ListOut:
    now = ctx.now()
    async with ctx.write() as tx:
        row = await tx.session.get(ShoppingList, list_id)
        if row is None:
            raise list_gone()
        _check_list_rights(actor, row)
        if row.deleted_at is not None:
            row.deleted_at = None
            row.updated_at = now
        tx.publish(EVENT, {"list_id": list_id})
        return await _list_out(tx.session, row, household_today(ctx))


# ---- items -------------------------------------------------------------------------------------


async def add_items(ctx: PluginContext, actor: Actor, list_id: str, body: ItemsIn) -> ItemsAdded:
    """New items go at the end. One that's on the list already, still to get, isn't added twice
    ("Milk" when Milk is there): its text comes back in ``already``."""
    await _check_people(
        ctx,
        [
            (f"items.{index}.assigned_member_id", entry.assigned_member_id)
            for index, entry in enumerate(body.items)
        ],
    )
    now = ctx.now()
    async with ctx.write() as tx:
        await _live_list(tx.session, list_id)
        on_list = {
            item_key(text)
            for text in await tx.session.scalars(
                select(ListItem.text).where(ListItem.list_id == list_id, IS_OPEN)
            )
        }
        last = await tx.session.scalar(
            select(func.max(ListItem.position)).where(ListItem.list_id == list_id)
        )
        position = -1 if last is None else last
        added: list[ListItem] = []
        already: list[str] = []
        for entry in body.items:
            key = item_key(entry.text)
            if key in on_list:
                already.append(entry.text)
                continue
            on_list.add(key)
            position += 1
            item = ListItem(
                id=new_id(),
                list_id=list_id,
                text=entry.text,
                note=_blank(entry.note) if entry.note is not None else None,
                quantity=_blank(entry.quantity) if entry.quantity is not None else None,
                due_date=entry.due_date,
                assigned_member_id=entry.assigned_member_id,
                checked_at=None,
                checked_by_member_id=None,
                position=position,
                version=1,
                created_by_member_id=actor.member_id,
                created_at=now,
                updated_at=now,
                cleared_at=None,
                deleted_at=None,
            )
            tx.session.add(item)
            added.append(item)
        tx.publish(EVENT, {"list_id": list_id})
        return ItemsAdded(items=[item_out(item) for item in added], already=already)


async def _move(session: AsyncSession, item: ListItem, index: int, now: datetime) -> None:
    """Put ``item`` at ``index`` among the list's open items (0 is the top); the others close
    up around it."""
    others = (
        await session.scalars(
            select(ListItem)
            .where(ListItem.list_id == item.list_id, ListItem.id != item.id, IS_OPEN)
            .order_by(*OPEN_ORDER)
        )
    ).all()
    order = list(others)
    order.insert(min(index, len(order)), item)
    for position, row in enumerate(order):
        if row.position != position:
            row.position = position
            if row is not item:  # the moved item is touched once, with the rest of its change
                _touch(row, now)


async def update_item(
    ctx: PluginContext, actor: Actor, list_id: str, item_id: str, body: ItemPatch
) -> ItemOut:
    """Only what's sent changes. Checking stamps who did it (the wall screen's tapped person, a
    phone's own person, or nobody: Everyone); a second check keeps the first one's name."""
    await _check_people(ctx, [("assigned_member_id", body.assigned_member_id)])
    now = ctx.now()
    async with ctx.write() as tx:
        item = await _live_item(tx.session, list_id, item_id)
        before = _fields(item)
        if body.text is not None:
            item.text = body.text
        if body.note is not None:
            item.note = _blank(body.note)
        if body.quantity is not None:
            item.quantity = _blank(body.quantity)
        if body.clear_due_date:
            item.due_date = None
        elif body.due_date is not None:
            item.due_date = body.due_date
        if body.clear_assignee:
            item.assigned_member_id = None
        elif body.assigned_member_id is not None:
            item.assigned_member_id = body.assigned_member_id
        if body.checked is True and item.checked_at is None:
            item.checked_at = now
            item.checked_by_member_id = actor.member_id
        elif body.checked is False:
            item.checked_at = None
            item.checked_by_member_id = None
        if body.position is not None:
            await _move(tx.session, item, body.position, now)
        if _fields(item) != before:
            _touch(item, now)
        tx.publish(EVENT, {"list_id": list_id})
        return item_out(item)


async def remove_item(ctx: PluginContext, actor: Actor, list_id: str, item_id: str) -> None:
    now = ctx.now()
    async with ctx.write() as tx:
        item = await _live_item(tx.session, list_id, item_id)
        _check_item_rights(actor, item)
        item.deleted_at = now
        _touch(item, now)
        tx.publish(EVENT, {"list_id": list_id})


async def restore_items(
    ctx: PluginContext, actor: Actor, list_id: str, ids: Sequence[str]
) -> list[ItemOut]:
    """Undo for Clear done and for a removal, and Put back in Recently removed: the items come
    back as they were (a checked one to Done). Ids that aren't this list's are skipped."""
    now = ctx.now()
    wanted = list(dict.fromkeys(ids))
    async with ctx.write() as tx:
        await _live_list(tx.session, list_id)
        found = {
            item.id: item
            for item in (
                await tx.session.scalars(
                    select(ListItem).where(ListItem.list_id == list_id, ListItem.id.in_(wanted))
                )
            ).all()
        }
        items = [found[item_id] for item_id in wanted if item_id in found]
        if not items:
            raise item_gone()
        for item in items:
            if item.deleted_at is not None:
                _check_item_rights(actor, item)
        for item in items:
            if item.deleted_at is not None or item.cleared_at is not None:
                item.deleted_at = None
                item.cleared_at = None
                _touch(item, now)
        tx.publish(EVENT, {"list_id": list_id})
        return [item_out(item) for item in items]


async def clear_checked(ctx: PluginContext, list_id: str) -> ClearedOut:
    """Clear done: the checked items leave Done. Their ids come back for Undo."""
    now = ctx.now()
    async with ctx.write() as tx:
        await _live_list(tx.session, list_id)
        done = (
            await tx.session.scalars(
                select(ListItem).where(ListItem.list_id == list_id, IS_DONE).order_by(*DONE_ORDER)
            )
        ).all()
        for item in done:
            item.cleared_at = now
            _touch(item, now)
        tx.publish(EVENT, {"list_id": list_id})
        return ClearedOut(ids=[item.id for item in done])


# ---- jobs (hourly) -----------------------------------------------------------------------------


async def auto_clear(ctx: PluginContext) -> None:
    """The setting "Clear done items by themselves": items checked longer ago than the chosen
    number of days leave Done, as if someone had tapped Clear done."""
    choice = str(ctx.settings().get("auto_clear_days") or "never")
    if not choice.isdigit():
        return
    now = ctx.now()
    cutoff = now - timedelta(days=int(choice))
    async with ctx.write() as tx:
        items = (
            await tx.session.scalars(select(ListItem).where(IS_DONE, ListItem.checked_at < cutoff))
        ).all()
        for item in items:
            item.cleared_at = now
            _touch(item, now)
        for list_id in sorted({item.list_id for item in items}):
            tx.publish(EVENT, {"list_id": list_id})


async def prune(ctx: PluginContext) -> None:
    """Gone for good: lists and items removed more than REMOVED_DAYS ago (a list with all its
    items), and items cleared more than HISTORY_DAYS ago (past what Usuals read)."""
    now = ctx.now()
    removed_before = now - timedelta(days=REMOVED_DAYS)
    history_before = now - timedelta(days=HISTORY_DAYS)
    async with ctx.write() as tx:
        gone = list(
            (
                await tx.session.scalars(
                    select(ShoppingList.id).where(ShoppingList.deleted_at < removed_before)
                )
            ).all()
        )
        stale = or_(
            ListItem.list_id.in_(gone),
            ListItem.deleted_at < removed_before,
            ListItem.cleared_at < history_before,
        )
        touched = set(
            (await tx.session.scalars(select(ListItem.list_id).where(stale).distinct())).all()
        )
        await tx.session.execute(delete(ListItem).where(stale))
        if gone:
            await tx.session.execute(delete(ShoppingList).where(ShoppingList.id.in_(gone)))
        for list_id in sorted(touched | set(gone)):
            tx.publish(EVENT, {"list_id": list_id})
