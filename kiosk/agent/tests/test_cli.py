"""``sunroom-kiosk``'s commands for the installers (cli.py, docs/M7.md T14): ``config --url``
(an address as the installers take it), ``policy --remove`` (the platform's own, never this
machine's), and a log file when there's no console. Temporary files only; synthetic addresses."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from sunroom_kiosk import cli
from sunroom_kiosk import config as settings_file
from sunroom_kiosk.platform.fake import FakePlatform


def test_an_address_is_taken_as_the_installers_take_it() -> None:
    assert cli.clean_address("http://192.168.1.20:7867/display/") == "http://192.168.1.20:7867"
    assert cli.clean_address(" HTTPS://Calendar.Example.com ") == "https://calendar.example.com"
    for wrong in ("calendar.example.com", "ftp://example.com", "http://", "http://a b.example.com"):
        assert cli.clean_address(wrong) is None


def test_config_saves_a_typed_address_and_keeps_the_rest(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "config"
    path.write_text(
        "# a note of the family's own\nSUNROOM_ID=00000000-0000-7000-8000-0000000000e1\n"
    )
    assert (
        cli.main(["config", "--config", str(path), "--url", "https://calendar.example.com/"]) == 0
    )
    assert "will show Sunroom from https://calendar.example.com" in capsys.readouterr().out
    saved = settings_file.load(path)
    assert (saved.url, saved.found, saved.sunroom_id) == (
        "https://calendar.example.com",
        "typed",
        None,
    )
    assert path.read_text().startswith("# a note of the family's own\n")
    assert cli.main(["config", "--config", str(path), "--url", "calendar.example.com"]) == 2
    assert "doesn't look like the address of Sunroom" in capsys.readouterr().err
    assert cli.main(["config", "--config", str(path)]) == 0
    assert "Sunroom: https://calendar.example.com" in capsys.readouterr().out


def test_policy_remove_asks_the_platform(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import sunroom_kiosk.platform as platforms

    pretend = FakePlatform("desktop")
    pretend.policies["edge"] = {"BrowserSignin": 0}

    def detect(fake: object = None, root: object = None) -> FakePlatform:
        return pretend

    monkeypatch.setattr(platforms, "detect", detect)
    assert cli.main(["policy", "--remove"]) == 0
    assert pretend.policies == {}
    assert capsys.readouterr().out == ""


def test_with_no_console_it_writes_a_log_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings_file, "config_dir", lambda: tmp_path)
    monkeypatch.setattr(sys, "stdout", sys.stdout)  # put back after the test
    monkeypatch.setattr(sys, "stderr", None)
    log = tmp_path / "sunroom-kiosk.log"
    log.write_text("x" * (cli.LOG_KEEP_BYTES + 1))
    cli._windowless_log()  # pyright: ignore[reportPrivateUsage]
    try:
        print("Sunroom Screen is running.", file=sys.stderr)
    finally:
        sys.stderr.close()
    assert log.read_text() == "Sunroom Screen is running.\n"
    assert (tmp_path / "sunroom-kiosk.log.1").stat().st_size == cli.LOG_KEEP_BYTES + 1
