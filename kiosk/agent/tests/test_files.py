"""kiosk/files, what the installer copies: each file agrees with the agent that relies on it. The
root helper is loaded from its file and runs here without root, on a temporary policy path.
Synthetic addresses only."""

from __future__ import annotations

import argparse
import importlib.machinery
import importlib.util
import io
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from sunroom_kiosk import cli, policy
from sunroom_kiosk.platform import linux

FILES = Path(__file__).resolve().parents[2] / "files"
URL = "http://192.168.1.20:8080"


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
