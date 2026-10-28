"""The household's own settings, app metadata, members, the display's panels and the network
allowlist (PLAN §10.1)."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import Boolean, CheckConstraint, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from sunroom.db.backup import KEEP_DAILY, KEEP_WEEKLY
from sunroom.db.base import Base
from sunroom.db.types import IsoDate, UTCDateTime, new_id, utcnow

# The twelve person colors (UX §7): the first eight, then four appended in 0.12.0 so nobody's
# color moved (ADR 0034). Users see plain words (Red, Olive, …); see PERSON_COLOR_WORDS.
PERSON_COLORS = (
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
)
PERSON_COLOR_WORDS = {
    "clay": "Red",
    "olive": "Olive",
    "moss": "Green",
    "sea": "Teal",
    "sky": "Blue",
    "iris": "Purple",
    "berry": "Plum",
    "rose": "Pink",
    "copper": "Orange",
    "bark": "Brown",
    "slate": "Gray",
    "lime": "Lime",
}


class Role(StrEnum):
    PARENT = "parent"
    KID = "kid"  # shown to the family as Child (M6); the stored value stays "kid"


class Theme(StrEnum):
    AUTO = "auto"
    LIGHT = "light"
    DARK = "dark"


class TextSize(StrEnum):
    SMALL = "small"  # for a 1080p screen read up close (ADR 0029)
    STANDARD = "standard"
    LARGE = "large"
    XL = "xl"


class HomeView(StrEnum):
    WEEK = "week"
    # Yesterday, today and the five days after: a view of its own since ADR 0042 (it was the
    # Week view's Rolling week switch, ADR 0033).
    ROLLING = "rolling"
    TODAY = "today"
    PEOPLE = "people"


class DisplayStart(StrEnum):
    """What a screen shows after a refresh, an update or a restart (ADR 0030): what it was
    showing, or the home view."""

    LAST = "last"
    HOME = "home"


class WeekLayout(StrEnum):
    """How the wall's Week board draws a day (ADR 0028): stacked chips, or an hour grid."""

    AGENDA = "agenda"
    HOURS = "hours"


class SleepMode(StrEnum):
    DIM_CLOCK = "dim_clock"
    SCREEN_OFF = "screen_off"


