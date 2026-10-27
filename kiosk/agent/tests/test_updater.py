"""Updates of Sunroom Screen itself (updater.py, docs/M7.md T9) against a pretend GitHub: the
newest tag, an update only once its wheel is in the Release's SHA256SUMS, a download that doesn't
match its checksum refused, the apply step keeping a version that answers and putting the
previous one back when it doesn't, and the nightly time. No network. Synthetic data only."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pytest

from sunroom_kiosk import updater
from sunroom_kiosk.apply import Paths, apply
from sunroom_kiosk.updater import DIDNT_START, Updater, newest, sums_from

WHEEL = b"sample wheel bytes"


class GitHub:
    """Tags and one Release's files, by URL."""

    def __init__(self, tags: list[str], files: dict[str, bytes] | None = None) -> None:
        self.tags = tags
        self.files = files or {}
        self.asked: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.asked.append(url)
        if url == updater.TAGS_URL:
            return httpx.Response(200, json=[{"name": tag} for tag in self.tags])
        for name, data in self.files.items():
            if url.endswith(f"/{name}"):
                return httpx.Response(200, content=data)
        return httpx.Response(404, text="Not Found")

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self))


def release(version: str, data: bytes = WHEEL, sums_for: bytes | None = None) -> dict[str, bytes]:
    name = updater.wheel_name(version)
    digest = hashlib.sha256(sums_for if sums_for is not None else data).hexdigest()
    return {name: data, "SHA256SUMS": f"{digest}  {name}\n{'0' * 64}  install.sh\n".encode()}


@pytest.fixture
def paths(tmp_path: Path) -> Paths:
    return Paths(wheels=tmp_path / "wheels", state=tmp_path / "state" / "update.json")


def test_the_newest_tag_wins_and_odd_ones_are_left_out() -> None:
    tags: list[Any] = [{"name": n} for n in ("v0.9.1", "v0.13.0", "v0.12.10", "v1.0.0-rc1", "x")]
    assert newest(tags) == "0.13.0"
    assert newest([]) is None and newest({"not": "a list"}) is None


def test_checksums_are_read_as_sha256sum_writes_them() -> None:
    text = f"{'a' * 64}  sunroom_kiosk-0.13.0-py3-none-any.whl\n{'B' * 64} *install.sh\nnoise\n"
    assert sums_from(text) == {
        "sunroom_kiosk-0.13.0-py3-none-any.whl": "a" * 64,
        "install.sh": "b" * 64,
    }


async def test_an_update_is_ready_only_once_its_wheel_is_published(paths: Paths) -> None:
    github = GitHub(["v0.12.0", "v0.13.0"])
    check = Updater(http=github.client, paths=paths, current="0.12.0")
    status = await check.check_now()
    assert (status.state, status.latest) == ("up_to_date", "0.13.0")  # tagged, no files yet
    github.files = release("0.13.0")
    status = await check.check_now()
    assert (status.state, status.latest) == ("available", "0.13.0")
    assert json.loads(paths.state.read_text())["latest"] == "0.13.0"
    assert (
        await Updater(http=github.client, paths=paths, current="0.13.0").check_now()
    ).state == "up_to_date"


async def test_github_not_answering_is_said_plainly(paths: Paths) -> None:
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    check = Updater(
        http=lambda: httpx.AsyncClient(transport=httpx.MockTransport(down)),
        paths=paths,
        current="0.12.0",
    )
    status = await check.check_now()
    assert status.message == "GitHub didn't answer. This screen asks again tomorrow."


async def test_a_download_that_doesnt_match_its_checksum_is_refused(paths: Paths) -> None:
    github = GitHub(["v0.13.0"], release("0.13.0", data=WHEEL, sums_for=b"something else"))
    with pytest.raises(updater.UpdateError, match="didn't match its checksum"):
        await Updater(http=github.client, paths=paths, current="0.12.0").download("0.13.0")
    assert not paths.wheels.exists() or not any(paths.wheels.glob("*.whl"))


async def test_a_good_download_is_kept_beside_the_running_one(paths: Paths) -> None:
    github = GitHub(["v0.13.0"], release("0.13.0"))
    kept = await Updater(http=github.client, paths=paths, current="0.12.0").download("0.13.0")
    assert kept == paths.wheels / "sunroom_kiosk-0.13.0-py3-none-any.whl"
    assert kept.read_bytes() == WHEEL


def wheels(paths: Paths, *versions: str) -> list[Path]:
    paths.wheels.mkdir(parents=True, exist_ok=True)
    made: list[Path] = []
    for version in versions:
        path = paths.wheels / updater.wheel_name(version)
        path.write_bytes(version.encode())
        made.append(path)
    return made


def test_apply_keeps_a_version_that_answers(paths: Paths) -> None:
    older, previous, new = wheels(paths, "0.11.0", "0.12.0", "0.13.0")
    installed: list[str] = []
    code = apply(
        new,
        previous,
        7800,
        install=lambda path: installed.append(path.name) or True,
        stop=lambda: True,
        restart=lambda: True,
        answers=lambda port, version, within: version == "0.13.0",
        paths=paths,
    )
    assert code == 0
    assert installed == [new.name]
    assert not older.exists() and previous.exists()  # the one before stays, to go back to


