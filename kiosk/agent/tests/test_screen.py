"""The screen's sleep and brightness (PLAN §13.5): Sunroom Screen's ``screen`` module, which was
the script kiosk/sunroom-screen until 0.13.0 (its tests moved here from the backend's).

The state → commands mapping on Wayland (wlopm, else wlr-randr) and X11 (xset), brightness by
DDC/CI and by a sysfs backlight in a temporary tree, only changes applied, the back-off, and
the screen switched on after repeated failures and when the helper stops. No network and no
real commands: the HTTP fetch, the command runner, the filesystem root and the sleep are
injected. Synthetic data only.
"""

from __future__ import annotations

import email.message
import io
import json
import sys
import urllib.error
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest

from sunroom_kiosk import cli
from sunroom_kiosk import screen as screen_helper

URL = "http://192.168.1.20:7867"

Answer = dict[str, Any] | bytes | BaseException


def answer(
    screen: str = "on", brightness: int = 100, reason: str = "day", etag: str = "e1"
) -> dict[str, Any]:
    """One answer of GET /api/display/state, as the server sends it."""
    return {
        "etag": etag,
        "screen": screen,
        "brightness": brightness,
        "reason": reason,
        "awake_until": None,
        "schedule": {
            "sleep_from": "22:00",
            "sleep_to": "06:30",
            "sleep_mode": "screen_off",
            "dim_from": "20:00",
            "dim_level": 40,
        },
        "server_time": "2026-10-08T03:30:05Z",
    }


class Server:
    """Sunroom's answers in order (a state, raw bytes, or an error to raise); then a stop."""

    def __init__(self, answers: list[Answer]) -> None:
        self.answers = answers
        self.urls: list[str] = []

    def __call__(self, url: str, timeout: float) -> bytes:
        assert timeout > 55  # a little over the server's longest wait
        self.urls.append(url)
        reply: Answer = self.answers.pop(0) if self.answers else screen_helper.Stop()
        if isinstance(reply, BaseException):
            raise reply
        return reply if isinstance(reply, bytes) else json.dumps(reply).encode()

    def queries(self) -> list[dict[str, list[str]]]:
        return [parse_qs(urlsplit(url).query) for url in self.urls]


@dataclass
class Shell:
    """Records each command line; ``codes`` fails a program, ``printed`` is what a command
    starting with that text prints."""

    codes: dict[str, int] = field(default_factory=dict[str, int])
    printed: dict[str, str] = field(default_factory=dict[str, str])
    calls: list[str] = field(default_factory=list[str])

    def __call__(self, argv: list[str]) -> tuple[int, str]:
        line = " ".join(argv)
        self.calls.append(line)
        text = next((out for start, out in self.printed.items() if line.startswith(start)), "")
        return self.codes.get(argv[0], 0), text


@dataclass
class Rig:
    helper: Any
    server: Server
    shell: Shell
    sleeps: list[float]
    lines: list[str]

    def steps(self, count: int) -> None:
        for _ in range(count):
            self.helper.step()


def rig(root: Path, *answers: Answer, shell: Shell | None = None, **config: str) -> Rig:
    values = {
        "SUNROOM_URL": URL,
        "SUNROOM_SESSION": "wayland",
        "SUNROOM_OUTPUT": "HDMI-A-1",
        "SUNROOM_BRIGHTNESS": "none",
        **config,
    }
    server, commands = Server(list(answers)), shell or Shell()
    sleeps: list[float] = []
    lines: list[str] = []
    helper = screen_helper.Helper(
        screen_helper.settings_from(values),
        fetch=server,
        run=commands,
        root=root,
        sleep=sleeps.append,
        say=lines.append,
    )
    return Rig(helper, server, commands, sleeps, lines)


def backlight(root: Path, name: str = "11-0045", maximum: int = 31) -> Path:
    device = root / "sys" / "class" / "backlight" / name
    device.mkdir(parents=True)
    (device / "max_brightness").write_text(f"{maximum}\n")
    (device / "brightness").write_text(f"{maximum}\n")
    (device / "bl_power").write_text("0\n")
    return device


