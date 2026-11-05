"""Updates of Sunroom Screen itself (docs/M7.md T9).

* **Check:** sunroom.day's ``version.json``, or GitHub's latest Release when that doesn't answer
  (as Sunroom's own check, ADR 0046), gives the newest version; that version's Release gives
  ``SHA256SUMS``, which must list its wheel. An update is "available" only then. One request to
  sunroom.day and one to github.com: they see this screen's public address (the setup page says
  so).
* **Install:** the wheel is downloaded, its sha256 checked against ``SHA256SUMS`` (a mismatch
  stops everything), and kept beside the one running, under ``~/.local/share/sunroom-kiosk/
  wheels``, after the small files are copied aside (setup_files.back_up). Then a separate
  process, the apply step (apply.py: ``sunroom-kiosk update --apply``, under ``systemd-run`` on
  Linux so it outlives the agent; on Windows a copy of apply.py run by the Python the agent's
  environment came from, since Windows locks a running program's files), installs it with ``uv
  tool install --reinstall``, runs the new version's own setup, starts the agent again as that
  setup says, and waits 60 s for the new version to answer on 127.0.0.1; if it doesn't, it puts
  the previous wheel back with its own setup, starts that, and leaves a note the agent shows
  ("The update didn't finish. Sunroom Screen 0.17.0 is back."). The new version finishes the
  rest at its start (state.py's ``finish_update``; ADR 0044).
* **Reinstall…:** the version installed, its wheel from the wheels folder (downloaded and checked
  again when it's gone), through the same apply step with ``--force``: its setup rewritten whole.
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
import sys
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Protocol, cast

import httpx

from sunroom_kiosk import apply as apply_step
from sunroom_kiosk import logs
from sunroom_kiosk.apply import Paths
from sunroom_kiosk.platform.base import spawn_detached
from sunroom_kiosk.version import version
from sunroom_kiosk.words import Said, SaidError, said, t_en

if TYPE_CHECKING:
    from sunroom_kiosk.state import Agent

log = logs.get("updater")

REPO = "ScopeXL/sunroom"
VERSION_URL = "https://sunroom.day/version.json"
RELEASE_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
DOWNLOAD = f"https://github.com/{REPO}/releases/download"
APPLY_UNIT = "sunroom-kiosk-update"
NIGHTLY_DEFAULT = (3, 30)
GO_BACK_FOR = timedelta(days=7)
_VERSION = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")

type UpdateState = Literal["unknown", "up_to_date", "available", "installing", "failed"]


@dataclass(frozen=True)
class UpdateStatus:
    state: UpdateState
    installed: str
    latest: str | None = None
    checked_at: str | None = None
    message: Said | None = None  # a failure, said for the family

    def out(self, check: str) -> dict[str, Any]:
        """As the API's ScreenUpdateOut: the message's English, key and values."""
        fields = asdict(self)
        said = self.message
        fields["message"] = said.message if said else None
        fields["message_key"] = said.key if said else None
        fields["message_params"] = said.params if said else {}
        return {"check": check, **fields}


class UpdaterLike(Protocol):
    def status(self, check: str) -> dict[str, Any]: ...
    async def check_now(self) -> UpdateStatus: ...
    async def install(self, agent: Agent) -> None: ...
    async def reinstall(self, agent: Agent) -> None: ...
    async def go_back(self, agent: Agent) -> None: ...
    def seen(self) -> None: ...
    def setup_said(self) -> dict[str, Any]: ...
    def kept_wheel(self) -> Path | None: ...
    def rebooted_for(self) -> str | None: ...
    def note_rebooted(self, release: str) -> None: ...
    async def run(self, agent: Agent) -> None: ...


def progress_out(percent: int, step: str, message: Said | None = None) -> dict[str, Any]:
    """A progress event (ScreenProgressOut): the step's English and key, and a message's."""
    return {
        "percent": percent,
        "step": t_en(step),
        "key": step,
        "message": message.message if message else None,
        "message_key": message.key if message else None,
        "message_params": message.params if message else {},
    }


def back_up_here() -> object:
    """The small files copied aside before an update changes anything (setup_files.back_up)."""
    from sunroom_kiosk import setup_files

    return setup_files.back_up(setup_files.Machine.here())


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def parse(text: str) -> tuple[int, int, int] | None:
    found = _VERSION.match(text.strip())
    if found is None:
        return None
    major, minor, patch = (int(part) for part in found.groups())
    return major, minor, patch


def _version(name: object) -> str | None:
    parsed = parse(name) if isinstance(name, str) else None
    return ".".join(map(str, parsed)) if parsed is not None else None


def version_from_site(body: object) -> str | None:
    """sunroom.day's version.json: {"version": "1.0.0", …}."""
    return _version(cast(dict[str, Any], body).get("version")) if isinstance(body, dict) else None


