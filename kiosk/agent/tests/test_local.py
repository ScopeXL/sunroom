"""Sunroom run on this computer (local.py, ADR 0038): where it keeps things on each system, which
computers can run it, its address, the checked download, uv's command, each system's service, a
run end to end, an update that goes back and brings the database with it, removal, and the agent
choosing it over the platform and bringing it up to its own version.
Commands are scripted and downloads answered by a pretend GitHub; nothing real runs. Synthetic
data only."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import plistlib
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from sunroom_kiosk import local as local_module
from sunroom_kiosk import state as state_module
from sunroom_kiosk.config import Config
from sunroom_kiosk.local import (
    LABEL,
    UNIT,
    LaunchdService,
    LocalSunroom,
    Places,
    Service,
    SystemdService,
    WindowsService,
    constraints_name,
    database_revision,
    server_wheel,
    unit_text,
)
from sunroom_kiosk.platform.base import CommandResult, PlatformError
from sunroom_kiosk.platform.fake import FakePlatform
from sunroom_kiosk.state import Agent
from sunroom_kiosk.version import version
from tests.support import Shell, ok

RELEASE = "0.15.0"
WHEEL = b"a pretend server wheel"
CONSTRAINTS = b"cryptography==50.0.2\n"
EVERYWHERE = "0.0.0.0"  # noqa: S104 - where the program listens, for phones


def places(tmp_path: Path, system: str = "linux") -> Places:
    return Places.default(system, {"LOCALAPPDATA": str(tmp_path / "AppData")}, home=tmp_path)


def github(
    files: dict[str, bytes], *, sums: dict[str, str] | None = None, status: int = 200
) -> Callable[[], httpx.AsyncClient]:
    """A pretend Releases download: SHA256SUMS for ``files`` (or ``sums``), then the files."""
    listed = (
        sums
        if sums is not None
        else {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}
    )

    def answer(request: httpx.Request) -> httpx.Response:
        name = request.url.path.rsplit("/", 1)[-1]
        assert request.url.path.startswith(f"/ScopeXL/sunroom/releases/download/v{RELEASE}/")
        if status != 200:
            return httpx.Response(status)
        if name == "SHA256SUMS":
            text = "".join(f"{digest}  {file}\n" for file, digest in listed.items())
            return httpx.Response(200, text=text)
        if name in files:
            return httpx.Response(200, content=files[name])
        return httpx.Response(404)

    return lambda: httpx.AsyncClient(
        transport=httpx.MockTransport(answer), base_url="https://github.com"
    )


def sunroom(
    tmp_path: Path,
    shell: Shell,
    *,
    system: str = "linux",
    machine: str = "x86_64",
    service: Service | None = None,
    http: Callable[[], httpx.AsyncClient] | None = None,
    free: Callable[[int], bool] = lambda port: True,
) -> LocalSunroom:
    return LocalSunroom(
        runner=shell,
        http=http or github({}),
        places=places(tmp_path, system),
        system=system,
        machine=machine,
        release=RELEASE,
        uv="/home/ana/.local/bin/uv",
        service=service,
        hostname=lambda: "kitchen",
        ip=lambda: "192.168.1.30",
        free=free,
    )


async def no_progress(percent: int, step: str) -> None:
    return None


# ---------------------------------------------------------------------- where and which


def test_each_system_keeps_sunroom_in_its_own_place(tmp_path: Path) -> None:
    linux = Places.default("linux", {}, home=tmp_path)
    assert linux.data == tmp_path / ".local" / "share" / "sunroom"
    assert linux.unit == tmp_path / ".config" / "systemd" / "user" / "sunroom.service"
    moved = Places.default("linux", {"XDG_DATA_HOME": str(tmp_path / "data")}, home=tmp_path)
    assert moved.data == tmp_path / "data" / "sunroom"
    mac = Places.default("darwin", {}, home=tmp_path)
    assert mac.data == tmp_path / "Library" / "Application Support" / "Sunroom"
    assert mac.launch_agent == tmp_path / "Library" / "LaunchAgents" / "app.sunroom.server.plist"
    assert mac.log == tmp_path / "Library" / "Logs" / "sunroom.log"
    windows = Places.default("win32", {"LOCALAPPDATA": str(tmp_path / "AppData")}, home=tmp_path)
    assert windows.data == tmp_path / "AppData" / "Sunroom"
    assert windows.state == tmp_path / "AppData" / "sunroom-kiosk" / "sunroom.json"
    # Sunroom Screen's own wheels and Sunroom's sit together.
    assert linux.wheels == tmp_path / ".local" / "share" / "sunroom-kiosk" / "wheels"


@pytest.mark.parametrize(
    ("system", "machine", "can"),
    [
        ("linux", "x86_64", True),
        ("linux", "aarch64", True),  # a Pi with 64-bit Raspberry Pi OS
        ("linux", "armv7l", False),
        ("darwin", "arm64", True),
        ("darwin", "x86_64", False),  # an Intel Mac: no cryptography wheel since 49
        ("win32", "AMD64", True),
        ("win32", "ARM64", True),  # on an x64 Python
    ],
)
def test_which_computers_can_run_sunroom(
    tmp_path: Path, system: str, machine: str, can: bool
) -> None:
    assert sunroom(tmp_path, Shell(), system=system, machine=machine).supported() is can


def test_a_checkout_with_no_release_version_cant(tmp_path: Path) -> None:
    here = sunroom(tmp_path, Shell())
    here.release = "0.0.0-dev"
    assert not here.supported()


async def test_phones_get_a_name_where_its_sure_and_the_ip_elsewhere(tmp_path: Path) -> None:
    mac = Shell(answers={"scutil --get LocalHostName": ok("Sample-Mac")})
    assert await sunroom(tmp_path, mac, system="darwin").advertised(7867) == (
        "http://Sample-Mac.local:7867"
    )
    avahi = Shell()  # systemctl is-active avahi-daemon: yes
    assert await sunroom(tmp_path, avahi).advertised(7868) == "http://kitchen.local:7868"
    no_avahi = Shell(answers={"systemctl is-active": CommandResult(3, "inactive")})
    assert await sunroom(tmp_path, no_avahi).advertised(7867) == "http://192.168.1.30:7867"
    windows = Shell()
    assert await sunroom(tmp_path, windows, system="win32", machine="AMD64").advertised(7867) == (
        "http://192.168.1.30:7867"
    )
    assert windows.calls == []


def test_the_port_is_7867_or_the_next_free_one(tmp_path: Path) -> None:
    taken = {7867, 7868}
    here = sunroom(tmp_path, Shell(), free=lambda port: port not in taken)
    assert here._port() == 7869  # pyright: ignore[reportPrivateUsage]
    here._remember(port=7877)  # pyright: ignore[reportPrivateUsage]
    assert here._port() == 7877  # pyright: ignore[reportPrivateUsage] - kept, even if busy
    full = sunroom(tmp_path / "full", Shell(), free=lambda port: False)
    with pytest.raises(PlatformError, match=r"^Every port from 7867 to 7886 is in use"):
        full._port()  # pyright: ignore[reportPrivateUsage]


# ---------------------------------------------------------------------- the program


async def test_a_kept_wheel_comes_first(tmp_path: Path) -> None:
    here = sunroom(tmp_path, Shell(), http=github({}, status=500))  # GitHub never asked
    here.places.wheels.mkdir(parents=True)
    (here.places.wheels / server_wheel(RELEASE)).write_bytes(WHEEL)
    wheel, constraints = await here.fetch(RELEASE)
    assert wheel.read_bytes() == WHEEL and constraints is None


async def test_the_release_is_downloaded_and_checked(tmp_path: Path) -> None:
    files = {server_wheel(RELEASE): WHEEL, constraints_name(RELEASE): CONSTRAINTS}
    said: list[tuple[int, str]] = []

    async def progress(percent: int, step: str) -> None:
        said.append((percent, step))

    here = sunroom(tmp_path, Shell(), http=github(files))
    wheel, constraints = await here.fetch(RELEASE, progress)
    assert wheel.read_bytes() == WHEEL
    assert constraints is not None and constraints.read_bytes() == CONSTRAINTS
    assert said[-1] == (55, "agent.local.step.downloading")


async def test_a_download_that_doesnt_match_isnt_kept(tmp_path: Path) -> None:
    files = {server_wheel(RELEASE): WHEEL}
    wrong = {server_wheel(RELEASE): "0" * 64}
    here = sunroom(tmp_path, Shell(), http=github(files, sums=wrong))
    with pytest.raises(PlatformError, match=r"didn't match its checksum"):
        await here.fetch(RELEASE)
    assert not (here.places.wheels / server_wheel(RELEASE)).exists()


async def test_an_unpublished_release_and_no_network_are_said_plainly(tmp_path: Path) -> None:
    unpublished = sunroom(tmp_path, Shell(), http=github({}, status=404))
    with pytest.raises(PlatformError, match=r"isn't published yet"):
        await unpublished.fetch(RELEASE)

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no network", request=request)

    offline = sunroom(
        tmp_path / "offline",
        Shell(),
        http=lambda: httpx.AsyncClient(transport=httpx.MockTransport(refuse)),
    )
    with pytest.raises(PlatformError, match=r"^Sunroom didn't download\. Check this computer"):
        await offline.fetch(RELEASE)


async def test_uv_installs_it_held_to_the_releases_versions(tmp_path: Path) -> None:
    shell = Shell()
    here = sunroom(tmp_path, shell)
    await here.install(tmp_path / "sunroom.whl", tmp_path / "constraints.txt")
    assert shell.calls[-1][0] == [
        "/home/ana/.local/bin/uv",
        "tool",
        "install",
        "--reinstall",
        "--force",
        "--python",
        "3.14",
        "--constraints",
        str(tmp_path / "constraints.txt"),
        str(tmp_path / "sunroom.whl"),
    ]
    arm = Shell()
    windows = sunroom(tmp_path, arm, system="win32", machine="ARM64")
    await windows.install(tmp_path / "sunroom.whl", None)
    assert arm.calls[-1][0][5:7] == ["--python", "cpython-3.14-windows-x86_64-none"]
    refused = Shell(answers={"/home/ana/.local/bin/uv tool install": CommandResult(2, "no")})
    with pytest.raises(PlatformError, match=r"^Sunroom didn't install"):
        await sunroom(tmp_path, refused).install(tmp_path / "sunroom.whl", None)


# ---------------------------------------------------------------------- each system's service


def test_the_user_service_quotes_what_it_runs_with() -> None:
    text = unit_text(
        ["/home/ana/.local/bin/sunroom", "serve", "--host", EVERYWHERE],
        {"DATA_DIR": "/home/ana/my data", "SUNROOM_ADVERTISED_URL": "http://kitchen.local:7867"},
    )
    assert 'ExecStart="/home/ana/.local/bin/sunroom" "serve" "--host" "0.0.0.0"' in text
    assert 'Environment="DATA_DIR=/home/ana/my data"' in text
    assert "RestartPreventExitStatus=65 70 73 78" in text
    assert "WantedBy=default.target" in text
    # A percent sign is systemd's own: doubled, so it stays one.
    assert 'Environment="NAME=100%%"' in unit_text(["x"], {"NAME": "100%"})


async def test_linux_runs_it_as_a_user_service_that_outlives_the_session(tmp_path: Path) -> None:
    shell = Shell()
    service = SystemdService(shell, places(tmp_path))
    await service.install(["/home/ana/.local/bin/sunroom", "serve"], {"PORT": "7867"})
    assert service.present()
    assert shell.lines() == [
        "systemctl --user daemon-reload",
        f"systemctl --user enable {UNIT}",
        f"systemctl --user restart {UNIT}",
        "loginctl enable-linger",
    ]
    await service.remove()
    assert not service.present()
    assert shell.lines()[-2:] == [
        f"systemctl --user disable --now {UNIT}",
        "systemctl --user daemon-reload",
    ]
    broken = SystemdService(
        Shell(answers={"systemctl --user restart": CommandResult(1, "failed")}),
        places(tmp_path / "broken"),
    )
    with pytest.raises(PlatformError, match=r"^Sunroom didn't start"):
        await broken.install(["sunroom"], {})


async def test_a_mac_runs_it_as_a_launch_agent_that_keeps_it_awake(tmp_path: Path) -> None:
    shell = Shell()
    where = places(tmp_path, "darwin")
    service = LaunchdService(shell, where, uid=501)
    command = ["/Users/ana/.local/bin/sunroom", "serve", "--host", EVERYWHERE]
    await service.install(command, {"PORT": "7867", "DATA_DIR": str(where.data)})
    plist: dict[str, Any] = plistlib.loads(where.launch_agent.read_bytes())
    assert plist["Label"] == LABEL
    assert plist["ProgramArguments"] == ["/usr/bin/caffeinate", "-i", *command]
    assert plist["EnvironmentVariables"]["PORT"] == "7867"
    assert plist["KeepAlive"] == {"SuccessfulExit": False}
    assert plist["StandardOutPath"] == str(where.log)
    assert where.data.is_dir()
    assert shell.lines() == [
        f"launchctl bootout gui/501/{LABEL}",
        f"launchctl bootstrap gui/501 {where.launch_agent}",
    ]
    await service.restart()
    assert shell.lines()[-1] == f"launchctl kickstart -k gui/501/{LABEL}"
    await service.remove()
    assert not where.launch_agent.exists()


class Started:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], dict[str, Any]]] = []

    def __call__(self, command: list[str], **options: Any) -> Any:
        self.calls.append((command, options))
        return type("Process", (), {"pid": 4242})()


async def test_windows_starts_it_with_no_window_and_stops_its_whole_tree(tmp_path: Path) -> None:
    shell = Shell()
    where = places(tmp_path, "win32")
    started = Started()
    service = WindowsService(shell, where, popen=started)
    command = [str(where.bin / "sunroom.exe"), "serve", "--host", EVERYWHERE]
    await service.install(command, {"PORT": "7867"})
    ((argv, options),) = started.calls
    assert argv == command
    assert options["env"]["PORT"] == "7867"
    assert options["cwd"] == str(where.data)
    assert options["creationflags"] & local_module.DETACHED_PROCESS
    assert options["creationflags"] & local_module.CREATE_BREAKAWAY_FROM_JOB
    assert where.pid.read_text(encoding="utf-8") == "4242"
    await service.stop()
    assert shell.lines()[-1] == "taskkill /PID 4242 /T /F"
    assert not where.pid.exists()


async def test_a_mac_tries_again_while_launchd_lets_the_old_one_go(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(local_module.asyncio, "sleep", _no_wait)
    tries: list[int] = []

    class Busy(Shell):
        async def __call__(
            self, argv: Any, *, limit: float = 20.0, stdin: str | None = None, env: Any = None
        ) -> Any:
            await super().__call__(argv, limit=limit, stdin=stdin)
            if argv[1] == "bootstrap":
                tries.append(1)
                return CommandResult(5 if len(tries) < 3 else 0, "Input/output error")
            return ok()

    service = LaunchdService(Busy(), places(tmp_path, "darwin"), uid=501)
    await service.install(["sunroom", "serve"], {})
    assert len(tries) == 3


async def _no_wait(seconds: float) -> None:
    return None


# ---------------------------------------------------------------------- a run, an update, removal


async def test_a_run_here_installs_starts_and_remembers_it(tmp_path: Path) -> None:
    shell = Shell()
    here = sunroom(tmp_path, shell, http=github({server_wheel(RELEASE): WHEEL}))
    said: list[tuple[int, str]] = []

    async def progress(percent: int, step: str) -> None:
        said.append((percent, step))

    url = await here.run_here(progress)
    assert url == "http://localhost:7867"
    assert here.installed()
    assert here.remembered() == {
        "port": 7867,
        "advertised": "http://kitchen.local:7867",
        "release": RELEASE,
    }
    unit = here.places.unit.read_text(encoding="utf-8")
    data = str(here.places.data).replace("\\", "\\\\")  # a unit's quoting, for Windows' tmp_path
    assert f'Environment="DATA_DIR={data}"' in unit
    assert 'Environment="SUNROOM_INSTALL_KIND=computer"' in unit
    assert 'Environment="SUNROOM_ADVERTISED_URL=http://kitchen.local:7867"' in unit
    assert any(line.startswith("/home/ana/.local/bin/uv tool install") for line in shell.lines())
    assert [step for _, step in said] == [
        "agent.local.step.downloading",
        *["agent.local.step.downloading"] * (len(said) - 3),
        "agent.local.step.installing",
        "agent.local.step.starting",
    ]


async def test_an_intel_mac_is_told_it_cant(tmp_path: Path) -> None:
    here = sunroom(tmp_path, Shell(), system="darwin", machine="x86_64")
    with pytest.raises(PlatformError, match=r"isn't something this screen can do"):
        await here.run_here(no_progress)


async def test_an_update_that_doesnt_answer_puts_the_last_one_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shell = Shell()
    here = sunroom(tmp_path, shell, http=github({server_wheel(RELEASE): WHEEL}))
    here.places.wheels.mkdir(parents=True)
    (here.places.wheels / server_wheel("0.14.0")).write_bytes(b"the one before")
    here.places.unit.parent.mkdir(parents=True)
    here.places.unit.write_text("[Unit]\n")
    here._remember(port=7867, advertised="http://kitchen.local:7867", release="0.14.0")  # pyright: ignore[reportPrivateUsage]
    answers: list[bool] = [False]

    async def answers_as(release: str, within_s: float = 0) -> bool:
        return answers[0]

    monkeypatch.setattr(here, "answers_as", answers_as)
    assert not await here.update(RELEASE)
    installs = [line for line in shell.lines() if " tool install " in line]
    assert installs[-1].endswith(server_wheel("0.14.0"))  # put back
    assert here.remembered()["release"] == "0.14.0"
    answers[0] = True
    assert await here.update(RELEASE)
    assert here.remembered()["release"] == RELEASE


def installed_at(here: LocalSunroom, release: str) -> None:
    """Sunroom run here at ``release``, its wheel kept, and a database at revision ``aaa``."""
    here.places.wheels.mkdir(parents=True, exist_ok=True)
    (here.places.wheels / server_wheel(release)).write_bytes(b"the one before")
    here.places.unit.parent.mkdir(parents=True, exist_ok=True)
    here.places.unit.write_text("[Unit]\n")
    here._remember(port=7867, advertised="http://kitchen.local:7867", release=release)  # pyright: ignore[reportPrivateUsage]
    here.places.data.mkdir(parents=True, exist_ok=True)
    set_revision(here, "aaa")


def set_revision(here: LocalSunroom, revision: str) -> None:
    with contextlib.closing(sqlite3.connect(here.places.data / "sunroom.db")) as db:
        db.execute("CREATE TABLE IF NOT EXISTS alembic_version (version_num TEXT)")
        db.execute("DELETE FROM alembic_version")
        db.execute("INSERT INTO alembic_version VALUES (?)", (revision,))
        db.commit()


def never_answers_as(
    here: LocalSunroom,
    monkeypatch: pytest.MonkeyPatch,
    release: str,
    *,
    migrates_to: str | None = None,
) -> list[float]:
    """``release`` never answers, having moved the database on first if it says so. The waits."""
    waits: list[float] = []

    async def answers_as(asked: str, within_s: float = 0) -> bool:
        waits.append(within_s)
        if asked == release and migrates_to is not None:
            set_revision(here, migrates_to)
        return asked != release

    monkeypatch.setattr(here, "answers_as", answers_as)
    return waits


async def test_a_version_gets_longer_to_answer_on_a_pi(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    here = sunroom(tmp_path, Shell(), http=github({server_wheel(RELEASE): WHEEL}))
    installed_at(here, "0.14.0")
    waits = never_answers_as(here, monkeypatch, RELEASE)
    await here.update(RELEASE)
    assert waits[0] == local_module.ANSWERS_WITHIN_S

    here.on_a_pi = lambda: True
    waits.clear()
    await here.update(RELEASE)
    assert waits[0] == local_module.ANSWERS_WITHIN_ON_A_PI_S


async def test_a_version_that_migrated_then_failed_gets_the_database_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shell = Shell()
    here = sunroom(tmp_path, shell, http=github({server_wheel(RELEASE): WHEEL}))
    installed_at(here, "0.14.0")
    folder = here.places.data / "backups" / "pre-migrate"
    folder.mkdir(parents=True)
    copy = folder / "sunroom.aaa.20261105T010000Z.db"
    copy.write_bytes(b"the database before")
    (folder / "sunroom.aaa.20261106T010000Z.partial.db").write_bytes(b"half of a copy")
    (folder / "sunroom.zzz.20261107T010000Z.db").write_bytes(b"a copy from another revision")
    never_answers_as(here, monkeypatch, RELEASE, migrates_to="bbb")

    assert not await here.update(RELEASE)

    lines = shell.lines()
    restore = f"{here.places.bin / 'sunroom'} restore {copy}"
    assert restore in lines
    assert shell.environments[restore]["DATA_DIR"] == str(here.places.data)
    in_order = [
        lines.index("systemctl --user stop sunroom.service"),
        next(at for at, line in enumerate(lines) if line.endswith(server_wheel("0.14.0"))),
        lines.index(restore),
    ]
    assert in_order == sorted(in_order)  # stopped, the old version in place, then its restore
    assert lines[-1] == "loginctl enable-linger"  # started again, all of it, last
    assert here.outcome == ["went-back", RELEASE, "0.14.0"]
    assert here.remembered()["release"] == "0.14.0"


async def test_a_version_that_failed_without_migrating_leaves_the_database_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shell = Shell()
    here = sunroom(tmp_path, shell, http=github({server_wheel(RELEASE): WHEEL}))
    installed_at(here, "0.14.0")
    folder = here.places.data / "backups" / "pre-migrate"
    folder.mkdir(parents=True)
    (folder / "sunroom.aaa.20261105T010000Z.db").write_bytes(b"a copy it took")
    never_answers_as(here, monkeypatch, RELEASE)
    assert not await here.update(RELEASE)
    assert not [line for line in shell.lines() if " restore " in line]
    assert here.outcome == ["went-back", RELEASE, "0.14.0"]


async def test_a_version_that_went_back_isnt_tried_again_until_a_newer_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    here = sunroom(tmp_path, Shell(), http=github({server_wheel(RELEASE): WHEEL}))
    installed_at(here, "0.14.0")
    assert here.behind(RELEASE)
    never_answers_as(here, monkeypatch, RELEASE)
    await here.update(RELEASE)
    assert not here.behind(RELEASE)
    assert here.behind("99.0.0")

    async def answers(release: str, within_s: float = 0) -> bool:
        return True

    monkeypatch.setattr(here, "answers_as", answers)  # Update Sunroom may still ask for it
    assert await here.update(RELEASE)
    assert here.outcome == []
    assert here.remembered()["went_back"] is None
    assert not here.behind(RELEASE)
    assert here.behind("99.0.0")


async def test_a_failed_download_changes_nothing_and_stays_behind(tmp_path: Path) -> None:
    shell = Shell()
    here = sunroom(tmp_path, shell, http=github({}, status=500))
    installed_at(here, "0.14.0")
    assert not await here.update(RELEASE)
    assert not [line for line in shell.lines() if " tool install " in line]
    assert here.behind(RELEASE)
    assert here.outcome == []


async def test_a_version_uv_couldnt_install_can_be_tried_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shell = Shell(answers={"/home/ana/.local/bin/uv tool install": CommandResult(1, "no disk")})
    here = sunroom(tmp_path, shell, http=github({server_wheel(RELEASE): WHEEL}))
    installed_at(here, "0.14.0")
    never_answers_as(here, monkeypatch, RELEASE)
    assert not await here.update(RELEASE)
    assert here.outcome == []  # it never ran, so there was nothing to go back from
    assert here.behind(RELEASE)


async def test_a_macs_sunroom_goes_back_with_launchd_loading_it_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shell = Shell()
    where = places(tmp_path, "darwin")
    here = LocalSunroom(
        runner=shell,
        http=github({server_wheel(RELEASE): WHEEL}),
        places=where,
        system="darwin",
        machine="arm64",
        release=RELEASE,
        uv="uv",
        service=LaunchdService(shell, where, uid=501),
    )
    where.wheels.mkdir(parents=True)
    (where.wheels / server_wheel("0.14.0")).write_bytes(b"the one before")
    where.launch_agent.parent.mkdir(parents=True)
    where.launch_agent.write_text("<plist/>")
    here._remember(port=7867, advertised="http://kitchen.local:7867", release="0.14.0")  # pyright: ignore[reportPrivateUsage]
    never_answers_as(here, monkeypatch, RELEASE)
    assert not await here.update(RELEASE)
    assert here.outcome == ["went-back", RELEASE, "0.14.0"]
    launchctl = [line for line in shell.lines() if line.startswith("launchctl")]
    assert launchctl[-1].startswith("launchctl bootstrap gui/501")  # kickstart can't load it


def test_a_database_says_what_revision_it_is_at_or_nothing(tmp_path: Path) -> None:
    here = sunroom(tmp_path, Shell())
    database = here.places.data / "sunroom.db"
    assert database_revision(database) is None  # none yet
    installed_at(here, "0.14.0")
    assert database_revision(database) == "aaa"
    garbage = tmp_path / "with a space" / "sunroom.db"  # a Mac's Application Support has one
    garbage.parent.mkdir()
    garbage.write_bytes(b"not a database")
    assert database_revision(garbage) is None
    fine = tmp_path / "with a space" / "fine.db"
    with contextlib.closing(sqlite3.connect(fine)) as db:
        db.execute("CREATE TABLE alembic_version (version_num TEXT)")
        db.execute("INSERT INTO alembic_version VALUES ('ccc')")
        db.commit()
    assert database_revision(fine) == "ccc"


async def test_windows_starts_it_again_after_an_update_from_what_it_remembered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Sunroom Screen started again since the run: its service knows no command until primed.
    started = Started()
    shell = Shell()
    where = places(tmp_path, "win32")
    here = LocalSunroom(
        runner=shell,
        http=github({}),
        places=where,
        system="win32",
        machine="AMD64",
        release=RELEASE,
        uv="uv.exe",
        service=WindowsService(shell, where, popen=started),
    )
    where.wheels.mkdir(parents=True)
    (where.wheels / server_wheel(RELEASE)).write_bytes(WHEEL)
    here._remember(port=7868, advertised="http://192.168.1.30:7868", release="0.14.0")  # pyright: ignore[reportPrivateUsage]

    async def answers_as(release: str, within_s: float = 0) -> bool:
        return True

    monkeypatch.setattr(here, "answers_as", answers_as)
    assert await here.update(RELEASE)
    ((argv, options),) = started.calls
    assert argv == [str(where.bin / "sunroom.exe"), "serve", "--host", EVERYWHERE]
    assert options["env"]["PORT"] == "7868"


async def test_removing_it_keeps_the_familys_data_unless_asked(tmp_path: Path) -> None:
    shell = Shell()
    here = sunroom(tmp_path, shell)
    here.places.unit.parent.mkdir(parents=True)
    here.places.unit.write_text("[Unit]\n")
    here._remember(port=7867)  # pyright: ignore[reportPrivateUsage]
    here.places.data.mkdir(parents=True)
    (here.places.data / "sunroom.db").write_bytes(b"the family's calendar")
    said = await here.remove()
    assert "Stopped Sunroom on this computer." in said
    assert any(line.startswith("Kept Sunroom's data") for line in said)
    assert (here.places.data / "sunroom.db").exists()
    assert "/home/ana/.local/bin/uv tool uninstall sunroom" in shell.lines()
    assert not here.installed()
    gone = await here.remove(delete_data=True)
    assert any(line.startswith("Deleted Sunroom's data") for line in gone)
    assert not here.places.data.exists()


# ---------------------------------------------------------------------- the agent's part


class FakeLocal:
    """Sunroom run here, as the agent sees it: supported, and a run that answers at once."""

    def __init__(self, url: str) -> None:
        self.url = url
        self.ran = False
        self.helped = 0
        self.installed_now = False

    def supported(self) -> bool:
        return True

    def installed(self) -> bool:
        return self.installed_now

    async def run_here(self, progress: Callable[[int, str], Any]) -> str:
        self.ran = True
        self.installed_now = True
        await progress(60, "agent.local.step.installing")
        return self.url

    async def keep_awake(self) -> None:
        self.helped += 1

    async def announce(self) -> None:
        self.helped += 1

    async def stop_helpers(self) -> None:
        return None

    def behind(self, own: str) -> bool:
        return False


class BehindLocal(FakeLocal):
    """Sunroom run here, older than this Sunroom Screen, and an update that does what it's told."""

    def __init__(self, url: str = "http://localhost:7867", *, works: bool = True) -> None:
        super().__init__(url)
        self.installed_now = True
        self.works = works
        self.outcome: list[str] = []
        self.updates: list[str] = []
        self.hold: asyncio.Event | None = None

    def behind(self, own: str) -> bool:
        return not self.updates or not self.works

    async def update(self, release: str) -> bool:
        self.updates.append(release)
        if self.hold is not None:
            await self.hold.wait()
        return self.works