def i2c_bus(root: Path, bus: int = 20) -> None:
    (root / "dev").mkdir(exist_ok=True)
    (root / "dev" / f"i2c-{bus}").write_text("")


REFUSED = urllib.error.URLError(ConnectionRefusedError(111, "Connection refused"))

DETECT = """\
Invalid display
   I2C bus:          /dev/i2c-21
   DRM connector:    card1-HDMI-A-2
   Monitor:          SMP:Sample Old Monitor:
   DDC communication failed

Display 1
   I2C bus:          /dev/i2c-20
   DRM connector:    card1-HDMI-A-1
   Monitor:          SMP:Sample Monitor:

Display 2
   I2C bus:          /dev/i2c-22
   DRM_connector:    card1-DP-1
   Monitor:          SMP:Sample Other Monitor:
"""


# ---------------------------------------------------------------------------- settings


def test_reads_the_installers_settings_without_running_them() -> None:
    text = "\n".join(
        [
            "# Written by the Sunroom installer (kiosk/install.sh 0.6.0).",
            f"SUNROOM_URL={URL}/",
            "SUNROOM_SESSION=x11",
            "SUNROOM_OUTPUT=HDMI-A-2",
            "SUNROOM_SCREEN_HELPER=yes",
            "SUNROOM_BRIGHTNESS=ddc",
            "SUNROOM_DDC_BUS=20",
            "SUNROOM_BACKLIGHT=''",
            "SUNROOM_LABEL=Sample\\ Street\\ kitchen",
            "SUNROOM_NOTE=$(reboot)",
            "SUNROOM_BROKEN='unclosed",
            "not a setting",
        ]
    )
    values = screen_helper.parse_config(text)
    assert values["SUNROOM_LABEL"] == "Sample Street kitchen"  # printf %q's escapes undone
    assert values["SUNROOM_NOTE"] == "$(reboot)"  # text, never a command
    assert values["SUNROOM_BACKLIGHT"] == ""
    assert "SUNROOM_BROKEN" not in values
    assert screen_helper.settings_from(values) == screen_helper.Settings(
        url=URL,
        session="x11",
        output="HDMI-A-2",
        helper=True,
        brightness="ddc",
        ddc_bus="20",
        backlight="",
    )


def test_missing_or_odd_settings_fall_back_to_the_defaults() -> None:
    odd = "\n".join(
        [
            "SUNROOM_SESSION=mir",
            "SUNROOM_BRIGHTNESS=bright",
            "SUNROOM_DDC_BUS=i2c-20",
            "SUNROOM_BACKLIGHT=../../etc",
            "SUNROOM_OUTPUT='HDMI A 1'",
        ]
    )
    defaults = screen_helper.Settings()
    assert screen_helper.settings_from(screen_helper.parse_config(odd)) == defaults
    assert defaults.url == "http://localhost:7867"
    assert (defaults.session, defaults.brightness, defaults.helper) == ("wayland", "auto", True)


