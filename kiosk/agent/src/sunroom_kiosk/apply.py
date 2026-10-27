"""An update's apply step (docs/M7.md T9, T14): install a checked wheel with uv, start Sunroom
Screen again, and keep it only if it answers within a minute; else put the wheel before it back,
start that, and leave a note the agent shows ("The update didn't start; the previous version is
back.").

Standard library only, and a file that runs on its own: the package's files are replaced under
it. On Linux and macOS it runs as ``sunroom-kiosk update --apply`` (a running program's files may
be replaced there). Windows locks a running program's files, so there the agent copies this file
out of its environment and runs it with the Python that environment was made from, and this asks
the running agent to quit (This Screen's own Quit) before uv replaces anything:

    python apply.py --apply WHEEL --port 7800 [--previous WHEEL]
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
from pathlib import Path
from typing import Any, cast

SERVICE = "sunroom-kiosk.service"
LAUNCH_AGENT = "app.sunroom.kiosk"
STARTS_WITHIN_S = 60.0
QUITS_WITHIN_S = 30.0
# Windows: this runs without a console (pythonw), so uv would get a console window of its own,
# open on the wall for as long as it installs (platform/base.py's NO_WINDOW; 0 elsewhere).
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


@dataclass(frozen=True)
class Paths:
    wheels: Path  # the running wheel and the one before it
    state: Path  # what the last check said, and a failed update's note

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
    """Windows: start the agent again, with no console window, as the Startup shortcut does."""
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


def restart_service() -> bool:
    if sys.platform.startswith("linux"):
        return run(["systemctl", "--user", "restart", SERVICE])
    if sys.platform == "darwin":
        return run(["launchctl", "kickstart", "-k", f"gui/{os.getuid()}/{LAUNCH_AGENT}"])
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


def apply(
    wheel: Path,
    previous: Path | None,
    port: int,
    *,
    install: Callable[[Path], bool] | None = None,
    stop: Callable[[], bool] | None = None,
    restart: Callable[[], bool] = restart_service,
    answers: Callable[[int, str, float], bool] = answers_as,
    paths: Paths | None = None,
) -> int:
    """Install ``wheel``, start it, and keep it only if it answers; else put ``previous`` back."""
    the_paths = paths or Paths.default()
    release = wheel.name.split("-")[1]

    def uv_install(path: Path) -> bool:
        return run([uv(), "tool", "install", "--reinstall", "--python", "3.14", str(path)])

    def stop_agent() -> bool:
        return stop_running(port)

    put = install or uv_install
    halt = stop or stop_agent
    if not halt() or not put(wheel) or not restart() or not answers(port, release, STARTS_WITHIN_S):
        print(f"Sunroom Screen {release} didn't start; putting the previous version back.")
        if previous is not None and previous.exists():
            halt()
            put(previous)
            restart()
        note_failure(the_paths, release)
        return 1
    for old in the_paths.wheels.glob("sunroom_kiosk-*.whl"):
        if old not in (wheel, previous):
            old.unlink(missing_ok=True)
    print(f"Sunroom Screen {release} is running.")
    return 0


def note_failure(paths: Paths, release: str) -> None:
    saved: dict[str, Any] = {}
    try:
        read = json.loads(paths.state.read_text(encoding="utf-8"))
        if isinstance(read, dict):
            saved = cast(dict[str, Any], read)
    except OSError, ValueError:
        pass
    saved = {**saved, "failed": release, "latest": release}
    paths.state.parent.mkdir(parents=True, exist_ok=True)
    paths.state.write_text(json.dumps(saved, sort_keys=True), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="apply.py", description="Apply a Sunroom Screen update.")
    parser.add_argument("--apply", type=Path, required=True, help="the checked wheel")
    parser.add_argument("--previous", type=Path, default=None, help="the wheel to go back to")
    parser.add_argument("--port", type=int, default=7800)
    args = parser.parse_args(argv)
    return apply(cast(Path, args.apply), cast(Path | None, args.previous), cast(int, args.port))


if __name__ == "__main__":
    sys.exit(main())
