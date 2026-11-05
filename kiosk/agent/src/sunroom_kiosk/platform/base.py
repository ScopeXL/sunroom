"""What the agent asks of the machine it runs on (docs/M7.md, "The pieces").

One adapter per kind of machine (``pi``, ``linux``, and in batch 2 ``macos`` and ``windows``),
each a thin layer over the system's own commands, and ``fake`` for tests and the e2e runs. The
base class says no to everything; an adapter overrides what its machine can do and lists it in
``capabilities()``, which is what This Screen shows buttons for.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import socket
import subprocess
import sys
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from sunroom_kiosk.policy import BrowserKind
from sunroom_kiosk.schemas import ScreenCapability, ScreenNetworkKind, ScreenPlatform, ScreenSession
from sunroom_kiosk.words import SaidError

COMMAND_TIMEOUT_S = 20.0
# Windows: the agent runs without a console (sunroom-kioskw), so a console program it starts
# (netsh every 30 s, taskkill, uv) would get a console window of its own, flashed on the wall.
NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


@dataclass(frozen=True)
class CommandResult:
    code: int
    output: str  # stderr then stdout, trimmed

    @property
    def ok(self) -> bool:
        return self.code == 0

    def first_line(self) -> str:
        return next((line.strip() for line in self.output.splitlines() if line.strip()), "")


class Runner(Protocol):
    async def __call__(
        self, argv: Sequence[str], *, limit: float = COMMAND_TIMEOUT_S, stdin: str | None = None
    ) -> CommandResult: ...


async def run_command(
    argv: Sequence[str], *, limit: float = COMMAND_TIMEOUT_S, stdin: str | None = None
) -> CommandResult:
    """Run a command without a shell: its exit status (127: not installed, 124: too slow) and
    what it printed."""
    try:
        process = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            creationflags=NO_WINDOW,
        )
    except FileNotFoundError:
        return CommandResult(127, f"{argv[0]} isn't installed")
    except OSError as error:
        return CommandResult(126, str(error.strerror or error))
    try:
        out, err = await asyncio.wait_for(
            process.communicate(stdin.encode() if stdin is not None else None), limit
        )
    except TimeoutError:
        process.kill()
        await process.wait()
        return CommandResult(124, f"it took longer than {limit:g} s")
    printed = [
        part.decode(errors="replace").strip() for part in (err, out) if part and part.strip()
    ]
    return CommandResult(process.returncode or 0, "\n".join(printed))


async def spawn_detached(argv: list[str], *, unit: str) -> bool:
    """Start ``argv`` so it outlives this process: in a systemd unit of its own where there is
    one (stopping or restarting the agent's unit would take a child down with it), else in a
    session of its own (a process group of its own on Windows), detached."""
    if sys.platform.startswith("linux") and shutil.which("systemd-run"):
        process = await asyncio.create_subprocess_exec(
            "systemd-run",
            "--user",
            "--collect",
            f"--unit={unit}-{int(time.time())}",
            "--",
            *argv,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        return await process.wait() == 0
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
        subprocess, "CREATE_NEW_PROCESS_GROUP", 0
    )
    try:
        subprocess.Popen(  # noqa: S603, ASYNC220 - our own command, fire and forget
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=sys.platform != "win32",
            creationflags=flags | NO_WINDOW,
        )
    except OSError:
        return False
    return True


type Spawn = Callable[..., Awaitable[bool]]

# Where install.sh leaves its uninstaller (Linux and macOS), which This Screen's Uninstall runs.
UNINSTALLER = Path.home() / ".local" / "share" / "sunroom-kiosk" / "uninstall.sh"
UNINSTALL_UNIT = "sunroom-kiosk-uninstall"


def uninstaller_command(script: Path, *, sunroom: bool) -> list[str]:
    """uninstall.sh as the screen runs it (ADR 0042): no questions, the root steps through the
    root helper, and Sunroom run here with the family's data when asked (never an all-in-one
    Pi's Docker Sunroom, the family's server)."""
    argv = ["bash", str(script), "--yes", "--from-screen"]
    return [*argv, "--purge-local"] if sunroom else argv


class PlatformError(SaidError):
    """A device action that didn't work, said for the family: a key from lang/en.json and its
    values (``str(error)`` is the English), plain words, no codes."""


class UnsupportedError(PlatformError):
    """What this machine can't do: ``agent.unsupported.restart`` and the like."""

    def __init__(self, key: str = "agent.unsupported.that") -> None:
        super().__init__(key)


@dataclass(frozen=True)
class SystemReport:
    """What the root helper's ``apply-system`` did with an update's system part (ADR 0044)."""

    changed: list[str]
    failed: list[str]
    needs_reboot: bool


@dataclass(frozen=True)
class NetworkStatus:
    kind: ScreenNetworkKind
    ssid: str | None = None
    ip: str | None = None
    strength: int | None = None


@dataclass(frozen=True)
class WifiNetwork:
    id: str | None  # a saved connection's own name, for Forget
    ssid: str
    strength: int
    secured: bool
    connected: bool
    saved: bool


# A long action's progress: its percent, and its step's key (``agent.local.step.downloading``).
type Progress = Callable[[int, str], Awaitable[None]]


