"""``sunroom-kiosk setup`` (ADR 0044, docs/KIOSK.md "What it changes"): Sunroom Screen keeps its
own setup in order, from the templates its wheel carries (``files.py``) and this screen's settings.

It renders each file the installer puts in place for this user, compares, and rewrites what
differs: the user service (Linux) or the LaunchAgent (a Mac) or the start-up entry (Windows'
``Run`` value), the desktop's autostart (labwc's block and window rule on a Pi, an XDG entry on
X11 and other Linux desktops), the helper copies the uninstaller and labwc need, the service of
Sunroom run here, the settings file (brought to this version's keys) and the install-state the
uninstaller reads. It runs at every start, so a file someone broke heals itself; after every
update, before the new version starts (``apply.py``); from This Screen's Reinstall…; and on the
installers' first install: one way to set a screen up, and it is Sunroom Screen's.

Root's files are never written here: ``needs_root`` names those that differ (the root helper, the
Wi-Fi, backlight and i2c files, an all-in-one Pi's avahi service), for the root helper's
``apply-system``. A file that differs only by the version that wrote it is rewritten quietly; a
restart (the service's own definition) or a reboot (labwc's autostart and window rule) is asked
for only when what the file says has changed. Before the first change, the small files are copied
aside (the last three versions' copies are kept); the browser's profile, which holds the pairing,
and Sunroom's data are never touched.
"""

from __future__ import annotations

import json
import os
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast

from sunroom_kiosk import config as settings_file
from sunroom_kiosk import local
from sunroom_kiosk.files import files_dir, script
from sunroom_kiosk.platform.base import user_id
from sunroom_kiosk.updater import newer
from sunroom_kiosk.version import version

if TYPE_CHECKING:
    from sunroom_kiosk.platform.windows import Registry

SYSTEM_PART_SINCE = "0.18.0"
"""The version whose root-owned files last changed (kiosk/files: the root helper, the sudoers
rule, the Wi-Fi, backlight and i2c files, the avahi service; the packages lists). A session that
changes one of them bumps this to the release it ships in: a screen whose root helper is older
can't finish that release's update by itself, and says so on This Screen."""


def needs_terminal(
    helper_version: str | None, needs_root: list[str], install_command: str | None
) -> str | None:
    """The installer's one line, when root's part differs and this screen's root helper can't
    put it right by itself: none, or one from before SYSTEM_PART_SINCE (it has no
    ``apply-system``). This Screen shows it under Software (ADR 0044)."""
    if install_command is None or not needs_root:
        return None
    if helper_version is not None and not newer(SYSTEM_PART_SINCE, helper_version):
        return None
    return install_command


BLOCK_BEGIN = "# >>> sunroom-kiosk"
BLOCK_END = "# <<< sunroom-kiosk <<<"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "SunroomScreen"
BACKUPS_KEPT = 3

type Kind = Literal["pi", "linux", "macos", "windows"]
type After = Literal["restart", "reboot"] | None
type Command = Callable[[list[str]], bool]

# What says who wrote a file, and the versions in it: neither counts as a change.
_STAMP = re.compile(
    r"^.*\b[Ww]ritten by (?:the Sunroom installer|Sunroom Screen)\b.*(?:\n|$)", re.M
)
_VERSION = re.compile(r"\b\d+\.\d+\.\d+(?:[-+.][0-9A-Za-z][0-9A-Za-z.-]*)?\b")
_STATE_HEADER = (
    "# What Sunroom's setup changed outside its own files, read by kiosk/uninstall.sh to put\n"
    "# things back. Sunroom Screen and the installer keep it up to date.\n"
)


def comparable(text: str) -> str:
    """A file's words that matter: without the line saying who wrote it, every version a mark."""
    return _VERSION.sub("@VERSION@", _STAMP.sub("", text))


def header_comment(release: str) -> str:
    """The line every file of the screen's setup starts with (``install.sh``'s, word for word)."""
    return (
        f"# Written by the Sunroom installer (kiosk/install.sh {release}). Running it again "
        "replaces this file.\n"
    )


