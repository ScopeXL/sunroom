"""Windows 10 and 11 (docs/M7.md T14): a computer someone signs in to, where Sunroom Screen runs
for that person from the Startup folder, with no administrator rights and no service.

* **Power:** ``shutdown /r /t 5`` and ``shutdown /s /t 5``, which a signed-in user may run.
* **The network:** Windows joins Wi-Fi itself, and the Network row reads ``netsh wlan show
  interfaces`` (English labels: in another language the row says Wired, or Not connected; and
  since Windows 11 24H2 netsh answers only with Location access on, so without it a Wi-Fi screen
  says Wired too).
* **The browser's policy** under ``HKEY_CURRENT_USER\\Software\\Policies\\…`` (policy.py's
  ``windows_values``), which a user may write for themselves and Edge and Chrome both read.
* **Quit** closes Sunroom Screen until the next sign-in. No rotation (Windows' own display
  settings turn the picture) and no brightness: the page dims itself (``?dimmer=page``).
"""

from __future__ import annotations

import re
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal, Protocol

from sunroom_kiosk import logs, policy
from sunroom_kiosk.platform.base import (
    CommandResult,
    NetworkStatus,
    Platform,
    PlatformError,
    Runner,
    local_ip,
    run_command,
)
from sunroom_kiosk.schemas import ScreenCapability, ScreenPlatform

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
    ) -> None:
        super().__init__(runner, root)
        self.registry = registry
        self.build = build
        self.address = address

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
        return ["restart", "shutdown", "update", "quit"]

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
