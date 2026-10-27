"""The wall's browser (browser.py): which one, its flags, the clean-exit mark, the nightly
restart's time, the supervisor starting it again after it exits and asking it to close before it
forces it (on Windows, with no console window), and Edge kept full screen. The "browser" here is
a tiny script; nothing real is started. Synthetic data only."""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from zoneinfo import ZoneInfo

import pytest

from sunroom_kiosk import browser as browser_module
from sunroom_kiosk.browser import (
    Browser,
    DevTools,
    Supervisor,
    close_command,
    find_browser,
    flags,
    insecure_origin,
    mark_clean_exit,
    next_nightly,
)
from sunroom_kiosk.platform.base import NO_WINDOW

CHROMIUM = Browser("chromium", "/usr/bin/chromium", "Chromium")
EDGE = Browser(
    "edge", r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe", "Microsoft Edge"
)
CHROME = Browser(
    "chrome", r"C:\Program Files\Google\Chrome\Application\chrome.exe", "Google Chrome"
)


def test_linux_prefers_chromium_then_chrome_then_edge() -> None:
    installed = {
        "google-chrome": "/usr/bin/google-chrome",
        "microsoft-edge": "/usr/bin/microsoft-edge",
    }
    found = find_browser("linux", which=installed.get, snap=lambda path: False)
    assert found == Browser("chrome", "/usr/bin/google-chrome", "Google Chrome")
    installed["chromium-browser"] = "/usr/bin/chromium-browser"
    assert find_browser("linux", which=installed.get, snap=lambda path: False) == Browser(
        "chromium", "/usr/bin/chromium-browser", "Chromium"
    )
    assert find_browser("linux", which=lambda name: None) is None


def test_linux_passes_over_a_snaps_browser() -> None:
    installed = {
        "chromium": "/snap/bin/chromium",
        "chromium-browser": "/usr/bin/chromium-browser",  # Ubuntu's script that runs the snap
        "google-chrome": "/usr/bin/google-chrome",
    }
    snaps = {"/snap/bin/chromium", "/usr/bin/chromium-browser"}
    assert find_browser("linux", which=installed.get, snap=snaps.__contains__) == Browser(
        "chrome", "/usr/bin/google-chrome", "Google Chrome"
    )
    del installed["google-chrome"]
    assert find_browser("linux", which=installed.get, snap=snaps.__contains__) is None


def test_a_snap_is_known_by_its_path_or_by_the_script_that_runs_it(tmp_path: Path) -> None:
    wrapper = tmp_path / "chromium-browser"
    wrapper.write_text('#!/bin/sh\nexec /snap/bin/chromium "$@"\n')
    plain = tmp_path / "chromium"
    plain.write_text('#!/bin/sh\nexec /usr/lib/chromium/chromium "$@"\n')
    program = tmp_path / "chrome"
    program.write_bytes(b"\x7fELF\x02\x01\x01\x00/snap/")
    assert browser_module.is_snap("/snap/bin/chromium")
    assert browser_module.is_snap(str(wrapper))
    assert not browser_module.is_snap(str(plain))
    assert not browser_module.is_snap(str(program))
    assert not browser_module.is_snap(str(tmp_path / "missing"))


def test_macos_looks_in_applications() -> None:
    edge = "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"
    assert find_browser("darwin", exists=lambda path: path == edge, home="/Users/ana") == Browser(
        "edge", edge, "Microsoft Edge"
    )


def test_macos_looks_in_the_accounts_own_applications_too() -> None:
    mine = "/Users/ana/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    shared = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    edge = "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"
    installed = {mine, edge}
    assert find_browser("darwin", exists=installed.__contains__, home="/Users/ana") == Browser(
        "chrome", mine, "Google Chrome"
    )
    installed.add(shared)
    assert find_browser("darwin", exists=installed.__contains__, home="/Users/ana") == Browser(
        "chrome", shared, "Google Chrome"
    )


