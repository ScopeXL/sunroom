"""Sunroom Screen's uninstaller on Windows (ADR 0042): what This Screen's Uninstall runs once the
wall page has unpaired the screen. Linux and macOS run the uninstall.sh their installer left
(``--from-screen``); Windows had only ``install.ps1 -Uninstall``, which a family can't type on a
wall.

Standard library only, and a file that runs on its own: it removes the environment the agent
runs from, so the agent copies it out to the temp folder and starts it with the Python that
environment was made from, as it does apply.py (updater.py):

    pythonw uninstall.py --agent C:\\Users\\…\\.local\\bin\\sunroom-kiosk.exe [--sunroom]

It waits for Sunroom Screen to quit (the agent quits right after starting this, closing its
browser), then takes off what install.ps1 put on: Sunroom run on this computer with the family's
data when ``--sunroom`` says so (the agent's own ``sunroom remove --delete-data``), the browser's
policy for this user (``policy --remove``), the Startup shortcut, Sunroom Screen itself (``uv
tool uninstall sunroom-kiosk``) and its folder, ``%LOCALAPPDATA%\\sunroom-kiosk`` (its settings,
the browser profile with the pairing, the log). uv stays, as ``install.ps1 -Uninstall`` leaves it.
Each step that fails is noted in the log beside this file and the rest go on.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

QUITS_WITHIN_S = 30.0
# This runs without a console (pythonw), so each console program it starts would get a window of
# its own on the wall (platform/base.py's NO_WINDOW; 0 elsewhere).
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


@dataclass(frozen=True)
class Places:
    agent: Path  # sunroom-kiosk.exe, uv's command for Sunroom Screen
    data: Path  # %LOCALAPPDATA%\sunroom-kiosk
    shortcut: Path  # the Startup folder's Sunroom Screen.lnk
    uv: Path | None
    log: Path

    @classmethod
    def default(cls, agent: Path) -> Places:
        local = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        appdata = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        startup = appdata / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
        found = shutil.which("uv") or shutil.which("uv", path=str(agent.parent))
        return cls(
            agent=agent,
            data=local / "sunroom-kiosk",
            shortcut=startup / "Sunroom Screen.lnk",
            uv=Path(found) if found else None,
            log=Path(__file__).with_suffix(".log"),
        )


type Run = Callable[[Sequence[str]], int]


def run(argv: Sequence[str]) -> int:
    try:
        return subprocess.run(  # noqa: S603 - our own commands
            list(argv),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=NO_WINDOW,
            check=False,
            timeout=300,
        ).returncode
    except OSError, subprocess.TimeoutExpired:
        return 1


def agent_answers(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/screen", timeout=2):
            return True
    except OSError:
        return False


def wait_for_quit(
    answers: Callable[[], bool], *, within: float = QUITS_WITHIN_S, pause: float = 0.5
) -> bool:
    """Whether Sunroom Screen stopped answering within ``within`` seconds."""
    deadline = time.monotonic() + within
    while time.monotonic() < deadline:
        if not answers():
            return True
        time.sleep(pause)
    return not answers()


def uninstall(places: Places, *, sunroom: bool, run: Run = run) -> list[str]:
    """Each step in order; what happened, in plain lines (the log's)."""
    said: list[str] = []

    def step(argv: Sequence[str], done: str) -> None:
        code = run(argv)
        said.append(done if code == 0 else f"{done.rstrip('.')} didn't work (exit {code}).")

    if places.agent.exists():
        if sunroom:
            step(
                [str(places.agent), "sunroom", "remove", "--delete-data"],
                "Removed Sunroom and its data from this computer.",
            )
        step([str(places.agent), "policy", "--remove"], "Took the browser's policy out.")
    if places.shortcut.exists():
        places.shortcut.unlink(missing_ok=True)
        said.append("Took Sunroom Screen out of the Startup folder.")
    if places.uv is not None:
        step([str(places.uv), "tool", "uninstall", "sunroom-kiosk"], "Uninstalled Sunroom Screen.")
    if places.data.exists():
        shutil.rmtree(places.data, ignore_errors=True)
        said.append(f"Deleted {places.data}: its settings, browser data and log.")
    return said


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Take Sunroom Screen off this computer.")
    parser.add_argument("--agent", required=True, type=Path, help="sunroom-kiosk.exe")
    parser.add_argument("--sunroom", action="store_true", help="Sunroom and its data too")
    parser.add_argument("--port", type=int, default=7800)
    args = parser.parse_args(argv)
    places = Places.default(args.agent)
    lines: list[str] = []
    if not wait_for_quit(lambda: agent_answers(args.port)):
        lines.append("Sunroom Screen didn't quit within 30 seconds; going on anyway.")
    lines += uninstall(places, sunroom=args.sunroom)
    try:
        places.log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