def stamp(text: str, release: str) -> str:
    """``text`` with the header after any ``#!`` line, as the installer's ``stamp_file``."""
    if text.startswith("#!"):
        first, _, rest = text.partition("\n")
        return f"{first}\n{header_comment(release)}{rest}"
    return header_comment(release) + text


def render(text: str, values: dict[str, str]) -> str:
    """The installer's ``render``: each ``@NAME@`` placeholder it knows filled in, others left."""
    for name, value in values.items():
        text = text.replace(f"@{name}@", value)
    return text


def run_quietly(argv: list[str]) -> bool:
    try:
        done = subprocess.run(  # noqa: S603 - our own, fixed commands
            argv, capture_output=True, text=True, check=False, timeout=30
        )
    except OSError, subprocess.TimeoutExpired:
        return False
    return done.returncode == 0


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except UnicodeDecodeError:
        return path.read_bytes().decode("utf-8", errors="replace")


def _write(path: Path, text: str, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
    ) as tmp:
        tmp.write(text)
    if sys.platform != "win32":
        os.chmod(tmp.name, mode)
    os.replace(tmp.name, path)


def set_lines(existing: str, wanted: dict[str, str], header: str) -> str:
    """``existing`` with each of ``wanted``'s keys set in place (bash-quoted), new ones added at
    the end, every other line kept; a new file starts with ``header``."""
    if not existing.strip():
        existing = header
    return settings_file.set_values(existing, wanted)


# ---------------------------------------------------------------------- the machine


@dataclass(frozen=True)
class Machine:
    """What the setup is for: the kind of computer, this user and their folders, the screen's
    settings, and the version setting it up."""

    kind: Kind
    home: Path
    user: str
    release: str
    settings: settings_file.Config
    config_path: Path
    state_dir: Path  # ~/.local/state/sunroom-kiosk; %LOCALAPPDATA%\sunroom-kiosk on Windows
    root: Path = Path("/")  # where /etc and /usr/local are (a test's own folder)
    python: str = sys.executable  # runs labwc-rule.py (standard library only)
    command: Command = run_quietly
    registry: Registry | None = None
    places: local.Places | None = None  # Sunroom run here

    @classmethod
    def here(cls, root: Path = Path("/"), registry: Registry | None = None) -> Machine:
        home = Path.home()
        config_path = settings_file.config_file()
        if sys.platform == "win32":
            from sunroom_kiosk.platform.windows import system_registry

            kind: Kind = "windows"
            state_dir = config_path.parent
            registry = registry or system_registry()
        else:
            from sunroom_kiosk.platform.pi import is_pi

            kind = "macos" if sys.platform == "darwin" else "pi" if is_pi(root) else "linux"
            state_dir = home / ".local" / "state" / "sunroom-kiosk"
        return cls(
            kind=kind,
            home=home,
            user=_user(),
            release=version(),
            settings=settings_file.load(config_path),
            config_path=config_path,
            state_dir=state_dir,
            root=root,
            registry=registry,
            places=local.Places.default(home=home),
        )

    @property
    def values(self) -> dict[str, str]:
        """The placeholders a user template may hold (the installer's ``render``)."""
        return {"VERSION": self.release, "USER": self.user, "HOME": str(self.home)}

    def at(self, absolute: str) -> Path:
        """A system path, under this machine's root."""
        return self.root / absolute.lstrip("/")

    @property
    def session(self) -> str:
        return self.settings.session or "wayland"


def _user() -> str:
    if sys.platform != "win32":
        import pwd

        return pwd.getpwuid(os.getuid()).pw_name
    return os.environ.get("USERNAME", "")


# ---------------------------------------------------------------------- the pieces


@dataclass(frozen=True)
class Look:
    """What a piece found: whether it differs from what it should be, and whether by more than
    the version that wrote it."""

    differs: bool
    meaningful: bool


class Piece:
    name: str = ""
    after: After = None

    def look(self) -> Look:
        raise NotImplementedError

    def apply(self) -> None:
        raise NotImplementedError


