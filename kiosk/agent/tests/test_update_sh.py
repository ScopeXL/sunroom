"""kiosk/update.sh, the way a Pi with Sunroom in Docker updates (ADR 0046), run for real with a
pretend docker and curl on PATH: a pull that fails changes nothing, a version that never turns
healthy goes back by itself, restoring the database copy if it had changed it, and a pinned version
stays. Synthetic data only."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "update.sh"

pytestmark = pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("bash") is None, reason="update.sh is for a Pi"
)

COMPOSE = """services:
  sunroom:
    image: scopexl/sunroom:{tag}
    ports:
      - "7867:7867"
"""

# What the versions do, by the tag in the compose file: `versions` maps a tag to its version, and
# `broken` lists the versions that never answer. A version that refuses the database exits 65.
DOCKER = r"""#!/usr/bin/env bash
echo "docker $*" >>"$FAKE/calls"
tag() { sed -nE 's#.*image: scopexl/sunroom:([^ ]*).*#\1#p' "$SUNROOM_DIR/docker-compose.yml"; }
case "$*" in
  "compose version") exit 0 ;;
  *" pull"*)
    [ -f "$FAKE/pull-fails" ] && exit 1
    exit 0 ;;
  *" up -d"*) tag >"$FAKE/running"; exit 0 ;;
  *" port "*) echo "0.0.0.0:7867"; exit 0 ;;
  *" stop "*) exit 0 ;;
  *"run --rm --no-deps --entrypoint sh"*) echo "sunroom.0.18.0-to-new.db"; exit 0 ;;
  *"run --rm --no-deps sunroom restore"*) touch "$FAKE/restored"; exit 0 ;;
  "pull -q "*) [ -f "$FAKE/pull-fails" ] && exit 1; exit 0 ;;
  "image inspect"*) cat "$FAKE/newest"; exit 0 ;;
  "inspect --format {{.Image}} sunroom") echo "image-$(cat "$FAKE/running")"; exit 0 ;;
  "inspect --format {{.State.ExitCode}} sunroom")
    if [ -f "$FAKE/refuses-$(cat "$FAKE/running")" ] && [ ! -f "$FAKE/restored" ]; then
      echo 65
    else
      echo 0
    fi
    exit 0 ;;
  "logs "*) echo "a log line"; exit 0 ;;
esac
exit 0
"""

CURL = r"""#!/usr/bin/env bash
running=$(cat "$FAKE/running")
version=$(cat "$FAKE/version-$running" 2>/dev/null || echo "$running")
case "$*" in
  *api/health*)
    if [ -f "$FAKE/broken-$version" ]; then printf 503; exit 0; fi
    if [ -f "$FAKE/refuses-$running" ] && [ ! -f "$FAKE/restored" ]; then printf 503; exit 0; fi
    printf 200 ;;
  *api/version*) printf '{"version":"%s"}' "$version" ;;
