"""The ``sunroom`` command (PLAN §14.4): serve, check-config, migrate, backup-now,
inspect-backup, reset-password, restore, status, openapi.

In the container: ``sudo docker exec -it sunroom sunroom reset-password``.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import shutil
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NoReturn

from sunroom.boot import EXIT_CONFIG, BootError, check_data_dir, prepare, reexec
from sunroom.core.clock import SystemClock
from sunroom.core.config import ConfigError, Settings, load_settings
from sunroom.core.logging import configure_logging, get_logger

log = get_logger(__name__)

# Placeholder settings that let `openapi` build the app without any environment.
_SCHEMA_SETTINGS: dict[str, Any] = {"tz": "UTC"}
_SCHEMA_SECRET = "schema-generation-only-" + "x" * 16


def _settings_or_exit() -> Settings:
    try:
        return load_settings()
    except ConfigError as exc:
        print("Sunroom can't start because of its configuration:", file=sys.stderr)
        for problem in exc.problems:
            print(f"  - {problem}", file=sys.stderr)
        print("See .env.example for every setting.", file=sys.stderr)
        raise SystemExit(EXIT_CONFIG) from None


def _boot_or_exit(settings: Settings) -> str:
    try:
        return prepare(settings, SystemClock())
    except BootError as failure:
        log.error("boot.failed", exit_code=failure.exit_code, reason=failure.message)
        raise SystemExit(failure.exit_code) from None


def cmd_serve(args: argparse.Namespace) -> None:
    settings = _settings_or_exit()
    configure_logging(settings.log_level, secret_literals=settings.secret_literals())
    for warning in settings.warnings():
        log.warning("config.warning", detail=warning)
    import uvicorn

    if args.reload:
        uvicorn.run(
            "sunroom.devserver:create",
            factory=True,
            reload=True,
            reload_dirs=[str(Path(__file__).parent)],
            host=args.host,
            port=settings.port,
            log_config=None,
            access_log=False,
        )
        return
    secret = _boot_or_exit(settings)
    configure_logging(settings.log_level, secret_literals=[*settings.secret_literals(), secret])
    from sunroom.app import create_app

    uvicorn.run(
        create_app(settings, secret=secret, restart=reexec),
        host=args.host,
        port=settings.port,
        # Forwarded headers are applied by the app itself, from private addresses only
        # (web/forwarded.py): uvicorn's own handling would trust 127.0.0.1 alone and miss a
        # proxy in Docker, and the Host rule needs to see the original Host too.
        proxy_headers=False,
        access_log=False,
        server_header=False,
        timeout_graceful_shutdown=10,
        log_config=None,
    )


def cmd_check_config(args: argparse.Namespace) -> None:
    settings = _settings_or_exit()
    for warning in settings.warnings():
        print(f"warning: {warning}")
    print("Configuration OK.")


def cmd_migrate(args: argparse.Namespace) -> None:
    from sunroom.db import migrate

    settings = _settings_or_exit()
    configure_logging(settings.log_level, secret_literals=settings.secret_literals())
    current = migrate.current_revision(settings.db_path)
    head = migrate.head_revision()
    print(f"database revision: {current or 'none'}; head: {head}")
    if args.dry_run:
        return
    _boot_or_exit(settings)


def _household_zone(settings: Settings) -> Any:
    from zoneinfo import ZoneInfo

    from sunroom.household.service import valid_zone

    name: str | None = None
    if settings.db_path.exists():
        conn = sqlite3.connect(f"file:{settings.db_path}?mode=ro", uri=True)
        try:
            row = conn.execute("SELECT timezone FROM household").fetchone()
            name = row[0] if row else None
        except sqlite3.OperationalError:
            name = None
        finally:
            conn.close()
    return valid_zone(name) or settings.env_zone or ZoneInfo("UTC")


def cmd_backup_now(args: argparse.Namespace) -> None:
    from sunroom.db import backup

    settings = _settings_or_exit()
    today = datetime.now(UTC).astimezone(_household_zone(settings)).date()
    result = backup.take_backup(settings.db_path, settings.backup_dir / backup.nightly_name(today))
    print(f"wrote {result.path.name} ({result.bytes} bytes, {result.seconds}s)")


def cmd_inspect_backup(args: argparse.Namespace) -> None:
    from sunroom.db import backup

    print(json.dumps(backup.inspect_backup(Path(args.file)), indent=2))


def cmd_reset_password(args: argparse.Namespace) -> None:
    """A lost household password (PLAN §13.4): set a new one, sign every device out."""
    from sunroom.auth.password import hash_password, password_problem

    settings = _settings_or_exit()
    if settings.app_password is not None:
        print(
            "APP_PASSWORD is set, and it always wins. Change it where the server's settings live "
            "(Sunroom's docker-compose.yml or the .env beside it) and restart.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    if not settings.db_path.exists():
        print(
            "Sunroom isn't set up yet: open it on a device to choose a password.", file=sys.stderr
        )
        raise SystemExit(1)
    first = getpass.getpass("New household password: ")
    second = getpass.getpass("Type it again: ")
    if first != second:
        print("Those didn't match. Nothing changed.", file=sys.stderr)
        raise SystemExit(1)
    problem = password_problem(first)
    if problem:
        print(f"{problem} Nothing changed.", file=sys.stderr)
        raise SystemExit(1)
    hashed = hash_password(first)
    conn = sqlite3.connect(settings.db_path, timeout=10)
    try:
        conn.execute("PRAGMA busy_timeout=10000")
        conn.execute(
            "UPDATE app_meta SET password_hash = ?, auth_epoch = auth_epoch + 1", (hashed,)
        )
        conn.commit()
    finally:
        conn.close()
    print(
        "Done. Every device signs in again with the new password, and wall screens show a pair "
        "code again (a signed-in device pairs them in a few seconds)."
    )


def _refuse(message: str) -> NoReturn:
    print(message, file=sys.stderr)
    raise SystemExit(1)


def cmd_restore(args: argparse.Namespace) -> None:
    """Swap in a backup (docs/RESTORE.md): a ``.db`` file, or the zip from Download everything,
    whose photos come back too. The server must be stopped. The checks and the moves are
    db/restore.py's, which Settings → Backup → Restore from a File shares (ADR 0034)."""
    import zipfile

    from sunroom.db import full_backup, instance_lock, restore

    settings = _settings_or_exit()
    source = Path(args.file)
    if source.is_dir():
        _refuse(f"{source} is a folder. Give restore the .db or .zip file itself.")
    if not source.is_file():
        _refuse(f"There's no file at {source}.")
    try:
        check_data_dir(settings)
    except BootError as failure:
        _refuse(failure.message)
    try:
        instance_lock.acquire(settings.lock_path)
    except instance_lock.InstanceLockError:
        _refuse("Sunroom is running. Stop it first (docker stop sunroom), then run restore again.")
    db = settings.db_path
    partial = db.with_name("sunroom.restore.partial.db")
    photos: str | None = None
    photos_problem: str | None = None
    try:
        try:
            prepared = restore.prepare(source, partial, settings.photos_dir, settings.data_dir)
            moved = restore.swap_in(db, partial, restore.aside_stamp(db, datetime.now(UTC)))
        except restore.RestoreError as problem:
            partial.unlink(missing_ok=True)
            restore.without_journal(partial)
            _refuse(problem.message)
        if prepared.kind == "zip":
            try:
                photos = restore.photos_line(restore.photos_back(source, settings.photos_dir))
            except OSError as exc:
                photos_problem = exc.strerror or type(exc).__name__
            except (zipfile.BadZipFile, full_backup.ArchiveError) as exc:
                photos_problem = str(exc)
    finally:
        instance_lock.release(settings.lock_path)
    before = (
        f"The previous database is kept as {moved[0]}."
        if moved
        else "There was no database here before."
    )
    print(f"Restored {source.name}. {before}")
    if photos_problem is not None:
        print(
            f"Some photos couldn't be put back ({photos_problem}). Fix that, then run restore "
            "again: photos already back are kept.",
            file=sys.stderr,
        )
    elif photos is not None:
        print(photos)
    else:
        print("A .db backup holds no photos: the photos on the volume stay as they are.")
    needs = prepared.info.get("app_version") or prepared.manifest.get("app_version")
    print(f"It needs Sunroom {needs or 'any version'} or newer. Start the container.")
    print("Every device signs in again, and wall screens show a pair code again.")
    if photos_problem is not None:
        raise SystemExit(1)