def user_id() -> str:
    """This user's numeric id (for pgrep, pkill and the runtime folder); Windows has none."""
    if sys.platform == "win32":
        return "0"
    return str(os.getuid())


def local_ip() -> str | None:
    """This machine's address on its network: the one a packet to a public address would leave
    from. Nothing is sent (a UDP socket only picks its route)."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("192.0.2.1", 9))  # TEST-NET-1: never answered, never sent
        address = probe.getsockname()[0]
    except OSError:
        return None
    finally:
        probe.close()
    return str(address) if address and not address.startswith("0.") else None


class Platform:
    """The defaults: a machine that can do nothing but run the browser."""

    def __init__(self, runner: Runner = run_command, root: Path = Path("/")) -> None:
        self.run = runner
        self.root = root

    # ------------------------------------------------------------------ what it is

    @property
    def name(self) -> ScreenPlatform:
        return "linux"

    @property
    def session(self) -> ScreenSession:
        return "desktop"

    @property
    def model(self) -> str:
        return "Computer"

    @property
    def system(self) -> str:
        return "Unknown system"

    def hostname(self) -> str:
        return socket.gethostname()

    def capabilities(self) -> list[ScreenCapability]:
        return []

    # ------------------------------------------------------------------ the machine

    async def restart(self) -> None:
        raise UnsupportedError("agent.unsupported.restart")

    async def shutdown(self) -> None:
        raise UnsupportedError("agent.unsupported.shutdown")

    # ------------------------------------------------------------------ the network

    async def network(self) -> NetworkStatus:
        ip = local_ip()
        return NetworkStatus(kind="wired" if ip else "none", ip=ip)

    async def wifi_networks(self) -> list[WifiNetwork]:
        raise UnsupportedError("agent.unsupported.wifi")

    async def wifi_join(self, ssid: str, password: str) -> None:
        raise UnsupportedError("agent.unsupported.wifi")

    async def wifi_forget(self, network_id: str) -> None:
        raise UnsupportedError("agent.unsupported.wifi")

    # ------------------------------------------------------------------ the screen

    async def rotate(self, rotation: int, output: str) -> None:
        """Turn the picture on the screen connected at ``output`` (HDMI-A-1), and touch with it."""
        raise UnsupportedError("agent.unsupported.rotate")

    # ------------------------------------------------------------------ before the browser

    async def wait_for_desktop(self) -> None:
        """Until there's a desktop for the browser to draw on (nothing to wait for, here)."""

    async def wait_for_clock(self) -> None:
        """Until the clock is right (a Pi has no clock of its own)."""

    async def prepare_session(self, rotation: int, output: str) -> None:
        """What the desktop needs before the browser opens: no blanking, the picture turned."""

    # ------------------------------------------------------------------ privileged files

    async def write_policy(self, kind: BrowserKind, document: dict[str, Any]) -> bool:
        """Write the browser's policy (policy.py) where that browser reads it: a file on Linux,
        its preferences on macOS, the registry on Windows. False when this machine doesn't let
        the agent write it (the installer wrote it, or the browser asks once, on the screen)."""
        return False

    async def remove_policy(self, kind: BrowserKind) -> bool:
        """Take Sunroom Screen's policy out of that browser's again (the uninstaller asks).
        False when it isn't the agent's to take out here (on Linux the uninstaller does it)."""
        return False

    async def update_sunroom(self) -> bool:
        """Update the Sunroom that runs on this machine (an all-in-one Pi)."""
        return False

    def sunroom_update_outcome(self) -> list[str]:
        """How the last update of an all-in-one Pi's Sunroom ended (update.sh's last-update):
        ["went-back", new, old], ["left-alone", version], ["updated", version] or ["failed"]."""
        return []

    def sunroom_pinned(self) -> str | None:
        """The version an all-in-one Pi's own Sunroom is pinned to, if the family pinned one."""
        return None

    # ------------------------------------------------------------------ the system's part

    async def root_helper_version(self) -> str | None:
        """The root helper's version (ADR 0044); None with no helper, or with one from before
        0.18.0, which can't say."""
        return None

    async def apply_system(self, wheel: Path) -> SystemReport | None:
        """An update's system part, from a wheel the root helper checks against the release's
        checksums itself; None where there's none (a Mac and Windows have no system part), or
        when it couldn't."""
        return None

    def install_command(self) -> str | None:
        """The installer's one line for this computer, for a screen whose root helper can't
        finish an update (This Screen shows it under Software); None with no system part."""
        return None

    async def uninstall(self, *, sunroom: bool, port: int) -> None:
        """Start Sunroom Screen's uninstaller as a process of its own, which outlives the agent
        (This Screen's Uninstall, ADR 0042); ``sunroom`` takes Sunroom run here and the family's
        data with it. The agent quits right after."""
        raise UnsupportedError("agent.unsupported.uninstall")

    async def run_sunroom(self, progress: Progress) -> str:
        """Start Sunroom on this machine; returns its address. Only the pretend machine does it
        itself (``--fake``): a real one runs Sunroom as a program, through local.py."""
        raise UnsupportedError("agent.unsupported.run_sunroom")

    def environment(self) -> dict[str, str]:
        """What the browser is started with: this process's environment."""
        return dict(os.environ)
