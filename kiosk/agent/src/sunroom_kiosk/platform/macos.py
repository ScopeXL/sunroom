"""macOS (docs/M7.md T15): a Mac someone signs in to, where Sunroom Screen runs for that person
from a LaunchAgent (``~/Library/LaunchAgents/app.sunroom.kiosk.plist``, which kiosk/install.sh
writes), started again if it fails and not after Quit.

* **Power:** System Events' ``restart`` and ``shut down`` through ``osascript`` (macOS asks once
  whether Sunroom Screen may control System Events).
* **Sleep:** the screen helper keeps the display awake with ``caffeinate`` while the household's
  times say on, and puts it to sleep with ``pmset displaysleepnow`` (screen.py). No brightness:
  the page dims itself (``?dimmer=page``).
* **The network:** macOS joins Wi-Fi itself. The Network row says how the Mac is connected: the
  default route's interface, Wi-Fi when that is the Wi-Fi port (``networksetup``), else wired.
  Its network's name only when macOS gives it: since macOS 14.4 ``networksetup`` and
  ``ipconfig`` tell it only to a program with Location access, which a screen's agent hasn't
  (so mostly "Wi-Fi: connected"); no signal strength (``system_profiler`` is too slow for every
  30 s).
* **The browser's policy** with ``defaults write`` in the browser's own preferences (policy.py's
  ``mac_commands``), as this user. Chrome reads those as recommended policies; a Mac managed by
  a profile may override them, and then the browser asks once, on the screen.
"""

from __future__ import annotations

import platform as python_platform
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sunroom_kiosk import logs, policy
from sunroom_kiosk.platform.base import (
    UNINSTALL_UNIT,
    UNINSTALLER,
    CommandResult,
    NetworkStatus,
    Platform,
    PlatformError,
    Runner,
    Spawn,
    local_ip,
    run_command,
    spawn_detached,
    uninstaller_command,
)
from sunroom_kiosk.schemas import ScreenCapability, ScreenPlatform

log = logs.get("platform")

# networksetup's names for the Wi-Fi port (before macOS 10.7 it was AirPort); not translated.
WIFI_PORTS = ("Wi-Fi", "AirPort")
JOINED = "Current Wi-Fi Network:"


def interface_of(route: str) -> str | None:
    """The default route's interface (``en0``) from ``route -n get default``."""
    for line in route.splitlines():
        key, _, value = line.strip().partition(":")
        if key == "interface" and value.strip():
            return value.strip()
    return None


def wifi_devices(ports: str) -> set[str]:
    """The Wi-Fi port's devices from ``networksetup -listallhardwareports``."""
    devices: set[str] = set()
    port = ""
    for line in ports.splitlines():
        key, _, value = line.strip().partition(":")
        if key == "Hardware Port":
            port = value.strip()
        elif key == "Device" and port in WIFI_PORTS:
            devices.add(value.strip())
    return devices


def network_name(joined: str) -> str | None:
    """The network's name from ``networksetup -getairportnetwork``, if macOS said it."""
    for line in joined.splitlines():
        if line.strip().startswith(JOINED):
            name = line.strip()[len(JOINED) :].strip()
            return name or None
    return None


def hardware_model() -> str:
    """The Mac's model identifier (``Mac14,2``), from sysctl; empty when it doesn't say."""
    try:
        done = subprocess.run(
            ["/usr/sbin/sysctl", "-n", "hw.model"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except OSError, subprocess.TimeoutExpired:
        return ""
    return done.stdout.strip() if done.returncode == 0 else ""


def macos_version() -> str:
    return python_platform.mac_ver()[0]


class MacPlatform(Platform):
    def __init__(
        self,
        runner: Runner = run_command,
        root: Path = Path("/"),
        *,
        identifier: Callable[[], str] = hardware_model,
        release: Callable[[], str] = macos_version,
        uninstaller: Path = UNINSTALLER,
        spawn: Spawn = spawn_detached,
    ) -> None:
        super().__init__(runner, root)
        self.identifier = identifier
        self.release = release
        self.uninstaller = uninstaller
        self.spawn = spawn

    # ------------------------------------------------------------------ what it is

    @property
    def name(self) -> ScreenPlatform:
        return "macos"

    @property
    def model(self) -> str:
        found = self.identifier()
        return f"Mac ({found})" if found else "Mac"

    @property
    def system(self) -> str:
        found = self.release()
        return f"macOS {found}" if found else "macOS"

    def capabilities(self) -> list[ScreenCapability]:
        have: list[ScreenCapability] = ["restart", "shutdown", "update", "quit"]
        if self.uninstaller.is_file():
            have.append("uninstall")
        return have

    # ------------------------------------------------------------------ the machine

    async def _must(self, argv: list[str], what: str) -> CommandResult:
        result = await self.run(argv)
        if not result.ok:
            log.info("%s didn't work: %s", " ".join(argv[:2]), result.first_line())
            raise PlatformError(f"{what} didn't work. Try again in a moment.")
        return result

    async def restart(self) -> None:
        await self._must(
            ["osascript", "-e", 'tell application "System Events" to restart'], "Restarting"
        )

    async def shutdown(self) -> None:
        await self._must(
            ["osascript", "-e", 'tell application "System Events" to shut down'], "Shutting down"
        )

    async def uninstall(self, *, sunroom: bool, port: int) -> None:
        """uninstall.sh in a session of its own: launchd's stop of Sunroom Screen's job takes
        its process group, not this."""
        if not self.uninstaller.is_file():
            raise PlatformError("Uninstalling Sunroom Screen isn't something this screen can do.")
        argv = uninstaller_command(self.uninstaller, sunroom=sunroom)
        if not await self.spawn(argv, unit=UNINSTALL_UNIT):
            raise PlatformError("Sunroom Screen couldn't start its uninstaller. Try again.")

    # ------------------------------------------------------------------ the network

    async def network(self) -> NetworkStatus:
        route = await self.run(["route", "-n", "get", "default"])
        device = interface_of(route.output) if route.ok else None
        ip = local_ip()
        if device is None or ip is None:
            return NetworkStatus(kind="none")
        ports = await self.run(["networksetup", "-listallhardwareports"])
        if device not in wifi_devices(ports.output):
            return NetworkStatus(kind="wired", ip=ip)
        joined = await self.run(["networksetup", "-getairportnetwork", device])
        return NetworkStatus(kind="wifi", ssid=network_name(joined.output), ip=ip)

    # ------------------------------------------------------------------ the browser's policy

    async def write_policy(self, kind: policy.BrowserKind, document: dict[str, Any]) -> bool:
        """This user's preferences for that browser: Sunroom Screen's keys that aren't in
        ``document`` taken out (an address that went leaves nothing), then each one written.
        Edge gets its own quiet keys too (policy.EDGE_QUIET)."""
        domain = policy.MAC_DOMAINS[kind]
        wanted = policy.for_browser(kind, document)
        for key in sorted(policy.own_keys(kind) - wanted.keys()):
            await self.run(["defaults", "delete", domain, key])  # not there: nothing to do
        for argv in policy.mac_commands(kind, wanted):
            await self._must(argv, "Saving the browser's settings")
        return True

    async def remove_policy(self, kind: policy.BrowserKind) -> bool:
        domain = policy.MAC_DOMAINS[kind]
        for key in sorted(policy.own_keys(kind)):
            await self.run(["defaults", "delete", domain, key])
        return True