@pytest.mark.parametrize(
    ("config", "has_backlight", "has_bus", "method"),
    [
        ({"SUNROOM_BRIGHTNESS": "auto", "SUNROOM_DDC_BUS": "20"}, True, True, "sysfs"),
        ({"SUNROOM_BRIGHTNESS": "auto", "SUNROOM_DDC_BUS": "20"}, False, True, "ddc"),
        ({"SUNROOM_BRIGHTNESS": "auto", "SUNROOM_DDC_BUS": "20"}, False, False, "none"),
        ({"SUNROOM_BRIGHTNESS": "auto"}, False, True, "none"),  # the installer found no bus
        ({"SUNROOM_BRIGHTNESS": "ddc", "SUNROOM_DDC_BUS": "20"}, True, True, "ddc"),
        ({"SUNROOM_BRIGHTNESS": "sysfs", "SUNROOM_DDC_BUS": "20"}, False, True, "none"),
        ({"SUNROOM_BRIGHTNESS": "none", "SUNROOM_DDC_BUS": "20"}, True, True, "none"),
        ({"SUNROOM_SCREEN_HELPER": "no", "SUNROOM_DDC_BUS": "20"}, True, True, "none"),
    ],
)
def test_how_the_brightness_is_set(
    tmp_path: Path, config: dict[str, str], has_backlight: bool, has_bus: bool, method: str
) -> None:
    if has_backlight:
        backlight(tmp_path)
    if has_bus:
        i2c_bus(tmp_path)
    settings = screen_helper.settings_from(config)
    assert screen_helper.brightness_method(settings, tmp_path)[0] == method


def test_a_renamed_backlight_is_still_found(tmp_path: Path) -> None:
    device = backlight(tmp_path, name="10-0045")
    settings = screen_helper.settings_from(
        {"SUNROOM_BRIGHTNESS": "sysfs", "SUNROOM_BACKLIGHT": "11-0045"}
    )
    assert screen_helper.brightness_method(settings, tmp_path) == ("sysfs", device)


def test_the_installer_finds_the_screens_ddc_bus() -> None:
    assert screen_helper.ddc_bus_from_detect(DETECT, "HDMI-A-1") == "20"
    assert screen_helper.ddc_bus_from_detect(DETECT, "DP-1") == "22"
    # The screen on HDMI-A-2 doesn't answer DDC/CI: the first one that does.
    assert screen_helper.ddc_bus_from_detect(DETECT, "HDMI-A-2") == "20"
    assert screen_helper.ddc_bus_from_detect("No displays found.\n", "HDMI-A-1") is None


def test_the_installer_asks_the_helper_through_the_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config = tmp_path / "config"
    config.write_text("SUNROOM_BRIGHTNESS=none\n")
    assert cli.main(["screen", "--method", "--config", str(config)]) == 0
    assert capsys.readouterr().out == "none\n"  # the wall opens /display?dimmer=page
    assert cli.main(["screen", "--method", "--config", str(tmp_path / "missing")]) == 0
    assert capsys.readouterr().out == "none\n"
    monkeypatch.setattr(sys, "stdin", io.StringIO(DETECT))
    assert cli.main(["screen", "--ddc-bus", "HDMI-A-1"]) == 0
    assert capsys.readouterr().out == "20\n"


def test_a_helper_switched_off_never_starts(tmp_path: Path) -> None:
    settings = screen_helper.settings_from({"SUNROOM_SCREEN_HELPER": "no"})
    thread = screen_helper.ScreenThread(settings, root=tmp_path)
    thread.start()
    assert thread._thread is None  # pyright: ignore[reportPrivateUsage]
    assert screen_helper.dimmer_for(settings, tmp_path) == "page"


def test_the_dimmer_is_the_screen_when_the_helper_sets_the_brightness(tmp_path: Path) -> None:
    backlight(tmp_path)
    settings = screen_helper.settings_from({"SUNROOM_BRIGHTNESS": "auto"})
    assert screen_helper.dimmer_for(settings, tmp_path) == "screen"


def test_retargeting_follows_a_new_address_with_no_etag(tmp_path: Path) -> None:
    thread = screen_helper.ScreenThread(screen_helper.settings_from({}), root=tmp_path)
    thread.helper.etag = "e9"
    thread.retarget("http://192.168.1.21:7867/")
    assert thread.helper.settings.url == "http://192.168.1.21:7867"
    assert thread.helper.etag is None


# ---------------------------------------------------------------------------- the panel


