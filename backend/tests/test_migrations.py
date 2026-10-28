"""Migration safety (PLAN §14.4): forward-only, one transaction, tested from each release."""

from __future__ import annotations

import hashlib
import sqlite3
import uuid
from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Integer, create_engine

from sunroom.db import migrate
from sunroom.db.models import Base

MIGRATIONS = Path(migrate.__file__).parent.parent / "migrations"
FIXTURE_DBS = Path(__file__).parent / "fixtures" / "db"


def released_revisions() -> list[str]:
    lock = (MIGRATIONS / "released.lock").read_text().splitlines()
    return [line.split()[0] for line in lock if line.strip() and not line.startswith("#")]


def row_counts(db: Path) -> dict[str, int]:
    conn = sqlite3.connect(db)
    try:
        tables = [
            name
            for (name,) in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name != 'alembic_version'"
            )
        ]
        return {t: conn.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0] for t in tables}  # noqa: S608
    finally:
        conn.close()


@pytest.mark.parametrize(
    "fixture",
    sorted(FIXTURE_DBS.glob("*.sql"))
    or [pytest.param(None, marks=pytest.mark.skip("no release yet"))],
    ids=lambda path: path.stem if path else "none",
)
def test_released_databases_upgrade_to_head_keeping_every_row(
    tmp_path: Path, fixture: Path
) -> None:
    db = tmp_path / "sunroom.db"
    conn = sqlite3.connect(db)
    conn.executescript(fixture.read_text())
    conn.close()
    before = row_counts(db)
    assert all(before.values()), "a fixture needs synthetic rows in every table"
    assert migrate.current_revision(db) == fixture.stem
    assert migrate.upgrade(db) == migrate.head_revision()
    migrate.verify(db)
    after = row_counts(db)
    assert {table: after[table] for table in before} == before
    conn = sqlite3.connect(db)
    try:
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        conn.close()


def test_unreleased_migrations_are_tested_against_the_last_release() -> None:
    """CLAUDE.md rule 4: a schema change needs an upgrade test from the last release's data."""
    released = released_revisions()
    if not released:
        return  # nothing released yet (before 0.1.0): the baseline is still being written
    latest = released[-1]
    if migrate.head_revision() != latest:
        assert (FIXTURE_DBS / f"{latest}.sql").is_file(), (
            f"build it: cd backend && uv run python -m tests.fixtures.db.build {latest}"
        )


def test_empty_database_upgrades_to_a_single_head(tmp_path: Path) -> None:
    db = tmp_path / "sunroom.db"
    assert migrate.upgrade(db) == migrate.head_revision()
    migrate.verify(db)
    conn = sqlite3.connect(db)
    try:
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert conn.execute("SELECT count(*) FROM household").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM app_meta").fetchone()[0] == 1
        assert conn.execute("SELECT onboarded_at FROM household").fetchone()[0] is None
    finally:
        conn.close()


def test_models_match_migrations(migrated_template: Path) -> None:
    engine = create_engine(f"sqlite:///{migrated_template}")
    with engine.connect() as conn:
        diff = compare_metadata(
            MigrationContext.configure(conn, opts={"compare_type": True}), Base.metadata
        )
    engine.dispose()
    assert diff == [], f"models and migrations differ: {diff}"


def test_released_migrations_are_unchanged() -> None:
    lock = (MIGRATIONS / "released.lock").read_text().splitlines()
    entries = [line.split() for line in lock if line.strip() and not line.startswith("#")]
    by_revision = {
        path.name.split("_", 1)[0]: path for path in (MIGRATIONS / "versions").glob("*.py")
    }
    for revision, digest in entries:
        path = by_revision.get(revision)
        assert path is not None, f"released migration {revision} is missing; never delete one"
        actual = hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
        assert actual == digest, f"released migration {revision} changed; write a new migration"


def test_a_failing_migration_leaves_the_database_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = tmp_path / "sunroom.db"
    seed = sqlite3.connect(db)
    seed.execute("PRAGMA journal_mode=WAL")
    seed.execute("CREATE TABLE keepme (x INTEGER)")
    seed.execute("INSERT INTO keepme VALUES (1)")
    seed.commit()
    seed.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    seed.close()
    before = db.read_bytes()
    real_upgrade = migrate.command.upgrade

    def upgrade_then_fail(config: object, revision: str) -> None:
        real_upgrade(config, revision)  # pyright: ignore[reportArgumentType]
        raise RuntimeError("simulated failure after the DDL ran")

    monkeypatch.setattr(migrate.command, "upgrade", upgrade_then_fail)
    with pytest.raises(migrate.MigrationError):
        migrate.upgrade(db)
    assert migrate.current_revision(db) is None
    conn = sqlite3.connect(db)
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        rows = conn.execute("SELECT x FROM keepme").fetchall()
    finally:
        conn.close()
    assert tables == [("keepme",)]
    assert rows == [(1,)]
    assert db.read_bytes() == before


