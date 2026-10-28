"""Linux: any desktop, and the base of the Raspberry Pi's adapter (docs/M7.md T7).

* **Power** through logind: ``systemctl reboot`` and ``poweroff``, which the active local
  session may do without a password.
* **Wi-Fi** through NetworkManager's ``nmcli``, when it's there and running. A password never
  goes on a command line (any user can read those): the connection is made without it, then
  brought up with ``passwd-file /dev/stdin``, the password on stdin.
* **Before the browser starts** (what ``kiosk/sunroom-kiosk`` did in bash): wait for the desktop
  (a Wayland socket or an X display), and up to a minute for the clock; on X11, switch off the
  screensaver and blanking (``xset s off``, ``xset dpms 0 0 0``, never ``xset -dpms``) and hide
  the pointer with ``unclutter``.
* **The root helper** ``/usr/local/sbin/sunroom-kiosk-root`` (kiosk/files, allowed by
  ``/etc/sudoers.d/sunroom-kiosk`` for this user only), which the installer puts on every Linux
  screen since ADR 0038: it writes the browser's policy, so Chrome's Local Network Access never
  asks on the screen.
* **Rotation** (ADR 0042), for a display mounted on its side that the computer doesn't know
  about: ``kscreen-doctor`` on KDE Plasma, ``xrandr`` on X11 (touch screens mapped to the turned
  output with ``xinput map-to-output``), ``wlr-randr`` on a wlroots compositor (labwc, sway). The
  output is the installer's ``--output`` or, without one, the one the tool says is primary, else
  the first connected; the saved rotation is applied again as the agent starts. GNOME on Wayland
  has none of these tools, so its screens have no Rotation row.

A desktop that isn't a Pi can Quit (Sunroom Screen stops until the next sign-in), and the root
helper does nothing else for it (its system updates aren't ours).
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, Literal, cast

from sunroom_kiosk import logs, policy
from sunroom_kiosk.platform.base import (
    CommandResult,
    NetworkStatus,
    Platform,
    PlatformError,
    Runner,
    WifiNetwork,
    local_ip,
    run_command,
    user_id,
)
from sunroom_kiosk.schemas import ScreenCapability, ScreenSession

log = logs.get("platform")

ROOT_HELPER = "/usr/local/sbin/sunroom-kiosk-root"
DESKTOP_WAIT_S = 2.0
CLOCK_TRIES = 30  # 2 s apart: a minute
# The agent's rotations (counter-clockwise: 90 puts the picture's top at the left) in each tool's
# words: xrandr and kscreen-doctor say left for it, wlr-randr's transform the degrees.
X11_TURNS = {0: "normal", 90: "left", 180: "inverted", 270: "right"}
KDE_TURNS = X11_TURNS
type RotationTool = Literal["kscreen-doctor", "xrandr", "wlr-randr"]


def split_terse(line: str) -> list[str]:
    """One line of ``nmcli -t`` output: fields split on ``:``, with ``\\:`` and ``\\\\`` undone."""
    fields: list[str] = []
    current: list[str] = []
    escaped = False
    for char in line:
        if escaped:
            current.append(char)
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == ":":
            fields.append("".join(current))
            current = []
        else:
            current.append(char)
    fields.append("".join(current))
    return fields


def wifi_from(listing: str, saved_names: set[str]) -> list[WifiNetwork]:
    """``nmcli -t -f IN-USE,SSID,SIGNAL,SECURITY device wifi list``: one row per network (the
    strongest of its access points), hidden networks left out."""
    best: dict[str, WifiNetwork] = {}
    for line in listing.splitlines():
        fields = split_terse(line)
        if len(fields) < 4 or not fields[1]:
            continue
        in_use, ssid, signal, security = fields[0], fields[1], fields[2], fields[3]
        try:
            strength = max(0, min(100, int(signal)))
        except ValueError:
            strength = 0
        saved = ssid in saved_names
        network = WifiNetwork(
            id=ssid if saved else None,
            ssid=ssid,
            strength=strength,
            secured=bool(security.strip()) and security.strip() != "--",
            connected=in_use.strip() == "*",
            saved=saved,
        )
        known = best.get(ssid)
        if (
            known is None
            or network.connected
            or (not known.connected and strength > known.strength)
        ):
            best[ssid] = network
    return list(best.values())


def x11_outputs(query: str) -> tuple[list[str], str | None]:
    """``xrandr --query``: the connected outputs in order, and the primary one."""
    connected: list[str] = []
    primary: str | None = None
    for line in query.splitlines():
        words = line.split()
        if len(words) > 1 and words[1] == "connected":
            connected.append(words[0])
            if len(words) > 2 and words[2] == "primary":
                primary = words[0]
    return connected, primary


def wlr_outputs(listing: str) -> list[str]:
    """``wlr-randr``'s plain listing: the enabled outputs in order (each starts a line, its
    properties indented under it)."""
    enabled: list[str] = []
    name: str | None = None
    for line in listing.splitlines():
        if line and not line[0].isspace():
            name = line.split()[0]
        elif name and line.strip() == "Enabled: yes":
            enabled.append(name)
    return enabled


def kde_output(listing: str) -> str | None:
    """``kscreen-doctor --json``: the enabled, connected output Plasma puts first (``priority``
    1; ``primary`` before Plasma 5.25), else the first such."""
    try:
        found = json.loads(listing)
    except ValueError:
        return None
    if not isinstance(found, dict):
        return None
    outputs = cast(dict[str, Any], found).get("outputs")
    if not isinstance(outputs, list):
        return None
    ready: list[dict[str, Any]] = [
        cast(dict[str, Any], output)
        for output in cast(list[object], outputs)
        if isinstance(output, dict)
        and cast(dict[str, Any], output).get("enabled")
        and cast(dict[str, Any], output).get("connected")
        and isinstance(cast(dict[str, Any], output).get("name"), str)
    ]
    if not ready:
        return None

    def first(output: dict[str, Any]) -> int:
        if output.get("primary") is True:
            return 0
        priority = output.get("priority")
        return priority if isinstance(priority, int) and priority > 0 else 1000

    return str(min(ready, key=first)["name"])


def touch_screens(listing: str) -> list[str]:
    """``xinput list --long``: the ids of direct-touch devices (a touch screen, not a pad)."""
    ids: list[str] = []
    current: str | None = None
    for line in listing.splitlines():
        if "id=" in line:
            current = line.split("id=", 1)[1].split()[0]
        elif current and line.strip() == "Touch mode: direct" and current not in ids:
            ids.append(current)
    return ids


def join_problem(ssid: str, result: CommandResult) -> str:
    """What nmcli's refusal means, in the family's words."""
    text = result.output.lower()
    if "secrets were required" in text or "psk" in text or "password" in text:
        return f"That password didn't work for {ssid}. Check it and try again."
    if "no network with ssid" in text or "not found" in text:
        return f"{ssid} is out of range. Move closer, or try another network."
    return f"Couldn't join {ssid}. Try again in a moment."


class LinuxPlatform(Platform):
    def __init__(
        self,
        runner: Runner = run_command,
        root: Path = Path("/"),
        *,
        environ: Mapping[str, str] | None = None,
        which: Callable[[str], str | None] = shutil.which,
    ) -> None:
        super().__init__(runner, root)
        self.environ: Mapping[str, str] = os.environ if environ is None else environ
        self.which = which

    # ------------------------------------------------------------------ what it is

    @property
    def session(self) -> ScreenSession:
        kind = self.environ.get("XDG_SESSION_TYPE", "")
        if kind == "x11":
            return "x11"
        if kind == "wayland" or self.environ.get("WAYLAND_DISPLAY"):
            return "wayland"
        return "x11" if self.environ.get("DISPLAY") else "desktop"

    @property
    def model(self) -> str:
        name = self._read("sys/devices/virtual/dmi/id/product_name")
        return name or "Computer"

    @property
    def system(self) -> str:
        for line in self._read("etc/os-release").splitlines():
            key, _, value = line.partition("=")
            if key == "PRETTY_NAME":
                return value.strip().strip('"') or "Linux"
        return "Linux"

    def _read(self, relative: str) -> str:
        try:
            return (
                (self.root / relative)
                .read_text(encoding="utf-8", errors="replace")
                .strip("\x00\n ")
            )
        except OSError:
            return ""

    def has_wifi(self) -> bool:
        return self.which("nmcli") is not None

    def rotation_tool(self) -> RotationTool | None:
        """What turns this desktop's picture, if anything does (ADR 0042)."""
        desktop = self.environ.get("XDG_CURRENT_DESKTOP", "").lower()
        if "kde" in desktop and self.which("kscreen-doctor") is not None:
            return "kscreen-doctor"
        if self.session == "x11":
            return "xrandr" if self.which("xrandr") is not None else None
        if self.session == "wayland" and not any(name in desktop for name in ("gnome", "kde")):
            return "wlr-randr" if self.which("wlr-randr") is not None else None
        return None

    def can_rotate(self) -> bool:
        return self.rotation_tool() is not None

    def _root_helper(self) -> bool:
        return (self.root / ROOT_HELPER.lstrip("/")).exists()

    def capabilities(self) -> list[ScreenCapability]:
        have: list[ScreenCapability] = ["restart", "shutdown", "update"]
        if self.has_wifi():
            have.append("wifi")
        if self.can_rotate():
            have.append("rotate")
        have.append("quit")
        return have

    # ------------------------------------------------------------------ root's part

    async def _as_root(self, *args: str, stdin: str | None = None, limit: float = 60.0) -> bool:
        """The root helper, when the installer put it here (a screen set up before ADR 0038
        has none, and its browser asks once instead)."""
        if not self._root_helper():
            return False
        result = await self.run(["sudo", "-n", ROOT_HELPER, *args], stdin=stdin, limit=limit)
        if not result.ok:
            log.info("The root helper's %s didn't work: %s", args[0], result.first_line())
        return result.ok

    async def write_policy(self, kind: policy.BrowserKind, document: dict[str, Any]) -> bool:
        return await self._as_root(
            "write-policy",
            policy.linux_path(kind).as_posix(),
            stdin=json.dumps(document, sort_keys=True),
        )

    # ------------------------------------------------------------------ the machine

    async def _must(self, argv: list[str], what: str, stdin: str | None = None) -> CommandResult:
        result = await self.run(argv, stdin=stdin)
        if not result.ok:
            log.info("%s didn't work: %s", " ".join(argv[:3]), result.first_line())
            raise PlatformError(f"{what} didn't work. Try again in a moment.")
        return result

    async def restart(self) -> None:
        await self._must(["systemctl", "reboot"], "Restarting")

    async def shutdown(self) -> None:
        await self._must(["systemctl", "poweroff"], "Shutting down")

    # ------------------------------------------------------------------ the screen

    async def _output(self, tool: RotationTool, want: str) -> str | None:
        """The output to turn: the one the installer named (as the tool calls it), else the
        primary one, else the first connected."""
        if tool == "xrandr":
            connected, primary = x11_outputs((await self.run(["xrandr", "--query"])).output)
            # X11's names differ from the kernel's: HDMI-A-1 there is usually HDMI-1 here.
            for name in (want, want.replace("HDMI-A-", "HDMI-")):
                if name and name in connected:
                    return name
            return primary or (connected[0] if connected else None)
        if want:
            return want
        if tool == "wlr-randr":
            enabled = wlr_outputs((await self.run(["wlr-randr"])).output)
            return enabled[0] if enabled else None
        return kde_output((await self.run(["kscreen-doctor", "--json"])).output)

    async def turn(self, rotation: int, output: str) -> None:
        """Turn the picture now (touch follows on X11; a Pi's labwc rule follows it there)."""
        tool = self.rotation_tool()
        if tool is None:
            raise PlatformError("Turning the picture isn't something this screen can do.")
        name = await self._output(tool, output)
        if name is None:
            raise PlatformError("No screen was found to turn.")
        if tool == "xrandr":
            argv = ["xrandr", "--output", name, "--rotate", X11_TURNS[rotation]]
        elif tool == "wlr-randr":
            transform = str(rotation) if rotation else "normal"
            argv = ["wlr-randr", "--output", name, "--transform", transform]
        else:
            argv = ["kscreen-doctor", f"output.{name}.rotation.{KDE_TURNS[rotation]}"]
        result = await self.run(argv)
        if not result.ok:
            log.info("%s didn't work: %s", " ".join(argv), result.first_line())
            raise PlatformError("The picture didn't turn. Try again in a moment.")
        if tool == "xrandr" and self.which("xinput") is not None:
            for device in touch_screens((await self.run(["xinput", "list", "--long"])).output):
                await self.run(["xinput", "map-to-output", device, name])

    async def rotate(self, rotation: int, output: str) -> None:
        await self.turn(rotation, output)

    # ------------------------------------------------------------------ the network

    async def network(self) -> NetworkStatus:
        if not self.has_wifi():
            return await super().network()
        devices = await self.run(["nmcli", "-t", "-f", "TYPE,STATE", "device"])
        wired = wifi = False
        for line in devices.output.splitlines():
            fields = split_terse(line)
            if len(fields) >= 2 and fields[1] == "connected":
                wired = wired or fields[0] == "ethernet"
                wifi = wifi or fields[0] == "wifi"
        ip = local_ip()
        if wired:
            return NetworkStatus(kind="wired", ip=ip)
        if wifi:
            joined = next((n for n in await self._scan(rescan=False) if n.connected), None)
            return NetworkStatus(
                kind="wifi",
                ssid=joined.ssid if joined else None,
                ip=ip,
                strength=joined.strength if joined else None,
            )
        return NetworkStatus(kind="none", ip=ip)

    async def _saved(self) -> set[str]:
        result = await self.run(["nmcli", "-t", "-f", "NAME,TYPE", "connection", "show"])
        names: set[str] = set()
        for line in result.output.splitlines():
            fields = split_terse(line)
            if len(fields) >= 2 and fields[1] in ("802-11-wireless", "wifi"):
                names.add(fields[0])
        return names

    async def _scan(self, *, rescan: bool) -> list[WifiNetwork]:
        result = await self.run(
            [
                "nmcli",
                "-t",
                "-f",
                "IN-USE,SSID,SIGNAL,SECURITY",
                "device",
                "wifi",
                "list",
                "--rescan",
                "auto" if rescan else "no",
            ],
            limit=30.0,
        )
        if not result.ok:
            raise PlatformError("This screen's Wi-Fi didn't answer. Try again in a moment.")
        return wifi_from(result.output, await self._saved())

    async def wifi_networks(self) -> list[WifiNetwork]:
        return await self._scan(rescan=True)

    async def wifi_join(self, ssid: str, password: str) -> None:
        networks = {n.ssid: n for n in await self._scan(rescan=False)}
        network = networks.get(ssid)
        if network is not None and network.saved and not password:
            result = await self.run(["nmcli", "connection", "up", "id", ssid], limit=60.0)
        elif not password:
            result = await self.run(["nmcli", "device", "wifi", "connect", ssid], limit=60.0)
        else:
            # Made without the password, then brought up with it on stdin (never in argv).
            await self.run(["nmcli", "connection", "delete", "id", ssid])
            added = await self.run(
                [
                    "nmcli",
                    "connection",
                    "add",
                    "type",
                    "wifi",
                    "con-name",
                    ssid,
                    "ssid",
                    ssid,
                    "wifi-sec.key-mgmt",
                    "wpa-psk",
                ]
            )
            if not added.ok:
                raise PlatformError(join_problem(ssid, added))
            result = await self.run(
                ["nmcli", "connection", "up", "id", ssid, "passwd-file", "/dev/stdin"],
                stdin=f"802-11-wireless-security.psk:{password}\n",
                limit=60.0,
            )
            if not result.ok:
                await self.run(["nmcli", "connection", "delete", "id", ssid])
        if not result.ok:
            raise PlatformError(join_problem(ssid, result))

    async def wifi_forget(self, network_id: str) -> None:
        await self._must(["nmcli", "connection", "delete", "id", network_id], "Forgetting it")

    # ------------------------------------------------------------------ before the browser

    async def wait_for_desktop(self) -> None:
        """A compositor to draw on: started too early, the browser only crashes and restarts."""
        waited = 0.0
        while not self._desktop_up():
            if waited % 60 == 0:
                log.info("Waiting for the desktop to start (no display yet).")
            await asyncio.sleep(DESKTOP_WAIT_S)
            waited += DESKTOP_WAIT_S

    def _desktop_up(self) -> bool:
        socket = self.environ.get("WAYLAND_DISPLAY", "")
        if socket:
            if not socket.startswith("/"):
                runtime = self.environ.get("XDG_RUNTIME_DIR", f"/run/user/{user_id()}")
                socket = os.path.join(runtime, socket)
            return Path(socket).exists()
        return bool(self.environ.get("DISPLAY"))

    async def wait_for_clock(self) -> None:
        """A Pi has no clock of its own: up to a minute for it to be set from the internet."""
        if self.which("timedatectl") is None:
            return
        for _ in range(CLOCK_TRIES):
            result = await self.run(["timedatectl", "show", "-p", "NTPSynchronized", "--value"])
            if result.output.strip() == "yes":
                return
            await asyncio.sleep(2)
        log.info("The clock hasn't been set after a minute; starting anyway.")

    async def prepare_session(self, rotation: int, output: str) -> None:
        await self._blank_off()
        if rotation and self.can_rotate():
            try:
                await self.turn(rotation, output)
            except PlatformError as error:
                log.info("%s", error)

    async def _blank_off(self) -> None:
        if self.session != "x11":
            return
        for argv in (
            ["xset", "s", "off"],
            ["xset", "dpms", "0", "0", "0"],
            ["xset", "s", "noblank"],
        ):
            await self.run(argv)
        if self.which("unclutter") is not None:
            running = await self.run(["pgrep", "-u", user_id(), "-x", "unclutter"])
            if not running.ok:
                await asyncio.create_subprocess_exec(
                    "unclutter",
                    "-idle",
                    "1",
                    "-root",
                    stdin=asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
