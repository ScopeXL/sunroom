"""Windows 10 and 11 (docs/M7.md T14): a computer someone signs in to, where Sunroom Screen runs
for that person from the Startup folder, with no administrator rights and no service.

* **Power:** ``shutdown /r /t 5`` and ``shutdown /s /t 5``, which a signed-in user may run.
* **The network:** Windows joins Wi-Fi itself, and the Network row reads ``netsh wlan show
  interfaces`` (English labels: in another language the row says Wired, or Not connected; and
  since Windows 11 24H2 netsh answers only with Location access on, so without it a Wi-Fi screen
  says Wired too).
* **The browser's policy** under ``HKEY_CURRENT_USER\\Software\\Policies\\…`` (policy.py's
  ``windows_values``), which a user may write for themselves and Edge and Chrome both read.
* **Rotation** (ADR 0042), for a display mounted on its side that Windows doesn't know about:
  the main display's mode read with ``EnumDisplaySettingsW`` and written back with
  ``ChangeDisplaySettingsExW``, its orientation changed (and its width and height swapped between
  landscape and portrait), kept in the registry so it holds across sign-ins; no administrator
  needed. Touch follows the display on Windows.
* **Quit** closes Sunroom Screen until the next sign-in. No brightness: the page dims itself
  (``?dimmer=page``).
* **Uninstall** (ADR 0042): uninstall.py, copied out to the temp folder (it removes the agent's
  own environment) and run with the Python that environment was made from, as apply.py is.
"""

from __future__ import annotations

import asyncio
import ctypes
import re
import shutil
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal, Protocol

from sunroom_kiosk import logs, policy
from sunroom_kiosk import uninstall as uninstall_step
from sunroom_kiosk.platform.base import (
    UNINSTALL_UNIT,
    CommandResult,
    NetworkStatus,
    Platform,
    PlatformError,
    Runner,
    Spawn,
    local_ip,
    run_command,
    spawn_detached,
)
from sunroom_kiosk.schemas import ScreenCapability, ScreenPlatform
from sunroom_kiosk.updater import base_python

log = logs.get("platform")

BIOS_KEY = r"HARDWARE\DESCRIPTION\System\BIOS"
WINDOWS_11_BUILD = 22000
# What a computer's maker leaves in its firmware when it names nothing.
PLACEHOLDERS = {
    "",
    "system manufacturer",
    "system product name",
    "to be filled by o.e.m.",
    "default string",
}

type RegistryKind = Literal["REG_DWORD", "REG_SZ"]


class Registry(Protocol):
    """The registry calls Sunroom Screen makes: this user's policy keys (HKEY_CURRENT_USER), and
    the computer's name from its firmware (HKEY_LOCAL_MACHINE, read only)."""

    def set_value(self, key: str, name: str, kind: RegistryKind, data: int | str) -> None: ...
    def delete_value(self, key: str, name: str) -> None: ...
    def delete_key(self, key: str) -> None: ...
    def machine_value(self, key: str, name: str) -> str | None: ...


if sys.platform == "win32":
    import winreg

    class _WindowsRegistry:
        def set_value(self, key: str, name: str, kind: RegistryKind, data: int | str) -> None:
            with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_SET_VALUE) as at:
                if kind == "REG_DWORD":
                    winreg.SetValueEx(at, name, 0, winreg.REG_DWORD, int(data))
                else:
                    winreg.SetValueEx(at, name, 0, winreg.REG_SZ, str(data))

        def delete_value(self, key: str, name: str) -> None:
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_SET_VALUE) as at:
                    winreg.DeleteValue(at, name)
            except FileNotFoundError:
                pass

        def delete_key(self, key: str) -> None:
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key)  # a list's key: values only
            except FileNotFoundError:
                pass

        def machine_value(self, key: str, name: str) -> str | None:
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key) as at:
                    value, _kind = winreg.QueryValueEx(at, name)
            except OSError:
                return None
            return str(value).strip() or None


def system_registry() -> Registry:
    if sys.platform == "win32":
        return _WindowsRegistry()
    raise PlatformError("The registry is Windows' own.")


def windows_build() -> int:
    if sys.platform == "win32":
        return sys.getwindowsversion().build
    return 0


# DEVMODEW's dmDisplayOrientation is measured counter-clockwise from the display's natural one
# (Microsoft's DEVMODEW reference), as xrandr's "left" is: the agent's 90, "Portrait, left" (the
# top of the picture at the left), is DMDO_90. Not yet tried on a real Windows display.
ORIENTATIONS = {0: 0, 90: 1, 180: 2, 270: 3}  # DMDO_DEFAULT, DMDO_90, DMDO_180, DMDO_270
DISP_CHANGE_SUCCESSFUL = 0


@dataclass(frozen=True)
class DisplayMode:
    """The main display's mode, as far as turning it goes."""

    width: int
    height: int
    orientation: int  # DMDO_*


