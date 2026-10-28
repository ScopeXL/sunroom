"""The Raspberry Pi (docs/M7.md T7): Linux, plus what a wall screen built on a Pi can do.

* **Rotation**: ``wlr-randr --output <name> --transform N`` on labwc (``xrandr --rotate`` on X11)
  for now, and ``labwc-rule.py --rotate N --output <name>`` so touch follows the turned picture
  (labwc rereads rc.xml when it's told to, SIGHUP). The agent applies the saved rotation each
  time it starts, after the desktop does.
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
from sunroom_kiosk.platform.base import PlatformError, Runner, run_command, user_id
from sunroom_kiosk.platform.linux import LinuxPlatform
from sunroom_kiosk.schemas import ScreenCapability, ScreenPlatform

log = logs.get("platform")

LABWC_RULE = Path.home() / ".local" / "share" / "sunroom-kiosk" / "labwc-rule.py"
X11_TURNS = {0: "normal", 90: "left", 180: "inverted", 270: "right"}


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

    def can_rotate(self) -> bool:
        tool = "xrandr" if self.session == "x11" else "wlr-randr"
        return self.which(tool) is not None

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

    async def _x11_output(self, want: str) -> str | None:
        """X11's names differ from the kernel's: HDMI-A-1 there is usually HDMI-1 here."""
        result = await self.run(["xrandr", "--query"])
        outputs = [
            line.split()[0]
            for line in result.output.splitlines()
            if len(line.split()) > 1 and line.split()[1] == "connected"
        ]
        for name in (want, want.replace("HDMI-A-", "HDMI-")):
            if name and name in outputs:
                return name
        return outputs[0] if outputs else None

    async def turn(self, rotation: int, output: str) -> None:
        """Turn the picture now (no touch, no files)."""
        if self.session == "x11":
            name = await self._x11_output(output)
            if name is None:
                raise PlatformError("No screen was found to turn.")
            argv = ["xrandr", "--output", name, "--rotate", X11_TURNS[rotation]]
        else:
            if not output:
                raise PlatformError("This screen's name isn't known, so it can't be turned here.")
            argv = [
                "wlr-randr",
                "--output",
                output,
                "--transform",
                str(rotation) if rotation else "normal",
            ]
        result = await self.run(argv)
        if not result.ok:
            log.info("%s didn't work: %s", " ".join(argv), result.first_line())
            raise PlatformError("The picture didn't turn. Try again in a moment.")

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

    async def prepare_session(self, rotation: int, output: str) -> None:
        await super().prepare_session(rotation, output)
        if rotation:
            try:
                await self.turn(rotation, output)
            except PlatformError as error:
                log.info("%s", error)

    # ------------------------------------------------------------------ root's part
    # (the browser's policy goes through the root helper as on any Linux screen)

    async def update_sunroom(self) -> bool:
        """An all-in-one Pi's own Sunroom, through /opt/sunroom/update.sh."""
        return await self._as_root("update-sunroom", limit=900.0)
