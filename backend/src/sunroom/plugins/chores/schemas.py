"""The chores API's shapes (PLAN §11.3, UX §4 "Chores room", "Stars & rewards", "Routine runner",
§5 "Chores"). Stars are the user's word for points (UX §2)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

from sunroom.calendar.schemas import RepeatPartsOut

ModeName = Literal["fixed", "rotate", "any"]
CompletionStatusName = Literal["done", "pending", "rejected"]
RedemptionStatusName = Literal["requested", "approved", "denied", "cancelled"]
Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
Description = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]
Icon = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=32)]
HHMM = Annotated[str, StringConstraints(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")]
Stars = Annotated[int, Field(ge=0, le=100)]
Weekday = Annotated[int, Field(ge=0, le=6)]  # 0 Monday … 6 Sunday


# ---- chores ---------------------------------------------------------------------------------


class ChoreOut(BaseModel):
    id: str
    title: str
    description: str | None
    icon: str | None
    points: int
    rrule: str | None
    repeat_text: str  # "Every day", "Every week on Mon, Wed and Fri", "Doesn't repeat" (English)
    repeat: RepeatPartsOut | None = None  # the same in parts, for the family's language
    start_date: date
    due_time: str | None  # "17:00": "by 5:00 PM"
    assignee_mode: ModeName
    assignee_member_ids: list[str]  # in turn order
    rotation_index: int
    requires_approval: bool | None  # None: the plugin's setting
    active: bool
    # The next day it's due, today or later (ADR 0036); None: finished, nothing ahead.
    next_due: date | None


class ChoreIn(BaseModel):
    title: Title
    description: Description | None = None
    icon: Icon | None = None
    points: Stars = 0
    rrule: str | None = None  # None: one day only
    start_date: date | None = None  # None: today
    due_time: HHMM | None = None
    assignee_mode: ModeName = "fixed"
    assignee_member_ids: list[str] = Field(default_factory=list[str], max_length=20)
    rotation_index: int = Field(default=0, ge=0)
    requires_approval: bool | None = None


class ChorePatch(BaseModel):
    """Only what's sent changes."""

    title: Title | None = None
    description: Description | None = None
    icon: Icon | None = None
    points: Stars | None = None
    rrule: str | None = None
    clear_rrule: bool = False
    start_date: date | None = None
    due_time: HHMM | None = None
    clear_due_time: bool = False
    assignee_mode: ModeName | None = None
    assignee_member_ids: list[str] | None = Field(default=None, max_length=20)
    rotation_index: int | None = Field(default=None, ge=0)
    requires_approval: bool | None = None
    clear_requires_approval: bool = False  # back to the plugin's setting
    active: bool | None = None


class DayIn(BaseModel):
    date: date


class CompletionOut(BaseModel):
    id: str
    chore_id: str
    due_date: date
    member_id: str  # who got the credit: "Done by Mia"
    completed_at: datetime
    points_awarded: int
    status: CompletionStatusName


class CompleteIn(BaseModel):
    due_date: date
    # Whose box, or who did it. A wall screen says who tapped with X-Sunroom-Member instead;
    # a phone means the person using it, unless a parent's phone ticks someone else's.
    member_id: str | None = None


class StarsOut(BaseModel):
    member_id: str
    balance: int
    held: int  # asked for, not yet answered: "Ask for it" can't spend these twice
    week: int  # earned this week: "+12 this week"
    streak: int  # "6 days in a row"


class CompleteOut(BaseModel):
    completion: CompletionOut
    stars: StarsOut | None  # the person's, when stars are on
    all_done: bool  # that ticked the last box in its column today: "All done, Mia!"


class BoxOut(BaseModel):
    """One box to tick on a day."""

    chore_id: str
    title: str
    icon: str | None
    points: int
    due_time: str | None
    due_date: date  # the day it's for
    since: date | None  # a one-day chore still to do from an earlier day: "since Mon"
    owner_id: str | None  # a fixed chore's person; None: the Anyone column
    turn_id: str | None  # a rotating chore: whose turn it is ("Mia's turn")
    needs_approval: bool
    completion: CompletionOut | None  # done, or waiting for a parent


class RoutineStepOut(BaseModel):
    id: str
    title: str
    icon: str | None
    position: int


class RoutineRunOut(BaseModel):
    """A child's routine on a day: its steps, what's checked, and whether its window is open."""

    routine_id: str
    member_id: str
    title: str
    icon: str | None
    points: int
    window_start: str
    window_end: str
    open_now: bool  # the day is today and the time is inside its window
    steps: list[RoutineStepOut]
    checked: list[str]  # step ids checked that day
    finished: bool