def test_wayland_switches_the_screen_off_and_on_with_wlopm(tmp_path: Path) -> None:
    r = rig(
        tmp_path,
        answer("on", 100, "day", "e1"),
        answer("off", 0, "sleep", "e2"),
        answer("on", 100, "awake", "e3"),
    )
    r.steps(3)
    assert r.shell.calls == ["wlopm --on *", "wlopm --off *", "wlopm --on *"]
    assert r.lines == [
        "Screen on: daytime.",
        "Screen off: sleep time.",
        "Screen on: tapped awake for 2 minutes.",
    ]


def test_wlr_randr_stands_in_when_wlopm_is_missing(tmp_path: Path) -> None:
    shell = Shell(codes={"wlopm": 127}, printed={"wlopm": "wlopm isn't installed"})
    r = rig(tmp_path, answer("off", 0, "sleep"), answer("on", 100, "awake", "e2"), shell=shell)
    r.steps(2)
    assert r.shell.calls == [
        "wlopm --off *",
        "wlr-randr --output HDMI-A-1 --off",
        "wlopm --on *",
        "wlr-randr --output HDMI-A-1 --on",
    ]
    assert r.lines == [
        "wlopm --off * didn't work: wlopm isn't installed.",
        "Screen off: sleep time.",
        "wlopm --on * didn't work: wlopm isn't installed.",
        "Screen on: tapped awake for 2 minutes.",
    ]


def test_x11_uses_xset_and_keeps_x_from_blanking_by_itself(tmp_path: Path) -> None:
    r = rig(
        tmp_path, answer("off", 0, "sleep"), answer("on", 100, "awake", "e2"), SUNROOM_SESSION="x11"
    )
    r.steps(2)
    # Never "xset -dpms": turning DPMS off switches a sleeping screen on.
    assert r.shell.calls == ["xset dpms force off", "xset dpms force on", "xset dpms 0 0 0"]


def test_only_what_changed_is_applied(tmp_path: Path) -> None:
    i2c_bus(tmp_path)
    r = rig(
        tmp_path,
        answer("on", 40, "dim", "e1"),
        answer("on", 40, "dim", "e1"),  # the server's wait ran out: the same state again
        answer("on", 20, "sleep", "e2"),  # the dim clock: still on, darker
        shell=Shell(printed={"ddcutil --brief": "VCP 10 C 100 100"}),
        SUNROOM_BRIGHTNESS="ddc",
        SUNROOM_DDC_BUS="20",
    )
    r.steps(3)
    assert r.shell.calls == [
        "wlopm --on *",
        "ddcutil --brief --bus 20 getvcp 10",
        "ddcutil --bus 20 setvcp 10 40",
        "ddcutil --bus 20 setvcp 10 20",
    ]
    assert r.lines == [
        "Screen on: evening dim.",
        "Brightness 40%: evening dim.",
        "Brightness 20%: sleep time.",
    ]


def test_a_failed_command_is_tried_again_with_the_next_answer(tmp_path: Path) -> None:
    shell = Shell(codes={"wlopm": 1, "wlr-randr": 1})
    r = rig(tmp_path, answer("off", 0, "sleep"), answer("off", 0, "sleep"), shell=shell)
    r.steps(1)
    shell.codes.clear()
    r.steps(1)
    assert r.shell.calls == ["wlopm --off *", "wlr-randr --output HDMI-A-1 --off", "wlopm --off *"]
    assert r.lines[-1] == "Screen off: sleep time."


def test_ddc_sets_the_monitors_brightness_on_its_own_scale(tmp_path: Path) -> None:
    i2c_bus(tmp_path)
    r = rig(
        tmp_path,
        answer("on", 100, "day", "e1"),
        answer("on", 40, "dim", "e2"),
        answer("off", 0, "sleep", "e3"),
        answer("on", 100, "awake", "e4"),
        shell=Shell(printed={"ddcutil --brief": "VCP 10 C 128 255"}),
        SUNROOM_BRIGHTNESS="auto",
        SUNROOM_DDC_BUS="20",
    )
    r.steps(4)
    assert r.shell.calls == [
        "wlopm --on *",
        "ddcutil --brief --bus 20 getvcp 10",
        "ddcutil --bus 20 setvcp 10 255",
        "ddcutil --bus 20 setvcp 10 102",  # 40% of 255
        "wlopm --off *",
        "wlopm --on *",
        "ddcutil --bus 20 setvcp 10 255",
    ]
    assert r.sleeps == [2]  # the monitor gets a moment after waking before DDC/CI
    assert "Brightness 40%: evening dim." in r.lines