@pytest.mark.parametrize(
    ("url", "origin"),
    [
        ("http://192.168.1.20:8080", "http://192.168.1.20:8080"),
        ("http://sunroom.local:8080", "http://sunroom.local:8080"),
        ("http://localhost:8080", None),
        ("http://127.0.0.1:8080", None),
        ("https://calendar.example.com", None),
    ],
)
def test_only_plain_http_elsewhere_is_marked_secure(url: str, origin: str | None) -> None:
    assert insecure_origin(url) == origin


def test_the_launchers_flags_on_wayland(tmp_path: Path) -> None:
    argv = flags(
        CHROMIUM,
        profile=tmp_path,
        session="wayland",
        sunroom_url="http://192.168.1.20:8080",
        system="linux",
    )
    assert argv[0] == f"--user-data-dir={tmp_path}"
    for flag in ("--kiosk", "--noerrdialogs", "--disable-pinch", "--remote-debugging-port=0"):
        assert flag in argv
    assert "--ozone-platform=wayland" in argv and "--password-store=basic" in argv
    assert "--unsafely-treat-insecure-origin-as-secure=http://192.168.1.20:8080" in argv
    assert not any(flag in argv for flag in ("--incognito", "--disable-gpu"))


def test_x11_and_https_need_neither_wayland_nor_the_secure_flag(tmp_path: Path) -> None:
    argv = flags(
        CHROMIUM,
        profile=tmp_path,
        session="x11",
        sunroom_url="https://calendar.example.com",
        system="linux",
    )
    assert "--ozone-platform=wayland" not in argv
    assert not any(flag.startswith("--unsafely-treat") for flag in argv)


@pytest.mark.parametrize("system", ["win32", "darwin", "linux"])
def test_edge_runs_full_screen_on_the_screens_profile_never_in_its_kiosk_mode(
    tmp_path: Path, system: str
) -> None:
    """Edge's kiosk mode is InPrivate: the screen forgot its pairing at every restart (ADR 0040)."""
    argv = flags(EDGE, profile=tmp_path, session="", sunroom_url=None, system=system)
    assert argv[0] == f"--user-data-dir={tmp_path}"
    assert "--start-fullscreen" in argv and "--no-first-run" in argv
    assert "--kiosk" not in argv
    assert not any(flag.startswith(("--edge-kiosk-type", "--inprivate")) for flag in argv)


def test_chrome_on_windows_keeps_its_kiosk_mode(tmp_path: Path) -> None:
    argv = flags(CHROME, profile=tmp_path, session="", sunroom_url=None, system="win32")
    assert "--kiosk" in argv and "--start-fullscreen" not in argv


def test_closing_asks_the_way_the_system_does() -> None:
    # terminate() is TerminateProcess on Windows, which writes nothing: WM_CLOSE, through taskkill.
    assert close_command(4242, "win32") == ["taskkill", "/PID", "4242"]
    assert close_command(4242, "darwin") is None  # SIGTERM
    assert close_command(4242, "linux") is None


async def test_asking_it_to_close_opens_no_console_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """taskkill, started by the agent that runs without a console, would flash one on the wall."""
    asked: list[tuple[tuple[str, ...], object]] = []

    class Closer:
        async def wait(self) -> int:
            return 0

    async def start(*argv: str, **options: object) -> Closer:
        asked.append((argv, options.get("creationflags")))
        return Closer()

    def taskkill(pid: int) -> list[str]:
        return ["taskkill", "/PID", str(pid)]

    monkeypatch.setattr(browser_module, "close_command", taskkill)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", start)
    supervisor = Supervisor(
        EDGE, profile=tmp_path / "profile", argv=lambda: [], page=lambda: "http://127.0.0.1:7800/"
    )
    process = cast(asyncio.subprocess.Process, SimpleNamespace(pid=4242))
    assert await supervisor._ask_to_close(process)
    assert asked == [(("taskkill", "/PID", "4242"), NO_WINDOW)]