def steps_and_toasts(agent: Agent) -> list[str]:
    said: list[str] = []

    def publish(kind: str, data: Any = None) -> None:
        if kind in ("update.progress", "toast"):
            said.append(data["key"])

    agent.hub.publish = publish  # type: ignore[method-assign]
    return said


async def test_sunroom_here_comes_up_to_this_version_with_the_step_on_the_wall(
    make_agent: Callable[..., Agent],
) -> None:
    local = BehindLocal()
    agent = make_agent(platform=FakePlatform("desktop"), local=local)
    said = steps_and_toasts(agent)
    assert agent.known.version is None  # after a restart: Sunroom Screen is up first
    await agent.finish_update()
    assert local.updates == [version()]
    assert said == [
        "agent.update.step.updating_sunroom",
        "agent.toast.sunroom_up_to_date",
        "agent.update.step.done",
    ]
    said.clear()
    await agent.finish_update()  # nothing more to do at the next start
    assert local.updates == [version()]
    assert said == []


async def test_sunroom_here_that_failed_to_download_is_tried_again_within_the_hour(
    make_agent: Callable[..., Agent],
) -> None:
    local = BehindLocal(works=False)
    agent = make_agent(platform=FakePlatform("desktop"), local=local)
    agent.save(Config(url=local.url, found="local"))

    async def answers(_url: str) -> bool:
        return True

    agent.healthy = answers  # type: ignore[method-assign]
    await agent.health_tick()
    await asyncio.sleep(0)
    assert local.updates == []  # not before the hour is up
    agent._behind_looked_at = -state_module.BEHIND_EVERY_S  # pyright: ignore[reportPrivateUsage]
    said = steps_and_toasts(agent)
    await agent.health_tick()
    await asyncio.sleep(0)
    assert local.updates == [version()]
    assert said == []  # on its own, a failed try says nothing