def test_a_backlight_is_dimmed_and_switched_off_through_sysfs(tmp_path: Path) -> None:
    device = backlight(tmp_path, maximum=31)
    r = rig(
        tmp_path,
        answer("on", 100, "day", "e1"),
        answer("on", 40, "dim", "e2"),
        answer("off", 0, "sleep", "e3"),
        answer("on", 100, "awake", "e4"),
        SUNROOM_BRIGHTNESS="sysfs",
        SUNROOM_BACKLIGHT="11-0045",
    )
    r.steps(2)
    assert (device / "brightness").read_text() == "12\n"  # 40% of 31
    r.steps(1)
    assert (device / "bl_power").read_text() == "4\n"  # the backlight off; touch keeps working
    r.steps(1)
    assert (device / "bl_power").read_text() == "0\n"
    assert (device / "brightness").read_text() == "31\n"
    assert r.shell.calls == ["wlopm --on *"]  # only at the start, to be sure


def test_a_backlight_that_cant_be_switched_off_falls_back_to_the_panel(tmp_path: Path) -> None:
    device = backlight(tmp_path)
    (device / "bl_power").unlink()
    (device / "bl_power").mkdir()  # so writing it fails
    r = rig(tmp_path, answer("off", 0, "sleep"), SUNROOM_BRIGHTNESS="sysfs")
    r.steps(1)
    assert r.shell.calls == ["wlopm --off *"]
    assert r.lines[0].startswith("Couldn't write ")
    assert r.lines[1] == "Screen off: sleep time."


def test_an_odd_answer_keeps_the_screen_on(tmp_path: Path) -> None:
    state, etag = screen_helper.state_from({"screen": "sideways", "brightness": "dark"})
    assert (state.screen, state.brightness, state.reason, etag) == ("on", 100, "", None)
    assert screen_helper.state_from({"screen": "on", "brightness": 0})[0].brightness == 1
    r = rig(tmp_path, b"<html>Sample proxy page</html>", b"[]")
    r.steps(2)
    assert r.lines == [
        f"No answer from Sunroom at {URL}: its answer wasn't the screen's state. Trying again."
    ]


# ---------------------------------------------------------------------------- failures


def test_the_etag_goes_back_so_the_server_can_wait(tmp_path: Path) -> None:
    r = rig(tmp_path, answer(etag="e1"), answer(etag="e1"), answer(etag="e2"))
    r.steps(3)
    assert r.server.urls[0].startswith(f"{URL}/api/display/state?")
    assert r.server.queries() == [
        {"wait": ["55"]},
        {"wait": ["55"], "etag": ["e1"]},
        {"wait": ["55"], "etag": ["e1"]},
    ]


def test_without_an_answer_it_waits_longer_each_time_up_to_a_minute(tmp_path: Path) -> None:
    r = rig(tmp_path, *[REFUSED] * 8)
    r.steps(8)
    assert r.sleeps == [2, 4, 8, 16, 32, 60, 60, 60]
    assert r.lines == [
        f"No answer from Sunroom at {URL}: nothing answers at that address "
        "(is Sunroom running?). Trying again.",
        "Screen on: Sunroom hasn't answered for half a minute.",
    ]


