"""The screen's sleep and brightness (PLAN §13.5): what ``kiosk/sunroom-screen`` did until
Sunroom Screen took it in (docs/M7.md, T6). It follows Sunroom's Sleep settings.

It long-polls Sunroom's ``GET /api/display/state`` (it answers when the screen should change:
bedtime, the evening dim, a tap that wakes it, a new setting; or after 55 s) and applies only
what changed:

* off and on: Wayland ``wlopm --off '*'`` / ``--on '*'``, else ``wlr-randr --output
  <SUNROOM_OUTPUT> --off`` / ``--on``; X11 ``xset dpms force off`` / ``on``, then ``xset dpms 0
  0 0`` so X never blanks the screen by itself (never ``xset -dpms``: that would switch a
  sleeping screen on). A panel with a backlight (Touch Display) switches only that off
  (``bl_power``), which keeps the panel and its touch running behind the black page. On a Mac
  (docs/M7.md T15): on is ``caffeinate -u`` (a moment of activity wakes the display) and a
  ``caffeinate -dis -w <the agent>`` held while it should stay on, which lets go by itself when
  the agent ends; off lets go and runs ``pmset displaysleepnow``.
* brightness, when the helper sets it (SUNROOM_BRIGHTNESS auto, ddc or sysfs): ``ddcutil --bus
  <SUNROOM_DDC_BUS> setvcp 10 <n>`` on monitors with DDC/CI, or the backlight's ``brightness``
  scaled to its ``max_brightness``. Otherwise the page darkens itself (``?dimmer=page``).

When Sunroom doesn't answer it tries again after 2 s, doubling up to 60 s; after five failures
in a row (about half a minute) it switches the screen on, and when it stops it does the same at
full brightness: a dark wall with no way back is worse than a lit one. Each change is one plain
line in the agent's log.

The helper is synchronous, standard-library code with its fetch, its commands, its root folder
and its sleep injected, as it was as a script; the agent runs it on a thread of its own
(``ScreenThread``). ``sunroom-kiosk screen --method`` and ``--ddc-bus NAME`` are its old flags.
"""

from __future__ import annotations

import http.client
import json
import os
import re
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import cast

from sunroom_kiosk import logs
from sunroom_kiosk.config import parse_values

log = logs.get("screen")

# The installer's KEY=value lines, parsed and never run (config.py holds the one parser).
parse_config = parse_values


def _say(line: str) -> None:
    log.info(line)


DEFAULT_URL = "http://localhost:7867"
WAIT_S = 55  # the longest the server holds a poll
TIMEOUT_S = 65  # a little over that
BACKOFF_FIRST_S = 2
BACKOFF_MAX_S = 60
FAILURES_BEFORE_ON = 5  # after 2 + 4 + 8 + 16 s of waiting: about half a minute
DDC_SETTLE_S = 2  # a monitor that has just woken may not take DDC/CI commands at once
COMMAND_TIMEOUT_S = 20
MAX_ANSWER_BYTES = 64 * 1024

REASONS = {
    "day": "daytime",
    "dim": "evening dim",
    "sleep": "sleep time",
    "awake": "tapped awake for 2 minutes",
}

Fetch = Callable[[str, float], bytes]  # (url, timeout) -> the body of a 200 answer
Run = Callable[[list[str]], tuple[int, str]]  # argv -> (exit status, what it printed)


class Stop(BaseException):
    """SIGTERM or SIGINT. A BaseException, so no `except Exception` swallows it."""


class NoAnswerError(Exception):
    """No usable answer from Sunroom; the text says why, in plain words."""


@dataclass(frozen=True)
class Settings:
    url: str = DEFAULT_URL
    session: str = "wayland"  # or "x11", or "macos"
    output: str = ""  # the screen's connector (HDMI-A-1, DSI-1), for wlr-randr
    helper: bool = True  # SUNROOM_SCREEN_HELPER
    brightness: str = "auto"  # auto, ddc, sysfs or none
    ddc_bus: str = ""  # the monitor's I2C bus number, found by the installer
    backlight: str = ""  # a device under /sys/class/backlight, found by the installer


