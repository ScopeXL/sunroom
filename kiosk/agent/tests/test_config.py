"""The settings file (config.py): read without running anything, written back keeping what it
doesn't own, and still sourceable by bash for the installer. Synthetic data only."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from sunroom_kiosk import config
from sunroom_kiosk.config import Config

INSTALLER = """\
# Written by the Sunroom installer (kiosk/install.sh 0.12.0). Running it again replaces this file.
# Read by ~/.local/bin/sunroom-kiosk and ~/.local/bin/sunroom-screen at every start.
SUNROOM_URL=http://192.168.1.20:7867
SUNROOM_SESSION=wayland
SUNROOM_OUTPUT=HDMI-A-1
SUNROOM_ROTATE=90
SUNROOM_SCREEN_HELPER=yes
SUNROOM_BRIGHTNESS=ddc
SUNROOM_DDC_BUS=20
SUNROOM_BACKLIGHT=''
SUNROOM_MODE=display
SUNROOM_LABEL=Sample\\ Street\\ kitchen
"""


def test_reads_the_installers_file() -> None:
    read = config.from_values(config.parse_values(INSTALLER))
    assert read == Config(
        url="http://192.168.1.20:7867",
        session="wayland",
        output="HDMI-A-1",
        rotate=90,
        brightness="ddc",
        ddc_bus="20",
        mode="display",
    )


def test_odd_values_fall_back_and_nothing_is_run() -> None:
    odd = "\n".join(
        [
            "SUNROOM_URL=file:///etc/passwd",
            "SUNROOM_ROTATE=45",
            "SUNROOM_FOUND=$(reboot)",
            "SUNROOM_ID=not an id",
            "SUNROOM_UPDATE_CHECK=hourly",
            "SUNROOM_BRIGHTNESS=bright",
        ]
    )
    assert config.from_values(config.parse_values(odd)) == Config()


def test_a_round_trip_keeps_comments_order_and_keys_it_doesnt_know(tmp_path: Path) -> None:
    path = tmp_path / "config"
    path.write_text(INSTALLER)
    before = config.load(path)
    config.save(
        path,
        before.with_sunroom(
            "https://calendar.example.com", "00000000-0000-7000-8000-0000000000e1", "typed"
        ),
    )
    text = path.read_text()
    assert text.startswith("# Written by the Sunroom installer")
    assert "SUNROOM_LABEL=Sample\\ Street\\ kitchen\n" in text  # untouched, as written
    assert text.index("SUNROOM_URL=") < text.index("SUNROOM_SESSION=")  # in place
    assert text.rstrip().endswith("SUNROOM_UPDATE_CHECK=''")  # new keys at the end
    after = config.load(path)
    assert after.url == "https://calendar.example.com"
    assert after.sunroom_id == "00000000-0000-7000-8000-0000000000e1"
    assert after.found == "typed"
    assert (after.rotate, after.ddc_bus, after.mode) == (90, "20", "display")


def test_a_new_file_has_a_header(tmp_path: Path) -> None:
    path = tmp_path / "sunroom-kiosk" / "config"
    config.save(path, Config(update_check="off"))
    text = path.read_text()
    assert text.startswith("# Sunroom Screen's settings")
    assert config.load(path).update_check == "off"


BASH = shutil.which("bash")


# Windows' bash is another world's (Git's or WSL's), with its own idea of a path.
@pytest.mark.skipif(BASH is None or sys.platform == "win32", reason="needs a Unix bash")
def test_bash_still_sources_it(tmp_path: Path) -> None:
    """kiosk/install.sh and the uninstaller read it with `.`: quoting must survive."""
    path = tmp_path / "config"
    config.save(path, Config(url="http://192.168.1.20:7867", output="HDMI-A-1"))
    assert BASH is not None
    printed = subprocess.run(  # noqa: S603 - a fixed command on a test file
        [
            BASH,
            "-c",
            '. "$1"; printf "%s|%s|%s" "$SUNROOM_URL" "$SUNROOM_OUTPUT" "$SUNROOM_ID"',
            "_",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert printed == "http://192.168.1.20:7867|HDMI-A-1|"
