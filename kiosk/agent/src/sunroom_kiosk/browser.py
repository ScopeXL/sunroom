"""The wall's browser: find it, start it full screen on the right page, keep it running, and
look at what it shows (docs/M7.md T6; what ``kiosk/sunroom-kiosk`` did in bash until 0.13.0).

* **Which browser.** Chromium, then Google Chrome, then Microsoft Edge on Linux, never a
  snap's; Chrome, Chromium, then Edge on macOS, in /Applications or ~/Applications; Edge, then
  Chrome, on Windows (batch 2). The installer brings one when there's none (ADR 0037).
* **Its profile.** ``~/.config/sunroom-kiosk/profile`` keeps the screen's pairing cookie, so
  never ``--incognito``, nor Edge's kiosk mode, which is an InPrivate session too (ADR 0040);
  and never ``--disable-gpu``, which makes the board crawl. Before each start the last exit is
  marked clean, so a power cut never shows "Restore pages?".
* **Its flags.** The launcher's (PLAN §13.2), plus ``--remote-debugging-port=0``: the port it
  picks is written to ``DevToolsActivePort`` in the profile, and the watchdog asks through it
  whether the page is a Sunroom and whether it still answers. Chromium and Chrome run with
  ``--kiosk``; Edge full screen instead, put back by the watchdog when someone leaves it.
* **Its cookies on disk.** Chromium writes new cookies to disk every 30 s, once 512 changes are
  waiting, and when it is closed through DevTools (``Browser.close``). A SIGTERM closes it at
  once and writes nothing new (tried with Chrome 155), as a system shutting it down most likely
  does too, so a pairing made just before was lost (ADR 0040). Closing asks through DevTools
  first, then the system's way (SIGTERM; on Windows taskkill without /F), and forces it after
  10 s; and right after a pairing the page asks for the cookies to be written now
  (``DevTools.write_cookies_now``).
* **Keeping it running.** Started again 3 s after any exit; restarted once a night at about
  04:00 (03:55 plus up to ten minutes), which gives back the memory Chromium gathers over days.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import random
import shutil
import sys
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, cast

import httpx

from sunroom_kiosk import logs
from sunroom_kiosk.platform.base import NO_WINDOW
from sunroom_kiosk.policy import BrowserKind

log = logs.get("browser")

RESTART_AFTER_S = 3.0
STOP_WAIT_S = 10.0
# After Edge starts, how long to wait for it to answer before putting its window full screen.
FULL_SCREEN_WITHIN_S = 20.0
# More cookie changes than Chromium lets wait before it writes them (512), on a name no page can
# use (RFC 2606's .invalid), each gone by itself a minute later: see write_cookies_now.
FLUSH_COOKIES = 600
FLUSH_DOMAIN = "flush.invalid"
FLUSH_LIFE_S = 60
NIGHTLY = (3, 55)
NIGHTLY_SPREAD_S = 600
DEVTOOLS_S = 5.0

# Whether a page is Sunroom's: its title, the nonce meta every page of it carries, and a root
# with something drawn in it. Read through the DevTools protocol; nothing is injected.
PAGE_CHECK = (
    "JSON.stringify({href: location.href, sunroom: document.title === 'Sunroom'"
    " && !!document.querySelector('meta[name=\"csp-nonce\"]')"
    " && !!(document.getElementById('root') || {}).firstElementChild})"
)


@dataclass(frozen=True)
class Browser:
    kind: BrowserKind
    path: str
    name: str  # "Chromium", "Google Chrome", "Microsoft Edge"


LINUX: tuple[tuple[BrowserKind, str, str], ...] = (
    ("chromium", "chromium", "Chromium"),
    ("chromium", "chromium-browser", "Chromium"),
    ("chrome", "google-chrome", "Google Chrome"),
    ("chrome", "google-chrome-stable", "Google Chrome"),
    ("edge", "microsoft-edge", "Microsoft Edge"),
    ("edge", "microsoft-edge-stable", "Microsoft Edge"),
)
MACOS: tuple[tuple[BrowserKind, str, str], ...] = (
    ("chrome", "Google Chrome.app/Contents/MacOS/Google Chrome", "Google Chrome"),
    ("chromium", "Chromium.app/Contents/MacOS/Chromium", "Chromium"),
    ("edge", "Microsoft Edge.app/Contents/MacOS/Microsoft Edge", "Microsoft Edge"),
)


def _mac_paths(home: str) -> tuple[tuple[BrowserKind, str, str], ...]:
    """Each browser in /Applications, then in ~/Applications, where the installer puts Google
    Chrome for an account that may not write to /Applications."""
    return tuple(
        (kind, f"{folder}/{app}", name)
        for kind, app, name in MACOS
        for folder in ("/Applications", f"{home}/Applications")
    )


def is_snap(path: str) -> bool:
    """A snap's browser can't open the profile under ``~/.config`` or read the policy in /etc
    (its sandbox hides both), so it isn't used: Ubuntu's Chromium is one, and its
    ``/usr/bin/chromium-browser`` is a script that runs the snap. The installer skips them too."""
    if path.startswith("/snap/") or os.path.realpath(path).startswith("/snap/"):
        return True
    try:
        with open(path, "rb") as file:
            start = file.read(4096)
    except OSError:
        return False
    return start.startswith(b"#!") and b"/snap/" in start


def _windows_paths() -> tuple[tuple[BrowserKind, str, str], ...]:
    roots = [
        os.environ.get(name, "")
        for name in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA")
        if os.environ.get(name)
    ]
    found: list[tuple[BrowserKind, str, str]] = []
    for root in roots:
        found.append(
            (
                "edge",
                str(Path(root, "Microsoft", "Edge", "Application", "msedge.exe")),
                "Microsoft Edge",
            )
        )
    for root in roots:
        found.append(
            (
                "chrome",
                str(Path(root, "Google", "Chrome", "Application", "chrome.exe")),
                "Google Chrome",
            )
        )
    return tuple(found)


def find_browser(
    system: str = sys.platform,
    *,
    which: Callable[[str], str | None] = shutil.which,
    exists: Callable[[str], bool] = os.path.exists,
    snap: Callable[[str], bool] = is_snap,
    home: str | None = None,
) -> Browser | None:
    if system == "darwin":
        for kind, path, name in _mac_paths(home or os.path.expanduser("~")):
            if exists(path):
                return Browser(kind, path, name)
        return None
    if system == "win32":
        for kind, path, name in _windows_paths():
            if exists(path):
                return Browser(kind, path, name)
        return None
    for kind, command, name in LINUX:
        path = which(command)
        if path and not snap(path):
            return Browser(kind, path, name)
    return None


def insecure_origin(url: str) -> str | None:
    """The Sunroom's origin when it is plain http on another machine: Chromium is told to treat
    it as secure, so the service worker and Wake Lock work (PLAN §13.1). ``localhost`` already
    is one, and https needs nothing."""
    if not url.lower().startswith("http://"):
        return None
    hostport = url[len("http://") :].split("/", 1)[0]
    host = hostport.rsplit(":", 1)[0] if not hostport.startswith("[") else hostport
    if host in ("localhost", "127.0.0.1", "[::1]") or host.startswith("[::1]"):
        return None
    return f"http://{hostport}"


def flags(
    browser: Browser,
    *,
    profile: Path,
    session: str,
    sunroom_url: str | None,
    system: str = sys.platform,
) -> list[str]:
    """The browser's command line, before the page to open (PLAN §13.2)."""
    argv = [
        f"--user-data-dir={profile}",
        # Edge's kiosk mode, with or without --edge-kiosk-type, is an InPrivate session that
        # forgets the screen's pairing, its remembered view and its offline copy whenever it
        # closes (Microsoft's "Configure Microsoft Edge kiosk mode"; ADR 0040). Edge runs full
        # screen on this profile instead, and the watchdog keeps it there.
        "--start-fullscreen" if browser.kind == "edge" else "--kiosk",
        "--start-maximized",
        "--no-first-run",
        "--no-default-browser-check",
        "--noerrdialogs",
        "--disable-infobars",
        "--hide-crash-restore-bubble",
        "--touch-events=enabled",
        "--disable-pinch",
        "--overscroll-history-navigation=0",
        "--enable-features=OverlayScrollbar",
        "--disable-features=Translate,TranslateUI",
        "--disable-component-update",
        "--check-for-update-interval=31536000",
        "--autoplay-policy=no-user-gesture-required",
        "--remote-debugging-port=0",
    ]
    if system.startswith("linux"):
        argv.append("--password-store=basic")
        if session == "wayland":
            argv += [
                "--ozone-platform=wayland",
                "--enable-wayland-ime",
                "--wayland-text-input-version=3",
            ]
    origin = insecure_origin(sunroom_url) if sunroom_url else None
    if origin:
        argv.append(f"--unsafely-treat-insecure-origin-as-secure={origin}")
    return argv