def version_from_release(body: object) -> str | None:
    """GitHub's latest Release: {"tag_name": "v1.0.0", …}. Never a draft or a pre-release."""
    if not isinstance(body, dict):
        return None
    release = cast(dict[str, Any], body)
    if release.get("draft") or release.get("prerelease"):
        return None
    return _version(release.get("tag_name"))


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
    """Start the apply step so it outlives this process (platform/base.py's spawn_detached)."""
    return await spawn_detached(argv, unit=APPLY_UNIT)


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
        backup: Callable[[], object] | None = None,
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
        # The small files copied aside before an update (the agent's own Updater does; one made
        # in a test copies nothing from the home it runs in).
        self.backup: Callable[[], object] = backup or (lambda: None)
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
            state, message = "failed", said("agent.update.didnt_finish", version=self.installed)
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
        return {
            **self.current.out(check),
            "last_result": self.last_result(),
            "go_back_to": self.go_back_to(),
        }

    def go_back_to(self) -> str | None:
        """Go Back…'s version: the one an update replaced, for a version that starts but
        misbehaves, for a week after that update and while its wheel is still here (ADR 0046)."""
        replaced = self._saved().get("replaced")
        if not isinstance(replaced, dict):
            return None
        fields = cast(dict[str, Any], replaced)
        release, at = fields.get("version"), fields.get("at")
        if not isinstance(release, str) or not isinstance(at, str):
            return None
        if fields.get("by") != self.installed or not newer(self.installed, release):
            return None
        try:
            when = datetime.fromisoformat(at)
        except ValueError:
            return None
        if datetime.now(UTC) - when > GO_BACK_FOR:
            return None
        return release if (self.paths.wheels / wheel_name(release)).is_file() else None

    def last_result(self) -> dict[str, Any] | None:
        """How the last update ended, until a page has shown it (ScreenUpdateResultOut)."""
        saved = self._saved()
        last = saved.get("last")
        if not isinstance(last, dict) or saved.get("last_seen"):
            return None
        fields = cast(dict[str, Any], last)
        release, previous = fields.get("version"), fields.get("previous")
        if not isinstance(release, str):
            return None
        ok = fields.get("ok") is True
        if ok and fields.get("back") is True:
            message = said("agent.update.went_back", version=release)
        elif ok and fields.get("again") is True:
            message = said("agent.update.reinstalled", version=release)
        elif ok:
            message = said("agent.update.updated", version=release)
        elif isinstance(previous, str):
            message = said("agent.update.didnt_finish", version=previous)
        else:
            message = said("agent.update.didnt_finish_plain")
        at = fields.get("at")
        return {
            "version": release,
            "ok": ok,
            "at": at if isinstance(at, str) else None,
            "message": message.message,
            "message_key": message.key,
            "message_params": message.params,
        }

    def seen(self) -> None:
        """A page has shown how the last update ended: it's said once."""
        self._remember(last_seen=True)

    def setup_said(self) -> dict[str, Any]:
        """The apply step's setup report (``--from-update``), for the agent's start."""
        report = self._saved().get("setup")
        return cast(dict[str, Any], report) if isinstance(report, dict) else {}

    def kept_wheel(self) -> Path | None:
        """The installed version's wheel, kept for root's part of its setup and Reinstall…."""
        kept = self.paths.wheels / wheel_name(self.installed)
        return kept if kept.is_file() else None

    def rebooted_for(self) -> str | None:
        found = self._saved().get("rebooted_for")
        return found if isinstance(found, str) else None

    def note_rebooted(self, release: str) -> None:
        """The computer restarts once for this version's setup, never in a loop."""
        self._remember(rebooted_for=release)

    def _saved(self) -> dict[str, Any]:
        try:
            saved = json.loads(self.paths.state.read_text(encoding="utf-8"))
        except OSError, ValueError:
            return {}
        return cast(dict[str, Any], saved) if isinstance(saved, dict) else {}

    # ------------------------------------------------------------------ check

    async def _latest(self, client: httpx.AsyncClient) -> str | None:
        try:
            site = await client.get(VERSION_URL)
            site.raise_for_status()
            found = version_from_site(site.json())
            if found is not None:
                return found
        except (httpx.HTTPError, ValueError) as error:
            log.info("sunroom.day didn't say the newest version: %s.", type(error).__name__)
        response = await client.get(RELEASE_URL, headers={"Accept": "application/vnd.github+json"})
        response.raise_for_status()
        return version_from_release(response.json())

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
            log.info("Couldn't find out the newest version: %s.", type(error).__name__)
            self.current = replace(
                self.current,
                checked_at=now_iso(),
                message=said("agent.update.github_silent"),
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
            message=(
                said("agent.update.didnt_finish", version=self.installed)
                if state == "failed"
                else None
            ),
        )
        self._remember(latest=latest, checked_at=self.current.checked_at)
        return self.current

    # ------------------------------------------------------------------ install

    async def install(self, agent: Agent) -> None:
        if self._busy.locked():
            return
        async with self._busy:
            await self._install(agent, again=False)

    async def reinstall(self, agent: Agent) -> None:
        """Reinstall…: the version already installed, its setup rewritten whole (ADR 0044)."""
        if self._busy.locked():
            return
        async with self._busy:
            await self._install(agent, again=True)

    async def go_back(self, agent: Agent) -> None:
        """Go Back…: the version this one replaced, with its own setup (ADR 0046)."""
        if self._busy.locked():
            return
        async with self._busy:
            release = self.go_back_to()
            if release is None:
                agent.toast("agent.update.cant_go_back")
                agent.publish_state()
                return
            await self._install(agent, again=False, back_to=release)

    async def _install(self, agent: Agent, *, again: bool, back_to: str | None = None) -> None:
        """The whole way (ADR 0044): the small files aside, the wheel downloaded and checked, then
        the apply step, which installs it, sets it up and starts it; its steps arrive here
        through the state file while this agent still runs."""

        async def say(percent: int, step: str) -> None:
            agent.hub.publish("update.progress", progress_out(percent, step))

        was = self.current.state
        if back_to is not None:
            release = back_to
        elif again:
            release = self.installed
        else:
            if self.current.state not in ("available", "failed") or self.current.latest is None:
                await self.check_now()
            latest = self.current.latest
            if latest is None or not newer(latest, self.installed):
                agent.toast("agent.update.up_to_date")
                agent.publish_state()
                return
            release = latest
        self.current = replace(self.current, state="installing", message=None)
        agent.publish_state()
        await say(10, "agent.update.step.downloading")
        await asyncio.to_thread(self.backup)
        try:
            wheel = await self.download(release, lambda: say(30, "agent.update.step.checking"))
        except UpdateError as error:
            log.info("The update to %s stopped: %s", release, error)
            after: UpdateState = (
                was if back_to is not None else "up_to_date" if again else "available"
            )
            self.current = replace(self.current, state=after, message=error.said)
            agent.publish_state()
            await say(100, "agent.update.step.stopped")
            return
        await say(50, "agent.update.step.installing")
        previous = self.paths.wheels / wheel_name(self.installed)
        kept = previous if await asyncio.to_thread(previous.exists) else None
        await asyncio.to_thread(self._remember, progress=None, last_seen=False)
        argv = await asyncio.to_thread(
            self.apply_command, wheel, kept, force=again, back=back_to is not None
        )
        log.info("Installing Sunroom Screen %s; it starts again in a moment.", release)
        if not await self.spawn(argv):
            self.current = replace(
                self.current,
                state=was if back_to is not None else "available",
                message=said("agent.update.couldnt_start"),
            )
            agent.publish_state()
            await say(100, "agent.update.step.stopped")
            return
        agent.spawn(self.relay(agent))

    async def relay(self, agent: Agent, every_s: float = 0.5, for_s: float = 600.0) -> None:
        """The apply step's own steps (Setting up…, Starting again…), from the state file, for as
        long as this agent still runs."""
        said_last = "null"
        deadline = asyncio.get_running_loop().time() + for_s
        while asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(every_s)
            progress = (await asyncio.to_thread(self._saved)).get("progress")
            now = json.dumps(progress, sort_keys=True)
            if now != said_last and isinstance(progress, dict):
                fields = cast(dict[str, Any], progress)
                percent, key = fields.get("percent"), fields.get("key")
                if isinstance(percent, int) and isinstance(key, str):
                    agent.hub.publish("update.progress", progress_out(percent, key))
            said_last = now

    def apply_command(
        self, wheel: Path, previous: Path | None, *, force: bool = False, back: bool = False
    ) -> list[str]:
        """How the apply step starts: this package's own command, or on Windows a copy of
        apply.py, run by the Python this environment was made from (its own files are locked
        while the agent runs)."""
        tail = ["--apply", str(wheel), "--port", str(self.port)]
        if previous is not None:
            tail += ["--previous", str(previous)]
        if force:
            tail.append("--force")
        if back:
            tail.append("--back")
        if self.system != "win32":
            return [sys.executable, "-m", "sunroom_kiosk", "update", *tail]
        script = self.paths.state.parent / "apply.py"
        script.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(apply_step.__file__, script)
        return [base_python(), str(script), *tail]

    async def download(
        self, release: str, checking: Callable[[], Awaitable[None]] | None = None
    ) -> Path:
        """The release's wheel, checked against its SHA256SUMS; kept beside the running one. One
        kept already (Reinstall…'s, checked when it came) isn't downloaded again."""
        name = wheel_name(release)
        kept = self.paths.wheels / name
        if await asyncio.to_thread(kept.is_file):
            return kept
        try:
            async with self.http() as client:
                expected = (await self._sums(client, release)).get(name)
                if expected is None:
                    raise UpdateError("agent.update.not_published")
                response = await client.get(f"{DOWNLOAD}/v{release}/{name}")
                response.raise_for_status()
                data = response.content
        except httpx.HTTPError as error:
            raise UpdateError("agent.update.download_failed") from error
        if checking is not None:
            await checking()
        if hashlib.sha256(data).hexdigest() != expected:
            raise UpdateError("agent.update.bad_checksum")
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
        # A version the family went back from stays away, until the one after (Update Now can).
        if (
            agent.update_check() == "nightly"
            and self.current.state == "available"
            and self.current.latest != self._saved().get("went_back_from")
        ):
            await self.install(agent)