async def test_sunroom_here_that_went_back_says_so(make_agent: Callable[..., Agent]) -> None:
    local = BehindLocal(works=False)
    local.outcome = ["went-back", "0.19.0", "0.18.0"]
    agent = make_agent(platform=FakePlatform("desktop"), local=local)
    said = steps_and_toasts(agent)
    await agent.update_sunroom(quiet=True)
    assert said == ["agent.toast.sunroom_went_back"]


async def test_update_sunroom_goes_to_the_newest_unless_it_is_told_a_version(
    make_agent: Callable[..., Agent],
) -> None:
    local = BehindLocal()
    agent = make_agent(platform=FakePlatform("desktop"), local=local)
    await agent.update_sunroom(release="0.19.0")
    assert local.updates == ["0.19.0"]


async def test_two_asks_to_update_sunroom_are_one_update(
    make_agent: Callable[..., Agent],
) -> None:
    local = BehindLocal()
    local.hold = asyncio.Event()
    agent = make_agent(platform=FakePlatform("desktop"), local=local)
    first = asyncio.create_task(agent.update_sunroom())
    await asyncio.sleep(0)
    await agent.update_sunroom()  # This Screen's button, while the night's update runs
    local.hold.set()
    await first
    assert len(local.updates) == 1
    await agent.update_sunroom()  # and a later one is its own
    assert len(local.updates) == 2