esac
"""

ID = "#!/usr/bin/env bash\necho 0\n"
SLEEP = "#!/usr/bin/env bash\nexit 0\n"


class Pi:
    def __init__(self, tmp_path: Path, tag: str, version: str, newest: str) -> None:
        self.dir = tmp_path / "opt-sunroom"
        self.dir.mkdir()
        self.fake = tmp_path / "fake"
        self.fake.mkdir()
        self.bin = tmp_path / "bin"
        self.bin.mkdir()
        for name, body in {"docker": DOCKER, "curl": CURL, "id": ID, "sleep": SLEEP}.items():
            path = self.bin / name
            path.write_text(body)
            path.chmod(path.stat().st_mode | stat.S_IEXEC)
        self.compose = self.dir / "docker-compose.yml"
        self.compose.write_text(COMPOSE.format(tag=tag))
        (self.fake / "running").write_text(tag)
        (self.fake / f"version-{tag}").write_text(version)
        if tag != "latest":
            (self.fake / "version-latest").write_text(newest)
        self.newest(newest)

    def newest(self, version: str) -> None:
        """What `latest` is on Docker Hub, now."""
        (self.fake / "newest").write_text(version)

    def flag(self, name: str) -> None:
        (self.fake / name).touch()

    def tag(self) -> str:
        for line in self.compose.read_text().splitlines():
            if "image:" in line:
                return line.rsplit(":", 1)[1].strip()
        raise AssertionError("no image line")

    def outcome(self) -> str:
        return (self.dir / "last-update").read_text().strip()

    def calls(self) -> str:
        return (self.fake / "calls").read_text()

    def update(self, *args: str) -> subprocess.CompletedProcess[str]:
        env = {
            **os.environ,
            "PATH": f"{self.bin}:{os.environ['PATH']}",
            "SUNROOM_DIR": str(self.dir),
            "FAKE": str(self.fake),
            "HEALTH_TIMEOUT": "4",
        }
        return subprocess.run(  # noqa: S603 - our own script, on a pretend folder
            ["bash", str(SCRIPT), *args],  # noqa: S607 - whichever bash the tests run under
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )


def test_it_updates_to_the_newest(tmp_path: Path) -> None:
    pi = Pi(tmp_path, "latest", "0.19.0", "0.19.0")
    done = pi.update()
    assert done.returncode == 0, done.stdout + done.stderr
    assert pi.tag() == "latest"
    assert pi.outcome() == "updated 0.19.0"


def test_a_pull_that_fails_changes_nothing(tmp_path: Path) -> None:
    pi = Pi(tmp_path, "0.18.0", "0.18.0", "0.19.0")
    pi.flag("pull-fails")
    done = pi.update("latest")
    assert done.returncode != 0
    assert "so nothing was changed" in done.stderr
    assert pi.tag() == "0.18.0"
    assert pi.outcome() == "failed"
    assert " up -d" not in pi.calls()


def test_a_pinned_version_stays_pinned(tmp_path: Path) -> None:
    pi = Pi(tmp_path, "0.18.0", "0.18.0", "0.19.0")
    done = pi.update()
    assert done.returncode == 0
    assert "pinned to 0.18.0" in done.stdout
    assert pi.tag() == "0.18.0"
    assert pi.outcome() == "left-alone 0.18.0"
    assert " up -d" not in pi.calls()


def test_asking_for_the_newest_or_a_version_moves_a_pin(tmp_path: Path) -> None:
    pi = Pi(tmp_path, "0.18.0", "0.18.0", "0.19.0")
    done = pi.update("latest")
    assert done.returncode == 0, done.stdout + done.stderr
    assert pi.tag() == "latest"
    assert pi.outcome() == "updated 0.19.0"
    (pi.fake / "version-0.17.0").write_text("0.17.0")
    done = pi.update("0.17.0")
    assert done.returncode == 0, done.stdout + done.stderr
    assert pi.tag() == "0.17.0"


def a_bad_update(tmp_path: Path) -> Pi:
    """Running 0.18.0 under `latest`, and the new `latest` is 0.19.0, which never turns healthy.
    The pretend `latest` answers as what's running until the pull: so start it as 0.18.0."""
    pi = Pi(tmp_path, "latest", "0.18.0", "0.19.0")
    (pi.fake / "version-0.18.0").write_text("0.18.0")
    # After the pull, `latest` is the broken one.
    docker = pi.bin / "docker"
    docker.write_text(
        docker.read_text().replace(
            '  *" pull"*)\n',
            '  *" pull"*)\n    echo 0.19.0 >"$FAKE/version-latest"\n',
        )
    )
    pi.flag("broken-0.19.0")
    return pi


def test_a_version_that_never_turns_healthy_goes_back_by_itself(tmp_path: Path) -> None:
    pi = a_bad_update(tmp_path)
    done = pi.update()
    assert done.returncode == 3, done.stdout + done.stderr
    assert "Sunroom 0.19.0 didn't start, so 0.18.0 is back." in done.stdout
    assert pi.tag() == "0.18.0"
    assert pi.outcome() == "went-back 0.19.0 0.18.0"
    assert (pi.dir / "held-back").read_text().split() == ["0.18.0", "0.19.0"]


def test_a_database_the_old_version_refuses_is_restored_first(tmp_path: Path) -> None:
    pi = a_bad_update(tmp_path)
    pi.flag("refuses-0.18.0")
    done = pi.update()
    assert done.returncode == 3, done.stdout + done.stderr
    assert (pi.fake / "restored").exists()
    assert "putting back the copy taken before it" in done.stdout
    assert "restore /data/backups/pre-migrate/sunroom.0.18.0-to-new.db" in pi.calls()
    assert pi.outcome() == "went-back 0.19.0 0.18.0"


def test_a_held_version_waits_for_something_newer_than_what_failed(tmp_path: Path) -> None:
    pi = a_bad_update(tmp_path)
    assert pi.update().returncode == 3
    # The same night's version is still the newest: it stays, and doesn't restart anything.
    calls_before = pi.calls()
    done = pi.update()
    assert done.returncode == 0, done.stdout + done.stderr
    assert "didn't start here, and nothing newer is out" in done.stdout
    assert pi.outcome() == "left-alone 0.18.0"
    assert " up -d" not in pi.calls()[len(calls_before) :]
    # A fixed version comes out: it moves on, and follows the newest again.
    pi.newest("0.19.1")
    (pi.fake / "broken-0.19.0").unlink()
    (pi.fake / "version-latest").write_text("0.19.1")
    docker = pi.bin / "docker"
    docker.write_text(docker.read_text().replace("echo 0.19.0 >", "echo 0.19.1 >"))
    done = pi.update()
    assert done.returncode == 0, done.stdout + done.stderr
    assert pi.tag() == "latest"
    assert pi.outcome() == "updated 0.19.1"
    assert not (pi.dir / "held-back").exists()


def test_a_pin_that_fails_goes_back_to_the_pin(tmp_path: Path) -> None:
    pi = Pi(tmp_path, "0.18.0", "0.18.0", "0.19.0")
    (pi.fake / "version-0.19.0").write_text("0.19.0")
    pi.flag("broken-0.19.0")
    done = pi.update("0.19.0")
    assert done.returncode == 3, done.stdout + done.stderr
    assert pi.tag() == "0.18.0"
    # The family's own pin, not a hold: it stays until they change it.
    assert not (pi.dir / "held-back").exists()
