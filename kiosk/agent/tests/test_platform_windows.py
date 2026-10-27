"""The Windows adapter (platform/windows.py) against a scripted command runner and a pretend
registry: what it can do, the exact command line of each action, the Network row from netsh, the
computer's name from its firmware, and the browser's policy for this user only, rewritten without
touching anyone else's keys; and the commands it starts open no console window. Nothing real
runs, so it passes on every system. Synthetic data only."""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass, field

import pytest

from sunroom_kiosk import policy
from sunroom_kiosk.platform.base import (
    NO_WINDOW,
    CommandResult,
    PlatformError,
    run_command,
    stream_command,
)
from sunroom_kiosk.platform.windows import (
    BIOS_KEY,
    NETWORK_SETTINGS,
    RegistryKind,
    WindowsPlatform,
    wifi_from_netsh,
)
from tests.support import Shell, ok

ORIGIN = "https://calendar.example.com"
NETSH = """
There is 1 interface on the system:

    Name                   : Wi-Fi
    Description            : Sample Wireless Adapter
    Physical address       : 00:00:5e:00:53:01
    State                  : connected
    SSID                   : HomeNet
    BSSID                  : 00:00:5e:00:53:02
    Radio type             : 802.11ax
    Authentication         : WPA2-Personal
    Signal                 : 82%
    Profile                : HomeNet
"""


@dataclass
class FakeRegistry:
    """HKEY_CURRENT_USER as {key: {name: (kind, data)}}, and the firmware's two names."""

    keys: dict[str, dict[str, tuple[RegistryKind, int | str]]] = field(
        default_factory=dict[str, dict[str, tuple[RegistryKind, int | str]]]
    )
    machine: dict[str, str] = field(default_factory=dict[str, str])

    def set_value(self, key: str, name: str, kind: RegistryKind, data: int | str) -> None:
        self.keys.setdefault(key, {})[name] = (kind, data)

    def delete_value(self, key: str, name: str) -> None:
        self.keys.get(key, {}).pop(name, None)

    def delete_key(self, key: str) -> None:
        self.keys.pop(key, None)

    def machine_value(self, key: str, name: str) -> str | None:
        assert key == BIOS_KEY
        return self.machine.get(name)


def windows(
    shell: Shell,
    registry: FakeRegistry | None = None,
    *,
    build: int = 22631,
    ip: str | None = "192.168.1.30",
) -> WindowsPlatform:
    held = registry or FakeRegistry()
    return WindowsPlatform(shell, registry=lambda: held, build=lambda: build, address=lambda: ip)


def test_a_windows_computer_restarts_shuts_down_and_quits_but_has_no_wifi_or_rotation() -> None:
    platform = windows(Shell())
    assert platform.name == "windows"
    assert platform.capabilities() == [
        "restart",
        "shutdown",
        "update",
        "open_network_settings",
        "quit",
    ]
    assert platform.system == "Windows 11"
    assert windows(Shell(), build=19045).system == "Windows 10"


async def test_power_and_the_network_page_are_windows_own_commands() -> None:
    shell = Shell()
    platform = windows(shell)
    await platform.restart()
    await platform.shutdown()
    await platform.open_network_settings()
    assert shell.lines() == [
        "shutdown /r /t 5",
        "shutdown /s /t 5",
        f"cmd /c start  {NETWORK_SETTINGS}",
    ]
    refused = Shell(answers={"shutdown": CommandResult(1, "Access is denied.")})
    with pytest.raises(PlatformError, match=r"^Restarting didn't work\. Try again in a moment\.$"):
        await windows(refused).restart()


async def test_the_network_row_reads_netsh() -> None:
    joined = await windows(Shell(answers={"netsh": ok(NETSH)})).network()
    assert (joined.kind, joined.ssid, joined.strength, joined.ip) == (
        "wifi",
        "HomeNet",
        82,
        "192.168.1.30",
    )
    cable = await windows(
        Shell(answers={"netsh": CommandResult(1, "no wireless interface")})
    ).network()
    assert (cable.kind, cable.ip) == ("wired", "192.168.1.30")
    nothing = await windows(
        Shell(answers={"netsh": ok(NETSH.replace("connected", "disconnected"))}), ip=None
    ).network()
    assert nothing.kind == "none"
    assert wifi_from_netsh("State : connected\nSSID : \n") is None


