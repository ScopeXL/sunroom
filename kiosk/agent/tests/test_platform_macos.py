"""The macOS adapter (platform/macos.py) against a scripted command runner: what a Mac can do,
the exact command line of each action, and the browser's policy in its own preferences, the keys
that went taken out first. Nothing real runs, so it passes on every system. Synthetic data
only."""

from __future__ import annotations

import pytest

from sunroom_kiosk import policy
from sunroom_kiosk.platform.base import CommandResult, PlatformError
from sunroom_kiosk.platform.macos import WIFI_SETTINGS, MacPlatform
from tests.support import Shell


def mac(shell: Shell, model: str = "Mac14,2", release: str = "15.1") -> MacPlatform:
    return MacPlatform(shell, identifier=lambda: model, release=lambda: release)


def test_a_mac_restarts_shuts_down_and_quits_but_has_no_wifi_or_rotation() -> None:
    platform = mac(Shell())
    assert platform.name == "macos"
    assert platform.capabilities() == [
        "restart",
        "shutdown",
        "update",
        "open_network_settings",
        "quit",
    ]
    assert (platform.model, platform.system) == ("Mac (Mac14,2)", "macOS 15.1")
    assert (mac(Shell(), "", "").model, mac(Shell(), "", "").system) == ("Mac", "macOS")


async def test_power_and_the_wifi_page_are_the_macs_own_commands() -> None:
    shell = Shell()
    platform = mac(shell)
    await platform.restart()
    await platform.shutdown()
    await platform.open_network_settings()
    assert [argv for argv, _ in shell.calls] == [
        ["osascript", "-e", 'tell application "System Events" to restart'],
        ["osascript", "-e", 'tell application "System Events" to shut down'],
        ["open", WIFI_SETTINGS],
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
