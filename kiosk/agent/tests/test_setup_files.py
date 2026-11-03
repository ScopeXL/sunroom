"""``sunroom-kiosk setup`` (setup_files.py, ADR 0044): the screen's own start-up files from this
version's templates, on temporary folders (a home and a root of their own) and the pretend
commands; nothing on this machine changes. The golden test runs the installer's own functions on
another home and compares; others run the installer's install-state and its reading of setup's
report beside setup itself. Synthetic values only."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from sunroom_kiosk import cli, local, setup_files
from sunroom_kiosk import config as settings_file
from sunroom_kiosk.config import Config
from sunroom_kiosk.files import files_dir, script
from sunroom_kiosk.setup_files import Kind, Machine
from tests.support import FakeRegistry

KIOSK = Path(__file__).resolve().parents[2]
RELEASE = "9.9.9"


class Commands:
    """What setup asked the machine to do: python (labwc-rule.py) runs for real, on the test's
    own files; everything else is only written down."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str]) -> bool:
        self.calls.append(argv)
        if argv[0] == sys.executable:
            return subprocess.run(argv, capture_output=True, check=False).returncode in (0, 2)  # noqa: S603
        return True

    def ran(self, *words: str) -> int:
        return sum(1 for call in self.calls if all(word in call for word in words))


def machine(
    tmp_path: Path,
    kind: Kind = "linux",
    *,
    release: str = RELEASE,
    settings: Config | None = None,
    commands: Commands | None = None,
    registry: FakeRegistry | None = None,
) -> Machine:
    home = tmp_path / "home"
    return Machine(
        kind=kind,
        home=home,
        user="ana",
        release=release,
        settings=settings or Config(session="wayland", output="HDMI-A-1"),
        config_path=home / ".config" / "sunroom-kiosk" / "config",
        state_dir=home / ".local" / "state" / "sunroom-kiosk",
        root=tmp_path / "root",
        command=commands or Commands(),
        registry=registry,
        places=local.Places.default(system="linux", home=home),
    )


def text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------- the same as the installer

INSTALLER_FUNCTIONS = (
    "header_comment",
    "stamp_file",
    "render",
    "install_template",
    "install_stamped",
    "save_state",
    "report_says",
    "report_failures",
)


def installer_script(tmp_path: Path, home: Path) -> Path:
    """The installer's functions, written to a file first (macOS's bash 3.2 can't source a
    process substitution), with the values a run would have."""
    source = text(KIOSK / "install.sh")
    bodies: list[str] = []
    for name in INSTALLER_FUNCTIONS:
        start = source.index(f"\n{name}() {{\n") + 1
        end = source.index("\n}\n", start) + 3
        bodies.append(source[start:end])
    path = tmp_path / "installer-functions.sh"
    path.write_text(
        "set -euo pipefail\n"
        f"KIOSK_VERSION={RELEASE}\nSRC_DIR='{KIOSK}'\nTMP_DIR='{tmp_path / 'tmp'}'\n"
        f"HOME='{home}'\nLABWC_DIR=\"$HOME/.config/labwc\"\n"
        'STATE_DIR="$HOME/.local/state/sunroom-kiosk"\nSTATE_FILE="$STATE_DIR/install-state"\n'
        "SUNROOM_IMAGE=scopexl/sunroom\nIMAGE_TAG=latest\nPORT=7867\n"
        "TEMPLATE_TZ=Etc/UTC\nTEMPLATE_ADVERTISED=\n"
        "note() { :; }\ntidy() { printf '%s' \"$1\"; }\nid() { printf 'ana\\n'; }\n"
        + "".join(bodies),
        encoding="utf-8",
    )
    (tmp_path / "tmp").mkdir(exist_ok=True)
    return path


