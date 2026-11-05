"""kiosk/install.sh's functions, run for real in bash with a pretend curl on PATH (ADR 0046): the
bare line keeps what the wall chose, an option changes only itself, and what it downloads is
checked before anything uses it. Bash here is whatever the computer's is, 3.2 on a Mac. Synthetic
data only."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

from sunroom_kiosk import config as config_file
from sunroom_kiosk.platform.linux import INSTALL_COMMAND

KIOSK = Path(__file__).resolve().parents[2]
REPO = KIOSK.parent
SCRIPT = KIOSK / "install.sh"

pytestmark = pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("bash") is None, reason="install.sh isn't for Windows"
)

# Answers for GitHub and uv's site from one folder, by the last part of the address. Each run is
# written down, so a test can say what was asked for.
CURL = """#!/bin/sh
out=""
url=""
while [ $# -gt 0 ]; do
    case $1 in
    -o) out=$2; shift ;;
    -*) ;;
    *) url=$1 ;;
    esac
    shift
done
echo "$url" >>"$FAKE_WEB/asked"
file="$FAKE_WEB/${url##*/}"
[ -f "$file" ] || exit 22
cp "$file" "$out"
"""


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Installer:
    """install.sh without its last line, ``main "$@"``, so a test can call its functions."""

    def __init__(self, tmp_path: Path) -> None:
        self.home = tmp_path / "home"
        self.home.mkdir()
        self.temp = tmp_path / "temp"
        self.temp.mkdir()
        self.web = tmp_path / "web"
        self.web.mkdir()
        self.bin = tmp_path / "bin"
        self.bin.mkdir()
        curl = self.bin / "curl"
        curl.write_text(CURL)
        curl.chmod(curl.stat().st_mode | stat.S_IEXEC)
        text = SCRIPT.read_text()
        assert text.rstrip().endswith('main "$@"')
        self.functions = tmp_path / "functions.sh"
        self.functions.write_text(text.rstrip().removesuffix('main "$@"'))
        self.config = self.home / ".config/sunroom-kiosk/config"
        self.version = re.search(r'^KIOSK_VERSION="([^"]+)"', text, re.M).group(1)  # type: ignore[union-attr]

    def had(self, **settings: str) -> None:
        """What an earlier run or the wall left in the screen's settings."""
        self.config.parent.mkdir(parents=True, exist_ok=True)
        self.config.write_text("".join(f"{key}={value}\n" for key, value in settings.items()))

    def run(self, then: str, *args: str) -> subprocess.CompletedProcess[str]:
        script = f"""
. "{self.functions}"
TMP_DIR="{self.temp}"
mkdir -p "$STATE_DIR"
parse_args "$@"
{then}
"""
        return subprocess.run(  # noqa: S603
            ["bash", "-c", script, "install.sh", *args],  # noqa: S607
            env={
                "HOME": str(self.home),
                "PATH": f"{self.bin}{os.pathsep}/usr/bin{os.pathsep}/bin",
                "FAKE_WEB": str(self.web),
            },
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )

    def write_config(self, *args: str) -> config_file.Config:
        """What main does with the screen's settings: the agent reads the result, as it will."""
        done = self.run(
            "MODE=display; SESSION=wayland; keep_screen_choices; write_kiosk_config",
            *args,
        )
        assert done.returncode == 0, done.stderr
        return config_file.load(self.config)

    def publish(self, name: str, content: bytes = b"a release's file") -> Path:
        path = self.web / name
        path.write_bytes(content)
        return path

    def sums(self, **wrong: str) -> None:
        """SHA256SUMS for everything on the pretend web, as the Release lists them."""
        lines = [
            f"{wrong.get(path.name, sha256(path))}  {path.name}\n"
            for path in sorted(self.web.iterdir())
            if path.name not in {"SHA256SUMS", "asked"}
        ]
        (self.web / "SHA256SUMS").write_text("".join(lines))

    def asked(self) -> str:
        path = self.web / "asked"
        return path.read_text() if path.exists() else ""

    def kiosk_tarball(self) -> None:
        """The kiosk folder as release-assets.yml makes it: every path starts ``kiosk/``."""
        with tarfile.open(self.web / f"kiosk-{self.version}.tar.gz", "w:gz") as tar:
            tar.add(
                KIOSK,
                arcname="kiosk",
                filter=lambda entry: None if "/agent" in entry.name else entry,
            )


@pytest.fixture
def installer(tmp_path: Path) -> Installer:
    return Installer(tmp_path)


WALL_CHOSE = {
    "SUNROOM_URL": "http://sunroom.local:7867",
    "SUNROOM_ID": "01890a5d-ac96-774b-bcce-b302099a8057",
    "SUNROOM_FOUND": "discovered",
    "SUNROOM_ROTATE": "90",
    "SUNROOM_OUTPUT": "HDMI-A-2",
    "SUNROOM_SCREEN_HELPER": "no",
    "SUNROOM_BRIGHTNESS": "ddc",
    "SUNROOM_UPDATE_CHECK": "off",
}