def test_batch_table_rebuild_keeps_child_rows(tmp_path: Path) -> None:
    """With foreign keys OFF (as at startup), rebuilding a parent table must not touch children."""
    db = tmp_path / "sunroom.db"
    migrate.upgrade(db)
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO members (id, name, role, color, sort, created_at) "
        "VALUES ('m1', 'Sample Parent', 'parent', 'clay', 0, '2026-10-06 12:00:00')"
    )
    conn.execute(
        "INSERT INTO devices (id, label, kind, member_id, is_kid_device, paired_via, "
        "created_at, last_seen_at) VALUES ('d1', 'Phone', 'phone', 'm1', 0, 'password', "
        "'2026-10-06 12:00:00', '2026-10-06 12:00:00')"
    )
    conn.commit()
    conn.close()

    engine = migrate.migration_engine(db)
    with engine.connect() as connection, connection.begin():
        operations = Operations(MigrationContext.configure(connection))
        with operations.batch_alter_table("members", recreate="always") as batch:
            batch.add_column(sa_column("temporary_flag"))
    engine.dispose()

    conn = sqlite3.connect(db)
    try:
        assert conn.execute("SELECT member_id FROM devices WHERE id='d1'").fetchone()[0] == "m1"
    finally:
        conn.close()


def sa_column(name: str):
    from sqlalchemy import Column

    return Column(name, Integer, nullable=True)


def test_unknown_revision_is_detected(tmp_path: Path) -> None:
    db = tmp_path / "sunroom.db"
    migrate.upgrade(db)
    conn = sqlite3.connect(db)
    conn.execute("UPDATE alembic_version SET version_num = '209912312359'")
    conn.commit()
    conn.close()
    with pytest.raises(migrate.UnknownRevisionError):
        migrate.check_known(db)


def test_a_household_from_0_10_0_keeps_the_calendar_week(tmp_path: Path) -> None:
    """0.11.0 (ADR 0033): Rolling week is new and off, so an upgraded wall still shows the
    calendar week until a parent turns it on."""
    db = tmp_path / "sunroom.db"
    conn = sqlite3.connect(db)
    conn.executescript((FIXTURE_DBS / "202610141930.sql").read_text())
    conn.close()
    assert migrate.upgrade(db) == migrate.head_revision()
    conn = sqlite3.connect(db)
    try:
        # Rolling week is a home view since 0.17.0 (ADR 0042): still the calendar week here.
        assert conn.execute("SELECT display_home_view FROM household").fetchall() == [("week",)]
    finally:
        conn.close()


def test_a_household_from_0_11_0_shows_tips(tmp_path: Path) -> None:
    """0.12.0 (ADR 0034): tips are on by default, and turned on once for every household that
    had them off; a column added later still starts on."""
    db = tmp_path / "sunroom.db"
    conn = sqlite3.connect(db)
    conn.executescript((FIXTURE_DBS / "202610151730.sql").read_text())
    conn.execute("UPDATE household SET show_tips = 0")
    conn.commit()
    conn.close()
    assert migrate.upgrade(db) == migrate.head_revision()
    conn = sqlite3.connect(db)
    try:
        assert conn.execute("SELECT show_tips FROM household").fetchall() == [(1,)]
        default = next(
            row[4] for row in conn.execute("PRAGMA table_info(household)") if row[1] == "show_tips"
        )
        assert default in ("1", "'1'", "true", "TRUE")
    finally:
        conn.close()