def test_apply_puts_the_previous_version_back_when_the_new_one_doesnt_start(
    paths: Paths,
) -> None:
    previous, new = wheels(paths, "0.12.0", "0.13.0")
    installed: list[str] = []
    restarts: list[bool] = []
    code = apply(
        new,
        previous,
        7800,
        install=lambda path: installed.append(path.name) or True,
        stop=lambda: True,
        restart=lambda: restarts.append(True) or True,
        answers=lambda port, version, within: False,
        paths=paths,
    )
    assert code == 1
    assert installed == [new.name, previous.name]
    assert len(restarts) == 2
    # The agent that starts again says so in This Screen's Software row.
    after = Updater(http=GitHub(["v0.13.0"]).client, paths=paths, current="0.12.0")
    assert after.current.state == "failed"
    assert after.current.message == DIDNT_START


async def test_install_downloads_then_hands_over_to_the_apply_step(paths: Paths) -> None:
    from sunroom_kiosk.events import EventHub

    github = GitHub(["v0.13.0"], release("0.13.0"))
    spawned: list[list[str]] = []

    async def spawn(argv: list[str]) -> bool:
        spawned.append(argv)
        return True

    wheels(paths, "0.12.0")
    check = Updater(http=github.client, paths=paths, current="0.12.0", spawn=spawn, port=7800)
    await check.check_now()

    class Agent:
        def __init__(self) -> None:
            self.hub = EventHub()
            self.said: list[str] = []

        def publish_state(self) -> None: ...

        def toast(self, message: str) -> None:
            self.said.append(message)

    await check.install(Agent())  # type: ignore[arg-type]
    assert spawned and spawned[0][1:5] == ["-m", "sunroom_kiosk", "update", "--apply"]
    assert spawned[0][5].endswith("sunroom_kiosk-0.13.0-py3-none-any.whl")
    assert spawned[0][-2:] == [
        "--previous",
        str(paths.wheels / "sunroom_kiosk-0.12.0-py3-none-any.whl"),
    ]
    assert check.current.state == "installing"


def test_the_nightly_check_runs_when_the_sleep_hours_start() -> None:
    zone = ZoneInfo("America/New_York")
    evening = datetime(2026, 10, 20, 21, 0, tzinfo=zone)
    assert updater.next_nightly(evening, "22:30") == datetime(2026, 10, 20, 22, 30, tzinfo=zone)
    assert updater.next_nightly(evening, None) == datetime(2026, 10, 21, 3, 30, tzinfo=zone)
    assert updater.next_nightly(evening, "25:00") == datetime(2026, 10, 21, 3, 30, tzinfo=zone)


def test_on_windows_the_apply_step_runs_outside_the_agents_own_files(paths: Paths) -> None:
    """Windows locks a running program's files: the apply step is a copy of apply.py, run by the
    Python the agent's environment was made from, which asks the agent to quit first."""
    from sunroom_kiosk import apply as apply_step

    wheel, previous = wheels(paths, "0.13.0", "0.12.0")
    check = Updater(http=GitHub([]).client, paths=paths, current="0.12.0", system="win32")
    argv = check.apply_command(wheel, previous)
    script = paths.state.parent / "apply.py"
    assert argv[1:] == [
        str(script),
        "--apply",
        str(wheel),
        "--port",
        "7800",
        "--previous",
        str(previous),
    ]
    assert script.read_text(encoding="utf-8") == Path(apply_step.__file__).read_text(
        encoding="utf-8"
    )
    elsewhere = Updater(http=GitHub([]).client, paths=paths, current="0.12.0", system="linux")
    assert elsewhere.apply_command(wheel, None)[1:5] == ["-m", "sunroom_kiosk", "update", "--apply"]


def test_the_apply_steps_uv_opens_no_console_window(monkeypatch: pytest.MonkeyPatch) -> None:
    """Windows runs the apply step without a console (pythonw), so uv would open one of its own
    on the wall for as long as it installs."""
    from sunroom_kiosk import apply as apply_step

    asked: list[object] = []

    def run(argv: list[str], **options: object) -> subprocess.CompletedProcess[str]:
        asked.append(options.get("creationflags"))
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(apply_step.subprocess, "run", run)
    assert apply_step.run(["uv", "tool", "install", "sunroom_kiosk-0.13.0-py3-none-any.whl"])
    assert asked == [apply_step.NO_WINDOW]
    assert apply_step.NO_WINDOW == (0x08000000 if sys.platform == "win32" else 0)


def test_the_apply_step_stops_the_agent_before_each_install(paths: Paths) -> None:
    previous, new = wheels(paths, "0.12.0", "0.13.0")
    steps: list[str] = []
    code = apply(
        new,
        previous,
        7800,
        install=lambda path: steps.append(f"install {path.name}") or True,
        stop=lambda: steps.append("stop") or True,
        restart=lambda: steps.append("start") or True,
        answers=lambda port, version, within: False,
        paths=paths,
    )
    assert code == 1
    assert steps == [
        "stop",
        f"install {new.name}",
        "start",
        "stop",
        f"install {previous.name}",
        "start",
    ]