def test_the_bare_line_keeps_what_the_wall_chose(installer: Installer) -> None:
    installer.had(**WALL_CHOSE)
    kept = installer.write_config()
    assert kept.rotate == 90
    assert kept.output == "HDMI-A-2"
    assert kept.screen_helper is False
    assert kept.brightness == "ddc"
    assert kept.url == "http://sunroom.local:7867"
    assert kept.sunroom_id == "01890a5d-ac96-774b-bcce-b302099a8057"
    assert kept.found == "discovered"
    assert kept.update_check == "off"


def test_it_keeps_what_only_a_hand_set(installer: Installer) -> None:
    installer.had(SUNROOM_DDC_BUS="7", SUNROOM_BACKLIGHT="rpi_backlight")
    kept = installer.write_config()
    assert kept.ddc_bus == "7"
    assert kept.backlight == "rpi_backlight"


def test_an_option_changes_only_itself(installer: Installer) -> None:
    installer.had(**WALL_CHOSE)
    kept = installer.write_config("--rotate", "180")
    assert kept.rotate == 180
    assert kept.output == "HDMI-A-2"
    assert kept.screen_helper is False
    assert kept.brightness == "ddc"


def test_every_option_can_put_a_choice_back(installer: Installer) -> None:
    installer.had(**WALL_CHOSE)
    back = installer.write_config(
        "--rotate=0", "--output=HDMI-A-1", "--brightness=auto", "--screen-helper"
    )
    assert back.rotate == 0
    assert back.output == "HDMI-A-1"
    assert back.brightness == "auto"
    assert back.screen_helper is True


def test_a_first_run_has_the_defaults(installer: Installer) -> None:
    first = installer.write_config()
    assert first.rotate == 0
    assert first.output == ""
    assert first.screen_helper is True
    assert first.brightness == "auto"


def test_a_value_no_option_would_take_is_left_behind(installer: Installer) -> None:
    installer.had(
        SUNROOM_ROTATE="45",
        SUNROOM_BRIGHTNESS="blinding",
        SUNROOM_SCREEN_HELPER="maybe",
        SUNROOM_OUTPUT="'not a connector'",
    )
    kept = installer.write_config()
    assert kept.rotate == 0
    assert kept.brightness == "auto"
    assert kept.screen_helper is True
    assert kept.output == ""


def test_a_real_run_reads_the_choices_before_it_says_or_does_anything(
    installer: Installer,
) -> None:
    """main itself, as a Pi's dry run: the plan names the rotation the file holds."""
    installer.had(**WALL_CHOSE)
    done = installer.run(
        'detect_platform() { PLATFORM=pi; MACHINE="this Pi"; }\nmain --dry-run',
    )
    assert done.returncode == 0, done.stderr
    assert "turn the picture 90 degrees" in done.stdout


# What a Pi's connectors say is the kernel's: the tests answer for /sys.
CONNECTORS = """
output_connected() {{ [[ " {plugged} " == *" $1 "* ]]; }}
detect_output() {{ [[ -n "{plugged}" ]] && printf %s "{plugged}"; }}
OUTPUT={kept}
resolve_output
printf 'OUTPUT=%s\\n' "$OUTPUT"
"""


@pytest.mark.parametrize(
    ("kept", "plugged", "ends_on"),
    [
        ("HDMI-A-2", "HDMI-A-1 HDMI-A-2", "HDMI-A-2"),  # two screens: the one it was on
        ("HDMI-A-2", "HDMI-A-1", "HDMI-A-1"),  # the cable moved
        ("HDMI-A-2", "", "HDMI-A-2"),  # a monitor that's off stays where it was
        ("", "HDMI-A-1", "HDMI-A-1"),  # nothing before: what's plugged in
        ("", "", "HDMI-A-1"),  # nothing at all: the likely one
    ],
)
def test_the_connector(installer: Installer, kept: str, plugged: str, ends_on: str) -> None:
    done = installer.run(CONNECTORS.format(kept=f'"{kept}"', plugged=plugged))
    assert done.returncode == 0, done.stderr
    assert f"OUTPUT={ends_on}\n" in done.stdout


def test_the_connector_given_wins_over_what_is_plugged_in(installer: Installer) -> None:
    done = installer.run(
        CONNECTORS.format(kept='"HDMI-A-2"', plugged="HDMI-A-1"),
        "--output",
        "HDMI-A-2",
    )
    assert done.returncode == 0, done.stderr
    assert "OUTPUT=HDMI-A-2\n" in done.stdout
    assert "as given" in done.stdout


MORNING_UPDATE = (
    'load_previous_state\nprintf "off=%s\\n" "$NO_AUTO_UPDATE"\nMODE=server\nsave_state'
)


def test_the_morning_update_stays_as_it_was_asked(installer: Installer) -> None:
    told = installer.run(MORNING_UPDATE, "--no-auto-update")
    assert "off=1\n" in told.stdout, told.stderr
    assert "off=1\n" in installer.run(MORNING_UPDATE).stdout
    assert "off=0\n" in installer.run(MORNING_UPDATE, "--auto-update").stdout
    assert "off=0\n" in installer.run(MORNING_UPDATE).stdout