class ColumnOut(BaseModel):
    member_id: str | None  # None: Anyone
    done: int
    total: int
    boxes: list[BoxOut]
    routines: list[RoutineRunOut]  # the kid's routines that day (always empty for Anyone)


class WaitingOut(BaseModel):
    """A completion waiting for a parent's OK."""

    completion: CompletionOut
    title: str


class RedemptionOut(BaseModel):
    id: str
    reward_id: str
    reward_title: str
    member_id: str
    cost_points: int
    status: RedemptionStatusName
    requested_at: datetime
    decided_at: datetime | None
    decided_by_member_id: str | None


class DayOut(BaseModel):
    """GET chores/today: the Chores room, the Today panel's Chores today, Who's doing what."""

    date: date
    stars_on: bool
    rewards_on: bool
    routines_on: bool
    columns: list[ColumnOut]  # people with chores or routines, in household order; Anyone last
    stars: list[StarsOut]  # every person with a column (empty when stars are off)
    asked: list[RedemptionOut]  # rewards asked for, waiting for a parent
    waiting: list[WaitingOut]  # completions waiting for a parent


class WeekCellOut(BaseModel):
    date: date
    done: int
    total: int


class WeekColumnOut(BaseModel):
    member_id: str | None
    days: list[WeekCellOut]


class WeekOut(BaseModel):
    """GET chores/week: seven compact rows per column, the fridge-chart view."""

    start: date
    columns: list[WeekColumnOut]


class RemovedChoreOut(BaseModel):
    id: str
    title: str
    deleted_at: datetime


# ---- stars and rewards ----------------------------------------------------------------------


class PointsOut(BaseModel):
    stars: list[StarsOut]


class AdjustIn(BaseModel):
    # One child or several at once (ADR 0034): a ledger row each, the same stars and reason.
    member_ids: Annotated[list[str], Field(min_length=1, max_length=20)]
    points: Annotated[int, Field(ge=-1000, le=1000)]
    reason: Annotated[str, StringConstraints(strip_whitespace=True, max_length=120)] = ""


class RewardOut(BaseModel):
    id: str
    title: str
    cost_points: int
    icon: str | None
    active: bool


class RewardIn(BaseModel):
    title: Title
    cost_points: Annotated[int, Field(ge=1, le=10_000)]
    icon: Icon | None = None


class RewardPatch(BaseModel):
    title: Title | None = None
    cost_points: Annotated[int, Field(ge=1, le=10_000)] | None = None
    icon: Icon | None = None
    active: bool | None = None


class RewardsOut(BaseModel):
    rewards: list[RewardOut]
    stars: list[StarsOut]  # kids' balances, for "Mia has 18 of 30 stars"
    asked: list[RedemptionOut]  # waiting for a parent, oldest first
    recent: list[RedemptionOut]  # answered in the last 14 days, newest first


class RedeemIn(BaseModel):
    member_id: str | None = None  # as CompleteIn


# ---- routines -------------------------------------------------------------------------------


class StepIn(BaseModel):
    id: str | None = None  # an existing step keeps its checks
    title: Title
    icon: Icon | None = None


class RoutineOut(BaseModel):
    id: str
    title: str
    member_id: str | None  # None: every kid
    days: list[int]  # 0 Monday … 6 Sunday
    window_start: str
    window_end: str
    icon: str | None
    points: int
    active: bool
    steps: list[RoutineStepOut]


class RoutineIn(BaseModel):
    title: Title
    member_id: str | None = None
    days: list[Weekday] = Field(default_factory=lambda: [0, 1, 2, 3, 4, 5, 6], max_length=7)
    window_start: HHMM
    window_end: HHMM
    icon: Icon | None = None
    points: Stars = 0
    steps: list[StepIn] = Field(default_factory=list[StepIn], max_length=20)


class RoutinePatch(BaseModel):
    title: Title | None = None
    member_id: str | None = None
    every_kid: bool = False  # set member_id back to None
    days: list[Weekday] | None = Field(default=None, max_length=7)
    window_start: HHMM | None = None
    window_end: HHMM | None = None
    icon: Icon | None = None
    points: Stars | None = None
    active: bool | None = None


class StepsIn(BaseModel):
    steps: list[StepIn] = Field(max_length=20)


class CheckIn(BaseModel):
    date: date
    member_id: str | None = None  # as CompleteIn
    checked: bool = True


class FinishIn(BaseModel):
    date: date
    member_id: str | None = None  # as CompleteIn


class FinishOut(BaseModel):
    points_awarded: int  # 0 when it was already finished that day, or gives no stars
    stars: StarsOut | None


class RoutinesOut(BaseModel):
    """GET chores/routines: the routines as made in Settings, and each child's day of them."""

    routines: list[RoutineOut]
    runs: list[RoutineRunOut]
