"""An update's apply step (docs/M7.md T9, T14; ADR 0044): install a checked wheel with uv, put
the new version's own setup in place (``sunroom-kiosk setup --from-update``), start Sunroom Screen
again as that setup says, and keep the new version only if it answers within a minute; else put
the wheel before it back, run that version's setup, start it, and leave a note the agent shows
("The update didn't finish. Sunroom Screen 0.17.0 is back.").

Standard library only, and a file that runs on its own: the package's files are replaced under
it. On Linux and macOS it runs as ``sunroom-kiosk update --apply`` (a running program's files may
be replaced there). Windows locks a running program's files, so there the agent copies this file
out of its environment and runs it with the Python that environment was made from, and this asks
the running agent to quit (This Screen's own Quit) before uv replaces anything:

    python apply.py --apply WHEEL --port 7800 [--previous WHEEL] [--force | --back]

``--force`` is Reinstall…: the version already installed, its setup rewritten whole. ``--back`` is
Go Back…: the version this one replaced (ADR 0046). What it's doing goes into the state file's
``progress`` (the agent still running shows it), how it ended into ``last``, which the new version
shows once ("Updated to 0.18.0"), the version an update replaced into ``replaced``, and the one
gone back from into ``went_back_from``, which the overnight update leaves alone.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

SERVICE = "sunroom-kiosk.service"
LAUNCH_AGENT = "app.sunroom.kiosk"
STARTS_WITHIN_S = 60.0
QUITS_WITHIN_S = 30.0
# Windows: this runs without a console (pythonw), so uv would get a console window of its own,
# open on the wall for as long as it installs (platform/base.py's NO_WINDOW; 0 elsewhere).
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# What setup said, as this step needs it: None when it didn't run at all.
type Report = dict[str, Any]


@dataclass(frozen=True)
class Paths:
    wheels: Path  # the running wheel and the one before it
    state: Path  # what the last check said, an update's progress and how it ended

    @classmethod
    def default(cls) -> Paths:
        if sys.platform == "win32":
            base = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "sunroom-kiosk"
            return cls(wheels=base / "wheels", state=base / "update.json")
        home = Path.home()
        return cls(
            wheels=home / ".local" / "share" / "sunroom-kiosk" / "wheels",
            state=home / ".local" / "state" / "sunroom-kiosk" / "update.json",
        )


def bin_dir() -> Path:
    """Where uv puts its tools' commands (and the installers put uv)."""
    return Path.home() / ".local" / "bin"


def uv() -> str:
    found = shutil.which("uv")
    if found:
        return found
    return str(bin_dir() / ("uv.exe" if sys.platform == "win32" else "uv"))


def run(argv: list[str]) -> bool:
    done = subprocess.run(  # noqa: S603
        argv, capture_output=True, text=True, check=False, creationflags=NO_WINDOW
    )
    if done.returncode != 0:
        print(f"{' '.join(argv[:3])} didn't work: {(done.stderr or done.stdout).strip()[:300]}")
    return done.returncode == 0


def run_setup(force: bool) -> Report | None:
    """The installed version's own ``sunroom-kiosk setup --from-update --json``: its report, or
    None when it didn't run (a version that fails here is put back)."""
    command = bin_dir() / ("sunroom-kiosk.exe" if sys.platform == "win32" else "sunroom-kiosk")
    argv = [str(command), "setup", "--from-update", "--json", *(["--force"] if force else [])]
    try:
        done = subprocess.run(  # noqa: S603 - our own command
            argv, capture_output=True, text=True, check=False, timeout=300, creationflags=NO_WINDOW
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        print(f"Its setup didn't run: {error}")
        return None
    try:
        report = json.loads(done.stdout)
    except ValueError:
        print(f"Its setup didn't finish: {(done.stderr or done.stdout).strip()[:300]}")
        return None
    return cast(Report, report) if isinstance(report, dict) else None


def _ask(port: int, method: str = "GET", path: str = "/api/screen") -> dict[str, Any] | None:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}", method=method, headers={"X-Sunroom-Screen": "1"}
    )
    try:
        with urllib.request.urlopen(request, timeout=3) as response:  # noqa: S310
            answer = json.loads(response.read() or b"{}")
    except OSError, ValueError:
        return None
    return cast(dict[str, Any], answer) if isinstance(answer, dict) else {}


def stop_running(port: int) -> bool:
    """Windows: ask the running agent to quit, and wait until it has (its files are free then)."""
    if sys.platform != "win32":
        return True
    _ask(port, "POST", "/api/screen/quit")
    deadline = time.monotonic() + QUITS_WITHIN_S
    while time.monotonic() < deadline and _ask(port) is not None:
        time.sleep(1)
    return True


def start_windows() -> bool:
    """Windows: start the agent again, with no console window, as its Run value does."""
    command = bin_dir() / "sunroom-kioskw.exe"
    folder = Paths.default().state.parent
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
        subprocess, "CREATE_NEW_PROCESS_GROUP", 0
    )
    try:
        subprocess.Popen(  # noqa: S603 - our own command
            [str(command), "run"],
            cwd=folder if folder.is_dir() else None,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
        )
    except OSError as error:
        print(f"Sunroom Screen didn't start: {error}")
        return False
    return True