def test_the_last_exit_is_marked_clean(tmp_path: Path) -> None:
    prefs = tmp_path / "Default" / "Preferences"
    prefs.parent.mkdir()
    prefs.write_text(
        json.dumps({"profile": {"exit_type": "Crashed", "exited_cleanly": False}, "x": 1})
    )
    mark_clean_exit(tmp_path)
    data = json.loads(prefs.read_text())
    assert data["profile"] == {"exit_type": "Normal", "exited_cleanly": True}
    assert data["x"] == 1
    mark_clean_exit(tmp_path / "missing")  # no profile yet: nothing to do


def test_the_nightly_restart_is_at_about_four() -> None:
    zone = ZoneInfo("America/New_York")
    evening = datetime(2026, 10, 20, 22, 0, tzinfo=zone)
    assert next_nightly(evening, 300) == datetime(2026, 10, 21, 4, 0, tzinfo=zone)
    early = datetime(2026, 10, 21, 1, 0, tzinfo=zone)
    assert next_nightly(early, 0) == datetime(2026, 10, 21, 3, 55, tzinfo=zone)


@pytest.mark.skipif(sys.platform == "win32", reason="the pretend browser is a shell script")
async def test_the_supervisor_starts_it_again_after_it_exits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(browser_module, "RESTART_AFTER_S", 0.01)
    started = tmp_path / "started"
    script = tmp_path / "browser.sh"
    script.write_text(f'#!/bin/sh\necho "$@" >> "{started}"\nexit 1\n')
    script.chmod(0o755)
    pages = iter(["http://127.0.0.1:7800/", "http://192.168.1.20:8080/display", "x", "y", "z"])
    supervisor = Supervisor(
        Browser("chromium", str(script), "Pretend"),
        profile=tmp_path / "profile",
        argv=lambda: ["--kiosk"],
        page=lambda: next(pages),
    )
    running = asyncio.create_task(supervisor.run())
    for _ in range(200):
        await asyncio.sleep(0.01)
        if started.exists() and len(started.read_text().splitlines()) >= 2:
            break
    await supervisor.stop()
    running.cancel()
    lines = started.read_text().splitlines()
    assert lines[:2] == [
        "--kiosk http://127.0.0.1:7800/",
        "--kiosk http://192.168.1.20:8080/display",
    ]
    assert (tmp_path / "profile").is_dir()


def pretend_browser(tmp_path: Path, on_term: str) -> Path:
    """A browser that says it started, and does ``on_term`` when asked to close (SIGTERM)."""
    script = tmp_path / "browser.sh"
    log = tmp_path / "log"
    script.write_text(
        f"#!/bin/sh\ntrap '{on_term}' TERM\necho started >> \"{log}\"\n"
        "while true; do sleep 0.05; done\n"
    )
    script.chmod(0o755)
    return script


async def started_once(supervisor: Supervisor, log: Path) -> asyncio.Task[None]:
    running = asyncio.create_task(supervisor.run())
    for _ in range(300):
        await asyncio.sleep(0.01)
        if supervisor.process is not None and await asyncio.to_thread(log.exists):
            break
    return running


@pytest.mark.skipif(sys.platform == "win32", reason="the pretend browser is a shell script")
async def test_stopping_asks_the_browser_to_close_so_it_writes_its_cookies(tmp_path: Path) -> None:
    log = tmp_path / "log"
    script = pretend_browser(tmp_path, f'echo asked to close >> "{log}"; exit 0')
    supervisor = Supervisor(
        Browser("chromium", str(script), "Pretend"),
        profile=tmp_path / "profile",
        argv=lambda: ["--kiosk"],
        page=lambda: "http://127.0.0.1:7800/",
    )
    running = await started_once(supervisor, log)
    await supervisor.stop()
    running.cancel()
    assert log.read_text().splitlines() == ["started", "asked to close"]
    assert supervisor.process is not None and supervisor.process.returncode == 0


