"""The kiosk browser's managed policy (docs/M7.md, "Browser facts the implementer must respect").

Two jobs. It quiets the browser (no sign-in, no password, translate or default-browser prompts,
no metrics, no promotions, no updates of its parts behind our back), and it lets the wall page
reach this agent on ``http://127.0.0.1``: Chrome 142's Local Network Access asks a page's
permission before it calls a local address, and a wall has nobody to say yes. The allowlist
names the *requesting* sites, and since ADR 0042 it is every site (``*``, a pattern the policy's
own documentation lists): this browser only ever shows the Sunroom this screen chose, the agent's
CORS admits no other origin, and the wall's CSP opens nothing else. So the policy is the same
for every address, right from the browser's first start, and choosing a Sunroom restarts
nothing. (Chrome 146's ``LoopbackNetworkAllowedForUrls`` would say the same more narrowly; a
Linux screen's installed root helper refuses keys it doesn't know, so the older key stays.)

Where each browser reads it:

* Linux: a JSON file, ``/etc/chromium/policies/managed/`` (Debian and Raspberry Pi OS),
  ``/etc/opt/chrome/policies/managed/`` (Google Chrome), ``/etc/opt/edge/policies/managed/``
  (Microsoft Edge). Root writes it: the root helper on a Pi, the installer elsewhere.
* macOS: the browser's preference domain (``com.google.Chrome``, ``org.chromium.Chromium``,
  ``com.microsoft.Edge``), written with ``defaults write``.
* Windows: ``HKCU\\Software\\Policies\\…``, a list as a subkey of numbered values.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal, cast

type BrowserKind = Literal["chromium", "chrome", "edge"]

FILE_NAME = "sunroom-kiosk.json"

QUIET: dict[str, Any] = {
    "MetricsReportingEnabled": False,
    "BackgroundModeEnabled": False,
    "PasswordManagerEnabled": False,
    "TranslateEnabled": False,
    "DefaultBrowserSettingEnabled": False,
    "BrowserSignin": 0,
    "PromotionsEnabled": False,
    "ComponentUpdatesEnabled": False,
}

# The only keys the root helper writes (kiosk/files/sunroom-kiosk-root checks them too).
ALLOWED_KEYS = frozenset(
    {*QUIET, "LocalNetworkAccessAllowedForUrls", "LocalNetworkAccessRestrictionsEnabled"}
)

# Edge's own, for Edge where the agent writes its policy itself (Windows' registry, a Mac's
# preferences). Edge runs without its kiosk mode (ADR 0040), so its welcome page, a full-tab
# "what's new" after an update and its recommendations would otherwise cover the wall. Never
# through Linux's root helper, whose copy of ALLOWED_KEYS a screen keeps from its install.
EDGE_QUIET: dict[str, Any] = {
    "HideFirstRunExperience": True,
    "PromotionalTabsEnabled": False,
    "ShowRecommendationsEnabled": False,
}


LINUX_DIRS: dict[BrowserKind, Path] = {
    "chromium": Path("/etc/chromium/policies/managed"),
    "chrome": Path("/etc/opt/chrome/policies/managed"),
    "edge": Path("/etc/opt/edge/policies/managed"),
}

MAC_DOMAINS: dict[BrowserKind, str] = {
    "chromium": "org.chromium.Chromium",
    "chrome": "com.google.Chrome",
    "edge": "com.microsoft.Edge",
}

WINDOWS_KEYS: dict[BrowserKind, str] = {
    "chromium": r"Software\Policies\Chromium",
    "chrome": r"Software\Policies\Google\Chrome",
    "edge": r"Software\Policies\Microsoft\Edge",
}


# Every page in this browser may call the agent on 127.0.0.1 without a prompt.
EVERY_SITE = "*"


def document() -> dict[str, Any]:
    """The policy for a screen, whichever Sunroom it shows (or none yet)."""
    return {
        **QUIET,
        "LocalNetworkAccessAllowedForUrls": [EVERY_SITE],
        "LocalNetworkAccessRestrictionsEnabled": True,
    }


def for_browser(kind: BrowserKind, policy: dict[str, Any]) -> dict[str, Any]:
    """``policy`` with Edge's own quiet keys for Edge (Windows and macOS only)."""
    return {**policy, **EDGE_QUIET} if kind == "edge" else policy


def own_keys(kind: BrowserKind) -> frozenset[str]:
    """Every key Sunroom Screen may write for that browser: what it clears again, and what the
    uninstaller takes out (Windows and macOS)."""
    return ALLOWED_KEYS.union(EDGE_QUIET) if kind == "edge" else ALLOWED_KEYS


def linux_path(kind: BrowserKind) -> Path:
    return LINUX_DIRS[kind] / FILE_NAME


def linux_json(policy: dict[str, Any]) -> str:
    return json.dumps(policy, indent=2, sort_keys=True) + "\n"


def valid(policy: object) -> bool:
    """What the root helper accepts: an object of known keys with plain values."""
    if not isinstance(policy, dict):
        return False
    for key, value in cast(dict[object, object], policy).items():
        if key not in ALLOWED_KEYS:
            return False
        if isinstance(value, list):
            if not all(isinstance(item, str) for item in cast(list[object], value)):
                return False
        elif not isinstance(value, bool | int | str):
            return False
    return True


def mac_commands(kind: BrowserKind, policy: dict[str, Any]) -> list[list[str]]:
    """``defaults write`` command lines that set ``policy`` for the browser on macOS."""
    domain = MAC_DOMAINS[kind]
    commands: list[list[str]] = []
    for key, value in sorted(policy.items()):
        if isinstance(value, bool):
            commands.append(
                ["defaults", "write", domain, key, "-bool", "true" if value else "false"]
            )
        elif isinstance(value, int):
            commands.append(["defaults", "write", domain, key, "-integer", str(value)])
        elif isinstance(value, list):
            items = [str(item) for item in cast(list[object], value)]
            commands.append(["defaults", "write", domain, key, "-array", *items])
        else:
            commands.append(["defaults", "write", domain, key, "-string", str(value)])
    return commands


type RegistryValue = tuple[str, str, Literal["REG_DWORD", "REG_SZ"], int | str]


def windows_values(kind: BrowserKind, policy: dict[str, Any]) -> list[RegistryValue]:
    """(key under HKEY_CURRENT_USER, value name, type, data) for each setting: a flag or a
    number is a DWORD, text a string, and a list a subkey of values named 1, 2, …"""
    base = WINDOWS_KEYS[kind]
    values: list[RegistryValue] = []
    for key, value in sorted(policy.items()):
        if isinstance(value, bool):
            values.append((base, key, "REG_DWORD", 1 if value else 0))
        elif isinstance(value, int):
            values.append((base, key, "REG_DWORD", value))
        elif isinstance(value, list):
            for index, item in enumerate(cast(list[object], value), start=1):
                values.append((rf"{base}\{key}", str(index), "REG_SZ", str(item)))
        else:
            values.append((base, key, "REG_SZ", str(value)))
    return values