def test_the_kiosk_files_come_from_the_release_checked(installer: Installer) -> None:
    installer.kiosk_tarball()
    installer.sums()
    done = installer.run('download_kiosk_files\nprintf "from=%s\\n" "$SRC_DIR"')
    assert done.returncode == 0, done.stderr
    source = installer.temp / "src/kiosk"
    assert f"from={source}\n" in done.stdout
    assert (source / "uninstall.sh").is_file()
    assert (source / "files/sunroom-kiosk-root").is_file()
    assert f"/releases/download/v{installer.version}/kiosk-" in installer.asked()
    assert "codeload" not in installer.asked()


def test_kiosk_files_that_dont_match_are_never_unpacked(installer: Installer) -> None:
    installer.kiosk_tarball()
    installer.sums(**{f"kiosk-{installer.version}.tar.gz": "0" * 64})
    done = installer.run("download_kiosk_files")
    assert done.returncode == 1
    assert "didn't match its checksum" in done.stderr
    assert not (installer.temp / "src/kiosk").exists()


def test_a_release_still_being_published_says_to_wait(installer: Installer) -> None:
    installer.kiosk_tarball()  # its SHA256SUMS, uploaded last, isn't there yet
    done = installer.run("download_kiosk_files")
    assert done.returncode == 1
    assert "still being published" in done.stderr
    assert "copy the whole kiosk folder" in done.stderr


def test_a_missing_file_says_so(installer: Installer) -> None:
    installer.publish(f"sunroom_kiosk-{installer.version}-py3-none-any.whl")
    installer.sums()
    (installer.web / f"sunroom_kiosk-{installer.version}-py3-none-any.whl").unlink()
    done = installer.run("fetch_agent_wheel")
    assert done.returncode == 1
    assert f"Couldn't download Sunroom Screen {installer.version}" in done.stderr


def test_the_wheel_and_the_kiosk_files_share_one_download_of_the_sums(
    installer: Installer,
) -> None:
    wheel = f"sunroom_kiosk-{installer.version}-py3-none-any.whl"
    installer.publish(wheel)
    installer.kiosk_tarball()
    installer.sums()
    done = installer.run("download_kiosk_files\nfetch_agent_wheel")
    assert done.returncode == 0, done.stderr
    assert (installer.home / ".local/share/sunroom-kiosk/wheels" / wheel).is_file()
    assert installer.asked().count("SHA256SUMS") == 1


def test_a_wheel_that_doesnt_match_is_never_kept(installer: Installer) -> None:
    wheel = f"sunroom_kiosk-{installer.version}-py3-none-any.whl"
    installer.publish(wheel)
    installer.sums(**{wheel: "0" * 64})
    done = installer.run("fetch_agent_wheel")
    assert done.returncode == 1
    assert "didn't match its checksum" in done.stderr
    assert not (installer.home / ".local/share/sunroom-kiosk/wheels" / wheel).exists()


UV_RAN = '#!/bin/sh\n: >"$HOME/uv-installer-ran"\n'


@pytest.mark.skipif(
    shutil.which("uv", path="/usr/bin:/bin") is not None, reason="this computer's uv would answer"
)
def test_uvs_installer_runs_only_when_it_matches_the_pin(installer: Installer) -> None:
    script = installer.publish("install.sh", UV_RAN.encode())
    refused = installer.run("install_uv")
    assert refused.returncode == 1
    assert "didn't match its checksum" in refused.stderr
    assert not (installer.home / "uv-installer-ran").exists()

    ran = installer.run(f"UV_INSTALLER_SHA256={sha256(script)}\ninstall_uv")
    assert ran.returncode == 0, ran.stderr
    assert (installer.home / "uv-installer-ran").exists()


def test_the_uv_pins_agree() -> None:
    linux = SCRIPT.read_text()
    windows = (KIOSK / "install.ps1").read_text()
    version = re.search(r'^UV_VERSION="([^"]+)"', linux, re.M)
    assert version is not None
    assert f'$UvVersion = "{version.group(1)}"' in windows
    assert re.search(r'^UV_INSTALLER_SHA256="[0-9a-f]{64}"$', linux, re.M)


def test_the_windows_installer_stays_plain_ascii() -> None:
    """A Release serves it with no charset, and `irm | iex` on Windows PowerShell reads that as
    Latin-1, so anything but ASCII would arrive changed."""
    assert (KIOSK / "install.ps1").read_bytes().isascii()


@pytest.mark.parametrize(
    "path",
    [
        "kiosk/install.sh",
        "kiosk/install.ps1",
        "kiosk/uninstall.sh",
        "kiosk/agent/src/sunroom_kiosk/platform/linux.py",
        "README.md",
        "docs/KIOSK.md",
        "docs/DEPLOY.md",
    ],
)
def test_no_install_line_names_a_branch(path: str) -> None:
    assert "/main/kiosk/install" not in (REPO / path).read_text()


def test_the_line_on_the_wall_is_the_stable_one() -> None:
    assert INSTALL_COMMAND == "curl -fsSL https://sunroom.day/install.sh | bash"