def cmd_status(args: argparse.Namespace) -> None:
    from sunroom.core.version import build_info
    from sunroom.db import backup, migrate

    settings = _settings_or_exit()
    print(f"Sunroom {build_info().version} ({build_info().revision})")
    db = settings.db_path
    if not db.exists():
        print("No database yet: it is created at the first start.")
        return
    current = migrate.current_revision(db)
    head = migrate.head_revision()
    print(f"database: {'up to date' if current == head else f'{current} (this version: {head})'}")
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        onboarded = conn.execute("SELECT onboarded_at FROM household").fetchone()
        devices = conn.execute(
            "SELECT kind, count(*) FROM devices WHERE revoked_at IS NULL GROUP BY kind"
        ).fetchall()
    except sqlite3.OperationalError:
        onboarded, devices = None, []
    finally:
        conn.close()
    print(f"set up: {'yes' if onboarded and onboarded[0] else 'no (open it on a device)'}")
    counts = {kind: count for kind, count in devices}
    print(f"signed in: {counts.get('phone', 0)} device(s), {counts.get('kiosk', 0)} screen(s)")
    files = backup.nightly_files(settings.backup_dir)
    print(f"newest nightly backup: {files[-1][1].name if files else 'none yet'}")
    free = shutil.disk_usage(settings.data_dir).free
    print(f"free space on the data volume: {free / 1024**3:.1f} GB")


