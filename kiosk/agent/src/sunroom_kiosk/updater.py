"""Updates of Sunroom Screen itself (docs/M7.md T9).

* **Check:** GitHub's list of the repository's tags (as Sunroom's own check, ADR 0032) gives the
  newest version; that version's Release gives ``SHA256SUMS``, which must list its wheel. An
  update is "available" only then. One request to api.github.com and one to github.com: they see
  this screen's public address (the setup page says so).
* **Install:** the wheel is downloaded, its sha256 checked against ``SHA256SUMS`` (a mismatch
  stops everything), and kept beside the one running, under ``~/.local/share/sunroom-kiosk/
  wheels``. Then a separate process, the apply step (apply.py: ``sunroom-kiosk update --apply``,
  under ``systemd-run`` on Linux so it outlives the agent; on Windows a copy of apply.py run by
  the Python the agent's environment came from, since Windows locks a running program's files),
  installs it with ``uv tool install --reinstall``, starts the agent again, and waits 60 s for
  the new version to answer on 127.0.0.1; if it doesn't, it puts the previous wheel back, starts
  that, and leaves a note the agent shows ("The update didn't start; the previous version is
  back.").
* **Nightly:** at the start of the household's sleep hours (from Sunroom's
  ``/api/display/state``; 03:30 without them) the check runs, and with Updates on Install
  overnight (every screen's default) an update installs.

``NoUpdates`` (nothing to update from: a checkout) and ``FakeUpdater`` (``--fake``) stand in.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Protocol, cast

import httpx

from sunroom_kiosk import apply as apply_step
from sunroom_kiosk import logs
from sunroom_kiosk.apply import Paths
from sunroom_kiosk.version import version

if TYPE_CHECKING:
    from sunroom_kiosk.state import Agent

log = logs.get("updater")

REPO = "ScopeXL/sunroom"
TAGS_URL = f"https://api.github.com/repos/{REPO}/tags?per_page=100"
DOWNLOAD = f"https://github.com/{REPO}/releases/download"
APPLY_UNIT = "sunroom-kiosk-update"
NIGHTLY_DEFAULT = (3, 30)
_VERSION = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")

type UpdateState = Literal["unknown", "up_to_date", "available", "installing", "failed"]

DIDNT_START = "The update didn't start; the previous version is back."


@dataclass(frozen=True)
class UpdateStatus:
    state: UpdateState
    installed: str
    latest: str | None = None
    checked_at: str | None = None
    message: str | None = None

    def out(self, check: str) -> dict[str, Any]:
        """As the API's ScreenUpdateOut."""
        return {"check": check, **asdict(self)}


class UpdaterLike(Protocol):
    def status(self, check: str) -> dict[str, Any]: ...
    async def check_now(self) -> UpdateStatus: ...
    async def install(self, agent: Agent) -> None: ...
    async def run(self, agent: Agent) -> None: ...


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def parse(text: str) -> tuple[int, int, int] | None:
    found = _VERSION.match(text.strip())
    if found is None:
        return None
    major, minor, patch = (int(part) for part in found.groups())
    return major, minor, patch


def newest(tags: object) -> str | None:
    """The highest X.Y.Z among GitHub's tags (pre-releases and other names left out)."""
    if not isinstance(tags, list):
        return None
    found: list[tuple[tuple[int, int, int], str]] = []
    for tag in cast(list[Any], tags):
        name = cast(dict[str, Any], tag).get("name") if isinstance(tag, dict) else None
        parsed = parse(name) if isinstance(name, str) else None
        if parsed is not None:
            found.append((parsed, ".".join(map(str, parsed))))
    return max(found)[1] if found else None


def newer(candidate: str | None, current: str) -> bool:
    theirs, ours = parse(candidate or ""), parse(current)
    return theirs is not None and ours is not None and theirs > ours


def wheel_name(release: str) -> str:
    return f"sunroom_kiosk-{release}-py3-none-any.whl"