class FilePiece(Piece):
    """A whole file of this user's, or one that shouldn't be there (``text`` None)."""

    def __init__(
        self,
        name: str,
        path: Path,
        text: str | None,
        *,
        mode: int = 0o644,
        after: After = None,
        then: Callable[[], object] | None = None,
    ) -> None:
        self.name = name
        self.path = path
        self.text = text
        self.mode = mode
        self.after = after
        self.then = then

    def look(self) -> Look:
        have = _read(self.path)
        if have == self.text:
            return Look(differs=False, meaningful=False)
        if have is None or self.text is None:
            return Look(differs=True, meaningful=True)
        return Look(differs=True, meaningful=comparable(have) != comparable(self.text))

    def apply(self) -> None:
        if self.text is None:
            self.path.unlink(missing_ok=True)
        else:
            _write(self.path, self.text, self.mode)
        if self.then is not None:
            self.then()


def strip_block(text: str) -> list[str]:
    """``text``'s lines without the managed block, as the installer's ``strip_block``; an
    unfinished block is kept as it was."""
    kept: list[str] = []
    held: list[str] | None = None
    for line in text.splitlines():
        if held is None and line.startswith(BLOCK_BEGIN):
            held = [line]
        elif held is not None:
            held.append(line)
            if line == BLOCK_END:
                held = None
        else:
            kept.append(line)
    return kept + (held or [])


class BlockPiece(Piece):
    """labwc's autostart: the managed block between the markers, the rest of the file the user's
    (``block`` None takes the block out, on a Pi that runs X11). A new block takes effect at the
    next sign-in, hence the reboot."""

    name = "labwc-autostart"
    after: After = "reboot"

    def __init__(self, path: Path, block: str | None) -> None:
        self.path = path
        self.block = block
        self.created = False  # this run made the file (the uninstaller then removes it)

    def wanted(self, have: str | None) -> str | None:
        if self.block is None:
            if have is None or not any(line.startswith(BLOCK_BEGIN) for line in have.splitlines()):
                return have
            return "".join(f"{line}\n" for line in strip_block(have))
        lines = strip_block(have or "")
        while lines and not lines[-1].strip():
            lines.pop()
        text = "".join(f"{line}\n" for line in lines)
        return (text + "\n" if text else "") + self.block

    def look(self) -> Look:
        have = _read(self.path)
        want = self.wanted(have)
        if want == have:
            return Look(differs=False, meaningful=False)
        if have is None or want is None:
            return Look(differs=True, meaningful=True)
        return Look(differs=True, meaningful=comparable(have) != comparable(want))

    def apply(self) -> None:
        have = _read(self.path)
        want = self.wanted(have)
        if want is None:
            return
        self.created = have is None
        _write(self.path, want, 0o644)


class LabwcRulePiece(Piece):
    """labwc's window rule and touch settings, through ``labwc-rule.py`` (which changes only what
    isn't there yet); looked at on a copy of ``rc.xml``. New settings take effect once labwc
    reads them again, and fully at the next sign-in."""

    name = "labwc-rule"
    after: After = "reboot"

    def __init__(self, machine: Machine) -> None:
        self.machine = machine
        self.rc = machine.home / ".config" / "labwc" / "rc.xml"
        self.state = machine.state_dir / "labwc-rule.json"

    def _run(self, rc: Path, state: Path) -> None:
        settings = self.machine.settings
        self.machine.command(
            [
                self.machine.python,
                str(script("labwc-rule.py")),
                "--rc",
                str(rc),
                "--state",
                str(state),
                "--system-rc",
                str(self.machine.at("/etc/xdg/labwc/rc.xml")),
                "--installer-version",
                self.machine.release,
                "--rotate",
                str(settings.rotate),
                "--output",
                settings.output,
            ]
        )

    def look(self) -> Look:
        with tempfile.TemporaryDirectory(prefix="sunroom-labwc-") as folder:
            rc, state = Path(folder) / "rc.xml", Path(folder) / "labwc-rule.json"
            for source, copy in ((self.rc, rc), (self.state, state)):
                if source.is_file():
                    shutil.copy2(source, copy)
            before = _read(rc)
            self._run(rc, state)
            differs = _read(rc) != before
        return Look(differs=differs, meaningful=differs)

    def apply(self) -> None:
        before = _read(self.rc)
        self._run(self.rc, self.state)
        if _read(self.rc) != before:
            # labwc reads its settings again on a hang-up; the next sign-in does the rest.
            self.machine.command(["pkill", "-HUP", "-u", user_id(), "-x", "labwc"])