def test_the_computer_is_named_by_its_maker_unless_the_firmware_names_nothing() -> None:
    named = FakeRegistry(
        machine={"SystemManufacturer": "Sample Maker", "SystemProductName": "Desk 5"}
    )
    assert windows(Shell(), named).model == "Sample Maker Desk 5"
    blank = FakeRegistry(
        machine={
            "SystemManufacturer": "System manufacturer",
            "SystemProductName": "System Product Name",
        }
    )
    assert windows(Shell(), blank).model == "Computer"


async def test_the_policy_is_this_users_and_leaves_other_keys_alone() -> None:
    registry = FakeRegistry()
    edge = policy.WINDOWS_KEYS["edge"]
    registry.set_value(edge, "HomepageLocation", "REG_SZ", "https://example.com")  # someone else's
    platform = windows(Shell(), registry)
    assert await platform.write_policy("edge", policy.document(ORIGIN))
    assert registry.keys[edge]["BrowserSignin"] == ("REG_DWORD", 0)
    assert registry.keys[edge]["LocalNetworkAccessRestrictionsEnabled"] == ("REG_DWORD", 1)
    assert registry.keys[rf"{edge}\LocalNetworkAccessAllowedForUrls"] == {"1": ("REG_SZ", ORIGIN)}
    # No address any more: the allowance goes, the quiet keys stay.
    assert await platform.write_policy("edge", policy.document(None))
    assert rf"{edge}\LocalNetworkAccessAllowedForUrls" not in registry.keys
    assert "LocalNetworkAccessRestrictionsEnabled" not in registry.keys[edge]
    assert registry.keys[edge]["TranslateEnabled"] == ("REG_DWORD", 0)
    # The uninstaller takes Sunroom Screen's keys out, and only those.
    assert await platform.remove_policy("edge")
    assert registry.keys[edge] == {"HomepageLocation": ("REG_SZ", "https://example.com")}


async def test_edge_gets_its_own_quiet_keys_and_chrome_doesnt() -> None:
    """Edge runs without its kiosk mode (ADR 0040): no welcome page, no full-tab promotions."""
    registry = FakeRegistry()
    platform = windows(Shell(), registry)
    edge, chrome = policy.WINDOWS_KEYS["edge"], policy.WINDOWS_KEYS["chrome"]
    assert await platform.write_policy("edge", policy.document(ORIGIN))
    assert registry.keys[edge]["HideFirstRunExperience"] == ("REG_DWORD", 1)
    assert registry.keys[edge]["PromotionalTabsEnabled"] == ("REG_DWORD", 0)
    assert await platform.write_policy("chrome", policy.document(ORIGIN))
    assert "PromotionalTabsEnabled" not in registry.keys[chrome]
    assert await platform.remove_policy("edge")
    assert registry.keys[edge] == {}


async def test_its_commands_open_no_console_window(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sunroom Screen runs without a console on Windows (sunroom-kioskw), so each console program
    it starts, netsh every 30 s, would flash a console window of its own unless asked for none."""
    asked: list[object] = []

    async def start(*argv: str, **options: object) -> object:
        asked.append(options.get("creationflags"))
        raise FileNotFoundError(argv[0])

    async def line(text: str) -> None: ...

    monkeypatch.setattr(asyncio, "create_subprocess_exec", start)
    assert (await run_command(["netsh", "wlan", "show", "interfaces"])).code == 127
    assert await stream_command(["uv", "--version"], line) == 127
    assert asked == [NO_WINDOW, NO_WINDOW]
    assert NO_WINDOW == (0x08000000 if sys.platform == "win32" else 0)  # CREATE_NO_WINDOW
