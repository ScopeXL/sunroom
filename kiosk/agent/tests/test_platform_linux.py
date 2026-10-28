"""The Linux and Raspberry Pi adapters (platform/linux.py, platform/pi.py) against a scripted
command runner: the exact command line of each action, that a Wi-Fi password never reaches a
command line, nmcli's answers read right, and what a Pi can do from what it has. Nothing real
runs. Synthetic data only."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from sunroom_kiosk.platform.base import CommandResult, PlatformError
from sunroom_kiosk.platform.linux import ROOT_HELPER, LinuxPlatform, split_terse, wifi_from
from sunroom_kiosk.platform.pi import PiPlatform, is_pi
from tests.support import Shell, ok

WIFI_LIST = "\n".join(
    [
        "*:HomeNet:82:WPA2",
        " :HomeNet:40:WPA2",  # the same network from another access point
        " :SampleStreet-5G:54:WPA1 WPA2",
        " :Library Guest:23:",
        " ::67:WPA2",  # a hidden network: no name to show
        " :Sample\\:Colon:10:--",
    ]
)


def tools(*names: str) -> Callable[[str], str | None]:
    return lambda name: f"/usr/bin/{name}" if name in names else None


def linux(shell: Shell, *have: str, **environ: str) -> LinuxPlatform:
    return LinuxPlatform(shell, environ=environ, which=tools(*have))


def test_nmcli_terse_fields_are_split_and_unescaped() -> None:
    assert split_terse("*:Sample\\:Net:82:WPA2") == ["*", "Sample:Net", "82", "WPA2"]
    assert split_terse("a\\\\b:c") == ["a\\b", "c"]


def test_the_wifi_list_has_one_row_per_network() -> None:
    networks = {n.ssid: n for n in wifi_from(WIFI_LIST, {"HomeNet"})}
    assert set(networks) == {"HomeNet", "SampleStreet-5G", "Library Guest", "Sample:Colon"}
    home = networks["HomeNet"]
    assert (home.connected, home.strength, home.saved, home.id) == (True, 82, True, "HomeNet")
    assert networks["SampleStreet-5G"].secured and not networks["SampleStreet-5G"].saved
    assert not networks["Library Guest"].secured
    assert not networks["Sample:Colon"].secured  # "--" is nmcli's "none"


async def test_power_goes_through_logind() -> None:
    shell = Shell()
    platform = linux(shell)
    await platform.restart()
    await platform.shutdown()
    assert shell.lines() == ["systemctl reboot", "systemctl poweroff"]
    shell.answers["systemctl"] = CommandResult(1, "Access denied")
    with pytest.raises(PlatformError, match=r"^Restarting didn't work\. Try again in a moment\.$"):
        await platform.restart()


async def test_a_wifi_password_is_given_on_stdin_never_in_a_command_line() -> None:
    shell = Shell(answers={"nmcli -t -f IN-USE": ok(WIFI_LIST)})
    platform = linux(shell, "nmcli")
    await platform.wifi_join("SampleStreet-5G", "sample-secret-99")
    assert not any("sample-secret-99" in " ".join(argv) for argv, _ in shell.calls)
    up = next((argv, stdin) for argv, stdin in shell.calls if "up" in argv)
    assert up == (
        ["nmcli", "connection", "up", "id", "SampleStreet-5G", "passwd-file", "/dev/stdin"],
        "802-11-wireless-security.psk:sample-secret-99\n",
    )
    added = "nmcli connection add type wifi con-name SampleStreet-5G ssid SampleStreet-5G"
    assert f"{added} wifi-sec.key-mgmt wpa-psk" in shell.lines()


async def test_a_refused_password_is_said_plainly_and_cleaned_up() -> None:
    shell = Shell(
        answers={
            "nmcli -t -f IN-USE": ok(WIFI_LIST),
            "nmcli connection up": CommandResult(
                4, "Error: Connection activation failed: Secrets were required, but not provided."
            ),
        }
    )
    platform = linux(shell, "nmcli")
    with pytest.raises(PlatformError) as refused:
        await platform.wifi_join("SampleStreet-5G", "wrong-password")
    assert (
        str(refused.value)
        == "That password didn't work for SampleStreet-5G. Check it and try again."
    )
    assert shell.lines()[-1] == "nmcli connection delete id SampleStreet-5G"


async def test_an_open_network_and_a_saved_one_need_no_password() -> None:
    shell = Shell(
        answers={
            "nmcli -t -f IN-USE": ok(WIFI_LIST),
            "nmcli -t -f NAME,TYPE": ok("HomeNet:802-11-wireless"),
        }
    )
    platform = linux(shell, "nmcli")
    await platform.wifi_join("Library Guest", "")
    await platform.wifi_join("HomeNet", "")
    assert "nmcli device wifi connect Library Guest" in shell.lines()
    assert "nmcli connection up id HomeNet" in shell.lines()
    await platform.wifi_forget("HomeNet")
    assert shell.lines()[-1] == "nmcli connection delete id HomeNet"


async def test_the_network_is_wired_wifi_or_none() -> None:
    shell = Shell(answers={"nmcli -t -f TYPE,STATE": ok("ethernet:connected\nwifi:disconnected")})
    assert (await linux(shell, "nmcli").network()).kind == "wired"
    shell.answers = {
        "nmcli -t -f TYPE,STATE": ok("ethernet:unavailable\nwifi:connected\nloopback:connected"),
        "nmcli -t -f IN-USE": ok(WIFI_LIST),
    }
    wifi = await linux(shell, "nmcli").network()
    assert (wifi.kind, wifi.ssid, wifi.strength) == ("wifi", "HomeNet", 82)
    shell.answers = {"nmcli -t -f TYPE,STATE": ok("wifi:disconnected")}
    assert (await linux(shell, "nmcli").network()).kind == "none"


async def test_a_desktops_policy_follows_the_address_through_the_root_helper(
    tmp_path: Path,
) -> None:
    helper = tmp_path / ROOT_HELPER.lstrip("/")
    helper.parent.mkdir(parents=True)
    helper.write_text("#!/bin/sh\n")
    shell = Shell()
    platform = LinuxPlatform(shell, tmp_path, which=tools("google-chrome"))
    allowed = {"LocalNetworkAccessAllowedForUrls": ["http://192.168.1.20:8080"]}
    assert await platform.write_policy("chrome", allowed)
    argv, stdin = shell.calls[0]
    policy = "/etc/opt/chrome/policies/managed/sunroom-kiosk.json"
    assert argv == ["sudo", "-n", ROOT_HELPER, "write-policy", policy]
    assert json.loads(stdin or "") == allowed
    # Set up before ADR 0038, a desktop has no helper: nothing is tried, and Chrome asks once.
    bare = Shell()
    assert not await LinuxPlatform(bare, tmp_path / "old").write_policy("chrome", allowed)
    assert bare.calls == []


def test_a_desktop_can_quit_and_joins_wifi_only_with_networkmanager() -> None:
    assert linux(Shell()).capabilities() == ["restart", "shutdown", "update", "quit"]
    assert "wifi" in linux(Shell(), "nmcli").capabilities()
    assert linux(Shell(), XDG_SESSION_TYPE="x11").session == "x11"
    assert linux(Shell(), WAYLAND_DISPLAY="wayland-0").session == "wayland"
    assert linux(Shell()).session == "desktop"


async def test_x11_switches_off_blanking_before_the_browser() -> None:
    shell = Shell()
    await linux(shell, XDG_SESSION_TYPE="x11").prepare_session(0, "")
    assert shell.lines()[:3] == ["xset s off", "xset dpms 0 0 0", "xset s noblank"]


# ---------------------------------------------------------------------------- the Pi


def pi_root(tmp_path: Path, *, helper: bool = True) -> Path:
    (tmp_path / "proc/device-tree").mkdir(parents=True)
    (tmp_path / "proc/device-tree/model").write_text("Raspberry Pi 5 Model B Rev 1.0\x00")
    if helper:
        (tmp_path / ROOT_HELPER.lstrip("/")).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / ROOT_HELPER.lstrip("/")).write_text("#!/bin/sh\n")
    return tmp_path


def pi(
    shell: Shell, root: Path, *have: str, rule: Path | None = None, **environ: str
) -> PiPlatform:
    return PiPlatform(
        shell,
        root,
        environ={"WAYLAND_DISPLAY": "wayland-0", **environ},
        which=tools(*have),
        labwc_rule=rule or root / "labwc-rule.py",
        version="0.13.0",
    )


def test_a_pi_is_known_by_its_device_tree(tmp_path: Path) -> None:
    assert not is_pi(tmp_path)
    root = pi_root(tmp_path)
    assert is_pi(root)
    platform = pi(Shell(), root)
    assert platform.name == "pi"
    assert platform.model == "Raspberry Pi 5 Model B Rev 1.0"


def test_what_a_pi_can_do_follows_what_it_has(tmp_path: Path) -> None:
    root = pi_root(tmp_path)
    assert pi(Shell(), root).capabilities() == ["restart", "shutdown", "update", "brightness"]
    assert pi(Shell(), root, "nmcli", "wlr-randr").capabilities() == [
        "restart",
        "shutdown",
        "update",
        "wifi",
        "rotate",
        "brightness",
    ]
    # Sunroom on a Pi runs as a program, as on any computer (local.py), never by the adapter.
    assert "run_sunroom" not in pi(Shell(), root, "docker").capabilities()
    assert "quit" not in pi(Shell(), root).capabilities()  # a wall never quits


async def test_turning_the_picture_on_labwc(tmp_path: Path) -> None:
    root = pi_root(tmp_path)
    rule = root / "labwc-rule.py"
    rule.write_text("")
    shell = Shell()
    await pi(shell, root, "wlr-randr", rule=rule).rotate(90, "HDMI-A-1")
    lines = shell.lines()
    assert lines[0] == "wlr-randr --output HDMI-A-1 --transform 90"
    assert lines[1].endswith(f"{rule} --rotate 90 --output HDMI-A-1 --installer-version 0.13.0")
    assert lines[2].startswith("pkill -HUP -u ") and lines[2].endswith(" -x labwc")
    shell.calls.clear()
    await pi(shell, root, "wlr-randr", rule=rule).rotate(0, "HDMI-A-1")
    assert shell.lines()[0] == "wlr-randr --output HDMI-A-1 --transform normal"


async def test_turning_the_picture_on_x11_finds_its_name_for_the_output(tmp_path: Path) -> None:
    root = pi_root(tmp_path)
    shell = Shell(
        answers={
            "xrandr --query": ok(
                "Screen 0: minimum 320\nHDMI-1 connected 1920x1080\nHDMI-2 disconnected"
            )
        }
    )
    await pi(shell, root, "xrandr", XDG_SESSION_TYPE="x11").rotate(270, "HDMI-A-1")
    assert shell.lines()[-1] == "xrandr --output HDMI-1 --rotate right"


async def test_a_turn_that_fails_says_so(tmp_path: Path) -> None:
    shell = Shell(answers={"wlr-randr": CommandResult(1, "no such output")})
    with pytest.raises(PlatformError, match=r"^The picture didn't turn"):
        await pi(shell, pi_root(tmp_path), "wlr-randr").rotate(90, "HDMI-A-1")


async def test_the_policy_and_updates_go_through_the_root_helper(tmp_path: Path) -> None:
    shell = Shell()
    platform = pi(shell, pi_root(tmp_path))
    assert await platform.write_policy("chromium", {"BrowserSignin": 0})
    argv, stdin = shell.calls[0]
    policy = "/etc/chromium/policies/managed/sunroom-kiosk.json"
    assert argv == ["sudo", "-n", ROOT_HELPER, "write-policy", policy]
    assert json.loads(stdin or "") == {"BrowserSignin": 0}
    assert await platform.update_sunroom()
    assert shell.calls[-1][0] == ["sudo", "-n", ROOT_HELPER, "update-sunroom"]
    # A Pi set up before 0.13.0 has no helper: nothing is tried.
    bare = Shell()
    assert not await pi(bare, pi_root(tmp_path / "old", helper=False)).write_policy("chromium", {})
    assert bare.calls == []
