"""The screen's settings file, ``~/.config/sunroom-kiosk/config`` (PLAN §13.2, docs/M7.md).

One ``KEY=value`` line per setting, quoted for bash, so ``kiosk/install.sh`` and the uninstaller
can still source it and a person can still edit it by hand. The agent is the source of truth
while it runs: it reads the file at start and writes it back when This Screen changes something,
keeping every line it doesn't own (comments, keys it doesn't know) where they were.

The installer's keys: SUNROOM_URL, SUNROOM_SESSION, SUNROOM_OUTPUT, SUNROOM_ROTATE,
SUNROOM_SCREEN_HELPER, SUNROOM_BRIGHTNESS, SUNROOM_DDC_BUS, SUNROOM_BACKLIGHT and SUNROOM_MODE.
The agent's own: SUNROOM_ID (the server's instance id, so a moved server is found again),
SUNROOM_FOUND (discovered, typed or local) and SUNROOM_UPDATE_CHECK (nightly or off).
"""

from __future__ import annotations

import os
import re
import shlex
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

type Found = Literal["discovered", "typed", "local"]
type UpdateCheck = Literal["nightly", "off"]
type Brightness = Literal["auto", "ddc", "sysfs", "none"]

ROTATIONS = (0, 90, 180, 270)
KEY = re.compile(r"[A-Z][A-Z0-9_]*")


def config_dir() -> Path:
    """Where the settings and the browser's profile live: ``~/.config/sunroom-kiosk`` on Linux
    and macOS (the installer's place since 0.6.0), ``%LOCALAPPDATA%\\sunroom-kiosk`` on Windows."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / "sunroom-kiosk"
    return Path.home() / ".config" / "sunroom-kiosk"


def config_file() -> Path:
    return config_dir() / "config"


@dataclass(frozen=True)
class Config:
    url: str | None = None  # the Sunroom this screen shows; None until one is chosen
    sunroom_id: str | None = None
    found: Found | None = None
    session: str = ""  # wayland or x11 on Linux (empty: worked out at start)
    output: str = ""  # the screen's connector (HDMI-A-1, DSI-1)
    rotate: int = 0
    screen_helper: bool = True
    brightness: Brightness = "auto"
    ddc_bus: str = ""
    backlight: str = ""
    mode: str = ""  # the installer's: all, display or server
    update_check: UpdateCheck | None = None  # None: the default, Install overnight

    def with_sunroom(self, url: str | None, sunroom_id: str | None, found: Found | None) -> Config:
        return replace(self, url=url, sunroom_id=sunroom_id, found=found)


def parse_values(text: str) -> dict[str, str]:
    """The ``KEY=value`` lines (written with ``printf %q`` or ``shlex.quote``), parsed and never
    run. Comments, blank lines and anything else are skipped."""
    values: dict[str, str] = {}
    for line in text.splitlines():
        key, sep, raw = line.strip().partition("=")
        if not sep or not KEY.fullmatch(key):
            continue
        try:
            words = shlex.split(raw, comments=True)
        except ValueError:  # an unclosed quote
            continue
        values[key] = words[0] if words else ""
    return values


def _pick(values: dict[str, str], key: str, pattern: str, default: str = "") -> str:
    value = values.get(key, "")
    return value if re.fullmatch(pattern, value) else default


def _found(value: str) -> Found | None:
    match value:
        case "discovered" | "typed" | "local":
            return value
        case _:
            return None


def _update_check(value: str) -> UpdateCheck | None:
    match value:
        case "nightly" | "off":
            return value
        case _:
            return None


def _brightness(value: str) -> Brightness:
    match value:
        case "auto" | "ddc" | "sysfs" | "none":
            return value
        case _:
            return "auto"


def from_values(values: dict[str, str]) -> Config:
    url = values.get("SUNROOM_URL", "").strip().rstrip("/")
    rotate = _pick(values, "SUNROOM_ROTATE", r"0|90|180|270", "0")
    return Config(
        url=url if re.match(r"https?://", url, re.IGNORECASE) else None,
        sunroom_id=_pick(values, "SUNROOM_ID", r"[0-9a-fA-F-]{8,64}") or None,
        found=_found(values.get("SUNROOM_FOUND", "")),
        session=_pick(values, "SUNROOM_SESSION", r"wayland|x11"),
        output=_pick(values, "SUNROOM_OUTPUT", r"[A-Za-z0-9-]+"),
        rotate=int(rotate),
        screen_helper=values.get("SUNROOM_SCREEN_HELPER", "yes") != "no",
        brightness=_brightness(values.get("SUNROOM_BRIGHTNESS", "auto")),
        ddc_bus=_pick(values, "SUNROOM_DDC_BUS", r"[0-9]+"),
        backlight=_pick(values, "SUNROOM_BACKLIGHT", r"[A-Za-z0-9][A-Za-z0-9_.:-]*"),
        mode=_pick(values, "SUNROOM_MODE", r"all|display|server"),
        update_check=_update_check(values.get("SUNROOM_UPDATE_CHECK", "")),
    )


def to_values(config: Config) -> dict[str, str]:
    return {
        "SUNROOM_URL": config.url or "",
        "SUNROOM_ID": config.sunroom_id or "",
        "SUNROOM_FOUND": config.found or "",
        "SUNROOM_SESSION": config.session,
        "SUNROOM_OUTPUT": config.output,
        "SUNROOM_ROTATE": str(config.rotate),
        "SUNROOM_SCREEN_HELPER": "yes" if config.screen_helper else "no",
        "SUNROOM_BRIGHTNESS": config.brightness,
        "SUNROOM_DDC_BUS": config.ddc_bus,
        "SUNROOM_BACKLIGHT": config.backlight,
        "SUNROOM_MODE": config.mode,
        "SUNROOM_UPDATE_CHECK": config.update_check or "",
    }


HEADER = (
    "# Sunroom Screen's settings (docs/KIOSK.md). Sunroom Screen keeps this file up to date;\n"
    "# a change by hand takes effect after: systemctl --user restart sunroom-kiosk\n"
)


def render(existing: str, config: Config) -> str:
    """``existing`` with each known key's line set to ``config``'s value, in place; keys that
    weren't there are added at the end. Every other line stays as it was."""
    wanted = to_values(config)
    seen: set[str] = set()
    lines: list[str] = []
    for line in existing.splitlines():
        key, sep, _ = line.strip().partition("=")
        if sep and key in wanted:
            if key in seen:
                continue  # a key twice: the first line holds it
            seen.add(key)
            lines.append(f"{key}={shlex.quote(wanted[key])}")
        else:
            lines.append(line)
    if not existing.strip():
        lines = [str(line) for line in HEADER.rstrip("\n").splitlines()]
    for key, value in wanted.items():
        if key not in seen:
            lines.append(f"{key}={shlex.quote(value)}")
    return "\n".join(lines) + "\n"


def load(path: Path) -> Config:
    try:
        return from_values(parse_values(path.read_text(encoding="utf-8")))
    except OSError:
        return Config()


def save(path: Path, config: Config) -> None:
    """Write ``config`` into ``path`` atomically, keeping what else the file holds."""
    try:
        existing = path.read_text(encoding="utf-8")
    except OSError:
        existing = ""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(render(existing, config), encoding="utf-8")
    os.replace(tmp, path)
