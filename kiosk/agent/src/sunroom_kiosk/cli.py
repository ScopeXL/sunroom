"""``sunroom-kiosk``: Sunroom Screen's one command (docs/KIOSK.md).

    sunroom-kiosk [run] [--port 7800] [--fake pi|desktop] [--fake-sunroom URL] [--dev]
                                  the agent: the API on 127.0.0.1, the browser, the screen's sleep
                                  (``run`` is the default: the units of a Pi set up before 0.13.0
                                  start the old launcher's path with no arguments)
    sunroom-kiosk openapi [--out FILE]
                                  the API's schema (``just api-types`` makes screen-schema.d.ts)
    sunroom-kiosk screen --method | --ddc-bus NAME
                                  how brightness is set here (sysfs, ddc or none), or the I2C bus
                                  of the screen on connector NAME from ``ddcutil detect --brief``
                                  on stdin (the installer's two questions, as sunroom-screen's)
    sunroom-kiosk status          what the running agent says about this screen
    sunroom-kiosk update          whether a newer Sunroom Screen is out
    sunroom-kiosk policy [--url URL] | --remove
                                  the browser's managed policy for a screen showing URL, as JSON
                                  (the installer writes it on a computer with no root helper); or
                                  take Sunroom Screen's policy out again (Windows, macOS)
    sunroom-kiosk config [--url URL]
                                  the screen's settings: where they are and the Sunroom it shows,
                                  or show the Sunroom at URL from now on (the installers' --url)
    sunroom-kiosk --version

Started with no console (Windows' ``sunroom-kioskw``, from the Startup folder), it writes what it
says to ``sunroom-kiosk.log`` beside its settings.

The service runs ``sunroom-kiosk run``; on a Pi that's the user unit sunroom-kiosk.service.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import cast

import httpx

from sunroom_kiosk import config as settings_file
from sunroom_kiosk import logs, screen
from sunroom_kiosk.version import version

DEFAULT_PORT = 7800
# just kiosk-dev: Vite serves the pages on 5174 and passes /api/screen through to the agent.
DEV_ORIGINS = ("http://127.0.0.1:5174", "http://localhost:5174")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sunroom-kiosk", description="Sunroom Screen: runs a Sunroom wall screen."
    )
    parser.add_argument("--version", action="version", version=f"sunroom-kiosk {version()}")
    commands = parser.add_subparsers(dest="command")

    run = commands.add_parser("run", help="run the agent (the service does this)")
    run.add_argument("--port", type=int, default=DEFAULT_PORT)
    run.add_argument("--config", type=Path, default=None, help="the settings file")
    run.add_argument(
        "--fake",
        choices=["pi", "desktop"],
        default=None,
        help="a pretend machine: no browser, no commands, nothing changed outside its folder",
    )
    run.add_argument(
        "--fake-sunroom",
        action="append",
        default=[],
        metavar="URL",
        help="with --fake: a Sunroom it finds on the network (asked for real)",
    )
    run.add_argument(
        "--log-level",
        choices=["debug", "info", "warning"],
        default="info",
        help="how much the agent says (the e2e runs keep it to warnings)",
    )
    run.add_argument(
        "--dev",
        action="store_true",
        help="leave the pages to Vite's dev server (just kiosk-dev)",
    )

    schema = commands.add_parser("openapi", help="write the API's OpenAPI schema")
    schema.add_argument("--out", type=Path, default=None)

    helper = commands.add_parser("screen", help="the screen helper's questions, for the installer")
    helper.add_argument("--config", type=Path, default=None)
    what = helper.add_mutually_exclusive_group(required=True)
    what.add_argument("--method", action="store_true")
    what.add_argument("--ddc-bus", metavar="NAME")

    status = commands.add_parser("status", help="what the running agent says about this screen")
    status.add_argument("--port", type=int, default=DEFAULT_PORT)

    policy = commands.add_parser("policy", help="the browser's policy for a Sunroom, as JSON")
    which = policy.add_mutually_exclusive_group()
    which.add_argument("--url", default=None)
    which.add_argument("--remove", action="store_true", help="take Sunroom Screen's policy out")

    settings = commands.add_parser("config", help="the screen's settings, or its Sunroom's address")
    settings.add_argument("--url", default=None, help="the address you open on your devices")
    settings.add_argument("--config", type=Path, default=None, help="the settings file")

    update = commands.add_parser("update", help="ask GitHub for a newer version (or apply one)")
    update.add_argument("--apply", type=Path, default=None, help=argparse.SUPPRESS)
    update.add_argument("--previous", type=Path, default=None, help=argparse.SUPPRESS)
    update.add_argument("--port", type=int, default=DEFAULT_PORT)

    here = commands.add_parser("sunroom", help="Sunroom run on this computer (ADR 0038)")
    here_commands = here.add_subparsers(dest="action", required=True)
    remove = here_commands.add_parser("remove", help="take it off (the uninstallers run this)")
    remove.add_argument(
        "--delete-data", action="store_true", help="delete the family's data too (kept otherwise)"
    )
    return parser


LOG_KEEP_BYTES = 1_000_000


def _windowless_log() -> None:
    """With no console (pythonw: Windows' sunroom-kioskw), say everything into a file instead,
    started over once it passes a megabyte (the previous one kept as .1)."""
    if sys.stderr is not None:
        return
    folder = settings_file.config_dir()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "sunroom-kiosk.log"
    try:
        if path.stat().st_size > LOG_KEEP_BYTES:
            path.replace(path.with_suffix(".log.1"))
    except OSError:
        pass
    sink = path.open("a", encoding="utf-8", buffering=1)
    sys.stdout = sink
    sys.stderr = sink


def cmd_run(args: argparse.Namespace) -> int:
    _windowless_log()

    from sunroom_kiosk.app import STATIC, AgentServer, create_app
    from sunroom_kiosk.browser import NoBrowser, Supervisor, find_browser, flags
    from sunroom_kiosk.discovery import Discovery, FakeDiscovery
    from sunroom_kiosk.events import EventHub
    from sunroom_kiosk.local import LocalSunroom
    from sunroom_kiosk.platform import detect
    from sunroom_kiosk.platform.fake import FakePlatform
    from sunroom_kiosk.state import Agent, BrowserLike
    from sunroom_kiosk.updater import FakeUpdater, NoUpdates, Updater, UpdaterLike

    logs.setup(getattr(logging, cast(str, args.log_level).upper()))
    log = logs.get("cli")
    port = cast(int, args.port)
    path = cast(Path | None, args.config) or settings_file.config_file()
    fake = cast(str | None, args.fake)
    platform = detect("pi" if fake == "pi" else "desktop" if fake == "desktop" else None)
    fake_sunrooms = cast(list[str], args.fake_sunroom)
    if isinstance(platform, FakePlatform) and fake_sunrooms:
        platform.local_url = fake_sunrooms[0]  # Run Sunroom Here "starts" the e2e server
    hub = EventHub()
    discovery = FakeDiscovery(hub.publish, fake_sunrooms) if fake else Discovery(hub.publish)
    updater: UpdaterLike = (
        FakeUpdater() if fake else Updater(port=port) if installed_as_tool() else NoUpdates()
    )
    found = None if fake else find_browser()
    holder: dict[str, Agent] = {}
    browser: BrowserLike
    if found is None:
        if not fake:
            log.info("No Chromium, Chrome or Edge is installed here; the screen can't open.")
        browser = NoBrowser()
    else:
        profile = settings_file.config_dir() / "profile"
        browser = Supervisor(
            found,
            profile=profile,
            argv=lambda: flags(
                found,
                profile=profile,
                session=holder["agent"].platform.session,
                sunroom_url=holder["agent"].config.url,
            ),
            page=lambda: holder["agent"].start_page(),
            environment=platform.environment,
            before=lambda: holder["agent"].before_browser(),
        )
    agent = Agent(
        port=port,
        config_path=path,
        platform=platform,
        browser=browser,
        updater=updater,
        hub=hub,
        discovery=discovery,
        browser_info=found,
        fake=fake is not None,
        dev_origins=DEV_ORIGINS if args.dev else (),
        # The pretend screen's Sunrooms are on this machine: an address that doesn't answer
        # says so at once, rather than after the real five seconds.
        http=_quick_client if fake else None,
        local=LocalSunroom() if not fake and installed_as_tool() else None,
    )
    holder["agent"] = agent
    app = create_app(agent, static=None if args.dev else STATIC, test_routes=bool(fake))
    server = AgentServer(app, hub=hub, port=port)
    try:
        asyncio.run(server.serve())
    except OSError as error:
        log.info("Sunroom Screen couldn't start on port %d: %s", port, error)
        return 1
    return 0 if server.started else 1


def _quick_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=httpx.Timeout(5.0, connect=0.5))


def cmd_openapi(args: argparse.Namespace) -> int:
    from fastapi.openapi.utils import get_openapi

    from sunroom_kiosk.app import router

    schema = get_openapi(title="Sunroom Screen", version="0", routes=router.routes)
    text = json.dumps(schema, indent=2, sort_keys=True) + "\n"
    out = cast(Path | None, args.out)
    if out is None:
        sys.stdout.write(text)
    else:
        out.write_text(text, encoding="utf-8")
    return 0


def cmd_screen(args: argparse.Namespace) -> int:
    if args.ddc_bus is not None:
        bus = screen.ddc_bus_from_detect(sys.stdin.read(), cast(str, args.ddc_bus))
        if bus is None:
            return 1
        print(bus)
        return 0
    path = cast(Path | None, args.config) or settings_file.config_file()
    try:
        values = settings_file.parse_values(path.read_text(encoding="utf-8"))
    except OSError:
        print("none")
        return 0
    print(screen.brightness_method(screen.settings_from(values), Path("/"))[0])
    return 0


def installed_as_tool() -> bool:
    """Installed by uv as a tool (the installer's way): it can update itself. Run from a checkout
    (``uv run``), it can't."""
    prefix = Path(sys.prefix)
    return prefix.name == "sunroom-kiosk" and prefix.parent.name == "tools"


def cmd_update(args: argparse.Namespace) -> int:
    from sunroom_kiosk import updater

    wheel = cast(Path | None, args.apply)
    if wheel is not None:
        from sunroom_kiosk.apply import apply

        return apply(wheel, cast(Path | None, args.previous), cast(int, args.port))
    status = asyncio.run(updater.Updater().check_now())
    if status.state == "available":
        print(f"Sunroom Screen {status.latest} is ready (this is {status.installed}).")
    elif status.message:
        print(status.message)
    else:
        print(f"Sunroom Screen {status.installed} is up to date.")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    url = f"http://127.0.0.1:{cast(int, args.port)}/api/screen"
    request = urllib.request.Request(url, headers={"Host": f"127.0.0.1:{args.port}"})
    try:
        with urllib.request.urlopen(request, timeout=5) as response:  # noqa: S310 - loopback only
            print(json.dumps(json.loads(response.read()), indent=2))
    except (OSError, urllib.error.URLError) as error:
        print(f"Sunroom Screen isn't running here ({error}).", file=sys.stderr)
        return 1
    return 0


def cmd_policy(args: argparse.Namespace) -> int:
    from sunroom_kiosk import policy
    from sunroom_kiosk.discovery import origin_of

    if cast(bool, args.remove):
        from sunroom_kiosk.platform import detect

        platform = detect()
        removed = [kind for kind in policy.LINUX_DIRS if asyncio.run(platform.remove_policy(kind))]
        if not removed:
            print(
                "The browser's policy here is the uninstaller's to take out (kiosk/uninstall.sh)."
            )
        return 0
    url = cast(str | None, args.url)
    sys.stdout.write(policy.linux_json(policy.document(origin_of(url) if url else None)))
    return 0


ADDRESS = re.compile(r"https?://[a-z0-9.-]+(:[0-9]{1,5})?")


def clean_address(text: str) -> str | None:
    """An address as the installers take it: ``http(s)://host[:port]``, without ``/display`` or a
    trailing slash; None when it isn't one."""
    url = text.strip().rstrip("/").lower().removesuffix("/display").rstrip("/")
    return url if ADDRESS.fullmatch(url) else None


def cmd_config(args: argparse.Namespace) -> int:
    path = cast(Path | None, args.config) or settings_file.config_file()
    current = settings_file.load(path)
    typed = cast(str | None, args.url)
    if typed is None:
        print(f"Settings: {path}")
        print(f"Sunroom: {current.url or 'none yet (the screen finds it, or asks for it)'}")
        return 0
    url = clean_address(typed)
    if url is None:
        print(f'"{typed}" doesn\'t look like the address of Sunroom.', file=sys.stderr)
        return 2
    if url != current.url:
        settings_file.save(path, current.with_sunroom(url, None, "typed"))
    print(f"This screen will show Sunroom from {url}.")
    return 0


def cmd_sunroom(args: argparse.Namespace) -> int:
    """``sunroom remove``: Sunroom run on this computer, taken off (its data kept unless asked)."""
    from sunroom_kiosk.local import LocalSunroom

    said = asyncio.run(LocalSunroom().remove(delete_data=bool(args.delete_data)))
    for line in said or ["Sunroom wasn't set up on this computer."]:
        print(line)
    return 0


def main(argv: list[str] | None = None) -> int:
    given = sys.argv[1:] if argv is None else argv
    # No command, or only run's options: run (the old launcher's units start it bare).
    if not given or (given[0].startswith("-") and given[0] not in ("-h", "--help", "--version")):
        given = ["run", *given]
    args = _parser().parse_args(given)
    handlers = {
        "run": cmd_run,
        "openapi": cmd_openapi,
        "screen": cmd_screen,
        "status": cmd_status,
        "update": cmd_update,
        "policy": cmd_policy,
        "config": cmd_config,
        "sunroom": cmd_sunroom,
    }
    return handlers[cast(str, args.command)](args)
