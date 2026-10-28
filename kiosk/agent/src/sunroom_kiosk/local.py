"""Sunroom on this computer (ADR 0038, docs/M8.md T5): the family's Sunroom as a program for this
computer's user, beside Sunroom Screen, when Welcome's On This Computer is chosen.

* **The program** is the release's server wheel (``sunroom-X.Y.Z-py3-none-any.whl``: the backend
  with the built app inside) of this Sunroom Screen's own version, installed with uv as Sunroom
  Screen is, and held to the release's constraints file so it runs the versions the image runs. A
  wheel already in the wheels folder is used first (the installers' ``--server-wheel``, to try a
  change before a release); otherwise both files come from the release, checked against its
  ``SHA256SUMS``. On Windows on ARM it runs on an x64 Python (``cryptography`` ships no ARM
  wheel).
* **Its data** is this user's: ``~/.local/share/sunroom`` on Linux, ``~/Library/Application
  Support/Sunroom`` on a Mac, ``%LOCALAPPDATA%\\Sunroom`` on Windows.
* **Its address** is port 8080, or the next free one up to 8099. Devices open
  ``http://<computer>.local:<port>`` where the computer surely answers to that name (a Mac, Linux
  with avahi), else ``http://<IP>:<port>``.
* **What keeps it running**: on Linux a systemd user service, ``sunroom.service``, kept running
  after sign-out (``loginctl enable-linger``, when that's allowed); on a Mac a LaunchAgent,
  ``app.sunroom.server``, under ``caffeinate -i`` so the Mac doesn't fall asleep while Sunroom
  runs; on Windows Sunroom Screen itself, with no window and its log beside its data, started
  again whenever it stops answering, and the computer kept awake meanwhile. A Linux screen holds a
  sleep inhibitor while it has Sunroom. Sunroom Screen announces it on the network
  (``_sunroom._tcp``), so other screens find it on any port.
* **Updates**: Sunroom Screen keeps it at its own version; This Screen's Update Sunroom Too installs
  the newest; a version that doesn't answer within five minutes is put back.
* **Removing it**: ``sunroom-kiosk sunroom remove`` (the uninstallers), the data kept unless asked.

Not on an Intel Mac: ``cryptography`` 49 and later ship no wheel for one (``supported()``).
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import os
import platform as host
import plistlib
import shutil
import socket
import subprocess
import sys
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, cast

import httpx

from sunroom_kiosk import apply as apply_step
from sunroom_kiosk import logs
from sunroom_kiosk.platform.base import (
    PlatformError,
    Progress,
    Runner,
    UnsupportedError,
    local_ip,
    run_command,
)
from sunroom_kiosk.updater import DOWNLOAD, parse, sums_from
from sunroom_kiosk.version import version

log = logs.get("local")

UNIT = "sunroom.service"
LABEL = "app.sunroom.server"
PORTS = range(8080, 8100)
KIND = "computer"
INSTALL_LIMIT_S = 1800.0  # uv downloads a Python and Sunroom's libraries the first time
ANSWERS_WITHIN_S = 300.0  # its first start makes the database: as long as the installer waits
LOG_KEEP_BYTES = 10 * 1024 * 1024
WINDOWS_ARM_PYTHON = "cpython-3.14-windows-x86_64-none"
# Windows' process flags (subprocess has them only there).
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_BREAKAWAY_FROM_JOB = 0x01000000
ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
BOOTSTRAP_TRIES = 3

DIDNT_DOWNLOAD = (
    "Sunroom didn't download. Check this computer's internet connection, then try again."
)
DIDNT_INSTALL = "Sunroom didn't install. Check this computer's internet connection, then try again."


def server_wheel(release: str) -> str:
    return f"sunroom-{release}-py3-none-any.whl"


def constraints_name(release: str) -> str:
    return f"sunroom-{release}-constraints.txt"


def port_free(port: int) -> bool:
    """Whether nothing listens on ``port`` here (a bind that's refused means something does)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind(("0.0.0.0", port))  # noqa: S104 - only to see whether it's free
        except OSError:
            return False
    return True


@dataclass(frozen=True)
class Places:
    """Where Sunroom run here keeps its things, and Sunroom Screen its notes about it."""

    data: Path  # Sunroom's DATA_DIR: the family's database, backups and photos
    log: Path  # its log on a Mac and on Windows (Linux has the journal)
    wheels: Path  # the wheels Sunroom Screen keeps: its own, and Sunroom's
    state: Path  # what Sunroom Screen remembers: the port, the address, the version
    unit: Path  # Linux: the user service's file
    launch_agent: Path  # a Mac: the LaunchAgent's file
    pid: Path  # Windows: the running program's process id
    bin: Path  # where uv puts the ``sunroom`` command

    @classmethod
    def default(
        cls,
        system: str = sys.platform,
        environ: Mapping[str, str] = os.environ,
        home: Path | None = None,
    ) -> Places:
        home = home or Path.home()
        unit = home / ".config" / "systemd" / "user" / UNIT
        launch_agent = home / "Library" / "LaunchAgents" / f"{LABEL}.plist"
        if system == "win32":  # the agent's own folder beside Sunroom's (apply.Paths)
            local = Path(environ.get("LOCALAPPDATA", str(home)))
            agent = local / "sunroom-kiosk"
            data = local / "Sunroom"
            return cls(
                data=data,
                log=data / "sunroom.log",
                wheels=agent / "wheels",
                state=agent / "sunroom.json",
                unit=unit,
                launch_agent=launch_agent,
                pid=agent / "sunroom.pid",
                bin=home / ".local" / "bin",
            )
        state = home / ".local" / "state" / "sunroom-kiosk"
        if system == "darwin":
            data = home / "Library" / "Application Support" / "Sunroom"
            log_file = home / "Library" / "Logs" / "sunroom.log"
        else:
            data = Path(environ.get("XDG_DATA_HOME") or home / ".local" / "share") / "sunroom"
            log_file = state / "sunroom.log"  # unused: the journal has it
        return cls(
            data=data,
            log=log_file,
            wheels=home / ".local" / "share" / "sunroom-kiosk" / "wheels",
            state=state / "sunroom.json",
            unit=unit,
            launch_agent=launch_agent,
            pid=state / "sunroom.pid",
            bin=home / ".local" / "bin",
        )


# ---------------------------------------------------------------------- what keeps it running


class Service(Protocol):
    """What starts Sunroom run here and keeps it running, on this kind of computer."""

    def present(self) -> bool: ...
    async def install(self, command: list[str], environment: dict[str, str]) -> None: ...
    async def restart(self) -> None: ...
    async def stop(self) -> None: ...
    async def remove(self) -> None: ...


def _unit_value(text: str) -> str:
    """A value for a unit's ``Environment=``: quoted, with systemd's specifiers left alone."""
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%") + '"'


def unit_text(command: list[str], environment: dict[str, str]) -> str:
    lines = [
        f"# Sunroom on this computer (ADR 0038), written by Sunroom Screen {version()}.",
        "# Its log: journalctl --user -u sunroom",
        "",
        "[Unit]",
        "Description=Sunroom (the family's calendar, on this computer)",
        "After=network-online.target",
        "",
        "[Service]",
        "Type=simple",
        "ExecStart=" + " ".join(_unit_value(part) for part in command),
        *(f"Environment={_unit_value(f'{key}={value}')}" for key, value in environment.items()),
        "Restart=on-failure",
        "RestartSec=3",
        # A wrong setting, a data folder it can't use, an unknown or failed migration: starting
        # again won't help, and its log says why.
        "RestartPreventExitStatus=65 70 73 78",
        "TimeoutStopSec=20",
        "",
        "[Install]",
        "WantedBy=default.target",
        "",
    ]
    return "\n".join(lines)


class SystemdService:
    """Linux: a systemd user service, started with the user's session and, with lingering,
    from the computer's start."""

    def __init__(self, runner: Runner, places: Places) -> None:
        self.run = runner
        self.places = places

    def present(self) -> bool:
        return self.places.unit.is_file()

    async def _systemctl(self, *args: str) -> bool:
        result = await self.run(["systemctl", "--user", *args])
        if not result.ok:
            log.info("systemctl --user %s didn't work: %s", args[0], result.first_line())
        return result.ok

    async def install(self, command: list[str], environment: dict[str, str]) -> None:
        self.places.unit.parent.mkdir(parents=True, exist_ok=True)
        self.places.unit.write_text(unit_text(command, environment), encoding="utf-8")
        await self._systemctl("daemon-reload")
        await self._systemctl("enable", UNIT)
        if not await self._systemctl("restart", UNIT):
            raise PlatformError("Sunroom didn't start. Restart this computer, then try again.")
        # Kept running after sign-out and from the computer's start; a desktop that doesn't
        # allow it still runs Sunroom while someone is signed in.
        linger = await self.run(["loginctl", "enable-linger"])
        if not linger.ok:
            log.info("Sunroom runs while someone is signed in (no lingering here).")

    async def restart(self) -> None:
        await self._systemctl("restart", UNIT)

    async def stop(self) -> None:
        await self._systemctl("stop", UNIT)

    async def remove(self) -> None:
        await self._systemctl("disable", "--now", UNIT)
        self.places.unit.unlink(missing_ok=True)
        await self._systemctl("daemon-reload")


def launch_agent_plist(command: list[str], environment: dict[str, str], places: Places) -> bytes:
    document: dict[str, Any] = {
        "Label": LABEL,
        # caffeinate -i keeps the Mac from idle sleep while Sunroom runs; the display still sleeps.
        "ProgramArguments": ["/usr/bin/caffeinate", "-i", *command],
        "EnvironmentVariables": environment,
        "WorkingDirectory": str(places.data),
        "RunAtLoad": True,
        "KeepAlive": {"SuccessfulExit": False},
        "ThrottleInterval": 5,
        "StandardOutPath": str(places.log),
        "StandardErrorPath": str(places.log),
    }
    return plistlib.dumps(document)


class LaunchdService:
    """A Mac: a LaunchAgent, started at sign-in and again if it fails."""

    def __init__(self, runner: Runner, places: Places, uid: int | None = None) -> None:
        self.run = runner
        self.places = places
        self.uid = uid if uid is not None else (os.getuid() if hasattr(os, "getuid") else 0)

    @property
    def domain(self) -> str:
        return f"gui/{self.uid}"

    def present(self) -> bool:
        return self.places.launch_agent.is_file()

    async def install(self, command: list[str], environment: dict[str, str]) -> None:
        self.places.launch_agent.parent.mkdir(parents=True, exist_ok=True)
        self.places.log.parent.mkdir(parents=True, exist_ok=True)
        self.places.data.mkdir(mode=0o700, parents=True, exist_ok=True)
        _trim(self.places.log)
        self.places.launch_agent.write_bytes(launch_agent_plist(command, environment, self.places))
        await self.run(["launchctl", "bootout", f"{self.domain}/{LABEL}"])  # not loaded: fine
        for attempt in range(BOOTSTRAP_TRIES):  # launchd may still be letting the old one go
            result = await self.run(
                ["launchctl", "bootstrap", self.domain, str(self.places.launch_agent)]
            )
            if result.ok:
                return
            log.info("launchctl bootstrap didn't work: %s", result.first_line())
            if attempt + 1 < BOOTSTRAP_TRIES:
                await asyncio.sleep(1)
        raise PlatformError("Sunroom didn't start. Restart this Mac, then try again.")

    async def restart(self) -> None:
        await self.run(["launchctl", "kickstart", "-k", f"{self.domain}/{LABEL}"])

    async def stop(self) -> None:
        await self.run(["launchctl", "bootout", f"{self.domain}/{LABEL}"])

    async def remove(self) -> None:
        await self.stop()
        self.places.launch_agent.unlink(missing_ok=True)


type Popen = Callable[..., Any]


class WindowsService:
    """Windows: Sunroom Screen starts it, with no window and its log beside its data, and starts
    it again whenever it stops answering (``LocalSunroom.ensure_running``). It runs on after
    Sunroom Screen quits, until the computer signs out."""

    def __init__(self, runner: Runner, places: Places, popen: Popen = subprocess.Popen) -> None:
        self.run = runner
        self.places = places
        self.popen = popen
        self.command: list[str] = []
        self.environment: dict[str, str] = {}

    def present(self) -> bool:
        return self.places.state.is_file()

    async def install(self, command: list[str], environment: dict[str, str]) -> None:
        self.command, self.environment = command, environment
        await self.stop()
        self.start()

    def start(self) -> None:
        if not self.command:
            return
        self.places.data.mkdir(parents=True, exist_ok=True)
        _trim(self.places.log)
        flags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        with self.places.log.open("ab") as output:
            for extra in (CREATE_BREAKAWAY_FROM_JOB, 0):  # out of the launcher's job, if it lets go
                try:
                    process = self.popen(
                        self.command,
                        env={**os.environ, **self.environment},
                        cwd=str(self.places.data),
                        stdin=subprocess.DEVNULL,
                        stdout=output,
                        stderr=subprocess.STDOUT,
                        creationflags=flags | extra,
                    )
                except OSError:
                    continue
                self.places.pid.parent.mkdir(parents=True, exist_ok=True)
                self.places.pid.write_text(str(process.pid), encoding="utf-8")
                return
        raise PlatformError("Sunroom didn't start. Restart this computer, then try again.")

    async def restart(self) -> None:
        await self.stop()
        self.start()

    async def stop(self) -> None:
        try:
            pid = int(self.places.pid.read_text(encoding="utf-8").strip())
        except OSError, ValueError:
            return
        # The command is uv's launcher with Python under it: the whole tree goes.
        await self.run(["taskkill", "/PID", str(pid), "/T", "/F"])
        self.places.pid.unlink(missing_ok=True)

    async def remove(self) -> None:
        await self.stop()


def _trim(path: Path) -> None:
    """Start a log afresh once it's grown past 10 MB (the last one kept beside it)."""
    with contextlib.suppress(OSError):
        if path.stat().st_size > LOG_KEEP_BYTES:
            os.replace(path, path.with_suffix(path.suffix + ".1"))


# ---------------------------------------------------------------------- Sunroom run here


class LocalSunroom:
    def __init__(
        self,
        *,
        runner: Runner = run_command,
        http: Callable[[], httpx.AsyncClient] | None = None,
        places: Places | None = None,
        system: str = sys.platform,
        machine: str | None = None,
        release: str | None = None,
        uv: str | None = None,
        service: Service | None = None,
        hostname: Callable[[], str] = socket.gethostname,
        ip: Callable[[], str | None] = local_ip,
        free: Callable[[int], bool] = port_free,
    ) -> None:
        self.run = runner
        self.http = http or (
            lambda: httpx.AsyncClient(
                timeout=httpx.Timeout(60.0, connect=10.0),
                headers={"User-Agent": f"sunroom-kiosk/{version()}"},
                follow_redirects=True,
            )
        )
        self.system = system
        self.places = places or Places.default(system)
        self.machine = (machine if machine is not None else host.machine()).lower()
        self.release = release or version()
        self.uv = uv or apply_step.uv()
        self.service = service or self._service()
        self.hostname = hostname
        self.ip = ip
        self.free = free
        self._awake: asyncio.subprocess.Process | None = None
        self._zeroconf: Any = None

    def _service(self) -> Service:
        if self.system == "win32":
            return WindowsService(self.run, self.places)
        if self.system == "darwin":
            return LaunchdService(self.run, self.places)
        return SystemdService(self.run, self.places)

    # ------------------------------------------------------------------ what it is

    def supported(self) -> bool:
        """Whether Sunroom can run on this computer: 64-bit Linux, a Mac with Apple silicon,
        Windows on x64 or ARM (an x64 Python there), and a release version to install."""
        if parse(self.release) is None:
            return False
        if self.system == "darwin":
            return self.machine == "arm64"  # no cryptography wheel for an Intel Mac
        if self.system == "win32":
            return self.machine in ("amd64", "x86_64", "arm64")
        return self.machine in ("x86_64", "amd64", "aarch64", "arm64")

    def installed(self) -> bool:
        return self.places.state.is_file() and self.service.present()

    def remembered(self) -> dict[str, Any]:
        try:
            saved = json.loads(self.places.state.read_text(encoding="utf-8"))
        except OSError, ValueError:
            return {}
        return cast(dict[str, Any], saved) if isinstance(saved, dict) else {}

    def _remember(self, **values: Any) -> None:
        merged = {**self.remembered(), **values}
        self.places.state.parent.mkdir(parents=True, exist_ok=True)
        self.places.state.write_text(json.dumps(merged, sort_keys=True), encoding="utf-8")

    @property
    def url(self) -> str | None:
        port = self.remembered().get("port")
        return f"http://localhost:{port}" if isinstance(port, int) else None

    def command(self) -> list[str]:
        name = "sunroom.exe" if self.system == "win32" else "sunroom"
        return [str(self.places.bin / name), "serve", "--host", "0.0.0.0"]  # noqa: S104 - phones

    def environment(self, port: int, advertised: str) -> dict[str, str]:
        return {
            "DATA_DIR": str(self.places.data),
            "PORT": str(port),
            "SUNROOM_INSTALL_KIND": KIND,
            "SUNROOM_ADVERTISED_URL": advertised,
        }

    def _port(self) -> int:
        kept = self.remembered().get("port")
        if isinstance(kept, int):
            return kept
        for port in PORTS:
            if self.free(port):
                return port
        raise PlatformError(
            "Every port from 8080 to 8099 is in use on this computer. Close a program that uses "
            "one, then try again."
        )

    async def advertised(self, port: int) -> str:
        """The address devices open: a name the computer surely answers to, else its IP."""
        if self.system == "darwin":
            found = await self.run(["scutil", "--get", "LocalHostName"])
            if found.ok and found.first_line():
                return f"http://{found.first_line()}.local:{port}"
        elif self.system != "win32":
            avahi = await self.run(["systemctl", "is-active", "--quiet", "avahi-daemon"])
            if avahi.ok:
                return f"http://{self.hostname().split('.')[0]}.local:{port}"
        address = self.ip()
        return f"http://{address or self.hostname()}:{port}"

    # ------------------------------------------------------------------ the program

    async def fetch(
        self, release: str, progress: Progress | None = None
    ) -> tuple[Path, Path | None]:
        """The server wheel of ``release`` and its constraints: a copy already kept here first,
        else the release's own, each checked against its SHA256SUMS."""
        wheel = self.places.wheels / server_wheel(release)
        constraints = self.places.wheels / constraints_name(release)
        if wheel.is_file():
            log.info("Using the Sunroom %s kept on this computer.", release)
            return wheel, constraints if constraints.is_file() else None
        try:
            async with self.http() as client:
                answer = await client.get(f"{DOWNLOAD}/v{release}/SHA256SUMS")
                if answer.status_code == 404:
                    raise PlatformError(
                        "This version of Sunroom isn't published yet. Try again in a while."
                    )
                answer.raise_for_status()
                sums = sums_from(answer.text)
                if server_wheel(release) not in sums:
                    raise PlatformError(
                        "This version of Sunroom isn't published yet. Try again in a while."
                    )
                await self._download(client, release, server_wheel(release), sums, progress)
                if constraints_name(release) in sums:
                    await self._download(client, release, constraints_name(release), sums, None)
        except httpx.HTTPError as error:
            log.info("Sunroom %s didn't download: %s.", release, type(error).__name__)
            raise PlatformError(DIDNT_DOWNLOAD) from error
        return wheel, constraints if constraints.is_file() else None

    async def _download(
        self,
        client: httpx.AsyncClient,
        release: str,
        name: str,
        sums: dict[str, str],
        progress: Progress | None,
    ) -> None:
        digest = hashlib.sha256()
        chunks: list[bytes] = []
        received = 0
        said = -1
        async with client.stream("GET", f"{DOWNLOAD}/v{release}/{name}") as response:
            response.raise_for_status()
            total = int(response.headers.get("content-length") or 0)
            async for chunk in response.aiter_bytes():
                digest.update(chunk)
                chunks.append(chunk)
                received += len(chunk)
                if progress is not None and total:
                    percent = 5 + 50 * received // total
                    if percent != said:
                        said = percent
                        await progress(percent, "Downloading Sunroom…")
        if digest.hexdigest() != sums[name]:
            raise PlatformError(
                "The download of Sunroom didn't match its checksum, so it wasn't installed. "
                "Try again."
            )
        await asyncio.to_thread(self._keep, name, b"".join(chunks))

    def _keep(self, name: str, data: bytes) -> None:
        self.places.wheels.mkdir(parents=True, exist_ok=True)
        path = self.places.wheels / name
        partial = path.with_name(name + ".partial")
        partial.write_bytes(data)
        os.replace(partial, path)

    def python(self) -> str:
        """The Python uv runs Sunroom on: 3.14, an x64 one on Windows on ARM."""
        if self.system == "win32" and self.machine == "arm64":
            return WINDOWS_ARM_PYTHON
        return "3.14"

    async def install(self, wheel: Path, constraints: Path | None) -> None:
        argv = [self.uv, "tool", "install", "--reinstall", "--force", "--python", self.python()]
        if constraints is not None:
            argv += ["--constraints", str(constraints)]
        argv.append(str(wheel))
        result = await self.run(argv, limit=INSTALL_LIMIT_S)
        if not result.ok:
            log.info("uv didn't install Sunroom: %s", result.first_line())
            raise PlatformError(DIDNT_INSTALL)

    # ------------------------------------------------------------------ running it

    async def run_here(self, progress: Progress) -> str:
        """Set Sunroom up on this computer and start it; its address here. The agent then waits
        for it to answer and shows it (state.run_sunroom)."""
        if not self.supported():
            raise UnsupportedError("Running Sunroom here")
        release = self.release
        await progress(5, "Downloading Sunroom…")
        wheel, constraints = await self.fetch(release, progress)
        await progress(60, "Installing Sunroom…")
        if self.system == "win32":
            await self.service.stop()  # Windows locks a running program's files
        await self.install(wheel, constraints)
        port = self._port()
        address = await self.advertised(port)
        self._remember(port=port, advertised=address, release=release)
        await progress(88, "Starting Sunroom…")
        await self.service.install(self.command(), self.environment(port, address))
        log.info("Sunroom %s runs on this computer, on port %d.", release, port)
        return f"http://localhost:{port}"

    async def answers_as(self, release: str, within_s: float = ANSWERS_WITHIN_S) -> bool:
        """Whether Sunroom here answers within ``within_s`` seconds, as ``release``."""
        url = self.url
        if url is None:
            return False
        deadline = time.monotonic() + within_s
        while time.monotonic() < deadline:
            try:
                async with self.http() as client:
                    answer = (await client.get(f"{url}/api/version")).json()
                if (
                    isinstance(answer, dict)
                    and cast(dict[str, Any], answer).get("version") == release
                ):
                    return True
            except httpx.HTTPError, ValueError:
                pass
            await asyncio.sleep(2)
        return False

    async def update(self, release: str) -> bool:
        """Sunroom here at ``release``, kept only if it answers as that within five minutes;
        otherwise the version before it is put back."""
        if not self.installed():
            return False
        before = self.remembered().get("release")
        try:
            wheel, constraints = await self.fetch(release)
        except PlatformError as error:
            log.info("Sunroom %s didn't download: %s", release, error)
            return False
        log.info("Updating Sunroom on this computer to %s.", release)
        if await self._swap(wheel, constraints) and await self.answers_as(release):
            self._remember(release=release)
            return True
        log.info("Sunroom %s didn't answer; putting %s back.", release, before)
        if isinstance(before, str):
            kept = self.places.wheels / server_wheel(before)
            if kept.is_file():
                again = self.places.wheels / constraints_name(before)
                await self._swap(kept, again if again.is_file() else None)
        return False

    def _prime(self) -> None:
        """Windows: what the service starts, from what was remembered (Sunroom Screen may have
        started again since the run that set it)."""
        settings = self.remembered()
        port, address = settings.get("port"), settings.get("advertised")
        if isinstance(self.service, WindowsService) and isinstance(port, int):
            self.service.command = self.command()
            self.service.environment = self.environment(
                port, address if isinstance(address, str) else f"http://localhost:{port}"
            )

    async def _swap(self, wheel: Path, constraints: Path | None) -> bool:
        self._prime()
        if self.system == "win32":
            await self.service.stop()
        try:
            await self.install(wheel, constraints)
        except PlatformError:
            if self.system == "win32":
                await self.service.restart()
            return False
        await self.service.restart()
        return True

    async def ensure_running(self) -> None:
        """Windows: start it again when it stopped (nothing else keeps it running there)."""
        if self.system == "win32" and self.installed() and isinstance(self.service, WindowsService):
            self._prime()
            if self.service.command:
                log.info("Starting Sunroom on this computer again.")
                await self.service.restart()

    async def keep_awake(self) -> None:
        """While Sunroom runs here the computer stays awake: Windows by Sunroom Screen's own
        request, Linux through a sleep inhibitor it holds (a Mac's LaunchAgent has caffeinate)."""
        if self.system == "win32":
            if sys.platform == "win32":
                import ctypes

                ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
            return
        if (
            self.system == "darwin"
            or self._awake is not None
            or not shutil.which("systemd-inhibit")
        ):
            return
        with contextlib.suppress(OSError):
            self._awake = await asyncio.create_subprocess_exec(
                "systemd-inhibit",
                "--what=sleep",
                "--who=Sunroom",
                "--why=Sunroom keeps the family's calendar on this computer",
                "--mode=block",
                "sleep",
                "infinity",
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
        await asyncio.sleep(1)
        if self._awake is not None and self._awake.returncode is not None:
            # The desktop said no (its policy for a service that isn't a signed-in session).
            self._awake = None
            log.info(
                "This computer may go to sleep while Sunroom runs here: turn off automatic "
                "suspend in its power settings, so your devices can reach Sunroom at night."
            )

    async def announce(self) -> None:
        """Tell screens on the network where it is (``_sunroom._tcp``), as an all-in-one Pi's
        avahi does, so they find it on any port."""
        settings = self.remembered()
        port, address = settings.get("port"), self.ip()
        if not isinstance(port, int) or address is None or self._zeroconf is not None:
            return
        try:
            from zeroconf import ServiceInfo
            from zeroconf.asyncio import AsyncZeroconf

            name = self.hostname().split(".")[0] or "computer"
            info = ServiceInfo(
                "_sunroom._tcp.local.",
                f"Sunroom on {name}._sunroom._tcp.local.",
                addresses=[socket.inet_aton(address)],
                port=port,
                server=f"{name}-sunroom.local.",
            )
            zeroconf = AsyncZeroconf()
            await zeroconf.async_register_service(info)  # pyright: ignore[reportUnknownMemberType]
            self._zeroconf = zeroconf
        except Exception as error:  # a network without multicast: the sweep still finds it
            log.info("Couldn't announce Sunroom on the network: %r", error)

    async def stop_helpers(self) -> None:
        """When Sunroom Screen stops: the inhibitor and the announcement go with it."""
        if self._awake is not None and self._awake.returncode is None:
            self._awake.kill()
            await self._awake.wait()
        self._awake = None
        if self._zeroconf is not None:
            with contextlib.suppress(Exception):
                await self._zeroconf.async_unregister_all_services()
                await self._zeroconf.async_close()
            self._zeroconf = None

    async def remove(self, *, delete_data: bool = False) -> list[str]:
        """Take Sunroom off this computer (the uninstallers): what was done, in plain lines."""
        said: list[str] = []
        if self.service.present() or self.places.state.is_file():
            await self.service.remove()
            said.append("Stopped Sunroom on this computer.")
        uninstalled = await self.run([self.uv, "tool", "uninstall", "sunroom"])
        if uninstalled.ok:
            said.append("Uninstalled Sunroom.")
        self.places.state.unlink(missing_ok=True)
        for kept in self.places.wheels.glob("sunroom-*"):
            kept.unlink(missing_ok=True)
        if delete_data and self.places.data.exists():
            shutil.rmtree(self.places.data, ignore_errors=True)
            said.append(f"Deleted Sunroom's data in {self.places.data}.")
        elif self.places.data.exists():
            said.append(f"Kept Sunroom's data (the family's calendar) in {self.places.data}.")
        return said