def test_after_five_failures_in_a_row_the_screen_comes_back_on(tmp_path: Path) -> None:
    r = rig(tmp_path, answer("off", 0, "sleep", "e1"), *[REFUSED] * 6, answer("off", 0, "sleep"))
    r.steps(1 + 4)
    assert r.shell.calls == ["wlopm --off *"]  # four failures: still asleep
    r.steps(1)
    assert r.shell.calls == ["wlopm --off *", "wlopm --on *"]
    r.steps(1)
    assert r.shell.calls == ["wlopm --off *", "wlopm --on *"]  # once is enough
    r.steps(1)  # Sunroom is back; with the etag forgotten, its answer comes at once
    assert r.server.queries()[-1] == {"wait": ["55"]}
    assert r.shell.calls[-1] == "wlopm --off *"
    assert r.lines[-2:] == ["Sunroom answers again.", "Screen off: sleep time."]


def test_an_older_sunroom_without_screen_sleep_is_explained(tmp_path: Path) -> None:
    missing = urllib.error.HTTPError(
        f"{URL}/api/display/state", 404, "Not Found", email.message.Message(), None
    )
    r = rig(tmp_path, missing)
    r.steps(1)
    assert "needs version 0.6.0 or newer" in r.lines[0]
    assert r.shell.calls == []


def test_stopping_switches_a_sleeping_screen_back_on(tmp_path: Path) -> None:
    r = rig(tmp_path, answer("off", 0, "sleep"), screen_helper.Stop())
    r.helper.run_forever()
    assert r.shell.calls == ["wlopm --off *", "wlopm --on *"]
    assert r.lines[-1] == "Stopped; the screen is left on."


def test_stopping_leaves_a_dimmed_backlight_at_full_brightness(tmp_path: Path) -> None:
    device = backlight(tmp_path, maximum=200)
    r = rig(
        tmp_path,
        answer("on", 40, "dim", "e1"),
        answer("off", 0, "sleep", "e2"),
        SUNROOM_BRIGHTNESS="auto",
    )
    r.helper.run_forever()  # the server's answers run out: a stop
    assert (device / "bl_power").read_text() == "0\n"
    assert (device / "brightness").read_text() == "200\n"


def test_stopping_brings_a_ddc_monitor_back_to_full_brightness(tmp_path: Path) -> None:
    """A monitor keeps its DDC/CI brightness after the helper is gone (an uninstall)."""
    i2c_bus(tmp_path)
    r = rig(
        tmp_path,
        answer("on", 40, "dim", "e1"),
        answer("off", 0, "sleep", "e2"),
        shell=Shell(printed={"ddcutil --brief": "VCP 10 C 100 100"}),
        SUNROOM_BRIGHTNESS="ddc",
        SUNROOM_DDC_BUS="20",
    )
    r.helper.run_forever()
    assert r.shell.calls[-2:] == ["wlopm --on *", "ddcutil --bus 20 setvcp 10 100"]
    assert r.sleeps == [2]  # a moment for the monitor to wake first


def test_a_surprise_counts_as_a_failure_not_a_crash(tmp_path: Path) -> None:
    r = rig(tmp_path, RuntimeError("Sample surprise"))
    r.helper.run_forever()
    assert r.sleeps == [2]
    assert "something unexpected went wrong" in r.lines[1]


def test_a_mac_holds_its_display_awake_and_lets_it_sleep(tmp_path: Path) -> None:
    held: list[str] = []

    class Hold:
        def hold(self) -> bool:
            held.append("hold")
            return True

        def release(self) -> None:
            held.append("release")

    r = rig(
        tmp_path,
        answer("on", 100, "day", "e1"),
        answer("off", 0, "sleep", "e2"),
        answer("on", 100, "awake", "e3"),
        SUNROOM_SESSION="macos",
    )
    r.helper.awake = Hold()
    r.steps(3)
    assert r.shell.calls == ["caffeinate -u -t 1", "pmset displaysleepnow", "caffeinate -u -t 1"]
    assert held == ["hold", "release", "hold"]
    assert r.lines == [
        "Screen on: daytime.",
        "Screen off: sleep time.",
        "Screen on: tapped awake for 2 minutes.",
    ]