class UpdateError(SaidError):
    """Why an update stopped, in plain words: a key and its values."""


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
        agent.toast("agent.update.nothing_here")

    async def reinstall(self, agent: Agent) -> None:
        agent.toast("agent.update.nothing_here")

    async def go_back(self, agent: Agent) -> None:
        agent.toast("agent.update.nothing_here")

    def seen(self) -> None:
        return None

    def setup_said(self) -> dict[str, Any]:
        return {}

    def kept_wheel(self) -> Path | None:
        return None

    def rebooted_for(self) -> str | None:
        return None

    def note_rebooted(self, release: str) -> None:
        return None

    async def run(self, agent: Agent) -> None:
        await asyncio.Event().wait()


class FakeUpdater:
    """``--fake``: a newer version is out; installing it runs the real steps, then the pretend
    agent answers nothing for ``away_s`` (as one starting itself again), and comes back as the
    new version, saying Updated once."""

    def __init__(self, latest: str = "9.9.9", step_s: float = 0.4, away_s: float = 2.0) -> None:
        self.latest = latest
        self.step_s = step_s
        self.away_s = away_s
        self.current = UpdateStatus(state="unknown", installed=version())
        self.result: dict[str, Any] | None = None
        self.replaced: str | None = None

    def reset(self) -> None:
        self.current = UpdateStatus(state="unknown", installed=version())
        self.result = None
        self.replaced = None

    def status(self, check: str) -> dict[str, Any]:
        result = None
        if self.result is not None:
            release = cast(str, self.result["version"])
            message = said(cast(str, self.result["key"]), version=release)
            result = {
                "version": release,
                "ok": True,
                "at": self.result["at"],
                "message": message.message,
                "message_key": message.key,
                "message_params": message.params,
            }
        return {**self.current.out(check), "last_result": result, "go_back_to": self.replaced}

    def seen(self) -> None:
        self.result = None

    def setup_said(self) -> dict[str, Any]:
        return {}

    def kept_wheel(self) -> Path | None:
        return None

    def rebooted_for(self) -> str | None:
        return None

    def note_rebooted(self, release: str) -> None:
        return None

    async def reinstall(self, agent: Agent) -> None:
        await self._install(agent, again=True)

    async def go_back(self, agent: Agent) -> None:
        await self._install(agent, again=False, back=True)

    async def check_now(self) -> UpdateStatus:
        state: UpdateState = "available" if self.current.installed != self.latest else "up_to_date"
        self.current = replace(self.current, state=state, latest=self.latest, checked_at=now_iso())
        return self.current

    async def install(self, agent: Agent) -> None:
        await self._install(agent, again=False)

    async def _install(self, agent: Agent, *, again: bool, back: bool = False) -> None:
        installed = self.current.installed
        release = installed if again else self.latest
        key = "agent.update.reinstalled" if again else "agent.update.updated"
        if back and self.replaced is not None:
            release, key = self.replaced, "agent.update.went_back"
        self.current = replace(self.current, state="installing")
        agent.publish_state()
        steps = (
            (10, "agent.update.step.downloading"),
            (30, "agent.update.step.checking"),
            (50, "agent.update.step.installing"),
            (70, "agent.update.step.setting_up"),
            (85, "agent.update.step.starting_again"),
        )
        for percent, step in steps:
            await asyncio.sleep(self.step_s)
            agent.hub.publish("update.progress", progress_out(percent, step))
        await agent.go_away(self.away_s)  # the pretend restart
        self.current = UpdateStatus(
            state="available" if back else "up_to_date",
            installed=release,
            latest=self.latest,
            checked_at=now_iso(),
        )
        self.result = {"version": release, "at": now_iso(), "key": key}
        if back:
            self.replaced = None
        elif not again:
            self.replaced = installed
        agent.publish_state()

    async def run(self, agent: Agent) -> None:
        await asyncio.Event().wait()