def sums_from(text: str) -> dict[str, str]:
    """``sha256sum``'s lines: hash, two spaces (or a space and a star), file name."""
    sums: dict[str, str] = {}
    for line in text.splitlines():
        found = re.match(r"^([0-9a-fA-F]{64})\s+\*?(\S+)$", line.strip())
        if found:
            sums[found.group(2)] = found.group(1).lower()
    return sums


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def next_nightly(now: datetime, sleep_from: str | None) -> datetime:
    """The next start of the sleep hours (HH:MM), or 03:30, after ``now`` (local time)."""
    hour, minute = NIGHTLY_DEFAULT
    found = re.match(r"^(\d{1,2}):(\d{2})$", sleep_from or "")
    if found and int(found.group(1)) < 24 and int(found.group(2)) < 60:
        hour, minute = int(found.group(1)), int(found.group(2))
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return target


type Spawn = Callable[[list[str]], Awaitable[bool]]


def base_python() -> str:
    """The Python this environment was made from (uv's own copy), without a console window
    where there's one (Windows' pythonw.exe)."""
    base = Path(getattr(sys, "_base_executable", sys.executable))
    windowless = base.with_name("pythonw.exe")
    return str(windowless if windowless.exists() else base)


async def spawn_apply(argv: list[str]) -> bool:
    """Start the apply step so it outlives this process: in its own systemd unit where there is
    one (the agent's own unit's restart would take a child down with it), else detached."""
    if sys.platform.startswith("linux") and shutil.which("systemd-run"):
        unit = [
            "systemd-run",
            "--user",
            "--collect",
            f"--unit={APPLY_UNIT}-{int(time.time())}",
            "--",
        ]
        process = await asyncio.create_subprocess_exec(
            *unit,
            *argv,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        return await process.wait() == 0
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
        subprocess, "CREATE_NEW_PROCESS_GROUP", 0
    )
    subprocess.Popen(  # noqa: S603, ASYNC220 - our own command, fire and forget
        argv,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=sys.platform != "win32",
        creationflags=flags,
    )
    return True