class ValuePiece(Piece):
    """Lines of a ``KEY=value`` file set to this version's (the settings file's keys, the
    install-state); ``quiet`` keys changing alone isn't a change worth saying."""

    def __init__(
        self,
        name: str,
        path: Path,
        wanted: Callable[[str], str],
        *,
        quiet: frozenset[str] = frozenset(),
        create: bool = False,
    ) -> None:
        self.name = name
        self.path = path
        self.wanted = wanted
        self.quiet = quiet
        self.create = create

    def look(self) -> Look:
        have = _read(self.path)
        if have is None and not self.create:
            return Look(differs=False, meaningful=False)
        want = self.wanted(have or "")
        if want == have:
            return Look(differs=False, meaningful=False)
        before = settings_file.parse_values(have or "")
        after = settings_file.parse_values(want)
        moved = {key for key in before.keys() | after.keys() if before.get(key) != after.get(key)}
        return Look(differs=True, meaningful=bool(moved - self.quiet) or have is None)

    def apply(self) -> None:
        have = _read(self.path)
        if have is None and not self.create:
            return
        _write(self.path, self.wanted(have or ""), 0o644)


class RunValuePiece(Piece):
    """Windows: the ``Run`` value under HKEY_CURRENT_USER that starts Sunroom Screen at sign-in,
    with no console window. It takes effect at the next sign-in."""

    name = "run-value"

    def __init__(self, registry: Registry, command: str) -> None:
        self.registry = registry
        self.command = command

    def look(self) -> Look:
        differs = self.registry.user_value(RUN_KEY, RUN_NAME) != self.command
        return Look(differs=differs, meaningful=differs)

    def apply(self) -> None:
        self.registry.set_value(RUN_KEY, RUN_NAME, "REG_SZ", self.command)


# ---------------------------------------------------------------------- what this machine has


def template(relative: str) -> str:
    return (files_dir() / relative).read_text(encoding="utf-8")


def _state_file(machine: Machine) -> Path:
    return machine.state_dir / "install-state"


def _systemctl(machine: Machine, *args: str) -> Callable[[], bool]:
    return lambda: machine.command(["systemctl", "--user", *args])


