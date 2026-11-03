"""kiosk/files, what the installer copies: each file agrees with the agent that relies on it. The
root helper is loaded from its file and runs here without root, on a temporary policy path.
Synthetic addresses only."""

from __future__ import annotations

import argparse
import getpass
import hashlib
import importlib.machinery
import importlib.util
import io
import json
import sys
import zipfile
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from sunroom_kiosk import cli, policy, setup_files
from sunroom_kiosk.config import Config
from sunroom_kiosk.files import files_dir
from sunroom_kiosk.platform import linux
from tests.support import FakeRegistry

# The package's copy when the wheel carries it, the checkout's otherwise (ADR 0044).
FILES = files_dir()
KIOSK = Path(__file__).resolve().parents[2]  # the installers aren't in the wheel
URL = "http://192.168.1.20:7867"


def _load(path: Path, name: str) -> ModuleType:
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = module
    loader.exec_module(module)
    return module


root_helper: Any = _load(FILES / "sunroom-kiosk-root", "sunroom_kiosk_root")


def lines(relative: str) -> list[str]:
    return (FILES / relative).read_text(encoding="utf-8").splitlines()


# ---------------------------------------------------------------------------- the root helper


def test_the_root_helper_writes_only_what_the_agent_writes() -> None:
    assert set(root_helper.ALLOWED_KEYS) == set(policy.ALLOWED_KEYS)
    assert set(root_helper.POLICY_FILES) == {
        policy.linux_path(kind).as_posix() for kind in policy.LINUX_DIRS
    }


def test_the_root_helper_writes_a_policy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "managed" / "sunroom-kiosk.json"
    monkeypatch.setattr(root_helper, "POLICY_FILES", {str(target)})
    document = policy.document()
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(document)))
    assert root_helper.write_policy(str(target)) == 0
    assert json.loads(target.read_text(encoding="utf-8")) == document
    assert [p.name for p in target.parent.iterdir()] == ["sunroom-kiosk.json"]  # no temp left


@pytest.mark.parametrize(
    ("given", "why"),
    [
        ('{"ExtensionInstallForcelist": ["sample"]}', "keys"),
        ('{"BrowserSignin": {"nested": true}}', "values"),
        ("not json", "JSON"),
        ('{"TranslateEnabled": false, "x": "' + "y" * 70_000 + '"}', "too big"),
    ],
)
def test_the_root_helper_refuses_any_other_policy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    given: str,
    why: str,
) -> None:
    target = tmp_path / "sunroom-kiosk.json"
    monkeypatch.setattr(root_helper, "POLICY_FILES", {str(target)})
    monkeypatch.setattr(sys, "stdin", io.StringIO(given))
    assert root_helper.write_policy(str(target)) == 2
    assert why in capsys.readouterr().err
    assert not target.exists()


def test_the_root_helper_refuses_another_path_and_other_commands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(policy.document())))
    assert root_helper.write_policy(str(tmp_path / "elsewhere.json")) == 2
    assert not (tmp_path / "elsewhere.json").exists()
    monkeypatch.setattr(root_helper.os, "geteuid", lambda: 1000, raising=False)
    assert root_helper.main(["update-sunroom"]) == 2  # not as root: nothing runs
    monkeypatch.setattr(root_helper.os, "geteuid", lambda: 0, raising=False)
    assert root_helper.main(["write-policy"]) == 2
    assert root_helper.main(["apt-get", "install", "sample"]) == 2
    # Sunroom OS's own commands went with it (ADR 0042).
    assert root_helper.main(["apt-upgrade"]) == 2
    assert root_helper.main(["run-sunroom"]) == 2


def test_sudoers_allows_the_root_helper_and_nothing_else() -> None:
    rules = [line for line in lines("sudoers/sunroom-kiosk") if line and not line.startswith("#")]
    assert rules == [f"@USER@ ALL=(root) NOPASSWD: {linux.ROOT_HELPER}"]


# ---------------------------------------------------------------------------- starting it