class Household(Base):
    """Exactly one row (id = 1). ``onboarded_at`` NULL means setup hasn't happened (PLAN §12.1)."""

    __tablename__ = "household"
    __table_args__ = (CheckConstraint("id = 1", name="single_row"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    name: Mapped[str] = mapped_column(String(80), default="Our home")
    timezone: Mapped[str | None] = mapped_column(String(64), default=None)
    week_starts_on: Mapped[int] = mapped_column(Integer, default=6)  # 0 Monday … 6 Sunday
    time_format: Mapped[str] = mapped_column(String(4), default="12h")
    theme: Mapped[str] = mapped_column(String(8), default=Theme.AUTO)
    daylight_tint: Mapped[bool] = mapped_column(Boolean, default=True)
    text_size: Mapped[str] = mapped_column(String(10), default=TextSize.STANDARD)
    display_home_view: Mapped[str] = mapped_column(String(10), default=HomeView.WEEK)
    # Settings → Display → When it starts: where the screen left off, or the home view (ADR 0030).
    display_start: Mapped[str] = mapped_column(String(8), default=DisplayStart.LAST)
    display_return_minutes: Mapped[int] = mapped_column(Integer, default=5)  # 0 = never
    display_rail_side: Mapped[str] = mapped_column(String(8), default="left")
    # Settings → Display → Compact rail: only the rooms' icons, for a wider board (ADR 0029).
    display_rail_compact: Mapped[bool] = mapped_column(Boolean, default=False)
    display_controls_bottom: Mapped[bool] = mapped_column(Boolean, default=False)
    display_show_today_panel: Mapped[bool] = mapped_column(Boolean, default=True)
    display_orientation: Mapped[str] = mapped_column(String(10), default="auto")
    display_sounds: Mapped[bool] = mapped_column(Boolean, default=False)
    display_dim_past: Mapped[bool] = mapped_column(Boolean, default=True)
    display_reduce_motion: Mapped[bool] = mapped_column(Boolean, default=False)
    # Settings → Display → Week layout: Agenda (stacked chips) or Hours (the grid), ADR 0028;
    # Hours for a new household since ADR 0042.
    display_week_layout: Mapped[str] = mapped_column(String(8), default=WeekLayout.HOURS)
    # Settings → Display → Show tips: a strip under the board on the wall and laptops; on by
    # default since ADR 0034 (it was off).
    show_tips: Mapped[bool] = mapped_column(Boolean, default=True)
    sleep_from: Mapped[str | None] = mapped_column(String(5), default=None)  # "HH:MM"
    sleep_to: Mapped[str | None] = mapped_column(String(5), default=None)
    sleep_mode: Mapped[str] = mapped_column(String(12), default=SleepMode.DIM_CLOCK)
    # The evening: the screen dims from this time until it sleeps (with a sleep schedule only).
    dim_from: Mapped[str | None] = mapped_column(String(5), default=None)  # "HH:MM"
    dim_level: Mapped[int] = mapped_column(Integer, default=40)  # percent of full brightness
    # Settings → About → "Check for updates daily" (off by default: it reaches GitHub).
    update_check: Mapped[bool] = mapped_column(Boolean, default=False)
    kid_safe_editing: Mapped[bool] = mapped_column(Boolean, default=True)
    # Where quick add puts an event when nothing else says (the Home calendar).
    default_calendar_id: Mapped[str | None] = mapped_column(
        ForeignKey("calendars.id"), default=None
    )
    # Settings → Calendars & Accounts → Default reminder: minutes before, for events with no
    # reminder of their own (None: none). Resolved by the wall, not stored on events (ADR 0034).
    default_reminder_minutes: Mapped[int | None] = mapped_column(Integer, default=None)
    # Settings → Backup (ADR 0034): a checked copy every night, and how many stay.
    backups_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    backups_keep_daily: Mapped[int] = mapped_column(Integer, default=KEEP_DAILY)
    backups_keep_weekly: Mapped[int] = mapped_column(Integer, default=KEEP_WEEKLY)
    parent_pin_hash: Mapped[str | None] = mapped_column(String(160), default=None)
    # How many digits, so the PIN pad accepts as soon as they're typed (UX §4).
    pin_length: Mapped[int | None] = mapped_column(Integer, default=None)
    pin_updated_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), default=None)
    onboarded_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), default=None)
    location_label: Mapped[str | None] = mapped_column(String(120), default=None)
    latitude: Mapped[float | None] = mapped_column(Float, default=None)
    longitude: Mapped[float | None] = mapped_column(Float, default=None)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)


class AppMeta(Base):
    """Exactly one row (id = 1): values the app itself manages across restarts."""

    __tablename__ = "app_meta"
    __table_args__ = (CheckConstraint("id = 1", name="single_row"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    auth_epoch: Mapped[int] = mapped_column(Integer, default=1)
    # The household password from the setup wizard (scrypt; auth/password.py). Unused while
    # APP_PASSWORD is set, which always wins.
    password_hash: Mapped[str | None] = mapped_column(String(200), default=None)
    password_fp: Mapped[str | None] = mapped_column(String(64), default=None)
    secret_key_check: Mapped[str | None] = mapped_column(String(64), default=None)
    last_boot_version: Mapped[str | None] = mapped_column(String(32), default=None)
    # This Sunroom's own id (UUIDv7), made once by the migration or at boot. It travels with
    # backups and restores, so a screen finds the same Sunroom again at a new address
    # (GET /api/discover, ADR 0035).
    instance_id: Mapped[str | None] = mapped_column(String(36), default=None)


class Member(Base):
    """A person in the household. Attribution and color, never access control (PLAN §10.1)."""

    __tablename__ = "members"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(40))
    role: Mapped[str] = mapped_column(String(8), default=Role.PARENT)
    color: Mapped[str] = mapped_column(String(8))
    avatar_photo_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("photos.id", ondelete="SET NULL"), default=None
    )
    birthday: Mapped[date | None] = mapped_column(IsoDate(), default=None)
    sort: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    archived_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), default=None)


class KioskPanel(Base):
    """The display's Today panel order (PLAN §6.5). Rows of a disabled plugin stay, unrendered."""

    __tablename__ = "kiosk_panels"

    panel_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    visible: Mapped[bool] = mapped_column(Boolean, default=True)
    size: Mapped[str] = mapped_column(String(8), default="m")


class NetworkAllowEntry(Base):
    """A private address an account or photo source may reach (PLAN §12.6)."""

    __tablename__ = "network_allowlist"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    target: Mapped[str] = mapped_column(String(255))  # a host name, an IP or a CIDR
    label: Mapped[str] = mapped_column(String(80), default="")
    created_by_member_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("members.id", ondelete="SET NULL"), default=None
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
