from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

MemberName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]
HouseholdName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)
]
Clock24 = Annotated[str, StringConstraints(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")]
PersonColor = Literal[
    "clay",
    "olive",
    "moss",
    "sea",
    "sky",
    "iris",
    "berry",
    "rose",
    "copper",
    "bark",
    "slate",
    "lime",
]
RoleName = Literal["parent", "kid"]
ThemeName = Literal["auto", "light", "dark"]
TextSizeName = Literal["small", "standard", "large", "xl"]
HomeViewName = Literal["week", "rolling", "today", "people"]
DisplayStartName = Literal["last", "home"]
WeekLayoutName = Literal["agenda", "hours"]
TimeFormat = Literal["12h", "24h"]
RailSide = Literal["left", "right"]
Orientation = Literal["auto", "landscape", "portrait"]
SleepModeName = Literal["dim_clock", "screen_off"]
PanelSize = Literal["s", "m", "l"]


class MemberOut(BaseModel):
    id: str
    name: str
    role: RoleName
    color: PersonColor
    color_word: str  # "Red", "Teal": what a screen reader says and the picker shows
    birthday: date | None
    avatar_url: str | None
    archived: bool


class MemberCreate(BaseModel):
    name: MemberName
    role: RoleName = "parent"
    color: PersonColor | None = None  # None: the next color nobody has
    birthday: date | None = None


class MemberUpdate(BaseModel):
    name: MemberName | None = None
    role: RoleName | None = None
    color: PersonColor | None = None
    birthday: date | None = None  # send null to clear it


class SettingsOut(BaseModel):
    household_name: str
    timezone: str  # the one in effect: the household's, else TZ, else UTC
    timezone_chosen: bool  # False until the household picks one (TZ or UTC is a fallback)
    week_starts_on: int  # 0 Monday … 6 Sunday
    time_format: TimeFormat
    theme: ThemeName
    daylight_tint: bool
    text_size: TextSizeName
    display_home_view: HomeViewName
    display_start: DisplayStartName  # after a refresh or a restart: where it left off, or home
    display_return_minutes: int
    display_rail_side: RailSide
    display_rail_compact: bool  # the rail shows only its icons (ADR 0029)
    display_controls_bottom: bool
    display_show_today_panel: bool
    display_orientation: Orientation
    display_sounds: bool
    display_dim_past: bool
    display_reduce_motion: bool
    display_week_layout: WeekLayoutName  # how the Week board draws a day (ADR 0028)
    show_tips: bool  # a tip under the board on the wall and laptops
    default_reminder_minutes: int | None  # events with no reminder of their own (ADR 0034)
    backups_enabled: bool  # a checked copy every night (ADR 0034)
    backups_keep_daily: int
    backups_keep_weekly: int
    sleep_from: str | None
    sleep_to: str | None
    sleep_mode: SleepModeName
    dim_from: str | None
    dim_level: int
    update_check: bool
    update_check_locked: bool  # SUNROOM_UPDATE_CHECK=0 keeps it off
    kid_safe_editing: bool
    has_pin: bool
    pin_length: int | None
    location_label: str | None
    latitude: float | None
    longitude: float | None
    setup_complete: bool


class SettingsUpdate(BaseModel):
    household_name: HouseholdName | None = None
    timezone: Annotated[str, StringConstraints(max_length=64)] | None = None
    week_starts_on: Annotated[int, Field(ge=0, le=6)] | None = None
    time_format: TimeFormat | None = None
    theme: ThemeName | None = None
    daylight_tint: bool | None = None
    text_size: TextSizeName | None = None
    display_home_view: HomeViewName | None = None
    display_start: DisplayStartName | None = None
    display_return_minutes: Literal[0, 2, 5, 10] | None = None
    display_rail_side: RailSide | None = None
    display_rail_compact: bool | None = None
    display_controls_bottom: bool | None = None
    display_show_today_panel: bool | None = None
    display_orientation: Orientation | None = None
    display_sounds: bool | None = None
    display_dim_past: bool | None = None
    display_reduce_motion: bool | None = None
    display_week_layout: WeekLayoutName | None = None
    show_tips: bool | None = None
    # Minutes before, for events with no reminder of their own; send null for none.
    default_reminder_minutes: Literal[5, 10, 15, 30, 60, 120, 1440] | None = None
    backups_enabled: bool | None = None
    # One daily copy at least, so the newest is always kept; the caps keep a Stepper usable.
    backups_keep_daily: Annotated[int, Field(ge=1, le=30)] | None = None
    backups_keep_weekly: Annotated[int, Field(ge=0, le=12)] | None = None
    sleep_from: Clock24 | None = None  # send null (with sleep_to) to turn sleep off
    sleep_to: Clock24 | None = None
    sleep_mode: SleepModeName | None = None
    dim_from: Clock24 | None = None  # send null to stop dimming
    dim_level: Literal[20, 40, 60] | None = None
    update_check: bool | None = None
    kid_safe_editing: bool | None = None
    location_label: Annotated[str, StringConstraints(max_length=120)] | None = None
    latitude: Annotated[float, Field(ge=-90, le=90)] | None = None
    longitude: Annotated[float, Field(ge=-180, le=180)] | None = None


class KioskPanelOut(BaseModel):
    key: str
    position: int
    visible: bool
    size: PanelSize


class KioskPanelIn(BaseModel):
    key: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")]
    visible: bool = True
    size: PanelSize = "m"


class KioskLayoutIn(BaseModel):
    panels: Annotated[list[KioskPanelIn], Field(max_length=40)]


class KioskCommandIn(BaseModel):
    command: Literal["reload", "wake", "screensaver", "show_event"]
    event_key: Annotated[str, StringConstraints(max_length=120)] | None = None


class AllowEntryIn(BaseModel):
    target: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
    label: Annotated[str, StringConstraints(strip_whitespace=True, max_length=80)] = ""


class AllowEntryOut(BaseModel):
    id: str
    target: str
    label: str
    created_at: datetime
