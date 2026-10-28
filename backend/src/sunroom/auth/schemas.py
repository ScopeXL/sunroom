from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, StringConstraints

from sunroom.household.schemas import MemberOut

DeviceKindName = Literal["phone", "kiosk"]
DeviceFormName = Literal["screen", "phone", "tablet", "computer"]
Label = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
Pin = Annotated[str, StringConstraints(pattern=r"^\d{4,6}$")]


class LoginIn(BaseModel):
    password: Annotated[str, StringConstraints(max_length=256)]


class SessionOut(BaseModel):
    device_id: str
    device_kind: DeviceKindName
    device_label: str
    member: MemberOut | None  # who's using this device (always None on a wall screen)
    members: list[MemberOut]
    household_name: str
    is_parent: bool
    is_kid_device: bool
    has_pin: bool
    pin_length: int | None  # the PIN pad accepts as soon as this many digits are in
    grant_expires_at: datetime | None  # a parent-PIN grant on this device, until then


class MemberChoice(BaseModel):
    member_id: str | None


class DeviceLabelIn(BaseModel):
    label: Label


class DeviceOut(BaseModel):
    id: str
    label: str
    kind: DeviceKindName
    # What it is, for its icon: from its kind and the label it signed in with (ADR 0032).
    form: DeviceFormName
    member_name: str | None
    is_kid_device: bool
    created_at: datetime
    last_seen_at: datetime
    is_current: bool


class DeviceUpdate(BaseModel):
    label: Label | None = None
    is_kid_device: bool | None = None


class SignOutOthersIn(BaseModel):
    include_kiosks: bool = False


class JoinCodeOut(BaseModel):
    code: str  # "7K4M9X", what the QR code carries
    display: str  # "7K4 M9X", for reading out and typing
    url: str  # the QR code: this address + "/join#" + the code
    expires_at: datetime


class JoinIn(BaseModel):
    code: Annotated[str, StringConstraints(max_length=40)]


class PinSetIn(BaseModel):
    pin: Pin
    current_pin: Pin | None = None  # needed when unlocking with the PIN is what made you a parent


class PinVerifyIn(BaseModel):
    pin: Annotated[str, StringConstraints(max_length=12)]


class GrantOut(BaseModel):
    expires_at: datetime


class KioskPairingOut(BaseModel):
    code: str
    display: str
    poll_token: str  # secret: only the screen that asked holds it
    expires_in: int  # seconds
    expires_at: datetime
    pair_url: str  # the QR code on the screen: <address>/pair#<code>


class KioskPollOut(BaseModel):
    status: Literal["waiting", "paired", "expired"]
    session: SessionOut | None = None


class KioskPairIn(BaseModel):
    code: Annotated[str, StringConstraints(max_length=40)]
    label: Label = "Wall screen"


class KioskPasswordPairIn(BaseModel):
    password: Annotated[str, StringConstraints(max_length=256)]
    label: Label = "Wall screen"
