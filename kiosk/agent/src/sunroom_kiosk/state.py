"""The agent itself: one object that holds the screen's settings and everything that acts on
them, which the API (app.py) reads and calls (docs/M7.md, "The agent's API" and "Flows").

What runs while it's up, each as an asyncio task: the browser (browser.Supervisor), a health
check of the Sunroom every 10 s (and the re-find of a found Sunroom that moved), the watchdog
that brings up the "Can't reach" page when the browser has shown no Sunroom for two minutes,
and the screen's sleep and brightness on a thread of its own (screen.ScreenThread).
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import platform as host
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Protocol

import httpx

from sunroom_kiosk import config as settings_file
from sunroom_kiosk import logs, policy, screen
from sunroom_kiosk.browser import Browser, PageLook
from sunroom_kiosk.config import Config
from sunroom_kiosk.discovery import Discovery, Found, found_out, origin_of
from sunroom_kiosk.events import EventHub
from sunroom_kiosk.local import LocalSunroom
from sunroom_kiosk.platform.base import Platform, PlatformError
from sunroom_kiosk.schemas import (
    ScreenAboutOut,
    ScreenBrightness,
    ScreenCapability,
    ScreenDisplayOut,
    ScreenFoundHow,
    ScreenNetworkOut,
    ScreenRotation,
    ScreenStateOut,
    ScreenSunroomOut,
    ScreenUpdateOut,
)
from sunroom_kiosk.updater import UpdaterLike, newer
from sunroom_kiosk.version import version

log = logs.get("agent")

HEALTH_EVERY_S = 10.0
HEALTH_TIMEOUT_S = 5.0
DOWN_BEFORE_REFIND_S = 120.0
WATCH_EVERY_S = 30.0
NO_SUNROOM_FOR_S = 120.0
ABOUT_EVERY_S = 600.0
ACTION_DELAY_S = 1.5  # a restart or shut down waits this long, so its toast shows first
RUN_SUNROOM_TRIES = 150  # a new Sunroom answering, 2 s apart: five minutes
RUN_SUNROOM_PAUSE_S = 2.0
LOCAL_DOWN_BEFORE_START_S = 20.0  # Windows: Sunroom run here, started again


def _rotation(degrees: int) -> ScreenRotation:
    match degrees:
        case 90 | 180 | 270:
            return degrees
        case _:
            return 0


class BrowserLike(Protocol):
    async def run(self) -> None: ...
    def restart(self, page: str | None = None) -> None: ...
    async def navigate(self, url: str) -> None: ...
    async def look(self) -> PageLook: ...
    async def keep_full_screen(self) -> None: ...
    async def save_cookies(self) -> None: ...
    async def stop(self) -> None: ...


@dataclass
class Known:
    """What the Sunroom said about itself the last time it was asked."""

    name: str | None = None
    version: str | None = None
    asked_at: float = 0.0


class Agent:
    def __init__(
        self,
        *,
        port: int,
        config_path: Path,
        platform: Platform,
        browser: BrowserLike,
        updater: UpdaterLike,
        hub: EventHub | None = None,
        discovery: Discovery | None = None,
        http: Callable[[], httpx.AsyncClient] | None = None,
        browser_info: Browser | None = None,
        screen_root: Path = Path("/"),
        fake: bool = False,
        dev_origins: tuple[str, ...] = (),
        local: LocalSunroom | None = None,
    ) -> None:
        self.port = port
        self.config_path = config_path
        self.config = settings_file.load(config_path)
        self.platform = platform
        self.browser = browser
        self.browser_info = browser_info
        self.updater = updater
        self.hub = hub or EventHub()
        self.discovery = discovery or Discovery(self.hub.publish)
        self.http = http or (lambda: httpx.AsyncClient(timeout=HEALTH_TIMEOUT_S))
        self.fake = fake
        self.dev_origins = dev_origins  # just kiosk-dev: Vite's page, in front of the agent
        # Sunroom run on this computer as a program (ADR 0038); None where it can't be (a
        # checkout, --fake: the pretend platform runs it itself).
        self.local = local
        self.reachable = False
        self.running_sunroom = False  # one run at a time (POST /run-sunroom)
        self.known = Known()
        self.started = time.monotonic()
        self.screen_root = screen_root
        self.screen: screen.ScreenThread | None = None
        self._tasks: list[asyncio.Task[None]] = []
        self._down_since: float | None = None
        self._no_sunroom_since: float | None = None
        self.network = ScreenNetworkOut(kind="none", ssid=None, ip=None, strength=None)

    # ------------------------------------------------------------------ addresses

    @property
    def own_origin(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def origins(self) -> set[str]:
        """Who may call the agent from a page: the Sunroom it shows, and its own pages."""
        allowed = {self.own_origin, f"http://localhost:{self.port}", *self.dev_origins}
        if self.config.url:
            allowed.add(origin_of(self.config.url))
        return allowed

    def agent_url(self, path: str = "/") -> str:
        return f"{self.own_origin}{path}"

    def dimmer(self) -> str:
        if self.screen is not None:
            return "screen" if self.screen.method in ("ddc", "sysfs") else "page"
        return screen.dimmer_for(self._screen_settings(), self.screen_root)

    def open_url(self) -> str | None:
        """The wall's address for this screen: Sunroom's /display, saying who dims and where
        this agent listens (T3: the server widens that page's connect-src for it)."""
        if not self.config.url:
            return None
        return f"{self.config.url}/display?dimmer={self.dimmer()}&screen={self.port}"

    def start_page(self) -> str:
        """What the browser opens: Sunroom when it answers, else the screen's own pages."""
        opened = self.open_url()
        if opened is None:
            return self.agent_url("/")
        return opened if self.reachable else self.agent_url("/opening")

    # ------------------------------------------------------------------ state

    def snapshot(self) -> ScreenStateOut:
        sunroom = None
        if self.config.url:
            sunroom = ScreenSunroomOut(
                url=self.config.url,
                id=self.config.sunroom_id,
                name=self.known.name,
                found=self.config.found or "typed",
                reachable=self.reachable,
                version=self.known.version,
            )
        status = {**self.updater.status(self.update_check()), "sunroom_outdated": self._outdated()}
        return ScreenStateOut(
            version=version(),
            platform=self.platform.name,
            model=self.platform.model,
            session=self.platform.session,
            capabilities=self.capabilities(),
            sunroom=sunroom,
            network=self.network,
            update=ScreenUpdateOut.model_validate(status),
            display=ScreenDisplayOut(
                rotation=_rotation(self.config.rotate),
                brightness_method=self._method(),
            ),
            open_url=self.open_url(),
        )

    def _method(self) -> ScreenBrightness:
        method = self.screen.method if self.screen is not None else "none"
        match method:
            case "ddc" | "sysfs":
                return method
            case _:
                return "none"

    def sunroom_here(self) -> bool:
        """Whether the Sunroom this screen shows runs on this machine (an all-in-one Pi)."""
        url = self.config.url or ""
        host = url.split("://", 1)[-1].split("/", 1)[0].rsplit(":", 1)[0].strip("[]")
        return host in ("localhost", "127.0.0.1", "::1")

    def _outdated(self) -> bool:
        latest = self.updater.status(self.update_check()).get("latest")
        return (
            "update_sunroom" in self.capabilities()
            and isinstance(latest, str)
            and self.known.version is not None
            and newer(latest, self.known.version)
        )

    def capabilities(self) -> list[ScreenCapability]:
        have = list(self.platform.capabilities())
        if self.local is not None:
            if self.local.supported() and "run_sunroom" not in have:
                have.append("run_sunroom")
            if self.local.installed() and "update_sunroom" not in have:
                have.append("update_sunroom")
            # Sunroom run here as a program: Uninstall can take it too (ADR 0042). An all-in-one
            # Pi's Docker Sunroom never goes from the screen: it's the family's server.
            if self.local.installed() and "uninstall" in have:
                have.append("remove_sunroom")
        if "update_sunroom" in have and not self.sunroom_here():
            have.remove("update_sunroom")
        if "brightness" in have and self._method() == "none" and not self.fake:
            have.remove("brightness")
        if "run_sunroom" in have and self.config.url is not None:
            have.remove("run_sunroom")
        return have

    def update_check(self) -> str:
        """Install overnight unless This Screen's Updates says Off (ADR 0042)."""
        if self.config.update_check is not None:
            return self.config.update_check
        return "nightly"

    def publish_state(self) -> None:
        self.hub.publish("state", self.snapshot())

    def toast(self, message: str) -> None:
        self.hub.publish("toast", {"message": message})

    def save(self, config: Config) -> None:
        self.config = config
        settings_file.save(self.config_path, config)

    # ------------------------------------------------------------------ running

    async def start(self) -> None:
        await self.refresh_network()
        if self.config.url:
            self.reachable = await self.healthy(self.config.url)
            await self.ask_sunroom()
        self.screen = screen.ScreenThread(self._screen_settings(), root=self.screen_root)
        if self.config.url and not self.fake:
            self.screen.start()
        await self.apply_policy()
        self.spawn(self.browser.run())
        self.spawn(self._health_loop())
        self.spawn(self._watch_loop())
        self.spawn(self._network_loop())
        self.spawn(self.updater.run(self))
        if self.local is not None and self.local.installed():
            self.spawn(self.look_after_local())
        log.info(
            "Sunroom Screen %s is running on %s; it shows %s.",
            version(),
            self.own_origin,
            self.config.url or "its own setup pages",
        )

    def spawn(self, work: Awaitable[Any]) -> None:
        async def guarded() -> None:
            try:
                await work
            except asyncio.CancelledError:
                raise
            except Exception as error:  # one part failing never takes the screen down
                log.exception("Something stopped unexpectedly: %r", error)

        self._tasks.append(asyncio.create_task(guarded()))

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        # The browser first, while there's time: closed as asked, it writes the pairing's cookie
        # (a forced close after the system's own wait would lose a fresh one; ADR 0040).
        await self.browser.stop()
        if self.screen is not None:
            await asyncio.to_thread(self.screen.stop)
        if self.local is not None:
            await self.local.stop_helpers()
        self.hub.close()

    async def before_browser(self) -> None:
        """Before the browser's first start: a desktop to draw on, the clock set, the session's
        blanking off and the saved rotation applied."""
        await self.platform.wait_for_desktop()
        await self.platform.wait_for_clock()
        await self.platform.prepare_session(self.config.rotate, self.config.output)

    def _screen_settings(self) -> screen.Settings:
        return screen.Settings(
            url=self.config.url or screen.DEFAULT_URL,
            session="macos"
            if self.platform.name == "macos"
            else "x11"
            if self.config.session == "x11"
            else "wayland",
            output=self.config.output,
            helper=self.config.screen_helper and self.platform.name in ("pi", "linux", "macos"),
            brightness=self.config.brightness,
            ddc_bus=self.config.ddc_bus,
            backlight=self.config.backlight,
        )

    async def healthy(self, url: str) -> bool:
        try:
            async with self.http() as client:
                response = await client.get(f"{url}/api/health")
        except httpx.HTTPError:
            return False
        return response.status_code == 200

    async def ask_sunroom(self) -> None:
        """The Sunroom's name and version, for the screen's words (never logged)."""
        url = self.config.url
        if not url:
            return
        try:
            found = await self.discovery.check(url)
        except Exception:
            return
        self.known = Known(name=found.name, version=found.version, asked_at=time.monotonic())
        if found.id and self.config.sunroom_id is None:
            self.save(replace(self.config, sunroom_id=found.id))

    async def _health_loop(self) -> None:
        while True:
            await asyncio.sleep(HEALTH_EVERY_S)
            await self.health_tick()

    async def health_tick(self) -> None:
        url = self.config.url
        if url is None:
            if self.reachable:
                self.reachable = False
                self.publish_state()
            return
        ok = await self.healthy(url)
        if ok != self.reachable:
            self.reachable = ok
            log.info("Sunroom at %s %s.", url, "answers" if ok else "doesn't answer")
            self.publish_state()
        now = time.monotonic()
        if ok:
            self._down_since = None
            if now - self.known.asked_at > ABOUT_EVERY_S:
                await self.ask_sunroom()
            return
        self._down_since = self._down_since or now
        if (
            self.local is not None
            and self.sunroom_here()
            and now - self._down_since >= LOCAL_DOWN_BEFORE_START_S
            and self.local.installed()
        ):
            await self.local.ensure_running()  # Windows only: nothing else restarts it there
        if (
            now - self._down_since >= DOWN_BEFORE_REFIND_S
            and self.config.found == "discovered"
            and self.config.sunroom_id
        ):
            self._down_since = now  # the next look in two minutes, not every 10 s
            await self.refind(self.config.sunroom_id)

    async def refind(self, sunroom_id: str) -> None:
        """A found Sunroom that stopped answering may have a new address (DHCP): look for the
        same id, and move to it. A typed address is never changed by itself."""
        log.info("Looking for this screen's Sunroom at a new address.")
        found = await self.discovery.refind(sunroom_id)
        if found is None or found.url == self.config.url:
            return
        log.info("Found this screen's Sunroom at %s.", found.url)
        await self.use(found, "discovered", moved=True)
        # Nobody chose it on a page, so no page moves itself: the open one goes there.
        await self.browser.navigate(self.start_page())

    async def _watch_loop(self) -> None:
        while True:
            await asyncio.sleep(WATCH_EVERY_S)
            await self.watch_tick()

    async def watch_tick(self) -> None:
        """The app is in charge while it shows anything (its offline pill, its reload). The
        agent steps in only when the browser has shown no Sunroom at all for two minutes, and
        puts Edge's window back to full screen when someone left it."""
        await self.browser.keep_full_screen()
        if not self.config.url:
            self._no_sunroom_since = None
            return
        look = await self.browser.look()
        on_own_pages = bool(look.href and look.href.startswith(self.own_origin))
        if look.answered and (look.sunroom or on_own_pages):
            self._no_sunroom_since = None
            return
        now = time.monotonic()
        self._no_sunroom_since = self._no_sunroom_since or now
        if now - self._no_sunroom_since < NO_SUNROOM_FOR_S:
            return
        self._no_sunroom_since = None
        page = self.agent_url("/cant-reach")
        if look.answered:
            log.info("The browser has shown no Sunroom for two minutes; showing Can't reach.")
            await self.browser.navigate(page)
        else:
            log.info("The browser stopped answering; starting it again.")
            self.browser.restart(page)

    async def _network_loop(self) -> None:
        while True:
            await asyncio.sleep(30)
            await self.refresh_network()

    async def refresh_network(self) -> None:
        try:
            status = await self.platform.network()
        except PlatformError:
            return
        network = ScreenNetworkOut(
            kind=status.kind, ssid=status.ssid, ip=status.ip, strength=status.strength
        )
        if network != self.network:
            self.network = network
            self.publish_state()

    # ------------------------------------------------------------------ the Sunroom

    async def check(self, typed: str) -> Found:
        return await self.discovery.check(typed)

    async def scan(self) -> None:
        found = await self.discovery.scan()
        log.info("Found %d Sunroom%s.", len(found), "" if len(found) == 1 else "s")

    def start_run(self) -> None:
        """Run Sunroom here, unless a run is already going: a second tap joins it."""
        if self.running_sunroom:
            return
        self.running_sunroom = True
        self.spawn(self.run_sunroom())

    async def run_sunroom(self) -> None:
        """Sunroom on this computer (ADR 0038): set it up and start it, then show it. One run at
        a time, and a run that stops says why in its last progress, which the page shows with Try
        Again."""

        async def progress(percent: int, step: str, message: str | None = None) -> None:
            self.hub.publish("run.progress", {"percent": percent, "step": step, "message": message})

        self.running_sunroom = True
        try:
            try:
                if self.local is not None:
                    url = await self.local.run_here(progress)
                else:
                    url = await self.platform.run_sunroom(progress)
            except PlatformError as error:
                await progress(100, "Stopped", str(error))
                return
            # Its first start migrates an empty database: up to five minutes, as the installer
            # waits.
            await progress(92, "Starting Sunroom…")
            for _ in range(RUN_SUNROOM_TRIES):
                if await self.healthy(url):
                    break
                await asyncio.sleep(RUN_SUNROOM_PAUSE_S)
            else:
                await progress(
                    100, "Stopped", "Sunroom didn't start. Restart this screen, then try again."
                )
                return
            await progress(100, "Sunroom is running.")
            if self.local is not None:
                await self.local.keep_awake()
                await self.local.announce()
            found = Found(url=url, id=None, name=None, version=None, setup_complete=False)
            try:
                found = await self.discovery.check(url)
            except Exception as error:  # it answered once; the screen still uses it
                log.info("The new Sunroom didn't answer its first check: %r", error)
            await self.use(found, "local")
        finally:
            self.running_sunroom = False

    async def use(self, found: Found, how: str, *, moved: bool = False) -> None:
        """Show ``found`` on this screen from now on: save it, write the browser's policy and
        follow it with the screen's sleep. The browser isn't restarted (ADR 0042): the page that
        chose it opens it itself when it hears the new state, so the wall shows Sunroom once,
        with one pairing code; a plain-http Sunroom on another machine gets its secure-context
        flag at the browser's next start (the nightly one, or This Screen's Restart)."""
        how_found: ScreenFoundHow = (
            "discovered" if how == "discovered" else "local" if how == "local" else "typed"
        )
        self.save(self.config.with_sunroom(found.url, found.id, how_found))
        self.known = Known(name=found.name, version=found.version, asked_at=time.monotonic())
        self.reachable = await self.healthy(found.url)
        await self.apply_policy()
        if self.screen is not None:
            self.screen.retarget(found.url)
            if not self.fake:
                self.screen.start()
        self.publish_state()
        if moved:
            self.toast("Found Sunroom at its new address.")
        log.info("This screen shows the Sunroom at %s now.", found.url)

    async def forget(self) -> None:
        """Forget the address (never the browser's profile, which keeps the pairing). The page
        that asked goes to Where Is Your Sunroom? itself; the browser isn't restarted."""
        self.save(self.config.with_sunroom(None, None, None))
        self.known = Known()
        self.reachable = False
        await self.apply_policy()
        self.publish_state()
        log.info("This screen forgot its Sunroom's address.")

    async def apply_policy(self) -> None:
        if self.browser_info is None and not self.fake:
            return
        kind = self.browser_info.kind if self.browser_info is not None else "chromium"
        document = policy.document()
        try:
            written = await self.platform.write_policy(kind, document)
        except PlatformError as error:
            log.info("Couldn't write the browser's policy: %s", error)
            return
        if not written:
            log.debug("The browser's policy is the installer's to write here.")

    # ------------------------------------------------------------------ the machine

    async def look_after_local(self) -> None:
        """Sunroom run here, as Sunroom Screen starts: the computer kept awake, Sunroom
        announced, started again on Windows, and brought to Sunroom Screen's own version (which
        an update of Sunroom Screen changed)."""
        local = self.local
        if local is None:
            return
        await local.keep_awake()
        await local.announce()
        if self.sunroom_here() and not self.reachable:
            await local.ensure_running()
        own = version()
        if self.known.version is not None and newer(own, self.known.version):
            log.info("Bringing Sunroom on this computer up to %s.", own)
            if await local.update(own):
                await self.ask_sunroom()
                self.publish_state()

    async def later(self, action: Callable[[], Awaitable[None]]) -> None:
        """Run ``action`` a moment from now, after the answer (and its toast) went out."""

        async def go() -> None:
            await asyncio.sleep(ACTION_DELAY_S)
            try:
                await action()
            except PlatformError as error:
                log.info("%s", error)
                self.toast(str(error))

        self.spawn(go())

    async def update_sunroom(self) -> None:
        """The Sunroom on this machine: run here as a program, to the newest version (ADR 0038),
        or an all-in-one Pi's through update.sh (minutes either way)."""
        log.info("Updating the Sunroom on this screen.")
        if self.local is not None and self.local.installed():
            latest = self.updater.status(self.update_check()).get("latest")
            updated = await self.local.update(latest if isinstance(latest, str) else version())
        else:
            updated = await self.platform.update_sunroom()
        if updated:
            await self.ask_sunroom()
            self.toast("Sunroom is up to date.")
        else:
            self.toast("Sunroom didn't update. Try again in a while.")
        self.publish_state()

    async def rotate(self, rotation: int) -> None:
        await self.platform.rotate(rotation, self.config.output)
        self.save(replace(self.config, rotate=rotation))
        self.publish_state()

    async def uninstall(self, *, sunroom: bool) -> None:
        """This Screen's Uninstall (ADR 0042), once the page has unpaired the screen: the
        platform starts its uninstaller as a process of its own, and this agent quits, which
        closes the browser; the uninstaller takes the rest off. ``sunroom`` takes Sunroom run
        here and the family's data too, only where it runs here as a program."""
        sunroom = sunroom and "remove_sunroom" in self.capabilities()
        log.info("Uninstalling Sunroom Screen%s, as This Screen asked.", " and Sunroom" * sunroom)
        await self.platform.uninstall(sunroom=sunroom, port=self.port)
        if not self.fake:  # the pretend screen stays up for the next test
            await self.quit()

    def set_update_check(self, check_policy: str) -> None:
        self.save(
            replace(self.config, update_check="nightly" if check_policy == "nightly" else "off")
        )
        self.publish_state()

    def about(self) -> ScreenAboutOut:
        return ScreenAboutOut(
            version=version(),
            platform=self.platform.name,
            model=self.platform.model,
            system=self.platform.system or f"{host.system()} {host.release()}",
            browser=self.browser_info.name if self.browser_info else None,
            hostname=self.platform.hostname(),
            ip=self.network.ip,
            uptime_s=int(time.monotonic() - self.started),
            sunroom_url=self.config.url,
            log=logs.recent(),
        )

    def scan_results(self) -> list[dict[str, Any]]:
        return [found_out(found) for found in self.discovery.found]

    async def reset_fake(self) -> None:
        """``--fake`` only: the pretend screen as it started, with no Sunroom chosen."""
        from sunroom_kiosk.platform.fake import FakePlatform
        from sunroom_kiosk.updater import FakeUpdater

        if not isinstance(self.platform, FakePlatform):
            return
        self.platform.reset()
        if isinstance(self.updater, FakeUpdater):
            self.updater.reset()
        self.save(Config())
        self.known = Known()
        self.reachable = False
        self.discovery.found = []
        await self.refresh_network()
        self.publish_state()

    async def change_fake(
        self,
        *,
        kind: str | None = None,
        wired: bool | None = None,
        offline: bool | None = None,
        sunroom: str | None = None,
        run: str | None = None,
    ) -> None:
        from sunroom_kiosk.platform.fake import FakePlatform

        if not isinstance(self.platform, FakePlatform):
            return
        if kind == "pi" or kind == "desktop":
            self.platform.kind = kind
        if run == "ok" or run == "hold" or run == "fail":
            self.platform.run = run
        if wired is not None:
            self.platform.wired = wired
        if offline:
            self.platform.networks = [replace(n, connected=False) for n in self.platform.networks]
        if sunroom is not None:
            self.save(self.config.with_sunroom(sunroom.rstrip("/"), None, "typed"))
            self.known = Known()
            await self.health_tick()
        await self.refresh_network()
        self.publish_state()

    async def quit(self) -> None:
        log.info("Sunroom Screen is quitting until the next sign-in.")
        await self.stop()
        os._exit(0)