class Updater:
    def __init__(
        self,
        *,
        http: Callable[[], httpx.AsyncClient] | None = None,
        paths: Paths | None = None,
        current: str | None = None,
        spawn: Spawn = spawn_apply,
        port: int = 7800,
        system: str = sys.platform,
    ) -> None:
        self.http = http or (
            lambda: httpx.AsyncClient(
                timeout=httpx.Timeout(60.0, connect=10.0),
                headers={"User-Agent": f"sunroom-kiosk/{version()}"},
                follow_redirects=True,
            )
        )
        self.paths = paths or Paths.default()
        self.installed = current or version()
        self.spawn = spawn
        self.port = port
        self.system = system
        self.current = self._remembered()
        self._busy = asyncio.Lock()

    # ------------------------------------------------------------------ what it knows

    def _remembered(self) -> UpdateStatus:
        """The last check's answer, and a failed update's note, from before a restart."""
        fresh = UpdateStatus(state="unknown", installed=self.installed)
        try:
            saved = json.loads(self.paths.state.read_text(encoding="utf-8"))
        except OSError, ValueError:
            return fresh
        if not isinstance(saved, dict):
            return fresh
        fields = cast(dict[str, Any], saved)
        latest = fields.get("latest") if isinstance(fields.get("latest"), str) else None
        failed = fields.get("failed")
        state: UpdateState = "available" if newer(latest, self.installed) else "up_to_date"
        if latest is None:
            state = "unknown"
        message = None
        if isinstance(failed, str) and failed == latest and newer(latest, self.installed):
            state, message = "failed", DIDNT_START
        checked = fields.get("checked_at")
        return replace(
            fresh,
            state=state,
            latest=latest,
            checked_at=checked if isinstance(checked, str) else None,
            message=message,
        )

    def _remember(self, **values: Any) -> None:
        try:
            saved = json.loads(self.paths.state.read_text(encoding="utf-8"))
            if not isinstance(saved, dict):
                saved = {}
        except OSError, ValueError:
            saved = {}
        merged = {**cast(dict[str, Any], saved), **values}
        self.paths.state.parent.mkdir(parents=True, exist_ok=True)
        self.paths.state.write_text(json.dumps(merged, sort_keys=True), encoding="utf-8")

    def status(self, check: str) -> dict[str, Any]:
        return self.current.out(check)

    # ------------------------------------------------------------------ check

    async def _latest(self, client: httpx.AsyncClient) -> str | None:
        response = await client.get(TAGS_URL, headers={"Accept": "application/vnd.github+json"})
        response.raise_for_status()
        return newest(response.json())

    async def _sums(self, client: httpx.AsyncClient, release: str) -> dict[str, str]:
        response = await client.get(f"{DOWNLOAD}/v{release}/SHA256SUMS")
        if response.status_code == 404:
            return {}
        response.raise_for_status()
        return sums_from(response.text)

    async def check_now(self) -> UpdateStatus:
        try:
            async with self.http() as client:
                latest = await self._latest(client)
                ready = latest is not None and newer(latest, self.installed)
                if ready and latest is not None:
                    # Released but its files not up yet: not an update until they are.
                    ready = wheel_name(latest) in await self._sums(client, latest)
        except (httpx.HTTPError, ValueError) as error:
            log.info("Couldn't ask GitHub for the newest version: %s.", type(error).__name__)
            self.current = replace(
                self.current,
                checked_at=now_iso(),
                message="GitHub didn't answer. This screen asks again tomorrow.",
            )
            return self.current
        state: UpdateState = "available" if ready else "up_to_date"
        if self.current.state == "failed" and self.current.latest == latest:
            state = "failed"
        self.current = UpdateStatus(
            state=state,
            installed=self.installed,
            latest=latest,
            checked_at=now_iso(),
            message=DIDNT_START if state == "failed" else None,
        )
        self._remember(latest=latest, checked_at=self.current.checked_at)
        return self.current

    # ------------------------------------------------------------------ install

    async def install(self, agent: Agent) -> None:
        if self._busy.locked():
            return
        async with self._busy:
            await self._install(agent)

    async def _install(self, agent: Agent) -> None:
        async def say(percent: int, step: str) -> None:
            agent.hub.publish("update.progress", {"percent": percent, "step": step})

        if self.current.state not in ("available", "failed") or self.current.latest is None:
            await self.check_now()
        release = self.current.latest
        if release is None or not newer(release, self.installed):
            agent.toast("This screen is up to date.")
            agent.publish_state()
            return
        self.current = replace(self.current, state="installing", message=None)
        agent.publish_state()
        await say(10, "Downloading…")
        try:
            wheel = await self.download(release)
        except UpdateError as error:
            log.info("The update to %s stopped: %s", release, error)
            self.current = replace(self.current, state="available", message=str(error))
            agent.publish_state()
            await say(100, "Stopped")
            return
        await say(60, "Installing…")
        previous = self.paths.wheels / wheel_name(self.installed)
        kept = previous if await asyncio.to_thread(previous.exists) else None
        argv = await asyncio.to_thread(self.apply_command, wheel, kept)
        log.info("Installing Sunroom Screen %s; it starts again in a moment.", release)
        if not await self.spawn(argv):
            self.current = replace(
                self.current, state="available", message="The update couldn't start. Try again."
            )
            agent.publish_state()
            await say(100, "Stopped")

    def apply_command(self, wheel: Path, previous: Path | None) -> list[str]:
        """How the apply step starts: this package's own command, or on Windows a copy of
        apply.py, run by the Python this environment was made from (its own files are locked
        while the agent runs)."""
        tail = ["--apply", str(wheel), "--port", str(self.port)]
        if previous is not None:
            tail += ["--previous", str(previous)]
        if self.system != "win32":
            return [sys.executable, "-m", "sunroom_kiosk", "update", *tail]
        script = self.paths.state.parent / "apply.py"
        script.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(apply_step.__file__, script)
        return [base_python(), str(script), *tail]

    async def download(self, release: str) -> Path:
        """The release's wheel, checked against its SHA256SUMS; kept beside the running one."""
        name = wheel_name(release)
        try:
            async with self.http() as client:
                expected = (await self._sums(client, release)).get(name)
                if expected is None:
                    raise UpdateError("This version's files aren't published yet. Try again later.")
                response = await client.get(f"{DOWNLOAD}/v{release}/{name}")
                response.raise_for_status()
                data = response.content
        except httpx.HTTPError as error:
            raise UpdateError("The download didn't finish. Try again in a while.") from error
        if hashlib.sha256(data).hexdigest() != expected:
            raise UpdateError("The download didn't match its checksum, so it wasn't installed.")
        return await asyncio.to_thread(self._keep, name, data)

    def _keep(self, name: str, data: bytes) -> Path:
        self.paths.wheels.mkdir(parents=True, exist_ok=True)
        path = self.paths.wheels / name
        partial = path.with_suffix(".partial")
        partial.write_bytes(data)
        os.replace(partial, path)
        return path

    # ------------------------------------------------------------------ nightly

    async def run(self, agent: Agent) -> None:
        while True:
            now = datetime.now().astimezone()
            when = next_nightly(now, await self._sleep_from(agent))
            await asyncio.sleep(max(60.0, (when - now).total_seconds()))
            await self.nightly(agent)

    async def _sleep_from(self, agent: Agent) -> str | None:
        """When the household's sleep hours start, from Sunroom (None: no schedule known)."""
        url = agent.config.url
        if not url:
            return None
        try:
            async with agent.http() as client:
                answer = (await client.get(f"{url}/api/display/state")).json()
        except httpx.HTTPError, ValueError:
            return None
        if not isinstance(answer, dict):
            return None
        schedule = cast(dict[str, Any], answer).get("schedule")
        if not isinstance(schedule, dict):
            return None
        sleep_from = cast(dict[str, Any], schedule).get("sleep_from")
        return sleep_from if isinstance(sleep_from, str) else None

    async def nightly(self, agent: Agent) -> None:
        await self.check_now()
        agent.publish_state()
        if agent.update_check() == "nightly" and self.current.state == "available":
            await self.install(agent)