def test_the_unit_starts_the_agent_with_no_arguments(monkeypatch: pytest.MonkeyPatch) -> None:
    unit = lines("systemd/sunroom-kiosk.service")
    assert "ExecStart=%h/.local/bin/sunroom-kiosk" in unit
    # Quit exits cleanly (os._exit(0)): a unit that restarted it anyway would undo Quit.
    assert "Restart=on-failure" in unit
    # A stop goes to the agent alone, which closes the browser so it writes its cookies; the
    # browser stopped by systemd's own SIGTERM wrote nothing new (ADR 0040).
    assert "KillMode=mixed" in unit
    ran: list[argparse.Namespace] = []

    def pretend_run(args: argparse.Namespace) -> int:
        ran.append(args)
        return 0

    monkeypatch.setattr(cli, "cmd_run", pretend_run)
    assert cli.main([]) == 0
    assert cli.main(["--port", "7801"]) == 0
    assert [args.port for args in ran] == [cli.DEFAULT_PORT, 7801]


def test_the_desktop_starts_the_agent_through_its_unit() -> None:
    block = lines("labwc/autostart-block")
    assert block[0].startswith("# >>> sunroom-kiosk")  # install.sh's BLOCK_BEGIN
    assert block[-1] == "# <<< sunroom-kiosk <<<"  # and BLOCK_END
    assert "systemctl --user --no-block restart sunroom-kiosk.service" in block
    assert not any("wlr-randr" in line for line in block)  # the agent turns the picture now
    (exec_line,) = [line for line in lines("xdg/sunroom-kiosk.desktop") if line.startswith("Exec=")]
    assert "restart sunroom-kiosk.service" in exec_line


# What the installers wrote themselves before 0.18.0, by the piece of ``sunroom-kiosk setup``
# that writes it now (T14): the user's part has one writer.
HANDED_TO_SETUP: dict[setup_files.Kind, set[str]] = {
    # install_units, write_labwc_autostart (and the X11 entry taken out), apply_labwc_settings,
    # install_helper_copies, and save_state's STATE_LABWC_AUTOSTART_CREATED
    "pi": {
        "service",
        "labwc-autostart",
        "xdg-autostart",
        "labwc-rule",
        "helper-uninstall.sh",
        "helper-labwc-rule.py",
        "install-state",
    },
    # install_units, write_xdg_autostart, install_helper_copies
    "linux": {"service", "xdg-autostart", "helper-uninstall.sh", "helper-labwc-rule.py"},
    # install_launch_agent, install_helper_copies
    "macos": {"launch-agent", "helper-uninstall.sh", "helper-labwc-rule.py"},
    # install.ps1's Add-StartupShortcut (a shortcut then, the Run value now)
    "windows": {"run-value", "startup-shortcut"},
}


@pytest.mark.parametrize("kind", list(HANDED_TO_SETUP))
def test_setup_writes_all_the_installers_used_to(tmp_path: Path, kind: setup_files.Kind) -> None:
    """Nothing the installers stopped writing is missing from setup's pieces; the golden test in
    test_setup_files.py shows they write it the same."""
    home = tmp_path / "home"
    here = setup_files.Machine(
        kind=kind,
        home=home,
        user="ana",
        release="9.9.9",
        settings=Config(session="wayland"),
        config_path=home / "config",
        state_dir=home / "state",
        root=tmp_path / "root",
        command=lambda argv: True,
        registry=FakeRegistry(),
    )
    names = {piece.name for piece in setup_files.user_pieces(here)}
    assert HANDED_TO_SETUP[kind] <= names


def test_the_installers_leave_the_users_part_to_setup() -> None:
    """install.sh renders none of the user's templates any more: each of its runs calls setup,
    as install.ps1 does for Windows' Run value."""
    installer = (KIOSK / "install.sh").read_text(encoding="utf-8")
    for relative in (
        "systemd/sunroom-kiosk.service",
        "labwc/autostart-block",
        "xdg/sunroom-kiosk.desktop",
        "launchd/app.sunroom.kiosk.plist",
    ):
        assert (FILES / relative).is_file(), relative  # setup's, and the uninstaller's lists
        assert f'"$SRC_DIR/files/{relative}"' not in installer, relative
    assert '"$SRC_DIR/labwc-rule.py"' not in installer
    for run in ("setup_kiosk", "install_on_linux", "install_on_macos"):
        start = installer.index(f"\n{run}() {{\n")
        assert "\n\tsetup_screen\n" in installer[start : installer.index("\n}\n", start)], run
    assert "setup --first-install --json" in installer
    windows = (KIOSK / "install.ps1").read_text(encoding="utf-8")
    assert '@("setup", "--first-install")' in windows
    assert "CreateShortcut" not in windows