def test_synced_events_with_nobody_on_them_let_their_title_decide(tmp_path: Path) -> None:
    """0.12.0 (ADR 0034): a synced event with no people was never a hand choice, so its title
    decides from now on; one with people, and every local event, stays as it was."""
    db = tmp_path / "sunroom.db"
    conn = sqlite3.connect(db)
    conn.executescript((FIXTURE_DBS / "202610151730.sql").read_text())
    columns = [row[1] for row in conn.execute("PRAGMA table_info(events)")]
    trip = dict(
        zip(
            columns,
            conn.execute("SELECT * FROM events WHERE source = 'sync'").fetchone(),
            strict=True,
        )
    )
    picked = {**trip, "id": str(trip["id"])[:-3] + "599", "remote_uid": "picked@test"}
    conn.execute(
        f"INSERT INTO events ({', '.join(picked)}) VALUES ({', '.join('?' for _ in picked)})",  # noqa: S608
        list(picked.values()),
    )
    member = conn.execute("SELECT id FROM members LIMIT 1").fetchone()[0]
    conn.execute("INSERT INTO event_members VALUES (?, ?)", (picked["id"], member))
    conn.commit()
    conn.close()
    assert migrate.upgrade(db) == migrate.head_revision()
    conn = sqlite3.connect(db)
    try:
        flagged = dict(conn.execute("SELECT id, people_from_title FROM events").fetchall())
    finally:
        conn.close()
    assert flagged.pop(trip["id"]) == 1
    assert flagged.pop(picked["id"]) == 0
    assert set(flagged.values()) == {0}


def test_a_household_from_0_11_0_has_no_default_reminder(tmp_path: Path) -> None:
    """0.12.0 (ADR 0034): the Default reminder starts as none, and no event is set to none,
    so every event keeps reminding exactly as it did."""
    db = tmp_path / "sunroom.db"
    conn = sqlite3.connect(db)
    conn.executescript((FIXTURE_DBS / "202610151730.sql").read_text())
    conn.close()
    assert migrate.upgrade(db) == migrate.head_revision()
    conn = sqlite3.connect(db)
    try:
        assert conn.execute("SELECT default_reminder_minutes FROM household").fetchall() == [
            (None,)
        ]
        assert {row[0] for row in conn.execute("SELECT reminders_off FROM events")} == {0}
    finally:
        conn.close()


def test_a_household_from_0_11_0_keeps_its_nightly_backups(tmp_path: Path) -> None:
    """0.12.0 (ADR 0034): Settings → Backup starts as 0.11.0 behaved: a copy every night, with
    14 daily and 8 weekly kept."""
    db = tmp_path / "sunroom.db"
    conn = sqlite3.connect(db)
    conn.executescript((FIXTURE_DBS / "202610151730.sql").read_text())
    conn.close()
    assert migrate.upgrade(db) == migrate.head_revision()
    conn = sqlite3.connect(db)
    try:
        assert conn.execute(
            "SELECT backups_enabled, backups_keep_daily, backups_keep_weekly FROM household"
        ).fetchall() == [(1, 14, 8)]
    finally:
        conn.close()


def test_a_sunroom_from_0_12_0_gets_its_own_id(tmp_path: Path) -> None:
    """0.13.0 (ADR 0035): GET /api/discover hands screens an id that lasts, made once by the
    migration for the one app_meta row; everything else in the row stays."""
    db = tmp_path / "sunroom.db"
    conn = sqlite3.connect(db)
    conn.executescript((FIXTURE_DBS / "202610161644.sql").read_text())
    before = conn.execute(
        "SELECT auth_epoch, password_hash, last_boot_version FROM app_meta"
    ).fetchall()
    conn.close()
    assert migrate.upgrade(db) == migrate.head_revision()
    conn = sqlite3.connect(db)
    try:
        rows = conn.execute(
            "SELECT auth_epoch, password_hash, last_boot_version, instance_id FROM app_meta"
        ).fetchall()
    finally:
        conn.close()
    assert [row[:3] for row in rows] == before
    assert len(rows) == 1 and uuid.UUID(rows[0][3]).version == 7


def test_photo_sources_from_0_13_0_are_connected_with_nothing_cached(tmp_path: Path) -> None:
    """0.14.0 (ADR 0036): every source gets a status (the inbox is connected), an empty cache of
    choices, and the new table of a library's photos starts empty; nothing else changes."""
    db = tmp_path / "sunroom.db"
    conn = sqlite3.connect(db)
    conn.executescript((FIXTURE_DBS / "202610201813.sql").read_text())
    before = conn.execute(
        "SELECT id, kind, label, config_json, enabled, items_seen FROM photo_sources"
    ).fetchall()
    conn.close()
    assert before
    assert migrate.upgrade(db) == migrate.head_revision()
    conn = sqlite3.connect(db)
    try:
        rows = conn.execute(
            "SELECT id, kind, label, config_json, enabled, items_seen, status, options_json,"
            " options_at FROM photo_sources"
        ).fetchall()
        items = conn.execute("SELECT count(*) FROM photo_source_items").fetchone()
    finally:
        conn.close()
    assert [row[:6] for row in rows] == before
    assert {row[6:] for row in rows} == {("connected", "{}", None)}
    assert items == (0,)


