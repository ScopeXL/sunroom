"""The agent's API shapes (docs/M7.md, "The agent's API"). ``sunroom-kiosk openapi`` writes them
out and ``just api-types`` turns them into ``frontend/src/api/screen-schema.d.ts``.

Every name starts with ``Screen``: the frontend has the server's shapes too, and a name used by
both apps would be one more thing to read twice.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

type ScreenPlatform = Literal["pi", "linux", "macos", "windows"]
type ScreenSession = Literal["wayland", "x11", "desktop"]
type ScreenCapability = Literal[
    "restart",
    "shutdown",
    "update",
    "wifi",
    "rotate",
    "brightness",
    "quit",
    "run_sunroom",
    "update_sunroom",
]
type ScreenFoundHow = Literal["discovered", "typed", "local"]
type ScreenUpdateCheck = Literal["nightly", "off"]
type ScreenUpdateState = Literal["unknown", "up_to_date", "available", "installing", "failed"]
type ScreenRotation = Literal[0, 90, 180, 270]
type ScreenBrightness = Literal["ddc", "sysfs", "none"]
type ScreenNetworkKind = Literal["wifi", "wired", "none"]

Address = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]


class ScreenErrorBody(BaseModel):
    code: str
    message: str


class ScreenErrorOut(BaseModel):
    """Every refusal, in the server's own envelope: a plain-English message, never a trace."""

    error: ScreenErrorBody


class ScreenSunroomOut(BaseModel):
    """The Sunroom this screen shows."""

    url: str
    id: str | None  # the server's instance id (GET /api/discover); None for an older server
    name: str | None  # the household's name, when the server tells a local address
    found: ScreenFoundHow
    reachable: bool  # its /api/health answered the last time the agent asked
    version: str | None = None  # what the Sunroom said it runs, when it said


class ScreenNetworkOut(BaseModel):
    kind: ScreenNetworkKind
    ssid: str | None  # the Wi-Fi network's name
    ip: str | None
    strength: int | None  # 0 to 100, Wi-Fi only


class ScreenUpdateOut(BaseModel):
    check: ScreenUpdateCheck  # nightly: installed overnight by itself; off: only Update Now
    state: ScreenUpdateState
    installed: str
    latest: str | None
    checked_at: str | None  # ISO time of the last check
    message: str | None  # a failure, in plain words
    # An all-in-one Pi: the Sunroom running on this screen is older than the newest release, and
    # this screen can update it (Update Sunroom Too).
    sunroom_outdated: bool = False


class ScreenDisplayOut(BaseModel):
    rotation: ScreenRotation
    brightness_method: ScreenBrightness


class ScreenStateOut(BaseModel):
    """``GET /api/screen``: everything This Screen and the screen's own pages show."""

    version: str
    platform: ScreenPlatform
    model: str  # "Raspberry Pi 5 Model B", "Mac", "PC"
    session: ScreenSession
    capabilities: list[ScreenCapability]
    sunroom: ScreenSunroomOut | None
    network: ScreenNetworkOut
    update: ScreenUpdateOut
    display: ScreenDisplayOut
    open_url: str | None  # the wall's address with this screen's parameters, once one is set


class ScreenWifiOut(BaseModel):
    """One Wi-Fi network in range, or one this screen has joined before."""

    id: str | None  # a saved network's own name in the system, for Forget; None if never joined
    ssid: str
    strength: int  # 0 to 100
    secured: bool
    connected: bool
    saved: bool


class ScreenWifiListOut(BaseModel):
    networks: list[ScreenWifiOut]


class ScreenWifiJoinIn(BaseModel):
    ssid: Annotated[str, StringConstraints(min_length=1, max_length=32)]
    password: Annotated[str, StringConstraints(max_length=63)] = ""


class ScreenFoundOut(BaseModel):
    """A Sunroom found on the network (or the one an address check reached)."""

    url: str
    id: str | None
    name: str | None
    version: str | None
    setup_complete: bool | None
    older: bool  # answers only the older routes (no /api/discover): shown as "A Sunroom"


class ScreenScanOut(BaseModel):
    scanning: bool
    found: list[ScreenFoundOut]


class ScreenCheckIn(BaseModel):
    url: Address


class ScreenCheckOut(BaseModel):
    ok: bool
    sunroom: ScreenFoundOut | None
    message: str | None  # why not, in plain words


class ScreenSaveIn(BaseModel):
    url: Address
    found: Literal["discovered", "typed"]


class ScreenUpdatePolicyIn(BaseModel):
    check: ScreenUpdateCheck


class ScreenRotationIn(BaseModel):
    rotation: ScreenRotation


class ScreenOpenIn(BaseModel):
    page: Literal["sunroom", "settings"]


class ScreenAcceptedOut(BaseModel):
    """An action has started; what it does next arrives on ``/api/screen/events``."""

    ok: bool = True


class ScreenAboutOut(BaseModel):
    """``GET /api/screen/about``: the Help sheet (never a password or the household's name)."""

    version: str
    platform: ScreenPlatform
    model: str
    system: str  # "Raspberry Pi OS (trixie)", "macOS 26.1", "Windows 11"
    browser: str | None
    hostname: str
    ip: str | None
    uptime_s: int
    sunroom_url: str | None
    log: list[str] = Field(default_factory=list[str])  # the last 50 lines


class ScreenProgressOut(BaseModel):
    """``update.progress`` and ``run.progress`` on the event stream."""

    percent: int
    step: str
    message: str | None = None  # why a run stopped, in the family's words (run.progress only)