def bash(functions: Path, steps: str, *args: str) -> subprocess.CompletedProcess[str]:
    """``steps`` run with the installer's functions; ``args`` are their ``$1``…"""
    return subprocess.run(  # noqa: S603
        ["bash", "-c", f". '{functions}'\n{steps}", "installer", *args],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.skipif(sys.platform == "win32" or not shutil.which("bash"), reason="needs bash")
def test_each_piece_is_what_the_installer_writes(tmp_path: Path) -> None:
    """The user's part, as 0.17.0's installer wrote it with the render, install_template and
    install_stamped it still writes root's part with: since 0.18.0 setup alone writes it (T14),
    and a screen installed before finds its files unchanged but for their version."""
    by_installer = tmp_path / "installer"
    functions = installer_script(tmp_path, by_installer)
    files, share = '"$SRC_DIR/files', '"$HOME/.local/share/sunroom-kiosk'
    plist = "app.sunroom.kiosk.plist"
    steps = "\n".join(
        [
            f'install_template {files}/systemd/sunroom-kiosk.service" \\',
            '  "$HOME/.config/systemd/user/sunroom-kiosk.service" 0644',
            f'install_template {files}/xdg/sunroom-kiosk.desktop" \\',
            '  "$HOME/.config/autostart/sunroom-kiosk.desktop" 0644',
            f'install_stamped "$SRC_DIR/uninstall.sh" {share}/uninstall.sh" 0755',
            f'install_stamped "$SRC_DIR/labwc-rule.py" {share}/labwc-rule.py" 0755',
            # The block after the desktop's own lines and one blank line, as its
            # write_labwc_autostart put it.
            'mkdir -p "$LABWC_DIR"',
            '{ printf "some-panel &\\n\\n"; render "$SRC_DIR/files/labwc/autostart-block"; } \\',
            '  >"$LABWC_DIR/autostart"',
            'mkdir -p "$HOME/Library/LaunchAgents"',
            f'render {files}/launchd/{plist}" >"$HOME/Library/LaunchAgents/{plist}"',
        ]
    )
    done = bash(functions, steps)
    assert done.returncode == 0, done.stderr

    linux = machine(tmp_path / "linux")
    setup_files.run(linux)
    pi = machine(tmp_path / "pi", "pi")
    (pi.home / ".config" / "labwc").mkdir(parents=True)
    (pi.home / ".config" / "labwc" / "autostart").write_text("some-panel &\n\n", encoding="utf-8")
    setup_files.run(pi)
    mac = machine(tmp_path / "mac", "macos")
    setup_files.run(mac)

    for home, relative in [
        (linux.home, ".config/systemd/user/sunroom-kiosk.service"),
        (linux.home, ".config/autostart/sunroom-kiosk.desktop"),
        (linux.home, ".local/share/sunroom-kiosk/uninstall.sh"),
        (linux.home, ".local/share/sunroom-kiosk/labwc-rule.py"),
        (pi.home, ".config/labwc/autostart"),
        (mac.home, "Library/LaunchAgents/app.sunroom.kiosk.plist"),
    ]:
        ours = text(home / relative).replace(str(home), "~")
        assert ours == text(by_installer / relative).replace(str(by_installer), "~"), relative
    assert os.stat(linux.home / ".local/share/sunroom-kiosk/uninstall.sh").st_mode & 0o777 == 0o755


# save_state's variables, the changes only the installer makes (with sudo, in a terminal).
STATE_VARIABLES = (
    "MODE",
    "SESSION",
    "TIME_WAIT_SYNC_BY_US",
    "NM_DROPIN_WRITTEN",
    "CMDLINE_FILE",
    "CMDLINE_BACKUP",
    "CMDLINE_KEYS",
    "BACKLIGHT_RULE_WRITTEN",
    "I2C_MODULES_WRITTEN",
)


def save_state(functions: Path, values: dict[str, str]) -> None:
    steps = "".join(f'{name}="${{{at}}}"\n' for at, name in enumerate(STATE_VARIABLES, 1))
    given = [values.get(name, "") for name in STATE_VARIABLES]
    done = bash(functions, f"{steps}save_state", *given)
    assert done.returncode == 0, done.stderr


@pytest.mark.skipif(sys.platform == "win32" or not shutil.which("bash"), reason="needs bash")
def test_the_installer_and_setup_keep_each_others_keys_in_the_install_state(
    tmp_path: Path,
) -> None:
    """One file, two writers (T14): the installer's save_state sets its own keys and keeps
    setup's, setup keeps the installer's, and both start a file with the same header. An older
    installer's header goes."""
    pi = machine(tmp_path, "pi")
    state = pi.state_dir / "install-state"
    state.parent.mkdir(parents=True)
    state.write_text(
        "# What the Sunroom installer (kiosk/install.sh 0.17.0) changed outside its own files,\n"
        "# read by kiosk/uninstall.sh to put things back. Rewritten on every run.\n"
        "STATE_MODE=display\nSTATE_LABWC_AUTOSTART_CREATED=0\nSTATE_TIME_WAIT_SYNC_BY_US=1\n",
        encoding="utf-8",
    )
    setup_files.run(pi)  # the installer's run of it, before its own root steps
    functions = installer_script(tmp_path, pi.home)
    save_state(
        functions,
        {
            "MODE": "all",
            "SESSION": "wayland",
            "TIME_WAIT_SYNC_BY_US": "1",
            "NM_DROPIN_WRITTEN": "/etc/NetworkManager/conf.d/zz-sunroom-kiosk-wifi.conf",
            "CMDLINE_FILE": "/boot/firmware/cmdline.txt",
            "CMDLINE_KEYS": "video=HDMI-A-1: vc4.force_hotplug=",
        },
    )
    saved = text(state)
    assert saved.startswith(setup_files._STATE_HEADER)
    assert "Rewritten on every run" not in saved
    assert settings_file.parse_values(saved) == {
        "STATE_MODE": "all",
        "STATE_SESSION": "wayland",
        "STATE_TIME_WAIT_SYNC_BY_US": "1",
        "STATE_NM_DROPIN": "/etc/NetworkManager/conf.d/zz-sunroom-kiosk-wifi.conf",
        "STATE_CMDLINE_FILE": "/boot/firmware/cmdline.txt",
        "STATE_CMDLINE_BACKUP": "",
        "STATE_CMDLINE_KEYS": "video=HDMI-A-1: vc4.force_hotplug=",
        "STATE_BACKLIGHT_RULE": "",
        "STATE_I2C_MODULES": "",
        "STATE_LABWC_AUTOSTART_CREATED": "1",  # setup made labwc's autostart: its word stands
        "STATE_SETUP_VERSION": RELEASE,
    }
    # The screen's next start: nothing in it to change, the installer's keys as they were.
    assert "install-state" not in setup_files.run(pi).changed
    assert text(state) == saved
    # Sunroom alone has no setup: the installer starts the file, with the same header.
    state.unlink()
    save_state(functions, {"MODE": "server"})
    assert text(state).startswith(setup_files._STATE_HEADER)
    assert settings_file.parse_values(text(state))["STATE_MODE"] == "server"


@pytest.mark.skipif(sys.platform == "win32" or not shutil.which("bash"), reason="needs bash")
def test_the_installer_reads_setups_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """install.sh's report_says and report_failures on the --json report as the command prints it
    (T14): a Pi's first install asks for a restart, the next run doesn't, and an entry that
    couldn't be written is named."""
    here: list[Machine] = [machine(tmp_path / "pi", "pi")]

    def this_one(cls: type[Machine]) -> Machine:
        return here[0]

    monkeypatch.setattr(setup_files.Machine, "here", classmethod(this_one))
    reports: list[str] = []
    for _ in range(2):
        assert cli.main(["setup", "--first-install", "--json"]) == 0
        reports.append(capsys.readouterr().out)
    functions = installer_script(tmp_path, here[0].home)
    assert bash(functions, 'report_says "$1" needs_reboot', reports[0]).returncode == 0
    assert bash(functions, 'report_says "$1" needs_reboot', reports[1]).returncode == 1
    assert bash(functions, 'report_says "$1" needs_restart', reports[1]).returncode == 1
    assert bash(functions, 'report_failures "$1"', reports[0]).stdout == ""

    broken = machine(tmp_path / "broken")
    (broken.home / ".config").mkdir(parents=True)
    (broken.home / ".config" / "systemd").write_text("", encoding="utf-8")  # not a folder
    here[0] = broken
    assert cli.main(["setup", "--first-install", "--json"]) == 1
    failures = bash(functions, 'report_failures "$1"', capsys.readouterr().out).stdout
    assert failures.startswith("service: ") and failures.count("\n") == 1


def test_a_pi_is_raspberry_pi_os_as_the_installer_sees_it(tmp_path: Path) -> None:
    """install.sh sets up a Pi only on Raspberry Pi OS (raspi-config), and any other system as
    another Linux computer; setup agrees, or it would swap the XDG entry the installer handed it
    for labwc's block (T14)."""
    model = tmp_path / "proc" / "device-tree" / "model"
    model.parent.mkdir(parents=True)
    model.write_text("Raspberry Pi 5 Model B Rev 1.0\x00", encoding="utf-8")
    assert not setup_files.raspberry_pi_os(tmp_path)  # another system on a Pi
    tool = tmp_path / "usr" / "bin" / "raspi-config"
    tool.parent.mkdir(parents=True)
    tool.write_text("", encoding="utf-8")
    assert setup_files.raspberry_pi_os(tmp_path)
    model.write_text("Generic Board\x00", encoding="utf-8")
    assert not setup_files.raspberry_pi_os(tmp_path)


def test_the_templates_are_the_packages_or_the_checkouts() -> None:
    assert (files_dir() / "systemd" / "sunroom-kiosk.service").is_file()
    assert (files_dir() / "sunroom-kiosk-root").is_file()
    for helper in ("uninstall.sh", "labwc-rule.py", "update.sh"):
        assert script(helper).is_file(), helper


# ---------------------------------------------------------------------- what a run does


def test_a_second_run_changes_nothing(tmp_path: Path) -> None:
    pi = machine(tmp_path, "pi")
    first = setup_files.run(pi)
    assert {"service", "labwc-autostart", "labwc-rule", "helper-uninstall.sh"} <= set(first.changed)
    assert first.needs_reboot and first.needs_restart
    again = setup_files.run(pi)
    assert again.changed == [] and again.failed == []
    assert not again.needs_reboot and not again.needs_restart


def test_a_new_version_rewrites_its_stamp_without_a_restart(tmp_path: Path) -> None:
    setup_files.run(machine(tmp_path, "pi"))
    later = machine(tmp_path, "pi", release="9.9.10")
    report = setup_files.run(later)
    assert report.changed == [] and not report.needs_reboot and not report.needs_restart
    assert "installer 9.9.10" in text(later.home / ".config" / "labwc" / "autostart")
    assert "kiosk/install.sh 9.9.10" in text(
        later.home / ".config" / "systemd" / "user" / "sunroom-kiosk.service"
    )


def test_a_changed_template_changes_the_file_and_says_what_it_needs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    commands = Commands()
    pi = machine(tmp_path, "pi", commands=commands)
    setup_files.run(pi)
    original = setup_files.template

    def edited(relative: str) -> str:
        changed = original(relative)
        if relative == "systemd/sunroom-kiosk.service":
            return changed.replace("RestartSec=3", "RestartSec=5")
        if relative == "labwc/autostart-block":
            return changed.replace("--no-block restart", "--no-block start")
        return changed

    monkeypatch.setattr(setup_files, "template", edited)
    reloads = commands.ran("daemon-reload")
    report = setup_files.run(pi)
    assert report.changed == ["service", "labwc-autostart"]
    assert report.needs_restart and report.needs_reboot
    assert "RestartSec=5" in text(
        pi.home / ".config" / "systemd" / "user" / "sunroom-kiosk.service"
    )
    assert commands.ran("daemon-reload") == reloads + 1


def test_check_says_and_changes_nothing(tmp_path: Path) -> None:
    linux = machine(tmp_path)
    report = setup_files.run(linux, check=True)
    assert "service" in report.changed and report.needs_restart
    assert not (linux.home / ".config").exists()


def test_force_rewrites_every_piece(tmp_path: Path) -> None:
    commands = Commands()
    linux = machine(tmp_path, commands=commands)
    setup_files.run(linux)
    reloads = commands.ran("daemon-reload")
    report = setup_files.run(linux, force=True)
    assert report.changed == []  # nothing differed, so nothing to restart for
    assert commands.ran("daemon-reload") == reloads + 1


def test_a_pi_on_x11_starts_through_xdg_and_loses_the_labwc_block(tmp_path: Path) -> None:
    pi = machine(tmp_path, "pi", settings=Config(session="x11"))
    autostart = pi.home / ".config" / "labwc" / "autostart"
    autostart.parent.mkdir(parents=True)
    block = setup_files.render(setup_files.template("labwc/autostart-block"), pi.values)
    autostart.write_text(f"some-panel &\n\n{block}", encoding="utf-8")
    report = setup_files.run(pi)
    assert "labwc-autostart" in report.changed and "xdg-autostart" in report.changed
    assert text(autostart) == "some-panel &\n\n"
    assert (pi.home / ".config" / "autostart" / "sunroom-kiosk.desktop").is_file()


def test_the_settings_file_is_brought_to_this_versions_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    linux = machine(tmp_path)
    linux.config_path.parent.mkdir(parents=True)
    linux.config_path.write_text(
        "# set by hand\nSUNROOM_URL=http://192.168.1.20:7867\nSUNROOM_OLD=yes\nLATER=1\n",
        encoding="utf-8",
    )
    assert "settings" not in setup_files.run(linux).changed  # only its version, quietly
    assert text(linux.config_path) == (
        "# set by hand\nSUNROOM_URL=http://192.168.1.20:7867\nSUNROOM_OLD=yes\nLATER=1\n"
        "SUNROOM_CONFIG_VERSION=1\n"
    )

    def rename(values: dict[str, str]) -> dict[str, str]:
        moved = {key: value for key, value in values.items() if key != "SUNROOM_OLD"}
        return moved | {"SUNROOM_NEW": values.get("SUNROOM_OLD", "")}

    monkeypatch.setattr(settings_file, "STEPS", (rename,))
    monkeypatch.setattr(settings_file, "CONFIG_VERSION", 2)
    assert "settings" in setup_files.run(linux).changed
    assert text(linux.config_path) == (
        "# set by hand\nSUNROOM_URL=http://192.168.1.20:7867\nLATER=1\n"
        "SUNROOM_CONFIG_VERSION=2\nSUNROOM_NEW=yes\n"
    )


def test_the_install_state_keeps_its_keys_and_says_who_made_the_autostart(tmp_path: Path) -> None:
    pi = machine(tmp_path, "pi")
    state = pi.state_dir / "install-state"
    state.parent.mkdir(parents=True)
    state.write_text(
        "# the installer's\nSTATE_MODE=display\nSTATE_NM_DROPIN=''\n", encoding="utf-8"
    )
    setup_files.run(pi)
    values = settings_file.parse_values(text(state))
    assert values == {
        "STATE_MODE": "display",
        "STATE_NM_DROPIN": "",
        "STATE_SETUP_VERSION": RELEASE,
        "STATE_LABWC_AUTOSTART_CREATED": "1",
    }
    assert text(state).startswith("# the installer's\n")


def test_windows_starts_from_the_run_value_and_loses_the_old_shortcut(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    startup = tmp_path / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    startup.mkdir(parents=True)
    (startup / "Sunroom Screen.lnk").write_bytes(b"L\x00\x00\x00 a shortcut")
    registry = FakeRegistry()
    windows = machine(tmp_path, "windows", registry=registry)
    report = setup_files.run(windows)
    assert report.changed == ["run-value", "startup-shortcut"]
    command = f'"{windows.home / ".local" / "bin" / "sunroom-kioskw.exe"}" run'
    assert registry.keys[setup_files.RUN_KEY][setup_files.RUN_NAME] == ("REG_SZ", command)
    assert not (startup / "Sunroom Screen.lnk").exists()
    assert setup_files.run(windows).changed == []


def test_sunroom_run_here_gets_its_service_back(tmp_path: Path) -> None:
    linux = machine(tmp_path)
    places = linux.places
    assert places is not None
    places.state.parent.mkdir(parents=True)
    places.state.write_text(
        json.dumps({"port": 7867, "advertised": "http://screen.local:7867"}), encoding="utf-8"
    )
    places.unit.parent.mkdir(parents=True)
    places.unit.write_text("[Unit]\nDescription=broken\n", encoding="utf-8")
    assert "sunroom-service" in setup_files.run(linux).changed
    unit = text(places.unit)
    assert "SUNROOM_ADVERTISED_URL=http://screen.local:7867" in unit
    assert "ExecStart=" in unit and "serve" in unit


def test_roots_part_is_only_named(tmp_path: Path) -> None:
    pi = machine(tmp_path, "pi")
    state = pi.state_dir / "install-state"
    state.parent.mkdir(parents=True)
    state.write_text(
        "STATE_NM_DROPIN=/etc/NetworkManager/conf.d/zz-sunroom-kiosk-wifi.conf\n", encoding="utf-8"
    )
    helper = pi.at("/usr/local/sbin/sunroom-kiosk-root")
    helper.parent.mkdir(parents=True)
    older = setup_files.render(setup_files.template("sunroom-kiosk-root"), pi.values)
    helper.write_text(setup_files.stamp(older, "9.9.1"), encoding="utf-8")  # same words, older
    report = setup_files.run(pi)
    assert report.needs_root == ["wifi"]  # the drop-in isn't there; the helper says the same
    helper.write_text(setup_files.stamp(older.replace("2", "3"), "9.9.1"), encoding="utf-8")
    assert setup_files.run(pi).needs_root == ["helper", "wifi"]
    assert not pi.at("/etc/NetworkManager").exists()  # never written here


def test_another_linux_computer_without_the_helper_isnt_asked_for_it(tmp_path: Path) -> None:
    assert setup_files.run(machine(tmp_path)).needs_root == []


def test_the_small_files_are_copied_aside_and_three_versions_kept(tmp_path: Path) -> None:
    linux = machine(tmp_path)
    for patch in range(4):
        linux = machine(tmp_path, release=f"9.9.{patch}")
        linux.config_path.parent.mkdir(parents=True, exist_ok=True)
        linux.config_path.write_text(f"SUNROOM_URL=http://192.168.1.{patch}:7867\n", "utf-8")
        setup_files.run(linux, force=True)
    backups = linux.state_dir / "backup"
    assert sorted(entry.name for entry in backups.iterdir()) == ["9.9.1", "9.9.2", "9.9.3"]
    assert "192.168.1.3" in text(backups / "9.9.3" / "config")


def test_the_json_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    linux = machine(tmp_path)

    def here(cls: type[Machine]) -> Machine:
        return linux

    monkeypatch.setattr(setup_files.Machine, "here", classmethod(here))
    assert cli.main(["setup", "--check", "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert set(report) == {
        "version",
        "changed",
        "failed",
        "needs_restart",
        "needs_reboot",
        "needs_root",
    }
    assert report["version"] == RELEASE and "service" in report["changed"]


def test_from_an_update_the_report_is_kept_for_the_next_start(tmp_path: Path) -> None:
    update_json = tmp_path / "update.json"
    update_json.write_text(json.dumps({"latest": "9.9.9"}), encoding="utf-8")
    report = setup_files.run(machine(tmp_path))
    setup_files.save_report(report, update_json)
    saved = json.loads(text(update_json))
    assert saved["latest"] == "9.9.9" and saved["setup"]["changed"] == report.changed


def test_the_terminal_is_asked_for_only_when_the_helper_cant_put_roots_part_right() -> None:
    line = "curl -fsSL … | bash"
    assert setup_files.needs_terminal(None, ["helper"], line) == line  # from before 0.18.0
    assert setup_files.needs_terminal("0.17.0", ["helper"], line) == line
    assert setup_files.needs_terminal(setup_files.SYSTEM_PART_SINCE, ["wifi"], line) is None
    assert setup_files.needs_terminal(None, [], line) is None  # nothing of root's differs
    assert setup_files.needs_terminal(None, ["helper"], None) is None  # a Mac, Windows