@dataclass(frozen=True)
class State:
    screen: str  # "on" or "off"
    brightness: int  # percent, 1 to 100 (meaningless while off)
    reason: str  # day, dim, sleep or awake


def settings_from(values: dict[str, str]) -> Settings:
    def pick(key: str, pattern: str, default: str) -> str:
        value = values.get(key, "")
        return value if re.fullmatch(pattern, value) else default

    return Settings(
        url=(values.get("SUNROOM_URL") or DEFAULT_URL).rstrip("/"),
        session=values.get("SUNROOM_SESSION", "")
        if values.get("SUNROOM_SESSION") in ("x11", "macos")
        else "wayland",
        output=pick("SUNROOM_OUTPUT", r"[A-Za-z0-9-]+", ""),
        helper=values.get("SUNROOM_SCREEN_HELPER", "yes") != "no",
        brightness=pick("SUNROOM_BRIGHTNESS", r"auto|ddc|sysfs|none", "auto"),
        ddc_bus=pick("SUNROOM_DDC_BUS", r"[0-9]+", ""),
        backlight=pick("SUNROOM_BACKLIGHT", r"[A-Za-z0-9][A-Za-z0-9_.:-]*", ""),
    )


def find_backlight(root: Path, name: str) -> Path | None:
    """The backlight to dim: the one the installer saved, else the first there is."""
    base = root / "sys" / "class" / "backlight"
    try:
        devices = sorted(base.iterdir())
    except OSError:
        devices = []
    if name:
        devices.insert(0, base / name)
    for device in devices:
        if (device / "brightness").is_file() and (device / "max_brightness").is_file():
            return device
    return None


def brightness_method(settings: Settings, root: Path) -> tuple[str, Path | None]:
    """How brightness is set here: ("sysfs", the backlight), ("ddc", None) or ("none", None).

    auto takes the backlight when there is one, else DDC/CI when the installer found the
    monitor's bus. This user must be able to write it (the video or the i2c group)."""
    if not settings.helper or settings.brightness == "none":
        return "none", None
    if settings.brightness in ("auto", "sysfs"):
        device = find_backlight(root, settings.backlight)
        if device is not None and os.access(device / "brightness", os.W_OK):
            return "sysfs", device
    if settings.brightness in ("auto", "ddc") and settings.ddc_bus:
        if os.access(root / "dev" / f"i2c-{settings.ddc_bus}", os.R_OK | os.W_OK):
            return "ddc", None
    return "none", None


def ddc_bus_from_detect(text: str, output: str) -> str | None:
    """The I2C bus of the screen on connector ``output`` (else the first one that answers) in
    the output of `ddcutil detect --brief`; None when no screen there takes DDC/CI."""
    found: list[tuple[str, str]] = []  # (bus, connector)
    usable, bus, connector = False, "", ""
    for line in [*text.splitlines(), "end"]:
        if line[:1] not in ("", " ", "\t"):  # "Display 1", "Invalid display", ...: a new block
            if usable and bus:
                found.append((bus, connector))
            usable, bus, connector = re.match(r"Display \d+\b", line) is not None, "", ""
            continue
        bus_match = re.search(r"I2C bus:\s*/dev/i2c-(\d+)", line)
        if bus_match:
            bus = bus_match.group(1)
        connector_match = re.search(r"DRM[ _]connector:\s*card\d+-(\S+)", line)
        if connector_match:
            connector = connector_match.group(1)
    for bus, connector in found:
        if connector == output:
            return bus
    return found[0][0] if found else None