def close_command(pid: int, system: str = sys.platform) -> list[str] | None:
    """How to ask the browser to close, as the system's own close does, so it writes its
    cookies first: on Windows taskkill without /F, which sends its windows WM_CLOSE (Python's
    terminate() is TerminateProcess there, which writes nothing); elsewhere None, for SIGTERM."""
    if system == "win32":
        return ["taskkill", "/PID", str(pid)]
    return None


def mark_clean_exit(profile: Path) -> None:
    """Chromium shows "Restore pages?" when its last exit wasn't clean, which is every power cut
    and every restart. Rewriting the two flags before a start prevents it."""
    prefs = profile / "Default" / "Preferences"
    try:
        data = json.loads(prefs.read_text(encoding="utf-8"))
    except OSError, ValueError:
        return
    if not isinstance(data, dict):
        return
    fields = cast(dict[str, Any], data)
    section = fields.setdefault("profile", {})
    if not isinstance(section, dict):
        return
    profile_fields = cast(dict[str, Any], section)
    profile_fields["exited_cleanly"] = True
    profile_fields["exit_type"] = "Normal"
    tmp = prefs.with_name("Preferences.sunroom-tmp")
    try:
        tmp.write_text(json.dumps(fields, separators=(",", ":")), encoding="utf-8")
        os.replace(tmp, prefs)
    except OSError as error:
        log.info("Couldn't mark the last browser exit as clean (%s); carrying on.", error)