def turned(mode: DisplayMode, rotation: int) -> DisplayMode:
    """``mode`` turned to ``rotation``: between landscape and portrait the width and height
    swap, as Windows' own display settings do."""
    orientation = ORIENTATIONS[rotation]
    if orientation % 2 == mode.orientation % 2:
        return replace(mode, orientation=orientation)
    return DisplayMode(width=mode.height, height=mode.width, orientation=orientation)


class Display(Protocol):
    """Windows' display settings: the main display's mode, and a change to it (``DISP_CHANGE_*``:
    0 when it worked)."""

    def current(self) -> DisplayMode: ...
    def apply(self, mode: DisplayMode) -> int: ...


if sys.platform == "win32":
    from ctypes import wintypes

    ENUM_CURRENT_SETTINGS = -1
    DM_DISPLAYORIENTATION = 0x00000080
    DM_PELSWIDTH = 0x00080000
    DM_PELSHEIGHT = 0x00100000
    CDS_UPDATEREGISTRY = 0x00000001

    class DEVMODEW(ctypes.Structure):
        """wingdi.h's DEVMODEW for a display (the union's display part); 220 bytes."""

        _fields_ = [
            ("dmDeviceName", wintypes.WCHAR * 32),
            ("dmSpecVersion", wintypes.WORD),
            ("dmDriverVersion", wintypes.WORD),
            ("dmSize", wintypes.WORD),
            ("dmDriverExtra", wintypes.WORD),
            ("dmFields", wintypes.DWORD),
            ("dmPositionX", wintypes.LONG),
            ("dmPositionY", wintypes.LONG),
            ("dmDisplayOrientation", wintypes.DWORD),
            ("dmDisplayFixedOutput", wintypes.DWORD),
            ("dmColor", ctypes.c_short),
            ("dmDuplex", ctypes.c_short),
            ("dmYResolution", ctypes.c_short),
            ("dmTTOption", ctypes.c_short),
            ("dmCollate", ctypes.c_short),
            ("dmFormName", wintypes.WCHAR * 32),
            ("dmLogPixels", wintypes.WORD),
            ("dmBitsPerPel", wintypes.DWORD),
            ("dmPelsWidth", wintypes.DWORD),
            ("dmPelsHeight", wintypes.DWORD),
            ("dmDisplayFlags", wintypes.DWORD),
            ("dmDisplayFrequency", wintypes.DWORD),
            ("dmICMMethod", wintypes.DWORD),
            ("dmICMIntent", wintypes.DWORD),
            ("dmMediaType", wintypes.DWORD),
            ("dmDitherType", wintypes.DWORD),
            ("dmReserved1", wintypes.DWORD),
            ("dmReserved2", wintypes.DWORD),
            ("dmPanningWidth", wintypes.DWORD),
            ("dmPanningHeight", wintypes.DWORD),
        ]

    class _WindowsDisplay:
        def __init__(self) -> None:
            self.user32 = ctypes.WinDLL("user32", use_last_error=True)

        def _read(self) -> DEVMODEW:
            mode = DEVMODEW()
            mode.dmSize = ctypes.sizeof(DEVMODEW)
            if not self.user32.EnumDisplaySettingsW(
                None, ENUM_CURRENT_SETTINGS, ctypes.byref(mode)
            ):
                raise OSError(ctypes.get_last_error(), "EnumDisplaySettingsW")
            return mode

        def current(self) -> DisplayMode:
            mode = self._read()
            return DisplayMode(
                width=int(mode.dmPelsWidth),
                height=int(mode.dmPelsHeight),
                orientation=int(mode.dmDisplayOrientation),
            )

        def apply(self, mode: DisplayMode) -> int:
            wanted = self._read()
            wanted.dmPelsWidth = mode.width
            wanted.dmPelsHeight = mode.height
            wanted.dmDisplayOrientation = mode.orientation
            wanted.dmFields = DM_DISPLAYORIENTATION | DM_PELSWIDTH | DM_PELSHEIGHT
            return int(
                self.user32.ChangeDisplaySettingsExW(
                    None, ctypes.byref(wanted), None, CDS_UPDATEREGISTRY, None
                )
            )


def system_display() -> Display:
    if sys.platform == "win32":
        return _WindowsDisplay()
    raise PlatformError("The display settings are Windows' own.")


def wifi_from_netsh(text: str) -> tuple[str, int] | None:
    """The joined network's name and signal from ``netsh wlan show interfaces``, or None."""
    fields: dict[str, str] = {}
    for line in text.splitlines():
        label, colon, value = line.partition(":")
        if colon:
            fields.setdefault(label.strip().lower(), value.strip())
    ssid = fields.get("ssid", "")
    if fields.get("state") != "connected" or not ssid:
        return None
    signal = re.match(r"(\d+)\s*%", fields.get("signal", ""))
    return ssid, max(0, min(100, int(signal.group(1)))) if signal else 0


