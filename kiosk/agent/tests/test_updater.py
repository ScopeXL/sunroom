"""Updates of Sunroom Screen itself (updater.py, docs/M7.md T9) against a pretend GitHub: the
newest tag, an update only once its wheel is in the Release's SHA256SUMS, a download that doesn't
match its checksum refused, the apply step keeping a version that answers and putting the
previous one back when it doesn't, and the nightly time. No network. Synthetic data only."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from collections.abc import Coroutine
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pytest

from sunroom_kiosk import updater
from sunroom_kiosk.apply import Paths, apply, note_progress
from sunroom_kiosk.events import EventHub
from sunroom_kiosk.updater import Updater, newest, sums_from
from sunroom_kiosk.words import said

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
    assert status.message is not None
    assert status.message.message == "GitHub didn't answer. This screen asks again tomorrow."


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
    happened: list[str] = []
    progress: list[object] = []

    def setup(force: bool) -> dict[str, object]:
        progress.append(json.loads(paths.state.read_text())["progress"])
        happened.append(f"setup force={force}")
        return {"changed": ["service"], "needs_reboot": False}

    def restart(report: dict[str, object] | None) -> bool:
        happened.append(f"restart {report}")
        return True

    code = apply(
        new,
        previous,
        7800,
        install=lambda path: happened.append(f"install {path.name}") or True,
        stop=lambda: True,
        setup=setup,
        restart=restart,
        answers=lambda port, version, within: version == "0.13.0",
        paths=paths,
    )
    assert code == 0
    # The new version's own setup between its install and its start (ADR 0044).
    assert happened == [
        f"install {new.name}",
        "setup force=False",
        "restart {'changed': ['service'], 'needs_reboot': False}",
    ]
    assert progress == [{"percent": 70, "key": "agent.update.step.setting_up"}]
    assert not older.exists() and previous.exists()  # the one before stays, to go back to
    saved = json.loads(paths.state.read_text())
    assert saved["progress"] is None and saved["last"]["version"] == "0.13.0"
    assert saved["last"]["ok"] is True


def test_apply_puts_the_previous_version_back_when_the_new_one_doesnt_start(
    paths: Paths,
) -> None:
    previous, new = wheels(paths, "0.12.0", "0.13.0")
    installed: list[str] = []
    setups: list[str] = []
    restarts: list[bool] = []
    code = apply(
        new,
        previous,
        7800,
        install=lambda path: installed.append(path.name) or True,
        stop=lambda: True,
        setup=lambda force: setups.append(installed[-1]) or {"changed": []},
        restart=lambda report: restarts.append(True) or True,
        answers=lambda port, version, within: False,
        paths=paths,
    )
    assert code == 1
    assert installed == [new.name, previous.name]
    assert setups == installed  # the version put back gets its own setup again
    assert len(restarts) == 2
    # The agent that starts again says so in This Screen's Software row, and once as a toast.
    after = Updater(http=GitHub(["v0.13.0"]).client, paths=paths, current="0.12.0")
    assert after.current.state == "failed"
    assert after.current.message == said("agent.update.didnt_finish", version="0.12.0")
    result = after.last_result()
    assert result is not None and result["ok"] is False
    assert result["message"] == "The update didn't finish. Sunroom Screen 0.12.0 is back."
    after.seen()
    assert after.last_result() is None


def test_a_setup_that_fails_outright_puts_the_previous_version_back(paths: Paths) -> None:
    previous, new = wheels(paths, "0.12.0", "0.13.0")
    installed: list[str] = []
    started: list[object] = []
    code = apply(
        new,
        previous,
        7800,
        install=lambda path: installed.append(path.name) or True,
        stop=lambda: True,
        setup=lambda force: None if installed[-1] == new.name else {"changed": []},
        restart=lambda report: started.append(report) or True,
        answers=lambda port, version, within: True,
        paths=paths,
    )
    assert code == 1
    assert installed == [new.name, previous.name]
    assert started == [{"changed": []}]  # only the version put back starts


@pytest.mark.skipif(sys.platform == "win32", reason="a Mac's own commands")
def test_a_mac_whose_launch_agent_changed_starts_it_out_and_in_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sunroom_kiosk import apply as apply_step

    ran: list[list[str]] = []

    def run(argv: list[str]) -> bool:
        ran.append(argv)
        return True

    monkeypatch.setattr(apply_step.sys, "platform", "darwin")
    monkeypatch.setattr(apply_step, "run", run)
    assert apply_step.restart_service({"changed": ["launch-agent"]})
    assert [argv[1] for argv in ran] == ["bootout", "bootstrap"]
    ran.clear()
    assert apply_step.restart_service({"changed": []})
    assert [argv[1:3] for argv in ran] == [["kickstart", "-k"]]


class StubAgent:
    """What the updater asks of the agent: its events and toasts (in order), and work to run."""

    def __init__(self, happened: list[str] | None = None) -> None:
        self.hub = EventHub()
        self.happened = happened if happened is not None else []
        self.spawned: list[str] = []
        self.hub.publish = lambda kind, data: self.happened.append(  # type: ignore[method-assign]
            f"{data['percent']} {data['key']}"
        )

    def publish_state(self) -> None: ...

    def toast(self, key: str, **params: object) -> None:
        self.happened.append(f"toast {key}")

    def spawn(self, work: Coroutine[Any, Any, None]) -> None:
        self.spawned.append(work.__qualname__)
        work.close()  # the apply step's own steps: relayed while this agent runs


async def test_install_downloads_then_hands_over_to_the_apply_step(paths: Paths) -> None:
    github = GitHub(["v0.13.0"], release("0.13.0"))
    spawned: list[list[str]] = []

    async def spawn(argv: list[str]) -> bool:
        spawned.append(argv)
        return True

    wheels(paths, "0.12.0")
    happened: list[str] = []
    check = Updater(
        http=github.client,
        paths=paths,
        current="0.12.0",
        spawn=spawn,
        port=7800,
        backup=lambda: happened.append("backup"),
    )
    await check.check_now()
    agent = StubAgent(happened)
    await check.install(agent)  # type: ignore[arg-type]
    assert happened == [
        "10 agent.update.step.downloading",
        "backup",  # the small files copied aside before anything changes
        "30 agent.update.step.checking",
        "50 agent.update.step.installing",
    ]
    assert agent.spawned == ["Updater.relay"]
    assert spawned and spawned[0][1:5] == ["-m", "sunroom_kiosk", "update", "--apply"]
    assert spawned[0][5].endswith("sunroom_kiosk-0.13.0-py3-none-any.whl")
    assert spawned[0][-2:] == [
        "--previous",
        str(paths.wheels / "sunroom_kiosk-0.12.0-py3-none-any.whl"),
    ]
    assert check.current.state == "installing"


async def test_reinstall_runs_the_installed_version_again_with_its_setup_rewritten(
    paths: Paths,
) -> None:
    github = GitHub(["v0.13.0"])  # nothing to download: its wheel was kept when it came
    spawned: list[list[str]] = []

    async def spawn(argv: list[str]) -> bool:
        spawned.append(argv)
        return True

    (kept,) = wheels(paths, "0.12.0")
    check = Updater(http=github.client, paths=paths, current="0.12.0", spawn=spawn)
    await check.reinstall(StubAgent())  # type: ignore[arg-type]
    assert github.asked == []
    assert spawned[0][5] == str(kept)
    assert spawned[0][-3:] == ["--previous", str(kept), "--force"]


def test_a_reinstall_says_so_once_it_is_back(paths: Paths) -> None:
    (kept,) = wheels(paths, "0.12.0")
    forced: list[bool] = []
    code = apply(
        kept,
        kept,
        7800,
        force=True,
        install=lambda path: True,
        stop=lambda: True,
        setup=lambda force: forced.append(force) or {"changed": ["service"]},
        restart=lambda report: True,
        answers=lambda port, version, within: True,
        paths=paths,
    )
    assert code == 0 and forced == [True]
    after = Updater(http=GitHub([]).client, paths=paths, current="0.12.0")
    result = after.last_result()
    assert result is not None and result["message"] == "Reinstalled Sunroom Screen 0.12.0"


def test_a_reinstall_that_fails_offers_nothing_new(paths: Paths) -> None:
    (kept,) = wheels(paths, "0.12.0")
    paths.state.parent.mkdir(parents=True)
    paths.state.write_text(json.dumps({"latest": "0.13.0"}))
    apply(
        kept,
        kept,
        7800,
        force=True,
        install=lambda path: True,
        stop=lambda: True,
        setup=lambda force: {"changed": []},
        restart=lambda report: True,
        answers=lambda port, version, within: False,
        paths=paths,
    )
    after = Updater(http=GitHub([]).client, paths=paths, current="0.12.0")
    assert (after.current.state, after.current.latest) == ("available", "0.13.0")


async def test_the_apply_steps_own_steps_reach_the_wall_once_each(paths: Paths) -> None:
    check = Updater(http=GitHub([]).client, paths=paths, current="0.12.0")
    agent = StubAgent()
    note_progress(paths, 70, "agent.update.step.setting_up")
    await check.relay(agent, every_s=0.01, for_s=0.05)  # type: ignore[arg-type]
    assert agent.happened == ["70 agent.update.step.setting_up"]


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
        setup=lambda force: steps.append("setup") or {"changed": []},
        restart=lambda report: steps.append("start") or True,
        answers=lambda port, version, within: False,
        paths=paths,
    )
    assert code == 1
    assert steps == [
        "stop",
        f"install {new.name}",
        "setup",
        "start",
        "stop",
        f"install {previous.name}",
        "setup",
        "start",
    ]