class UpdateError(Exception):
    """Why an update stopped, in plain words."""


# ---------------------------------------------------------------------- stand-ins


class NoUpdates:
    """A screen with nothing to update from (run from a checkout): its version, and that's all."""

    def __init__(self) -> None:
        self.current = UpdateStatus(state="unknown", installed=version())

    def status(self, check: str) -> dict[str, Any]:
        return self.current.out(check)

    async def check_now(self) -> UpdateStatus:
        return self.current

    async def install(self, agent: Agent) -> None:
        agent.toast("There's nothing to update from here.")

    async def run(self, agent: Agent) -> None:
        await asyncio.Event().wait()


class FakeUpdater:
    """``--fake``: a newer version is out; installing it takes a few seconds of progress and
    then this screen says it runs it."""

    def __init__(self, latest: str = "9.9.9", step_s: float = 0.4) -> None:
        self.latest = latest
        self.step_s = step_s
        self.current = UpdateStatus(state="unknown", installed=version())

    def reset(self) -> None:
        self.current = UpdateStatus(state="unknown", installed=version())

    def status(self, check: str) -> dict[str, Any]:
        return self.current.out(check)

    async def check_now(self) -> UpdateStatus:
        state: UpdateState = "available" if self.current.installed != self.latest else "up_to_date"
        self.current = replace(self.current, state=state, latest=self.latest, checked_at=now_iso())
        return self.current

    async def install(self, agent: Agent) -> None:
        self.current = replace(self.current, state="installing")
        agent.publish_state()
        steps = ((10, "Downloading…"), (45, "Checking it…"), (80, "Installing…"), (100, "Done"))
        for percent, step in steps:
            await asyncio.sleep(self.step_s)
            agent.hub.publish("update.progress", {"percent": percent, "step": step})
        self.current = UpdateStatus(
            state="up_to_date", installed=self.latest, latest=self.latest, checked_at=now_iso()
        )
        agent.publish_state()

    async def run(self, agent: Agent) -> None:
        await asyncio.Event().wait()