def user_pieces(machine: Machine) -> list[Piece]:
    """Everything of this user's that the installer would put in place on this machine, in the
    order it does it: the settings file first, the install-state last."""
    pieces: list[Piece] = [
        ValuePiece(
            "settings",
            machine.config_path,
            settings_file.migrated,
            quiet=frozenset({"SUNROOM_CONFIG_VERSION"}),
        )
    ]
    home = machine.home
    block: BlockPiece | None = None
    if machine.kind in ("pi", "linux"):
        unit = home / ".config" / "systemd" / "user" / "sunroom-kiosk.service"
        pieces.append(
            FilePiece(
                "service",
                unit,
                stamp(
                    render(template("systemd/sunroom-kiosk.service"), machine.values),
                    machine.release,
                ),
                after="restart",
                then=_systemctl(machine, "daemon-reload"),
            )
        )
        xdg = home / ".config" / "autostart" / "sunroom-kiosk.desktop"
        xdg_text = stamp(
            render(template("xdg/sunroom-kiosk.desktop"), machine.values), machine.release
        )
        labwc_autostart = home / ".config" / "labwc" / "autostart"
        if machine.kind == "pi" and machine.session == "wayland":
            block = BlockPiece(
                labwc_autostart, render(template("labwc/autostart-block"), machine.values)
            )
            pieces += [block, FilePiece("xdg-autostart", xdg, None), LabwcRulePiece(machine)]
        elif machine.kind == "pi":
            pieces += [FilePiece("xdg-autostart", xdg, xdg_text), BlockPiece(labwc_autostart, None)]
        else:
            pieces.append(FilePiece("xdg-autostart", xdg, xdg_text))
    elif machine.kind == "macos":
        plist = render(template("launchd/app.sunroom.kiosk.plist"), machine.values)
        plistlib.loads(plist.encode())  # one that doesn't parse is never written
        pieces.append(
            FilePiece(
                "launch-agent",
                home / "Library" / "LaunchAgents" / "app.sunroom.kiosk.plist",
                plist,
                after="restart",
            )
        )
    elif machine.registry is not None:
        windowless = home / ".local" / "bin" / "sunroom-kioskw.exe"
        pieces.append(RunValuePiece(machine.registry, f'"{windowless}" run'))
        startup = Path(os.environ.get("APPDATA", str(home / "AppData" / "Roaming")))
        shortcut = startup / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
        pieces.append(FilePiece("startup-shortcut", shortcut / "Sunroom Screen.lnk", None))
    if machine.kind != "windows":
        share = home / ".local" / "share" / "sunroom-kiosk"
        for helper in ("uninstall.sh", "labwc-rule.py"):
            text = stamp(script(helper).read_text(encoding="utf-8"), machine.release)
            pieces.append(FilePiece(f"helper-{helper}", share / helper, text, mode=0o755))
    pieces += sunroom_here(machine)
    if machine.kind != "windows":
        made = block

        def install_state(existing: str) -> str:
            wanted = {"STATE_SETUP_VERSION": machine.release}
            if made is not None and made.created:
                wanted["STATE_LABWC_AUTOSTART_CREATED"] = "1"
            return set_lines(existing, wanted, _STATE_HEADER)

        pieces.append(
            ValuePiece(
                "install-state",
                _state_file(machine),
                install_state,
                quiet=frozenset({"STATE_SETUP_VERSION"}),
                create=True,
            )
        )
    return pieces


def sunroom_here(machine: Machine) -> list[Piece]:
    """The service of Sunroom run on this computer (ADR 0038), when there is one: what
    ``local.py`` would write for it now, from what it remembers."""
    places = machine.places
    if places is None or not places.state.is_file():
        return []
    try:
        read: object = json.loads(places.state.read_text(encoding="utf-8"))
    except OSError, ValueError:
        return []
    remembered = cast(dict[str, object], read) if isinstance(read, dict) else {}
    port, advertised = remembered.get("port"), remembered.get("advertised")
    if not isinstance(port, int) or not isinstance(advertised, str):
        return []
    system = {"macos": "darwin", "windows": "win32"}.get(machine.kind, "linux")
    command = local.program_command(places, system)
    environment = local.program_environment(places, port, advertised)
    if machine.kind in ("pi", "linux") and places.unit.is_file():
        return [
            FilePiece(
                "sunroom-service",
                places.unit,
                local.unit_text(command, environment),
                then=_systemctl(machine, "daemon-reload"),
            )
        ]
    if machine.kind == "macos" and places.launch_agent.is_file():
        plist = local.launch_agent_plist(command, environment, places).decode()
        return [FilePiece("sunroom-launch-agent", places.launch_agent, plist)]
    return []


