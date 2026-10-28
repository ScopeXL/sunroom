"""The Windows adapter (platform/windows.py) against a scripted command runner and a pretend
registry: what it can do, the exact command line of each action, the Network row from netsh, the
computer's name from its firmware, and the browser's policy for this user only, rewritten without
touching anyone else's keys; and the commands it starts open no console window. Nothing real
runs, so it passes on every system. Synthetic data only."""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from sunroom_kiosk import policy
from sunroom_kiosk.platform.base import (
    NO_WINDOW,
    CommandResult,
    PlatformError,
    run_command,
)
from sunroom_kiosk.platform.windows import (
    BIOS_KEY,
    DisplayMode,
    RegistryKind,
    WindowsPlatform,
    wifi_from_netsh,
)
from tests.support import Shell, ok

ORIGIN = "https://calendar.example.com"
# The allowance as 0.16.1 wrote it: the one Sunroom a screen showed.
ONE_SUNROOM = {"LocalNetworkAccessAllowedForUrls": [ORIGIN]}
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


def test_a_windows_computer_restarts_shuts_down_turns_and_quits_but_has_no_wifi() -> None:
    platform = windows(Shell())
    assert platform.name == "windows"
    assert platform.capabilities() == [
        "restart",
        "shutdown",
        "update",
        "rotate",
        "quit",
        "uninstall",
    ]
    assert platform.system == "Windows 11"
    assert windows(Shell(), build=19045).system == "Windows 10"


async def test_power_is_windows_own_commands() -> None:
    shell = Shell()
    platform = windows(shell)
    await platform.restart()
    await platform.shutdown()
    assert shell.lines() == ["shutdown /r /t 5", "shutdown /s /t 5"]
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
    # As 0.16.1 wrote it, naming the Sunroom; since 0.17.0 every site (ADR 0042).
    assert await platform.write_policy("edge", {**policy.document(), **ONE_SUNROOM})
    assert registry.keys[rf"{edge}\LocalNetworkAccessAllowedForUrls"] == {"1": ("REG_SZ", ORIGIN)}
    assert await platform.write_policy("edge", policy.document())
    assert registry.keys[edge]["BrowserSignin"] == ("REG_DWORD", 0)
    assert registry.keys[edge]["LocalNetworkAccessRestrictionsEnabled"] == ("REG_DWORD", 1)
    assert registry.keys[rf"{edge}\LocalNetworkAccessAllowedForUrls"] == {"1": ("REG_SZ", "*")}
    # Fewer keys: the ones left out go, the quiet keys stay.
    assert await platform.write_policy("edge", dict(policy.QUIET))
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
    assert await platform.write_policy("edge", policy.document())
    assert registry.keys[edge]["HideFirstRunExperience"] == ("REG_DWORD", 1)
    assert registry.keys[edge]["PromotionalTabsEnabled"] == ("REG_DWORD", 0)
    assert await platform.write_policy("chrome", policy.document())
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

    monkeypatch.setattr(asyncio, "create_subprocess_exec", start)
    assert (await run_command(["netsh", "wlan", "show", "interfaces"])).code == 127
    assert asked == [NO_WINDOW]
    assert NO_WINDOW == (0x08000000 if sys.platform == "win32" else 0)  # CREATE_NO_WINDOW


@dataclass
class FakeDisplay:
    """Windows' display settings, pretended: the main display's mode and what was asked of it."""

    mode: DisplayMode = field(default_factory=lambda: DisplayMode(1920, 1080, 0))
    answer: int = 0  # DISP_CHANGE_SUCCESSFUL
    applied: list[DisplayMode] = field(default_factory=list[DisplayMode])

    def current(self) -> DisplayMode:
        return self.mode

    def apply(self, mode: DisplayMode) -> int:
        self.applied.append(mode)
        if self.answer == 0:
            self.mode = mode
        return self.answer


async def test_windows_turns_the_main_displays_picture() -> None:
    """ChangeDisplaySettingsExW with the orientation (counter-clockwise, as DEVMODEW measures it:
    the agent's 90, Portrait left, is DMDO_90) and the width and height swapped between landscape
    and portrait (ADR 0042)."""
    display = FakeDisplay()
    platform = WindowsPlatform(Shell(), display=lambda: display)
    await platform.rotate(90, "")
    assert display.applied[-1] == DisplayMode(1080, 1920, 1)
    await platform.rotate(270, "")  # portrait to portrait: no swap
    assert display.applied[-1] == DisplayMode(1080, 1920, 3)
    await platform.rotate(180, "")
    assert display.applied[-1] == DisplayMode(1920, 1080, 2)
    await platform.rotate(0, "")
    assert display.applied[-1] == DisplayMode(1920, 1080, 0)


async def test_a_turn_windows_refuses_says_so() -> None:
    refused = FakeDisplay(answer=-2)  # DISP_CHANGE_BADMODE
    with pytest.raises(PlatformError, match=r"^The picture didn't turn\. Try again in a moment\.$"):
        await WindowsPlatform(Shell(), display=lambda: refused).rotate(90, "")

    def away() -> FakeDisplay:
        raise OSError(87, "EnumDisplaySettingsW")

    with pytest.raises(PlatformError, match=r"^The picture didn't turn"):
        await WindowsPlatform(Shell(), display=away).rotate(90, "")


async def test_windows_uninstalls_with_a_copy_of_its_script(tmp_path: Path) -> None:
    """uninstall.py copied out (it removes the agent's own environment) and run with uv's Python,
    as apply.py is (ADR 0042)."""
    started: list[list[str]] = []

    async def spawn(argv: list[str], *, unit: str) -> bool:
        started.append(argv)
        return True

    platform = WindowsPlatform(Shell(), spawn=spawn, temp=tmp_path)
    await platform.uninstall(sunroom=True, port=7800)
    (argv,) = started
    script = tmp_path / "sunroom-kiosk-uninstall.py"
    assert script.is_file()
    assert argv[1:] == [
        str(script),
        "--agent",
        str(Path.home() / ".local" / "bin" / "sunroom-kiosk.exe"),
        "--port",
        "7800",
        "--sunroom",
    ]
