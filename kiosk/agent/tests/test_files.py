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