def root_pieces(machine: Machine) -> list[FilePiece]:
    """Root's part on Linux and a Pi, looked at and never written here: the root helper, and on a
    Pi the system files the install-state says the installer wrote."""
    if machine.kind not in ("pi", "linux"):
        return []
    state = settings_file.parse_values(_read(_state_file(machine)) or "")
    release = machine.release
    helper = machine.at("/usr/local/sbin/sunroom-kiosk-root")
    pieces: list[FilePiece] = []
    # Another Linux computer has the helper only when its installer could put it in (sudo, and
    # the system's Python): without one, its browser asks once, on the screen, and that's all.
    if machine.kind == "pi" or helper.is_file():
        text = stamp(render(template("sunroom-kiosk-root"), machine.values), release)
        pieces.append(FilePiece("helper", helper, text))
    for name, key, relative in (
        ("wifi", "STATE_NM_DROPIN", "NetworkManager/zz-sunroom-kiosk-wifi.conf"),
        ("backlight", "STATE_BACKLIGHT_RULE", "udev/90-sunroom-kiosk-backlight.rules"),
        ("i2c", "STATE_I2C_MODULES", "modules-load/sunroom-kiosk-i2c.conf"),
    ):
        written = state.get(key, "")
        if written.startswith("/"):
            text = stamp(render(template(relative), machine.values), release)
            pieces.append(FilePiece(name, machine.at(written), text))
    avahi = machine.at("/etc/avahi/services/sunroom.service")
    have = _read(avahi)
    if machine.settings.mode in ("all", "server") and have is not None:
        port = re.search(r"<port>(\d+)</port>", have)
        note = header_comment(release).removeprefix("# ").rstrip("\n")
        values = {"PORT": port[1] if port else "8080", "VERSION": release, "NOTE": note}
        pieces.append(FilePiece("avahi", avahi, render(template("avahi/sunroom.service"), values)))
    return pieces


# ---------------------------------------------------------------------- the run


@dataclass
class Report:
    """What a run did (``--json``): the pieces it changed, those it couldn't, what applying them
    needs, and root's pieces that differ."""

    version: str
    changed: list[str] = field(default_factory=list[str])
    failed: list[str] = field(default_factory=list[str])
    needs_restart: bool = False
    needs_reboot: bool = False
    needs_root: list[str] = field(default_factory=list[str])

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


def back_up(machine: Machine) -> Path | None:
    """The small files copied aside, once per version, before setup changes anything; the last
    three versions' copies kept. Never the browser's profile, nor Sunroom's data."""
    folder = machine.state_dir / "backup" / machine.release
    if folder.exists():
        return folder
    small = [machine.config_path, _state_file(machine), machine.state_dir / "update.json"]
    if machine.places is not None:
        small.append(machine.places.state)
    folder.mkdir(parents=True)
    for path in small:
        if path.is_file():
            shutil.copy2(path, folder / path.name)
    kept = sorted(
        (entry for entry in folder.parent.iterdir() if entry.is_dir()),
        key=lambda entry: entry.stat().st_mtime_ns,
        reverse=True,
    )
    for old in kept[BACKUPS_KEPT:]:
        shutil.rmtree(old, ignore_errors=True)
    return folder


def run(
    machine: Machine, *, check: bool = False, force: bool = False, backup: bool = True
) -> Report:
    """Look at every piece and, unless ``check``, rewrite what differs (``force``: every piece)."""
    report = Report(version=machine.release)

    def said(piece: Piece) -> None:
        report.changed.append(piece.name)
        report.needs_restart |= piece.after == "restart"
        report.needs_reboot |= piece.after == "reboot"

    backed_up = False
    for piece in user_pieces(machine):
        try:
            look = piece.look()
            if check or not (look.differs or force):
                if check and look.meaningful:
                    said(piece)
                continue
            if backup and not backed_up:
                back_up(machine)
                backed_up = True
            piece.apply()
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            report.failed.append(f"{piece.name}: {error}")
            continue
        if look.meaningful:
            said(piece)
    for piece in root_pieces(machine):
        try:
            if piece.look().meaningful:
                report.needs_root.append(piece.name)
        except OSError:
            continue  # one only root can read is the root helper's to rewrite anyway
    return report


def save_report(report: Report, update_json: Path) -> None:
    """``--from-update``: the report kept in update.json's ``setup``, for the agent's start."""
    saved: dict[str, Any] = {}
    try:
        read = json.loads(update_json.read_text(encoding="utf-8"))
        if isinstance(read, dict):
            saved = cast(dict[str, Any], read)
    except OSError, ValueError:
        pass
    saved["setup"] = report.to_json()
    update_json.parent.mkdir(parents=True, exist_ok=True)
    update_json.write_text(json.dumps(saved, sort_keys=True), encoding="utf-8")