def test_the_policy_command_prints_one_policy_for_every_address(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main(["policy"]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["LocalNetworkAccessAllowedForUrls"] == ["*"]
    # An older installer's line names the address; it's taken, and changes nothing (ADR 0042).
    assert cli.main(["policy", "--url", f"{URL}/display"]) == 0
    assert json.loads(capsys.readouterr().out) == printed


# ---------------------------------------------------------------------------- uninstalling


def test_the_root_helper_takes_its_files_off_then_itself(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """This Screen's Uninstall (ADR 0042): fixed paths only, its own rule and itself last."""
    files = {name: tmp_path / name for name in ("policy.json", "wifi.conf", "rule", "sudoers")}
    me = tmp_path / "sunroom-kiosk-root"
    for path in [*files.values(), me]:
        path.write_text("")
    monkeypatch.setattr(root_helper, "POLICY_FILES", {str(files["policy.json"])})
    monkeypatch.setattr(root_helper, "SCREEN_FILES", [str(files["wifi.conf"]), str(files["rule"])])
    monkeypatch.setattr(root_helper, "SUDOERS_FILE", str(files["sudoers"]))
    monkeypatch.setattr(root_helper, "SELF", str(me))
    removed: list[str] = []
    real_remove = root_helper.os.remove

    def remove(path: str) -> None:
        removed.append(Path(path).name)
        real_remove(path)

    monkeypatch.setattr(root_helper.os, "remove", remove)

    def no_tool(name: str) -> None:  # no udevadm here (this patches shutil for the test)
        return None

    monkeypatch.setattr(root_helper.shutil, "which", no_tool)
    monkeypatch.setattr(root_helper.os, "geteuid", lambda: 0, raising=False)
    assert root_helper.main(["remove-root-files"]) == 0
    assert removed[-2:] == ["sudoers", "sunroom-kiosk-root"]
    assert not any(path.exists() for path in [*files.values(), me])
    assert root_helper.main(["remove-root-files"]) == 0  # again: nothing left, nothing wrong
    assert root_helper.main(["remove-root-files", "/etc/passwd"]) == 2  # takes no paths


def test_the_root_helper_and_the_uninstaller_name_the_same_files() -> None:
    script = (FILES.parent / "uninstall.sh").read_text(encoding="utf-8")
    for path in [*root_helper.SCREEN_FILES, root_helper.SUDOERS_FILE, root_helper.SELF]:
        assert f'"{path}"' in script, path


@pytest.mark.skipif(sys.platform == "win32", reason="install.sh is Linux's and macOS's")
@pytest.mark.parametrize(
    ("compose", "kept"),
    [
        ('    ports:\n      - "9000:7867"\n    volumes:\n      - sunroom_data:/data\n', "9000"),
        ('    ports:\n      - "8080:8080"\n    volumes:\n      - sunroom_data:/data\n', "8080"),
        ("    volumes:\n      - sunroom_data:/data\n", ""),
        (None, ""),  # no earlier install
    ],
)
def test_running_the_installer_again_finds_the_port_devices_have_saved(
    tmp_path: Path, compose: str | None, kept: str
) -> None:
    """Whatever the container's own port was then (ADR 0045)."""
    import shlex
    import subprocess

    if compose is not None:
        (tmp_path / "docker-compose.yml").write_text(compose, encoding="utf-8")
    installer = (FILES.parent / "install.sh").read_text(encoding="utf-8")
    functions = installer[: installer.rindex('main "$@"')]  # nothing runs until that last line
    pretend = f'sudo() {{ "$@"; }}\nSERVER_DIR={shlex.quote(str(tmp_path))}\n'
    done = subprocess.run(  # noqa: S603 - our own script, on a pretend folder
        ["/bin/bash", "-c", f"{functions}\n{pretend}existing_port\n"],
        env={"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == kept


@pytest.mark.skipif(sys.platform == "win32", reason="the uninstaller is Linux's and macOS's")
def test_the_uninstallers_dry_run_from_the_screen_changes_nothing(tmp_path: Path) -> None:
    """What This Screen's Uninstall would take off, said and left in place."""
    import subprocess

    home = tmp_path / "home"
    profile = home / ".config" / "sunroom-kiosk" / "profile"
    profile.mkdir(parents=True)
    (home / ".local" / "bin").mkdir(parents=True)
    (home / ".local" / "bin" / "sunroom-kiosk").write_text("")
    unit = home / ".config" / "systemd" / "user" / "sunroom.service"
    unit.parent.mkdir(parents=True)
    unit.write_text("")  # Sunroom run on this computer
    script = str(FILES.parent / "uninstall.sh")
    # /bin/bash: a Mac's own 3.2 here, which the uninstaller must run under (GOTCHAS).
    done = subprocess.run(  # noqa: S603 - our own script, on a pretend home
        ["/bin/bash", script, "--dry-run", "--from-screen", "--purge-local"],
        env={"HOME": str(home), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    said = done.stdout
    assert "Nothing on this computer changes." in said
    assert "stop Sunroom Screen and uninstall it" in said
    assert "delete the screen's browser data (its pairing)" in said  # no question from a screen
    assert "delete it and ALL its data" in said
    assert profile.is_dir() and unit.is_file()
    assert not (home / ".local" / "state").exists()  # not even a log


# ---------------------------------------------------------------------------- apply-system

RELEASE = "9.9.9"
WHEEL_NAME = f"sunroom_kiosk-{RELEASE}-py3-none-any.whl"


def wheel(tmp_path: Path, files: dict[str, str]) -> Path:
    """A wheel of our own, with a kiosk/files of its own."""
    path = tmp_path / "wheels" / WHEEL_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("sunroom_kiosk/__init__.py", "")
        for relative, text in files.items():
            archive.writestr(f"sunroom_kiosk/files/{relative}", text)
    return path


SHIPPED = {
    relative: (FILES / relative).read_text(encoding="utf-8")
    for relative in (
        "NetworkManager/zz-sunroom-kiosk-wifi.conf",
        "udev/90-sunroom-kiosk-backlight.rules",
        "modules-load/sunroom-kiosk-i2c.conf",
        "avahi/sunroom.service",
        "sudoers/sunroom-kiosk",
        "sunroom-kiosk-root",
        "packages/pi.txt",
        "packages/linux.txt",
    )
}


class System:
    """Root's commands, written down and answered: which packages are in, what apt offers."""

    def __init__(self, installed: set[str], offered: set[str]) -> None:
        self.installed = installed
        self.offered = offered
        self.groups = {"pi", "adm"}
        self.ran: list[list[str]] = []

    def __call__(self, argv: list[str]) -> tuple[int, str]:
        self.ran.append(argv)
        name = argv[-1]
        if argv[0] == "dpkg-query":
            return 0, "install ok installed" if name in self.installed else "unknown"
        if argv[0] == "apt-cache":
            return (0, "") if name in self.offered else (100, "")
        if "install" in argv:
            self.installed |= set(argv[argv.index("-y") + 1 :])
        if argv[0] == "id":
            return 0, " ".join(sorted(self.groups))
        if argv[0] == "usermod":
            self.groups.add(argv[2])
        return 0, ""

    def index(self, word: str) -> int:
        return next(i for i, argv in enumerate(self.ran) if word in argv)


@pytest.fixture
def system(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> System:
    """The helper's root paths under the test's folder, GitHub's sums and root's commands
    answered here, a Pi on Wayland dimming over DDC/CI."""
    etc = tmp_path / "root"
    for name, path in (
        ("NM_DROPIN", "etc/NetworkManager/conf.d/zz-sunroom-kiosk-wifi.conf"),
        ("BACKLIGHT_RULE", "etc/udev/rules.d/90-sunroom-kiosk-backlight.rules"),
        ("I2C_MODULES", "etc/modules-load.d/sunroom-kiosk-i2c.conf"),
        ("AVAHI_SERVICE", "etc/avahi/services/sunroom.service"),
        ("SUDOERS_FILE", "etc/sudoers.d/sunroom-kiosk"),
        ("SELF", "usr/local/sbin/sunroom-kiosk-root"),
    ):
        monkeypatch.setattr(root_helper, name, str(etc / path))
    (etc / "etc" / "NetworkManager" / "conf.d").mkdir(parents=True)
    monkeypatch.setenv("SUDO_USER", getpass.getuser())
    monkeypatch.setattr(root_helper, "is_pi", lambda: True)

    def settings(home: str) -> dict[str, str]:
        return {"SUNROOM_SESSION": "wayland", "SUNROOM_BRIGHTNESS": "ddc"}

    monkeypatch.setattr(root_helper, "screen_settings", settings)
    answer = System(
        installed={"curl", "ca-certificates", "jq", "qrencode", "python3"},
        offered={"wlr-randr", "ddcutil"},
    )
    monkeypatch.setattr(root_helper, "run", answer)
    return answer


def sums_for(path: Path) -> dict[str, str]:
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest()}


def test_the_helper_says_its_version() -> None:
    assert root_helper.VERSION == "@VERSION@"  # the installer stamps it, as apply-system does


def test_apply_system_refuses_a_wheel_github_doesnt_list(
    tmp_path: Path, system: System, monkeypatch: pytest.MonkeyPatch
) -> None:
    built = wheel(tmp_path, SHIPPED)

    def wrong(release: str) -> dict[str, str]:
        return {WHEEL_NAME: "0" * 64}

    monkeypatch.setattr(root_helper, "fetch_sums", wrong)
    assert root_helper.apply_system(str(built)) == 2
    assert system.ran == []
    assert not Path(root_helper.SUDOERS_FILE).exists() and not Path(root_helper.NM_DROPIN).exists()

    def right(release: str) -> dict[str, str]:
        return sums_for(built)

    monkeypatch.setattr(root_helper, "fetch_sums", right)
    other = tmp_path / "elsewhere" / "sunroom_kiosk-1.0-py3-none-any.whl"  # not a release's name
    other.parent.mkdir()
    other.write_bytes(built.read_bytes())
    assert root_helper.apply_system(str(other)) == 2


def test_apply_system_puts_the_releases_system_part_in_place(
    tmp_path: Path,
    system: System,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    built = wheel(tmp_path, SHIPPED)
    asked: list[str] = []

    def sums(release: str) -> dict[str, str]:
        asked.append(release)
        return sums_for(built)

    monkeypatch.setattr(root_helper, "fetch_sums", sums)
    assert root_helper.apply_system(str(built)) == 0
    assert asked == [RELEASE]  # the release's own sums, from GitHub, by the wheel's name
    report = json.loads(capsys.readouterr().out)
    assert report["changed"] == ["wifi", "i2c", "packages", "groups", "sudoers", "helper"]
    # A desktop's package (wlr-randr) and a group (i2c) both count from the next sign-in.
    assert report["failed"] == [] and report["needs_reboot"] is True
    assert ["usermod", "-aG", "i2c", getpass.getuser()] in system.ran
    wifi = Path(root_helper.NM_DROPIN).read_text(encoding="utf-8")
    assert wifi.startswith(f"# Written by the Sunroom installer (kiosk/install.sh {RELEASE}).")
    assert not Path(root_helper.BACKLIGHT_RULE).exists()  # this screen dims over DDC/CI
    installs = [argv for argv in system.ran if "install" in argv]
    assert installs and installs[0][-2:] == ["wlr-randr", "ddcutil"]  # wlopm isn't offered
    assert "x11-xserver-utils" not in installs[0]  # Wayland's, not X11's
    rule = Path(root_helper.SUDOERS_FILE)
    assert f"{getpass.getuser()} ALL=(root) NOPASSWD:" in rule.read_text(encoding="utf-8")
    assert oct(rule.stat().st_mode & 0o777) == "0o440"
    helper = Path(root_helper.SELF).read_text(encoding="utf-8")
    assert f'VERSION = "{RELEASE}"' in helper and helper.startswith("#!/usr/bin/python3\n# Written")
    # Who may run the helper changes last, after the packages and the groups.
    assert system.index("visudo") > system.index("install")
    assert root_helper.apply_system(str(built)) == 0  # again: nothing left to change
    assert json.loads(capsys.readouterr().out)["changed"] == []


def test_the_packages_follow_the_desktop_and_the_brightness() -> None:
    listed = "curl\nwayland:wlr-randr\nx11:unclutter\nddc:ddcutil\n# a note\nBad Name\n"
    assert root_helper.packages(listed, "x11", "backlight") == [
        ("curl", False),
        ("unclutter", True),
    ]
    assert root_helper.packages(listed, "wayland", "ddc") == [
        ("curl", False),
        ("wlr-randr", True),
        ("ddcutil", False),
    ]
