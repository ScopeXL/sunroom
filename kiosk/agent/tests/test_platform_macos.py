"""The macOS adapter (platform/macos.py) against a scripted command runner: what a Mac can do,
the exact command line of each action, and the browser's policy in its own preferences, the keys
that went taken out first. Nothing real runs, so it passes on every system. Synthetic data
only."""

from __future__ import annotations

import pytest

from sunroom_kiosk import policy
from sunroom_kiosk.platform import macos
from sunroom_kiosk.platform.base import CommandResult, PlatformError
from sunroom_kiosk.platform.macos import MacPlatform, interface_of, network_name, wifi_devices
from tests.support import Shell, ok


def mac(shell: Shell, model: str = "Mac14,2", release: str = "15.1") -> MacPlatform:
    return MacPlatform(shell, identifier=lambda: model, release=lambda: release)


def test_a_mac_restarts_shuts_down_and_quits_but_has_no_wifi_or_rotation() -> None:
    platform = mac(Shell())
    assert platform.name == "macos"
    assert platform.capabilities() == ["restart", "shutdown", "update", "quit"]
    assert (platform.model, platform.system) == ("Mac (Mac14,2)", "macOS 15.1")
    assert (mac(Shell(), "", "").model, mac(Shell(), "", "").system) == ("Mac", "macOS")


async def test_power_is_the_macs_own_commands() -> None:
    shell = Shell()
    platform = mac(shell)
    await platform.restart()
    await platform.shutdown()
    assert [argv for argv, _ in shell.calls] == [
        ["osascript", "-e", 'tell application "System Events" to restart'],
        ["osascript", "-e", 'tell application "System Events" to shut down'],
    ]
    refused = Shell(answers={"osascript": CommandResult(1, "Not authorized to send events.")})
    with pytest.raises(PlatformError, match=r"^Shutting down didn't work\. Try again"):
        await mac(refused).shutdown()


async def test_the_policy_goes_in_the_browsers_preferences() -> None:
    shell = Shell()
    platform = mac(shell)
    domain = policy.MAC_DOMAINS["chrome"]
    assert await platform.write_policy("chrome", policy.document())
    lines = shell.lines()
    assert not any(line.startswith("defaults delete") for line in lines)
    assert f"defaults write {domain} LocalNetworkAccessAllowedForUrls -array *" in lines
    assert f"defaults write {domain} BrowserSignin -integer 0" in lines
    # Fewer keys: the ones left out are taken out, the quiet ones written again.
    shell.calls.clear()
    assert await platform.write_policy("chrome", dict(policy.QUIET))
    assert shell.lines()[:2] == [
        f"defaults delete {domain} LocalNetworkAccessAllowedForUrls",
        f"defaults delete {domain} LocalNetworkAccessRestrictionsEnabled",
    ]
    shell.calls.clear()
    assert await platform.remove_policy("chrome")
    assert len(shell.lines()) == len(policy.ALLOWED_KEYS)
    assert all(line.startswith(f"defaults delete {domain} ") for line in shell.lines())


async def test_edge_gets_its_own_quiet_keys_too() -> None:
    """Edge runs without its kiosk mode (ADR 0040): no welcome page, no full-tab promotions."""
    shell = Shell()
    platform = mac(shell)
    domain = policy.MAC_DOMAINS["edge"]
    assert await platform.write_policy("edge", policy.document())
    lines = shell.lines()
    assert f"defaults write {domain} HideFirstRunExperience -bool true" in lines
    assert f"defaults write {domain} PromotionalTabsEnabled -bool false" in lines
    shell.calls.clear()
    assert await platform.remove_policy("edge")
    assert f"defaults delete {domain} PromotionalTabsEnabled" in shell.lines()


ROUTE = """\
   route to: default
destination: default
       mask: default
    gateway: 192.168.1.1
  interface: en0
      flags: <UP,GATEWAY,DONE,STATIC,PRCLONING,GLOBAL>
"""

PORTS = """\
Hardware Port: Ethernet Adapter (en3)
Device: en3
Ethernet Address: 0e:00:00:00:00:01

Hardware Port: Wi-Fi
Device: en0
Ethernet Address: 0e:00:00:00:00:02

Hardware Port: Thunderbolt Bridge
Device: bridge0
Ethernet Address: 0e:00:00:00:00:03
"""


def test_the_macs_network_answers_read_right() -> None:
    assert interface_of(ROUTE) == "en0"
    assert interface_of("route: writing to routing socket: not in table") is None
    assert wifi_devices(PORTS) == {"en0"}
    assert network_name("Current Wi-Fi Network: HomeNet\n") == "HomeNet"
    # Since macOS 14.4 the name is told only to a program with Location access.
    assert network_name("You are not associated with an AirPort network.\n") is None


async def test_a_mac_says_how_it_is_connected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(macos, "local_ip", lambda: "192.168.1.31")
    on_wifi = Shell(answers={"route -n get default": ok(ROUTE), "networksetup -list": ok(PORTS)})
    joined = await mac(on_wifi).network()
    assert (joined.kind, joined.ssid, joined.ip, joined.strength) == (
        "wifi",
        None,
        "192.168.1.31",
        None,
    )
    assert on_wifi.lines()[-1] == "networksetup -getairportnetwork en0"
    named = Shell(
        answers={
            "route -n get default": ok(ROUTE),
            "networksetup -list": ok(PORTS),
            "networksetup -getairportnetwork": ok("Current Wi-Fi Network: HomeNet"),
        }
    )
    assert (await mac(named).network()).ssid == "HomeNet"
    cable = Shell(
        answers={
            "route -n get default": ok(ROUTE.replace("en0", "en3")),
            "networksetup -list": ok(PORTS),
        }
    )
    assert (await mac(cable).network()).kind == "wired"
    nowhere = Shell(answers={"route -n get default": CommandResult(1, "not in table")})
    assert (await mac(nowhere).network()).kind == "none"