def cmd_openapi(args: argparse.Namespace) -> None:
    from sunroom.app import create_app

    app = create_app(Settings.model_validate(_SCHEMA_SETTINGS), secret=_SCHEMA_SECRET)
    schema = app.openapi()
    schema["info"]["version"] = "0"  # version bumps must not make the generated types stale
    text = json.dumps(schema, indent=2, sort_keys=True) + "\n"
    if args.out:
        Path(args.out).write_text(text)
    else:
        sys.stdout.write(text)


def cmd_bench(args: argparse.Namespace) -> None:
    """Time a week of occurrences on a throwaway database of synthetic events (PLAN §7.3)."""
    from sunroom.calendar import bench

    result = asyncio.run(bench.run(args.events, args.recurring, args.weeks))
    print(
        f"occurrences: {result.events} events ({result.recurring} repeating), "
        f"{result.weeks} week(s), {result.occurrences} occurrences: "
        f"cold {result.cold_ms:.1f} ms, warm {result.warm_ms:.1f} ms (median of 5)"
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="sunroom", description="Sunroom server")
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="run the app (backup + migrate first)")
    serve.add_argument("--reload", action="store_true", help="development auto-reload")
    serve.add_argument("--host", default="0.0.0.0")  # noqa: S104 - the container's listen address
    serve.set_defaults(func=cmd_serve)
    sub.add_parser("check-config", help="validate the environment").set_defaults(
        func=cmd_check_config
    )
    mig = sub.add_parser("migrate", help="back up and migrate, then exit")
    mig.add_argument("--dry-run", action="store_true", help="only show the revisions")
    mig.set_defaults(func=cmd_migrate)
    sub.add_parser("backup-now", help="write a verified backup").set_defaults(func=cmd_backup_now)
    inspect = sub.add_parser("inspect-backup", help="show a backup's revision and row counts")
    inspect.add_argument("file")
    inspect.set_defaults(func=cmd_inspect_backup)
    sub.add_parser(
        "reset-password", help="choose a new household password (signs every device out)"
    ).set_defaults(func=cmd_reset_password)
    restore = sub.add_parser("restore", help="swap in a backup (stop the server first)")
    restore.add_argument("file")
    restore.set_defaults(func=cmd_restore)
    sub.add_parser("status", help="version, database, devices and backups").set_defaults(
        func=cmd_status
    )
    bench = sub.add_parser("bench", help="time the calendar on synthetic data")
    bench.add_argument("what", choices=["occurrences"])
    bench.add_argument("--events", type=int, default=500)
    bench.add_argument("--recurring", type=int, default=100)
    bench.add_argument("--weeks", type=int, default=1)
    bench.set_defaults(func=cmd_bench)
    openapi = sub.add_parser("openapi", help="print the OpenAPI schema")
    openapi.add_argument("--out")
    openapi.set_defaults(func=cmd_openapi)
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
