"""The lists API's shapes (PLAN §11.3, UX §4 "Lists room", §5 "Lists")."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

ListKindName = Literal["grocery", "todo", "packing", "custom"]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
ItemText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Note = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]
Quantity = Annotated[str, StringConstraints(strip_whitespace=True, max_length=20)]


class LastChange(BaseModel):
    """A list tile's last line, written out by the app: "Mia added Milk · 2:10 PM"."""

    action: Literal["added", "checked"]
    text: str
    member_id: str | None  # None: Everyone (the wall screen, nobody tapped)
    at: datetime


class ListOut(BaseModel):
    id: str
    name: str
    kind: ListKindName
    sort: int
    open_count: int  # still to get or do ("12 to get")
    done_count: int  # checked, not cleared
    due_count: int  # open items due today or before ("1 for today")
    last_change: LastChange | None
    created_by_member_id: str | None


class ListIn(BaseModel):
    name: Name
    kind: ListKindName | None = None  # None: guessed from the name (Groceries, Packing: beach…)


class ListPatch(BaseModel):
    name: Name | None = None
    kind: ListKindName | None = None


class OrderIn(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=200)


class ItemOut(BaseModel):
    id: str
    list_id: str
    text: str
    note: str | None
    quantity: str | None
    due_date: date | None
    assigned_member_id: str | None
    checked_at: datetime | None
    checked_by_member_id: str | None
    created_by_member_id: str | None
    created_at: datetime
    position: int
    version: int


class ListDetailOut(BaseModel):
    list: ListOut
    items: list[ItemOut]  # open, in their order
    done: list[ItemOut]  # checked and not cleared, most recent first
    usuals: list[str]  # what this list often has, not on it now (the Usuals strip)


class ItemIn(BaseModel):
    text: ItemText
    note: Note | None = None
    quantity: Quantity | None = None
    due_date: date | None = None
    assigned_member_id: str | None = None


class ItemsIn(BaseModel):
    """One or several items ("Milk, eggs, bread" is split by the app)."""

    items: list[ItemIn] = Field(min_length=1, max_length=50)


class ItemsAdded(BaseModel):
    items: list[ItemOut]  # what was added
    already: list[str]  # what was on the list already, still to get, so not added twice


class ItemPatch(BaseModel):
    """Only what's sent changes. Empty text clears a note or quantity."""

    text: ItemText | None = None
    note: Note | None = None
    quantity: Quantity | None = None
    due_date: date | None = None
    clear_due_date: bool = False
    assigned_member_id: str | None = None
    clear_assignee: bool = False
    position: int | None = Field(default=None, ge=0)
    checked: bool | None = None


class IdsIn(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=500)


class ClearedOut(BaseModel):
    """What Clear done took away, for Undo (POST lists/{id}/restore-items)."""

    ids: list[str]


class TodoItemOut(ItemOut):
    list_name: str
    list_kind: ListKindName


class TodoOut(BaseModel):
    """The Today panel's To do: items still open that are due on the day or before, the oldest
    first."""

    date: date
    items: list[TodoItemOut]


class RemovedListOut(BaseModel):
    id: str
    name: str
    item_count: int
    deleted_at: datetime


class RemovedItemOut(BaseModel):
    id: str
    list_id: str
    list_name: str
    text: str
    deleted_at: datetime


class RemovedOut(BaseModel):
    """Recently removed (the last 7 days), newest first. Cleared items aren't here: Clear done
    has its Undo, and the list keeps them as its history."""

    lists: list[RemovedListOut]
    items: list[RemovedItemOut]
