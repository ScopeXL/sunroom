"""The Raspberry Pi (docs/M7.md T7): Linux, plus what a wall screen built on a Pi can do.

* **Rotation**: the Linux adapter's turn (``wlr-randr --output <name> --transform N`` on labwc,
  ``xrandr --rotate`` on X11), and ``labwc-rule.py --rotate N --output <name>`` so touch follows
  the turned picture (labwc rereads rc.xml when it's told to, SIGHUP). The agent applies the
  saved rotation each time it starts, after the desktop does.
* **The root helper** ``/usr/local/sbin/sunroom-kiosk-root`` (kiosk/files, allowed by
  ``/etc/sudoers.d/sunroom-kiosk`` for this user only, and only it): the browser's policy file,
  and ``/opt/sunroom/update.sh`` on an all-in-one Pi. Nothing else here needs root: logind lets
  the session restart and power off, and the user is in netdev.
* **Sunroom here**: an all-in-one Pi (``install.sh --with-sunroom``) runs it in Docker, which the
  agent updates through the helper; any other Pi runs it as a program, as any computer does
  (local.py, ADR 0038).
"""

from __future__ import annotations

import shutil
import sys
from collections.abc import Callable, Mapping
from pathlib import Path

from sunroom_kiosk import logs
from sunroom_kiosk.platform.base import Runner, run_command, user_id
from sunroom_kiosk.platform.linux import LinuxPlatform
from sunroom_kiosk.schemas import ScreenCapability, ScreenPlatform

log = logs.get("platform")

LABWC_RULE = Path.home() / ".local" / "share" / "sunroom-kiosk" / "labwc-rule.py"


def is_pi(root: Path = Path("/")) -> bool:
    try:
        model = (root / "proc/device-tree/model").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return "raspberry pi" in model.lower()


class PiPlatform(LinuxPlatform):
    def __init__(
        self,
        runner: Runner = run_command,
        root: Path = Path("/"),
        *,
        environ: Mapping[str, str] | None = None,
        which: Callable[[str], str | None] = shutil.which,
        labwc_rule: Path = LABWC_RULE,
        version: str = "dev",
    ) -> None:
        super().__init__(runner, root, environ=environ, which=which)
        self.labwc_rule = labwc_rule
        self.version = version

    # ------------------------------------------------------------------ what it is

    @property
    def name(self) -> ScreenPlatform:
        return "pi"

    @property
    def model(self) -> str:
        return self._read("proc/device-tree/model") or "Raspberry Pi"

    def capabilities(self) -> list[ScreenCapability]:
        have: list[ScreenCapability] = ["restart", "shutdown", "update"]
        if self.has_wifi():
            have.append("wifi")
        if self.can_rotate():
            have.append("rotate")
        have.append("brightness")  # the agent drops it when the helper found no way to dim
        if self._root_helper() and (self.root / "opt/sunroom/update.sh").exists():
            have.append("update_sunroom")  # the agent keeps it only while it shows that Sunroom
        return have

    # ------------------------------------------------------------------ the screen

    async def follow_touch(self, rotation: int, output: str) -> None:
        """Touch follows the turned picture from labwc's next read of rc.xml, asked for now."""
        if self.session == "x11" or not self.labwc_rule.exists():
            return
        argv = [sys.executable, str(self.labwc_rule), "--rotate", str(rotation)]
        if output:
            argv += ["--output", output]
        argv += ["--installer-version", self.version]
        result = await self.run(argv)
        if not result.ok:
            log.info("Touch may not follow the turned picture: %s", result.first_line())
            return
        await self.run(["pkill", "-HUP", "-u", user_id(), "-x", "labwc"])

    async def rotate(self, rotation: int, output: str) -> None:
        await self.turn(rotation, output)
        await self.follow_touch(rotation, output)

    # ------------------------------------------------------------------ root's part
    # (the browser's policy goes through the root helper as on any Linux screen)

    async def update_sunroom(self) -> bool:
        """An all-in-one Pi's own Sunroom, through /opt/sunroom/update.sh."""
        return await self._as_root("update-sunroom", limit=900.0)