async def test_the_agent_runs_sunroom_here_through_it_on_a_computer(
    make_agent: Callable[..., Agent],
    sunrooms: Any,
    config_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sunroom_kiosk import config as settings_file

    monkeypatch.setattr(state_module, "RUN_SUNROOM_PAUSE_S", 0)
    local = FakeLocal("http://localhost:7867")
    sunrooms.new[local.url] = {**sunrooms.new[next(iter(sunrooms.new))], "setup_complete": False}
    sunrooms.healthy.add(local.url)
    agent = make_agent(platform=FakePlatform("desktop"), local=local)
    assert "run_sunroom" in agent.capabilities()
    await agent.run_sunroom()
    assert local.ran and local.helped == 2
    saved = settings_file.load(config_path)
    assert (saved.url, saved.found) == (local.url, "local")
    # Shown now: no running it again, and Update Sunroom Too while it's this screen's own.
    assert "run_sunroom" not in agent.capabilities()
    assert "update_sunroom" in agent.capabilities()


async def test_uninstall_takes_sunroom_only_where_it_runs_here_then_quits(
    make_agent: Callable[..., Agent], monkeypatch: pytest.MonkeyPatch
) -> None:
    """This Screen's Uninstall (ADR 0042): the platform's uninstaller, with Sunroom only where
    it runs here as a program; then the agent quits (not the pretend one, in tests and e2e)."""
    platform = FakePlatform("desktop")
    local = FakeLocal("http://localhost:7867")
    agent = make_agent(platform=platform, local=local)
    assert "remove_sunroom" not in agent.capabilities()
    await agent.uninstall(sunroom=True)  # asked, but nothing runs here: Sunroom Screen alone
    assert platform.calls == ["uninstall"]
    local.installed_now = True
    assert "remove_sunroom" in agent.capabilities()
    await agent.uninstall(sunroom=True)
    assert platform.calls[-1] == "uninstall and sunroom"
    quits: list[str] = []

    async def quit_() -> None:
        quits.append("quit")

    real = make_agent(platform=platform, local=local, fake=False)
    monkeypatch.setattr(real, "quit", quit_)
    await real.uninstall(sunroom=False)
    assert (platform.calls[-1], quits) == ("uninstall", ["quit"])
