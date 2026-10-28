"""Windows' uninstaller (uninstall.py, ADR 0042) against a temporary folder: what it removes, in
what order, and that it waits for Sunroom Screen to quit first. Its commands are recorded, never
run, so it passes on every system. Synthetic paths only."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from sunroom_kiosk import uninstall


def places(tmp_path: Path, *, uv: bool = True) -> uninstall.Places:
    agent = tmp_path / "bin" / "sunroom-kiosk.exe"
    agent.parent.mkdir(parents=True)
    agent.write_text("")
    data = tmp_path / "AppData" / "Local" / "sunroom-kiosk"
    (data / "profile").mkdir(parents=True)
    (data / "config").write_text("SUNROOM_URL=http://192.168.1.20:8080\n")
    shortcut = tmp_path / "Startup" / "Sunroom Screen.lnk"
    shortcut.parent.mkdir(parents=True)
    shortcut.write_text("")
    return uninstall.Places(
        agent=agent,
        data=data,
        shortcut=shortcut,
        uv=tmp_path / "bin" / "uv.exe" if uv else None,
        log=tmp_path / "uninstall.log",
    )


def test_it_takes_off_what_install_ps1_put_on(tmp_path: Path) -> None:
    where = places(tmp_path)
    ran: list[list[str]] = []

    def run(argv: Sequence[str]) -> int:
        ran.append(list(argv))
        return 0

    said = uninstall.uninstall(where, sunroom=False, run=run)
    agent, uv = str(where.agent), str(where.uv)
    assert ran == [[agent, "policy", "--remove"], [uv, "tool", "uninstall", "sunroom-kiosk"]]
    assert not where.shortcut.exists()
    assert not where.data.exists()  # its settings, the browser profile with the pairing, the log
    assert said[-1].startswith("Deleted ")


def test_with_sunroom_it_takes_sunroom_and_the_familys_data_first(tmp_path: Path) -> None:
    where = places(tmp_path)
    ran: list[list[str]] = []

    def run(argv: Sequence[str]) -> int:
        ran.append(list(argv))
        return 0

    uninstall.uninstall(where, sunroom=True, run=run)
    assert ran[0] == [str(where.agent), "sunroom", "remove", "--delete-data"]


def test_a_step_that_fails_is_said_and_the_rest_go_on(tmp_path: Path) -> None:
    where = places(tmp_path, uv=False)

    def run(argv: Sequence[str]) -> int:
        return 1

    said = uninstall.uninstall(where, sunroom=False, run=run)
    assert said[0] == "Took the browser's policy out didn't work (exit 1)."
    assert not where.data.exists()


def test_it_waits_for_sunroom_screen_to_quit() -> None:
    answers = iter([True, True, False])
    assert uninstall.wait_for_quit(lambda: next(answers), within=5, pause=0)
    assert not uninstall.wait_for_quit(lambda: True, within=0.01, pause=0)