class WindowsPlatform(Platform):
    def __init__(
        self,
        runner: Runner = run_command,
        root: Path = Path("C:/"),
        *,
        registry: Callable[[], Registry] = system_registry,
        build: Callable[[], int] = windows_build,
        address: Callable[[], str | None] = local_ip,
        display: Callable[[], Display] = system_display,
        spawn: Spawn = spawn_detached,
        temp: Path | None = None,
    ) -> None:
        super().__init__(runner, root)
        self.registry = registry
        self.build = build
        self.address = address
        self.display = display
        self.spawn = spawn
        self.temp = temp or Path(tempfile.gettempdir())

    # ------------------------------------------------------------------ what it is

    @property
    def name(self) -> ScreenPlatform:
        return "windows"

    @property
    def model(self) -> str:
        try:
            registry = self.registry()
        except PlatformError:
            return "Computer"
        parts = [
            registry.machine_value(BIOS_KEY, field) or ""
            for field in ("SystemManufacturer", "SystemProductName")
        ]
        named = [part for part in parts if part.lower() not in PLACEHOLDERS]
        return " ".join(named) or "Computer"

    @property
    def system(self) -> str:
        build = self.build()
        if not build:
            return "Windows"
        return "Windows 11" if build >= WINDOWS_11_BUILD else "Windows 10"

    def capabilities(self) -> list[ScreenCapability]:
        return ["restart", "shutdown", "update", "rotate", "quit", "uninstall"]

    # ------------------------------------------------------------------ the machine

    async def _must(self, argv: list[str], what: str) -> CommandResult:
        result = await self.run(argv)
        if not result.ok:
            log.info("%s didn't work: %s", " ".join(argv[:2]), result.first_line())
            raise PlatformError(f"{what} didn't work. Try again in a moment.")
        return result

    async def restart(self) -> None:
        await self._must(["shutdown", "/r", "/t", "5"], "Restarting")

    async def shutdown(self) -> None:
        await self._must(["shutdown", "/s", "/t", "5"], "Shutting down")

    # ------------------------------------------------------------------ the screen

    async def rotate(self, rotation: int, output: str) -> None:
        """Turn the main display's picture; kept in the registry, so it holds at sign-in."""
        try:
            display = self.display()
            now = await asyncio.to_thread(display.current)
            answer = await asyncio.to_thread(display.apply, turned(now, rotation))
        except (OSError, PlatformError) as error:
            log.info("The display settings didn't answer: %s", error)
            raise PlatformError("The picture didn't turn. Try again in a moment.") from error
        if answer != DISP_CHANGE_SUCCESSFUL:
            log.info("ChangeDisplaySettingsExW answered %d.", answer)
            raise PlatformError("The picture didn't turn. Try again in a moment.")

    async def uninstall(self, *, sunroom: bool, port: int) -> None:
        script = self.temp / "sunroom-kiosk-uninstall.py"
        try:
            await asyncio.to_thread(shutil.copyfile, uninstall_step.__file__, script)
        except OSError as error:
            log.info("The uninstaller couldn't be copied out: %s", error)
            raise PlatformError(
                "Sunroom Screen couldn't start its uninstaller. Try again."
            ) from error
        agent = Path.home() / ".local" / "bin" / "sunroom-kiosk.exe"
        argv = [base_python(), str(script), "--agent", str(agent), "--port", str(port)]
        if sunroom:
            argv.append("--sunroom")
        if not await self.spawn(argv, unit=UNINSTALL_UNIT):
            raise PlatformError("Sunroom Screen couldn't start its uninstaller. Try again.")

    # ------------------------------------------------------------------ the network

    async def network(self) -> NetworkStatus:
        ip = self.address()
        listing = await self.run(["netsh", "wlan", "show", "interfaces"])
        joined = wifi_from_netsh(listing.output) if listing.ok else None
        if joined is not None:
            ssid, strength = joined
            return NetworkStatus(kind="wifi", ssid=ssid, ip=ip, strength=strength)
        return NetworkStatus(kind="wired" if ip else "none", ip=ip)

    # ------------------------------------------------------------------ the browser's policy

    def _clear(self, registry: Registry, kind: policy.BrowserKind) -> None:
        base = policy.WINDOWS_KEYS[kind]
        for key in sorted(policy.own_keys(kind)):
            registry.delete_value(base, key)
            registry.delete_key(rf"{base}\{key}")  # a list's own key (1, 2, …)

    async def write_policy(self, kind: policy.BrowserKind, document: dict[str, Any]) -> bool:
        """This user's policy for that browser: Sunroom Screen's keys cleared, then written
        (so an address that changed leaves nothing of the old one); any other key is kept.
        Edge gets its own quiet keys too (policy.EDGE_QUIET)."""
        registry = self.registry()
        try:
            self._clear(registry, kind)
            for key, name, value_kind, data in policy.windows_values(
                kind, policy.for_browser(kind, document)
            ):
                registry.set_value(key, name, value_kind, data)
        except OSError as error:
            raise PlatformError("The browser's settings couldn't be saved.") from error
        return True

    async def remove_policy(self, kind: policy.BrowserKind) -> bool:
        try:
            self._clear(self.registry(), kind)
        except OSError as error:
            raise PlatformError("The browser's settings couldn't be changed.") from error
        return True