def next_nightly(now: datetime, spread_s: float) -> datetime:
    """The next 03:55 local time after ``now``, plus ``spread_s`` seconds."""
    target = now.replace(hour=NIGHTLY[0], minute=NIGHTLY[1], second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return target + timedelta(seconds=spread_s)


@dataclass(frozen=True)
class PageLook:
    """What the watchdog saw: whether the browser answered, and whether its page is Sunroom."""

    answered: bool
    href: str | None = None
    sunroom: bool = False


def devtools_port(profile: Path) -> int | None:
    try:
        first = (profile / "DevToolsActivePort").read_text(encoding="ascii").splitlines()[0]
        return int(first)
    except OSError, ValueError, IndexError:
        return None


class DevTools:
    """A few calls of the Chrome DevTools protocol, on the port the browser picked."""

    def __init__(self, profile: Path) -> None:
        self.profile = profile

    async def _get(self, path: str) -> Any:
        port = devtools_port(self.profile)
        if port is None:
            return None
        async with httpx.AsyncClient(timeout=DEVTOOLS_S) as client:
            return (await client.get(f"http://127.0.0.1:{port}{path}")).json()

    async def _page(self) -> tuple[str, str] | None:
        """The first page's target id and socket."""
        targets = await self._get("/json/list")
        if not isinstance(targets, list):
            return None
        for target in cast(list[Any], targets):
            if isinstance(target, dict):
                fields = cast(dict[str, Any], target)
                url, target_id = fields.get("webSocketDebuggerUrl"), fields.get("id")
                if fields.get("type") == "page" and isinstance(url, str):
                    return (target_id if isinstance(target_id, str) else "", url)
        return None

    async def _call(self, method: str, params: dict[str, Any]) -> dict[str, Any] | None:
        """One call on the page's own socket."""
        page = await self._page()
        return None if page is None else await self._send(page[1], method, params)

    async def _send(self, url: str, method: str, params: dict[str, Any]) -> dict[str, Any] | None:
        from websockets.asyncio.client import connect  # here: only on a real screen

        async with asyncio.timeout(DEVTOOLS_S), connect(url, max_size=2**20) as socket:
            await socket.send(json.dumps({"id": 1, "method": method, "params": params}))
            while True:
                message = json.loads(await socket.recv())
                if isinstance(message, dict) and cast(dict[str, Any], message).get("id") == 1:
                    return cast(dict[str, Any], message)

    async def look(self) -> PageLook:
        try:
            answer = await self._call(
                "Runtime.evaluate", {"expression": PAGE_CHECK, "returnByValue": True}
            )
        except (OSError, TimeoutError, httpx.HTTPError, ValueError) as error:
            log.debug("The browser didn't answer the watchdog: %r", error)
            return PageLook(answered=False)
        except Exception as error:  # websockets' own errors: the page didn't answer
            log.debug("The browser didn't answer the watchdog: %r", error)
            return PageLook(answered=False)
        if answer is None:
            return PageLook(answered=False)
        try:
            value = cast(dict[str, Any], answer["result"]["result"])["value"]
            seen = json.loads(value)
        except KeyError, TypeError, ValueError:
            return PageLook(answered=False)
        return PageLook(answered=True, href=seen.get("href"), sunroom=bool(seen.get("sunroom")))

    async def navigate(self, url: str) -> bool:
        try:
            return await self._call("Page.navigate", {"url": url}) is not None
        except Exception as error:  # any failure: the caller restarts the browser instead
            log.debug("Couldn't navigate through DevTools: %r", error)
            return False

    async def _browser_socket(self) -> str | None:
        version = await self._get("/json/version")
        fields = cast(dict[str, Any], version) if isinstance(version, dict) else {}
        url = fields.get("webSocketDebuggerUrl")
        return url if isinstance(url, str) else None

    async def close(self) -> bool:
        """Close the browser the way that writes its cookies first. Whether it was asked: a
        browser that closes before it answers was."""
        from websockets.exceptions import ConnectionClosed  # here: only on a real screen

        try:
            browser = await self._browser_socket()
            if browser is None:
                return False
            await self._send(browser, "Browser.close", {})
        except ConnectionClosed:
            return True
        except Exception as error:
            log.debug("Couldn't close the browser through DevTools: %r", error)
            return False
        return True

    async def write_cookies_now(self, now: float | None = None) -> bool:
        """Have the browser write its cookies to disk now, not within 30 s: a fresh pairing then
        survives a shutdown straight after. Chromium writes them at once when more than 512
        changes are waiting, so this makes 600 (throwaway cookies on ``flush.invalid``, which no
        page can see or send, that expire after a minute). Whether the browser answered."""
        expires = (now if now is not None else time.time()) + FLUSH_LIFE_S
        cookies = [
            {
                "name": f"n{index}",
                "value": "1",
                "domain": FLUSH_DOMAIN,
                "path": "/",
                "expires": expires,
            }
            for index in range(FLUSH_COOKIES)
        ]
        try:
            browser = await self._browser_socket()
            if browser is None:
                return False
            answer = await self._send(browser, "Storage.setCookies", {"cookies": cookies})
        except Exception as error:
            log.info("Couldn't have the browser save its cookies now: %r", error)
            return False
        return answer is not None and "error" not in answer

    async def full_screen(self) -> bool:
        """Put the page's window back to full screen if it left it (F11, Esc, its exit button, or
        a minimize), through the browser's own socket. Whether the browser answered."""
        try:
            page, browser = await self._page(), await self._browser_socket()
            if page is None or browser is None:
                return False
            window = await self._send(browser, "Browser.getWindowForTarget", {"targetId": page[0]})
            result = cast(dict[str, Any], (window or {}).get("result") or {})
            if "windowId" not in result:
                return False
            state = cast(dict[str, Any], result.get("bounds") or {}).get("windowState")
            if state == "fullscreen":
                return True
            log.info("The browser had left full screen; putting it back.")
            # A minimized window goes back to normal first: the two can't be one step.
            for wanted in ("normal", "fullscreen") if state == "minimized" else ("fullscreen",):
                bounds = {"windowId": result["windowId"], "bounds": {"windowState": wanted}}
                await self._send(browser, "Browser.setWindowBounds", bounds)
        except Exception as error:  # a browser that doesn't answer: the watchdog handles it
            log.debug("Couldn't check the window through DevTools: %r", error)
            return False
        return True


class Supervisor:
    """Keeps the browser running. ``page`` is asked for the address to open at each start."""

    def __init__(
        self,
        browser: Browser,
        *,
        profile: Path,
        argv: Callable[[], list[str]],
        page: Callable[[], str],
        environment: Callable[[], dict[str, str]] = lambda: dict(os.environ),
        before: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self.browser = browser
        self.profile = profile
        self.argv = argv
        self.page = page
        self.environment = environment
        # Once, before the first start: the desktop, the clock, no blanking, the picture turned.
        self.before = before
        self.devtools = DevTools(profile)
        self.process: asyncio.subprocess.Process | None = None
        self.next_page: str | None = None
        self._restart = asyncio.Event()
        self._stopping = False

    async def run(self) -> None:
        self.profile.mkdir(parents=True, exist_ok=True)
        with contextlib.suppress(OSError):
            self.profile.chmod(0o700)
        if self.before is not None:
            await self.before()
        nightly = asyncio.create_task(self._nightly())
        try:
            while not self._stopping:
                await self._once()
        finally:
            nightly.cancel()

    async def _once(self) -> None:
        mark_clean_exit(self.profile)
        page = self.next_page or self.page()
        self.next_page = None
        log.info("Opening %s with %s.", page, self.browser.name)
        try:
            self.process = await asyncio.create_subprocess_exec(
                self.browser.path,
                *self.argv(),
                page,
                env=self.environment(),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
        except OSError as error:
            log.info("%s didn't start (%s); trying again in a minute.", self.browser.name, error)
            await self._wait_or_restart(60)
            return
        self._restart.clear()
        settle = (
            asyncio.ensure_future(self._full_screen_soon()) if self.browser.kind == "edge" else None
        )
        try:
            exited = asyncio.ensure_future(self.process.wait())
            asked = asyncio.ensure_future(self._restart.wait())
            await asyncio.wait({exited, asked}, return_when=asyncio.FIRST_COMPLETED)
            asked.cancel()
            if not exited.done():
                await self._stop_process()
                exited.cancel()
                return
        finally:
            if settle is not None:
                settle.cancel()
        if not self._stopping:
            log.info(
                "%s closed (exit %s); starting it again in 3 seconds.",
                self.browser.name,
                self.process.returncode,
            )
            await self._wait_or_restart(RESTART_AFTER_S)

    async def _wait_or_restart(self, seconds: float) -> None:
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._restart.wait(), seconds)
        self._restart.clear()

    async def _stop_process(self) -> None:
        """Close the browser through DevTools, which writes its cookies (else the system's way:
        a browser that doesn't answer DevTools has nothing new to write); force it after 10 s."""
        process = self.process
        if process is None or process.returncode is not None:
            return
        if await self.devtools.close() or await self._ask_to_close(process):
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(process.wait(), STOP_WAIT_S)
                return
        log.info("%s didn't close when asked; closing it by force.", self.browser.name)
        with contextlib.suppress(ProcessLookupError):
            process.kill()
        await process.wait()

    async def _ask_to_close(self, process: asyncio.subprocess.Process) -> bool:
        command = close_command(process.pid)
        if command is None:
            with contextlib.suppress(ProcessLookupError):
                process.terminate()
            return True
        try:
            closer = await asyncio.create_subprocess_exec(
                *command,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
                creationflags=NO_WINDOW,
            )
            return await closer.wait() == 0  # not 0: it has no window to ask yet
        except OSError:
            return False

    async def _full_screen_soon(self) -> None:
        """Edge, just started: full screen as soon as it answers (--start-fullscreen should have
        done it; this is in case it didn't)."""
        deadline = asyncio.get_running_loop().time() + FULL_SCREEN_WITHIN_S
        while asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(1)
            if await self.devtools.full_screen():
                return

    async def keep_full_screen(self) -> None:
        """The watchdog's look at the window: Edge, which isn't in kiosk mode, back to full
        screen if someone left it. Chromium and Chrome can't leave it."""
        if self.browser.kind == "edge" and self.process is not None:
            await self.devtools.full_screen()

    async def save_cookies(self) -> None:
        """Right after the wall paired: its cookie on disk now (DevTools.write_cookies_now)."""
        if self.process is not None and await self.devtools.write_cookies_now():
            log.info("The browser saved this screen's pairing.")

    def restart(self, page: str | None = None) -> None:
        """Close the browser and start it again, on ``page`` if given."""
        self.next_page = page
        self._restart.set()

    async def navigate(self, url: str) -> None:
        """Go to ``url`` in the open page; restart the browser on it when that doesn't work."""
        if not await self.devtools.navigate(url):
            self.restart(url)

    async def look(self) -> PageLook:
        return await self.devtools.look()

    async def stop(self) -> None:
        self._stopping = True
        self._restart.set()
        await self._stop_process()

    async def _nightly(self) -> None:
        while True:
            now = datetime.now().astimezone()
            when = next_nightly(now, random.uniform(0, NIGHTLY_SPREAD_S))  # noqa: S311 - not secret
            await asyncio.sleep((when - now).total_seconds())
            log.info("Restarting %s for the night, to give back its memory.", self.browser.name)
            self.restart()


class NoBrowser:
    """``--fake`` (and a screen with no browser found): records what it was asked, starts
    nothing. The e2e runs bring their own browser."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def run(self) -> None:
        await asyncio.Event().wait()

    def restart(self, page: str | None = None) -> None:
        self.calls.append(f"restart {page or ''}".strip())

    async def navigate(self, url: str) -> None:
        self.calls.append(f"navigate {url}")

    async def look(self) -> PageLook:
        return PageLook(answered=True, sunroom=True)

    async def keep_full_screen(self) -> None:
        return None

    async def save_cookies(self) -> None:
        self.calls.append("save cookies")

    async def stop(self) -> None:
        self.calls.append("stop")