def scale(percent: int, maximum: int) -> int:
    """``percent`` of ``maximum``, rounded half up and never 0: a lit screen stays readable."""
    return max(1, (percent * maximum + 50) // 100)


def read_number(path: Path) -> int:
    try:
        return int(path.read_text(encoding="ascii").strip())
    except OSError, ValueError:
        return 0


def state_from(answer: object) -> tuple[State, str | None]:
    """The state and its etag from Sunroom's answer; anything unexpected means "on"."""
    if not isinstance(answer, dict):
        raise NoAnswerError("its answer wasn't the screen's state")
    fields = cast("dict[str, object]", answer)
    level = fields.get("brightness")
    brightness = 100
    if isinstance(level, int) and not isinstance(level, bool):
        brightness = min(100, max(1, level))
    reason, etag = fields.get("reason"), fields.get("etag")
    state = State(
        screen="off" if fields.get("screen") == "off" else "on",
        brightness=brightness,
        reason=reason if isinstance(reason, str) else "",
    )
    return state, etag if isinstance(etag, str) and etag else None


def plain(error: BaseException) -> str:
    """Why a request failed, in a few plain words for the journal."""
    if isinstance(error, urllib.error.HTTPError):
        if error.code == 404:
            return "this Sunroom has no screen sleep yet (it needs version 0.6.0 or newer)"
        return f"it answered with an error (HTTP {error.code})"
    reason = error.reason if isinstance(error, urllib.error.URLError) else error
    if isinstance(reason, (TimeoutError, socket.timeout)):
        return "no answer in time"
    if isinstance(reason, ConnectionRefusedError):
        return "nothing answers at that address (is Sunroom running?)"
    if isinstance(reason, socket.gaierror):
        return "that name doesn't lead anywhere from this Pi"
    if isinstance(reason, ValueError):
        return "its answer wasn't the screen's state"
    return str(reason) or type(reason).__name__


def http_get(url: str, timeout: float) -> bytes:
    if not re.match(r"https?://", url, re.IGNORECASE):
        raise urllib.error.URLError("SUNROOM_URL isn't a web address")  # never file: and such
    request = urllib.request.Request(  # noqa: S310 (http or https only, checked above)
        url, headers={"Accept": "application/json", "User-Agent": "sunroom-kiosk"}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        return cast(bytes, response.read(MAX_ANSWER_BYTES))


def run_command(argv: list[str]) -> tuple[int, str]:
    """Run a command: its exit status (127: not installed) and what it printed."""
    try:
        done = subprocess.run(  # noqa: S603 (the helper's own fixed commands, no shell)
            argv,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=COMMAND_TIMEOUT_S,
            check=False,
        )
    except FileNotFoundError:
        return 127, f"{argv[0]} isn't installed"
    except subprocess.TimeoutExpired:
        return 124, f"it took longer than {COMMAND_TIMEOUT_S} s"
    except OSError as error:
        return 126, str(error.strerror or error)
    printed = [part.strip() for part in (done.stderr, done.stdout) if part and part.strip()]
    return done.returncode, "\n".join(printed)


class Awake:
    """macOS: holds the display awake (``caffeinate -dis``) until let go, and never longer than
    this process lives (``-w``: caffeinate ends when the agent does)."""

    def __init__(self) -> None:
        self.process: subprocess.Popen[bytes] | None = None

    def hold(self) -> bool:
        if self.process is not None and self.process.poll() is None:
            return True
        try:
            self.process = subprocess.Popen(  # noqa: S603 - a fixed command
                ["caffeinate", "-dis", "-w", str(os.getpid())],  # noqa: S607 - the system's own
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            return False
        return True

    def release(self) -> None:
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
        self.process = None


class Helper:
    """Polls the state and keeps the panel matching it. ``screen`` and ``level`` are what was
    last applied successfully, so a failed command is tried again with the next answer."""

    def __init__(
        self,
        settings: Settings,
        *,
        fetch: Fetch = http_get,
        run: Run = run_command,
        root: Path = Path("/"),
        sleep: Callable[[float], None] = time.sleep,
        say: Callable[[str], None] = _say,
        awake: Awake | None = None,
    ) -> None:
        self.settings = settings
        self.awake = awake or Awake()
        self.fetch = fetch
        self.run = run
        self.sleep = sleep
        self.say = say
        self.method, self.backlight = brightness_method(settings, root)
        self.etag: str | None = None
        self.screen: str | None = None  # "on", "off", or None before the first answer
        self.level: int | None = None  # percent
        self.failures = 0  # polls in a row without an answer
        self.ddc_max: int | None = None
        self.last_note = ""

    # ------------------------------------------------------------------ the loop

    def run_forever(self) -> None:
        self.say(f"Following the screen's sleep times from {self.settings.url}; {self.how()}.")
        try:
            while True:
                try:
                    self.step()
                except Exception as error:  # a surprise must never leave the wall dark
                    self.failed(f"something unexpected went wrong ({error!r})")
        except Stop:
            pass
        finally:
            self.light(full=True)
            self.say("Stopped; the screen is left on.")

    def step(self) -> None:
        """One poll, then the changes; or, without an answer, a pause."""
        try:
            state = self.poll()
        except NoAnswerError as problem:
            self.failed(str(problem))
            return
        if self.failures:
            self.failures = 0
            self.last_note = ""
            self.say("Sunroom answers again.")
        self.apply(state)

    def poll(self) -> State:
        query = {"wait": str(WAIT_S)}
        if self.etag:
            query["etag"] = self.etag
        url = f"{self.settings.url}/api/display/state?{urllib.parse.urlencode(query)}"
        try:
            answer: object = json.loads(self.fetch(url, TIMEOUT_S))
        except (OSError, http.client.HTTPException, ValueError) as error:
            raise NoAnswerError(plain(error)) from None
        state, self.etag = state_from(answer)
        return state

    def failed(self, problem: str) -> None:
        self.failures += 1
        self.etag = None  # so the next answer comes at once
        delay = min(BACKOFF_MAX_S, BACKOFF_FIRST_S * 2 ** min(self.failures - 1, 5))
        self.note(f"No answer from Sunroom at {self.settings.url}: {problem}. Trying again.")
        if self.failures >= FAILURES_BEFORE_ON and self.screen != "on":
            self.light()
            if self.screen == "on":
                self.say("Screen on: Sunroom hasn't answered for half a minute.")
        self.sleep(delay)

    # ------------------------------------------------------------------ the panel

    def apply(self, state: State) -> None:
        why = REASONS.get(state.reason)
        ending = f": {why}." if why else "."
        woke = self.screen == "off" and state.screen == "on"
        if state.screen != self.screen:
            if state.screen == "off":
                done = self.panel_off()
            else:
                done = self.panel_on(everything=self.screen is None)
            if done:
                self.screen = state.screen
                self.say(f"Screen {state.screen}{ending}")
        if self.screen != "on" or self.method == "none" or state.brightness == self.level:
            return
        if woke and self.method == "ddc":
            self.sleep(DDC_SETTLE_S)
        if self.set_level(state.brightness):
            self.level = state.brightness
            self.say(f"Brightness {state.brightness}%{ending}")

    def panel_off(self) -> bool:
        if self.method == "sysfs" and self.write_backlight("bl_power", 4):
            return True
        return self.dpms("off")

    def panel_on(self, everything: bool = False) -> bool:
        """``everything``: also the ways this helper may not have used, to be sure."""
        lit = self.method == "sysfs" and self.write_backlight("bl_power", 0)
        if lit and not everything:
            return True
        return self.dpms("on") or lit

    def dpms(self, word: str) -> bool:
        if self.settings.session == "macos":
            if word == "off":
                self.awake.release()
                return self.command(["pmset", "displaysleepnow"])
            woke = self.command(["caffeinate", "-u", "-t", "1"])
            return self.awake.hold() and woke
        if self.settings.session == "x11":
            commands = [["xset", "dpms", "force", word]]
            if word == "on":  # and with every DPMS timeout off, X never blanks it by itself
                commands.append(["xset", "dpms", "0", "0", "0"])
            return all([self.command(argv) for argv in commands])
        if self.command(["wlopm", f"--{word}", "*"]):
            return True
        output = self.settings.output
        return bool(output) and self.command(["wlr-randr", "--output", output, f"--{word}"])

    def set_level(self, percent: int) -> bool:
        if self.method == "sysfs" and self.backlight is not None:
            maximum = read_number(self.backlight / "max_brightness")
            if maximum <= 0:
                self.note(f"Couldn't read {self.backlight / 'max_brightness'}.")
                return False
            return self.write_backlight("brightness", scale(percent, maximum))
        if self.method == "ddc":
            value = str(scale(percent, self.ddc_maximum()))
            return self.command(["ddcutil", "--bus", self.settings.ddc_bus, "setvcp", "10", value])
        return False

    def ddc_maximum(self) -> int:
        """The monitor's top brightness value (most say 100), asked once."""
        if self.ddc_max is None:
            argv = ["ddcutil", "--brief", "--bus", self.settings.ddc_bus, "getvcp", "10"]
            code, printed = self.run(argv)
            found = re.search(r"^VCP 10 C \d+ (\d+)", printed, re.MULTILINE)
            if code != 0 or found is None or int(found.group(1)) <= 0:
                return 100  # and ask again next time
            self.ddc_max = int(found.group(1))
        return self.ddc_max

    def write_backlight(self, name: str, value: int) -> bool:
        if self.backlight is None:
            return False
        path = self.backlight / name
        try:
            path.write_text(f"{value}\n", encoding="ascii")
        except OSError as error:
            self.note(f"Couldn't write {path}: {error.strerror or error}.")
            return False
        return True

    def light(self, full: bool = False) -> None:
        """Switch the screen on whatever was applied; ``full``: at full brightness too (when
        stopping: a monitor keeps a DDC/CI brightness after the helper has gone)."""
        woke = self.screen == "off"
        if self.panel_on(everything=True):
            self.screen = "on"
        if not full or self.level in (None, 100):
            return
        if woke and self.method == "ddc":
            self.sleep(DDC_SETTLE_S)
        if self.set_level(100):
            self.level = 100

    # ------------------------------------------------------------------ words

    def command(self, argv: list[str]) -> bool:
        code, printed = self.run(argv)
        if code == 0:
            return True
        detail = next((line for line in printed.splitlines() if line.strip()), "")
        self.note(f"{' '.join(argv)} didn't work: {detail or f'exit status {code}'}.")
        return False

    def note(self, line: str) -> None:
        """A problem, said once while it repeats."""
        if line != self.last_note:
            self.last_note = line
            self.say(line)

    def how(self) -> str:
        if self.method == "sysfs" and self.backlight is not None:
            return f"brightness through the backlight {self.backlight.name}"
        if self.method == "ddc":
            return f"brightness through DDC/CI on I2C bus {self.settings.ddc_bus}"
        if self.settings.brightness == "none":
            return "brightness left to the screen (the page dims itself)"
        return (
            f"no way to set the brightness was found for SUNROOM_BRIGHTNESS="
            f"{self.settings.brightness}, so the page dims itself (docs/KIOSK.md)"
        )


def dimmer_for(settings: Settings, root: Path = Path("/")) -> str:
    """``screen`` when the helper sets the panel's own brightness here, else ``page`` (the page
    darkens itself): the wall's ``?dimmer=`` (frontend/src/lib/dimmer.ts)."""
    return "screen" if brightness_method(settings, root)[0] in ("ddc", "sysfs") else "page"


class ScreenThread:
    """The helper on a daemon thread of its own, for as long as the agent runs.

    ``retarget`` follows a new address (the next poll goes there, with no etag); ``stop`` ends
    the loop and leaves the screen on at full brightness."""

    def __init__(self, settings: Settings, *, root: Path = Path("/")) -> None:
        self._stopping = threading.Event()
        self._lock = threading.Lock()
        self.helper = Helper(settings, fetch=self._fetch, root=root, sleep=self._sleep)
        self._thread: threading.Thread | None = None

    @property
    def method(self) -> str:
        return self.helper.method

    def _fetch(self, url: str, timeout: float) -> bytes:
        if self._stopping.is_set():
            raise Stop
        return http_get(url, timeout)

    def _sleep(self, seconds: float) -> None:
        if self._stopping.wait(seconds):
            raise Stop

    def start(self) -> None:
        if self._thread is not None or not self.helper.settings.helper:
            return
        self._thread = threading.Thread(
            target=self.helper.run_forever, name="sunroom-screen", daemon=True
        )
        self._thread.start()

    def retarget(self, url: str) -> None:
        with self._lock:
            self.helper.settings = replace(self.helper.settings, url=url.rstrip("/"))
            self.helper.etag = None

    def stop(self) -> None:
        """Called on the way out: whatever the thread is doing, the screen ends up lit."""
        self._stopping.set()
        if self._thread is not None:
            with self._lock:
                self.helper.light(full=True)