def test_accounts_named_icloud_become_apple(tmp_path: Path) -> None:
    """0.10.0 (ADR 0032): the family reads "Apple", so a CalDAV account 0.9.0 named "iCloud · …"
    as it connected reads "Apple · …". A name someone chose, and a calendar address, keep theirs."""
    db = tmp_path / "sunroom.db"
    conn = sqlite3.connect(db)
    conn.executescript((FIXTURE_DBS / "202610131907.sql").read_text())
    columns = [row[1] for row in conn.execute("PRAGMA table_info(sync_accounts)")]
    apple = dict(
        zip(
            columns,
            conn.execute("SELECT * FROM sync_accounts WHERE provider = 'caldav'").fetchone(),
            strict=True,
        )
    )
    for suffix, label in (("b", "iCloud"), ("c", "Our iCloud")):
        row = {**apple, "id": str(apple["id"])[:-1] + suffix, "label": label}
        conn.execute(
            f"INSERT INTO sync_accounts ({', '.join(row)}) VALUES ({', '.join('?' for _ in row)})",  # noqa: S608
            list(row.values()),
        )
    conn.execute(
        "UPDATE sync_accounts SET label = 'iCloud · a public calendar' WHERE provider = 'ics'"
    )
    conn.commit()
    conn.close()
    assert migrate.upgrade(db) == migrate.head_revision()
    conn = sqlite3.connect(db)
    try:
        labels = sorted(conn.execute("SELECT provider, label FROM sync_accounts").fetchall())
    finally:
        conn.close()
    assert labels == [
        ("caldav", "Apple"),
        ("caldav", "Apple · sample@…"),
        ("caldav", "Our iCloud"),
        ("ics", "iCloud · a public calendar"),
    ]


@pytest.mark.parametrize(
    ("rolling", "home", "wakes_on"),
    [(1, "week", "rolling"), (0, "week", "week"), (1, "people", "people")],
)
def test_a_household_from_0_16_1_on_rolling_week_wakes_on_rolling_week(
    tmp_path: Path, rolling: int, home: str, wakes_on: str
) -> None:
    """0.17.0 (ADR 0042): Rolling week is a view of its own, not a switch on Week. A household
    that had it on, starting on Week, starts on Rolling Week; any other keeps its home view, and
    a household that's set up keeps its layout (Hours is a new household's start)."""
    db = tmp_path / "sunroom.db"
    conn = sqlite3.connect(db)
    conn.executescript((FIXTURE_DBS / "202610211809.sql").read_text())
    conn.execute(
        "UPDATE household SET display_rolling_week = ?, display_home_view = ?,"
        " display_week_layout = 'agenda'",
        (rolling, home),
    )
    conn.commit()
    conn.close()
    assert migrate.upgrade(db) == migrate.head_revision()
    conn = sqlite3.connect(db)
    try:
        assert conn.execute(
            "SELECT display_home_view, display_week_layout, onboarded_at IS NOT NULL FROM household"
        ).fetchall() == [(wakes_on, "agenda", 1)]
        columns = [row[1] for row in conn.execute("PRAGMA table_info(household)")]
        assert "display_rolling_week" not in columns
    finally:
        conn.close()


def test_a_new_household_starts_on_week_with_hours(tmp_path: Path) -> None:
    """0.17.0 (ADR 0042): the household's row exists from the first migration on, before setup;
    a household not set up yet starts on Week with the Hours layout."""
    db = tmp_path / "sunroom.db"
    assert migrate.upgrade(db) == migrate.head_revision()
    conn = sqlite3.connect(db)
    try:
        assert conn.execute(
            "SELECT display_home_view, display_week_layout, onboarded_at FROM household"
        ).fetchall() == [("week", "hours", None)]
        default = next(
            row[4]
            for row in conn.execute("PRAGMA table_info(household)")
            if row[1] == "display_week_layout"
        )
        assert default == "'hours'"
    finally:
        conn.close()