def restart_service(report: Report | None) -> bool:
    """Start the agent again as its setup says: on a Mac whose LaunchAgent changed, out and in
    again (a running job can't read its own new file); else the service's own restart."""
    changed = cast(list[str], (report or {}).get("changed", []))
    if sys.platform.startswith("linux"):
        if "service" in changed:
            run(["systemctl", "--user", "daemon-reload"])
        return run(["systemctl", "--user", "restart", SERVICE])
    if sys.platform == "darwin":
        domain = f"gui/{os.getuid()}"
        if "launch-agent" in changed:
            plist = Path.home() / "Library" / "LaunchAgents" / f"{LAUNCH_AGENT}.plist"
            run(["launchctl", "bootout", f"{domain}/{LAUNCH_AGENT}"])  # not loaded: fine
            return run(["launchctl", "bootstrap", domain, str(plist)])
        return run(["launchctl", "kickstart", "-k", f"{domain}/{LAUNCH_AGENT}"])
    if sys.platform == "win32":
        return start_windows()
    return False


def answers_as(port: int, release: str, within_s: float) -> bool:
    """Whether the agent on ``port`` answers within ``within_s`` seconds, as ``release``."""
    deadline = time.monotonic() + within_s
    while time.monotonic() < deadline:
        answer = _ask(port)
        if answer is not None and answer.get("version") == release:
            return True
        time.sleep(2)
    return False


def _read(paths: Paths) -> dict[str, Any]:
    try:
        read = json.loads(paths.state.read_text(encoding="utf-8"))
    except OSError, ValueError:
        return {}
    return cast(dict[str, Any], read) if isinstance(read, dict) else {}


def _note(paths: Paths, **values: Any) -> None:
    saved = {**_read(paths), **values}
    paths.state.parent.mkdir(parents=True, exist_ok=True)
    tmp = paths.state.with_name(paths.state.name + ".tmp")
    tmp.write_text(json.dumps(saved, sort_keys=True), encoding="utf-8")
    os.replace(tmp, paths.state)


def note_progress(paths: Paths, percent: int, key: str) -> None:
    """What this step is doing, for the agent still running to show (``agent.update.step.*``)."""
    _note(paths, progress={"percent": percent, "key": key})


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def apply(
    wheel: Path,
    previous: Path | None,
    port: int,
    *,
    force: bool = False,
    back: bool = False,
    install: Callable[[Path], bool] | None = None,
    stop: Callable[[], bool] | None = None,
    setup: Callable[[bool], Report | None] = run_setup,
    restart: Callable[[Report | None], bool] = restart_service,
    answers: Callable[[int, str, float], bool] = answers_as,
    paths: Paths | None = None,
) -> int:
    """Install ``wheel``, set it up, start it, and keep it only if it answers; else put
    ``previous`` back, with its own setup."""
    the_paths = paths or Paths.default()
    release = wheel.name.split("-")[1]
    before = previous.name.split("-")[1] if previous is not None else None

    def uv_install(path: Path) -> bool:
        return run([uv(), "tool", "install", "--reinstall", "--python", "3.14", str(path)])

    def stop_agent() -> bool:
        return stop_running(port)

    put = install or uv_install
    halt = stop or stop_agent
    report: Report | None = None
    went = halt() and put(wheel)
    if went:
        note_progress(the_paths, 70, "agent.update.step.setting_up")
        report = setup(force)
        went = report is not None
    if went:
        note_progress(the_paths, 85, "agent.update.step.starting_again")
        went = restart(report) and answers(port, release, STARTS_WITHIN_S)
    if not went:
        print(f"Sunroom Screen {release} didn't start; putting the previous version back.")
        if previous is not None and previous.exists():
            halt()
            put(previous)
            restart(setup(False))
        note_failure(the_paths, release, before, again=force or back)
        return 1
    if not force:  # a Reinstall… leaves which versions are here as they were: Go Back… still can
        for old in the_paths.wheels.glob("sunroom_kiosk-*.whl"):
            if old not in (wheel, previous):
                old.unlink(missing_ok=True)
    at = _now()
    last = {"version": release, "ok": True, "at": at, "again": force, "back": back}
    if back:
        _note(the_paths, progress=None, last=last, replaced=None, went_back_from=before)
    elif force:
        _note(the_paths, progress=None, last=last)
    else:
        replaced = {"version": before, "by": release, "at": at} if before else None
        _note(the_paths, progress=None, last=last, replaced=replaced, went_back_from=None)
    print(f"Sunroom Screen {release} is running.")
    return 0


def note_failure(
    paths: Paths, release: str, previous: str | None = None, *, again: bool = False
) -> None:
    """How it ended, and the failed version, so the check doesn't offer it as new again (a
    Reinstall… of the version installed offers nothing new either way)."""
    last = {"version": release, "ok": False, "at": _now(), "previous": previous, "again": again}
    if again:
        _note(paths, progress=None, last=last)
    else:
        _note(paths, failed=release, latest=release, progress=None, last=last)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="apply.py", description="Apply a Sunroom Screen update.")
    parser.add_argument("--apply", type=Path, required=True, help="the checked wheel")
    parser.add_argument("--previous", type=Path, default=None, help="the wheel to go back to")
    parser.add_argument("--port", type=int, default=7800)
    parser.add_argument("--force", action="store_true", help="Reinstall…: every file rewritten")
    parser.add_argument("--back", action="store_true", help="Go Back…: the version it replaced")
    args = parser.parse_args(argv)
    return apply(
        cast(Path, args.apply),
        cast(Path | None, args.previous),
        cast(int, args.port),
        force=cast(bool, args.force),
        back=cast(bool, args.back),
    )


if __name__ == "__main__":
    sys.exit(main())