@pytest.mark.skipif(sys.platform == "win32", reason="the pretend browser is a shell script")
async def test_a_browser_that_wont_close_is_closed_by_force_after_the_wait(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(browser_module, "STOP_WAIT_S", 0.2)
    log = tmp_path / "log"
    script = pretend_browser(tmp_path, f'echo not closing >> "{log}"')
    supervisor = Supervisor(
        Browser("chromium", str(script), "Pretend"),
        profile=tmp_path / "profile",
        argv=lambda: ["--kiosk"],
        page=lambda: "http://127.0.0.1:7800/",
    )
    running = await started_once(supervisor, log)
    await supervisor.stop()
    running.cancel()
    assert "not closing" in log.read_text()
    assert supervisor.process is not None and supervisor.process.returncode == -9


class Window(DevTools):
    """DevTools with a pretend browser behind it: a window in ``state``, and what was asked."""

    def __init__(self, state: str | None) -> None:
        super().__init__(Path("unused"))
        self.state = state
        self.sent: list[tuple[str, dict[str, object]]] = []

    async def _page(self) -> tuple[str, str] | None:
        return ("PAGE-1", "ws://127.0.0.1:9222/devtools/page/PAGE-1")

    async def _get(self, path: str) -> object:
        assert path == "/json/version"
        return {"webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/browser/B"}

    async def _send(self, url: str, method: str, params: dict[str, object]) -> dict[str, object]:
        assert url.endswith("/devtools/browser/B")  # Browser.* go to the browser's own socket
        self.sent.append((method, params))
        if self.state is None:
            raise OSError("no browser")
        if method == "Browser.getWindowForTarget":
            return {"id": 1, "result": {"windowId": 7, "bounds": {"windowState": self.state}}}
        return {"id": 1, "result": {}}


def window_states(window: Window) -> list[object]:
    return [
        params["bounds"]["windowState"]  # type: ignore[index]
        for method, params in window.sent
        if method == "Browser.setWindowBounds"
    ]


async def test_a_window_that_left_full_screen_is_put_back() -> None:
    full = Window("fullscreen")
    assert await full.full_screen()
    assert window_states(full) == []
    assert full.sent == [("Browser.getWindowForTarget", {"targetId": "PAGE-1"})]
    normal = Window("normal")
    assert await normal.full_screen()
    assert window_states(normal) == ["fullscreen"]
    minimized = Window("minimized")  # back to normal first: the two can't be one step
    assert await minimized.full_screen()
    assert window_states(minimized) == ["normal", "fullscreen"]
    assert not await Window(None).full_screen()  # no browser: the watchdog handles it


async def test_closing_and_writing_now_go_to_the_browsers_own_socket() -> None:
    """Browser.close writes the cookies first; a batch past Chromium's 512 writes them now."""
    window = Window("fullscreen")
    assert await window.close()
    assert await window.write_cookies_now(now=1_000_000.0)
    assert [method for method, _ in window.sent] == ["Browser.close", "Storage.setCookies"]
    cookies = cast(list[dict[str, object]], window.sent[1][1]["cookies"])
    assert len(cookies) > 512
    assert {cookie["domain"] for cookie in cookies} == {"flush.invalid"}  # no page can see it
    assert {cookie["expires"] for cookie in cookies} == {1_000_060.0}  # gone a minute later
    assert not await Window(None).close()  # nothing answered: the system's way, then


async def test_a_browser_that_closes_before_it_answers_was_asked() -> None:
    from websockets.exceptions import ConnectionClosedOK

    class Closing(Window):
        async def _send(
            self, url: str, method: str, params: dict[str, object]
        ) -> dict[str, object]:
            raise ConnectionClosedOK(None, None)

    assert await Closing("normal").close()


async def test_only_edge_is_kept_full_screen_by_the_watchdog(tmp_path: Path) -> None:
    asked: list[str] = []

    class Counting(DevTools):
        async def full_screen(self) -> bool:
            asked.append("full screen")
            return True

    for browser in (CHROMIUM, EDGE):
        supervisor = Supervisor(browser, profile=tmp_path, argv=list, page=lambda: "x")
        supervisor.devtools = Counting(tmp_path)
        supervisor.process = object()  # type: ignore[assignment]  # as if it were running
        await supervisor.keep_full_screen()
    assert asked == ["full screen"]  # Edge's; Chromium's kiosk window can't leave it
