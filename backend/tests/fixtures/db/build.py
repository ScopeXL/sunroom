"""Build a synthetic fixture database for a released migration revision (CLAUDE.md rule 3).

Every release adds `tests/fixtures/db/<revision>.sql`: the schema at that release plus a few
synthetic rows in every table. `tests/test_migrations.py` replays each file and migrates it to
head, so a new migration can't break a real household's data.

    cd backend && uv run python -m tests.fixtures.db.build 202610071800

Only synthetic values: "Sample Family", "Sample Parent", made-up ids and hashes.
Seeds never change once their file is committed; a new release adds a new entry.
"""

# Only this file's own constant ids are interpolated into the seed SQL.
# ruff: noqa: S608

from __future__ import annotations

import sqlite3
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

from alembic import command

from sunroom.db import migrate

HERE = Path(__file__).parent

# A statement, or a statement with `?` parameters.
Statement = str | tuple[str, tuple[object, ...]]

PARENT = "00000000-0000-7000-8000-000000000001"  # Sample Parent
KID = "00000000-0000-7000-8000-000000000002"  # Sample Kid
GUEST = "00000000-0000-7000-8000-000000000003"  # Sample Guest, removed
PHONE = "00000000-0000-7000-8000-0000000000d1"
SCREEN = "00000000-0000-7000-8000-0000000000d2"
AVATAR = "00000000-0000-7000-8000-000000000201"


def _v0_1_0() -> list[Statement]:
    """0.1.0: a set-up household with two people and a removed one, a phone and a paired
    screen, an expired code, an avatar, an allowlist entry and a plugin row."""
    return [
        "UPDATE household SET name = 'Sample Family', timezone = 'America/New_York', "
        "week_starts_on = 6, onboarded_at = '2026-10-07 12:00:00', "
        "updated_at = '2026-10-07 12:00:00' WHERE id = 1",
        "UPDATE app_meta SET password_hash = 'scrypt$sample$sample', last_boot_version = '0.1.0' "
        "WHERE id = 1",
        "INSERT INTO photos (id, kind, source_key, original_name, taken_at, width, height, bytes, "
        "sha256, created_at, hidden, deleted_at) VALUES "
        f"('{AVATAR}', 'avatar', 'upload', 'sample.jpg', NULL, 512, 512, 2048, "
        f"'{'0' * 63}1', '2026-10-07 12:05:00', 0, NULL)",
        "INSERT INTO members (id, name, role, color, avatar_photo_id, birthday, sort, "
        "created_at, archived_at) VALUES "
        f"('{PARENT}', 'Sample Parent', 'parent', 'sky', '{AVATAR}', NULL, 0, "
        "'2026-10-07 12:01:00', NULL), "
        f"('{KID}', 'Sample Kid', 'kid', 'berry', NULL, '2018-05-04', 1, "
        "'2026-10-07 12:02:00', NULL), "
        f"('{GUEST}', 'Sample Guest', 'parent', 'moss', NULL, NULL, 2, "
        "'2026-10-07 12:03:00', '2026-10-07 13:00:00')",
        "INSERT INTO devices (id, label, kind, member_id, is_kid_device, paired_via, created_at, "
        "last_seen_at, revoked_at) VALUES "
        f"('{PHONE}', 'iPhone, Safari', 'phone', '{PARENT}', 0, 'password', "
        "'2026-10-07 12:00:00', '2026-10-07 12:30:00', NULL), "
        f"('{SCREEN}', 'Wall screen', 'kiosk', NULL, 0, 'kiosk_code', "
        "'2026-10-07 12:10:00', '2026-10-07 12:40:00', NULL)",
        "INSERT INTO join_codes (code_hash, kind, created_by_device_id, poll_token_hash, "
        "created_at, expires_at, used_at, used_by_device_id) VALUES "
        f"('{'0' * 63}2', 'kiosk', NULL, '{'0' * 63}3', '2026-10-07 12:09:00', "
        f"'2026-10-07 12:19:00', '2026-10-07 12:10:00', '{SCREEN}')",
        "INSERT INTO network_allowlist (id, target, label, created_by_member_id, created_at) "
        "VALUES ('00000000-0000-7000-8000-000000000301', '192.168.1.20/32', 'Sample NAS', "
        f"'{PARENT}', '2026-10-07 12:20:00')",
        "INSERT INTO plugin_state (plugin_id, enabled, settings_json, settings_version, "
        "plugin_version, enabled_at, disabled_at, updated_at) VALUES "
        "('sample', 0, '{}', 1, '1.0.0', NULL, NULL, '2026-10-07 12:00:00')",
    ]


KIDS = "00000000-0000-7000-8000-000000000401"  # the "Kids' activities" calendar
SOCCER = "00000000-0000-7000-8000-000000000501"  # weekly, with one moved occurrence
SOCCER_MOVED = "00000000-0000-7000-8000-000000000502"
PAJAMAS = "00000000-0000-7000-8000-000000000503"  # all-day
VET = "00000000-0000-7000-8000-000000000504"  # removed, in Recently removed
SCHOOL = "00000000-0000-7000-8000-000000000402"  # a synced calendar, from a calendar address
FIELD_TRIP = "00000000-0000-7000-8000-000000000505"  # a synced event in it
FEED = "00000000-0000-7000-8000-000000000701"  # the calendar address's account
FEED_CALENDAR = "00000000-0000-7000-8000-000000000702"  # the account's one calendar


def _v0_2_0() -> list[Statement]:
    """0.2.0: 0.1.0's household plus a second calendar, a weekly event with a moved
    occurrence, people and a reminder, an all-day event, a removed event and its revision."""
    timed = (
        "INSERT INTO events (id, calendar_id, parent_event_id, recurrence_id, title, description,"
        " location, all_day, start_utc, end_utc, tzid, start_date, end_date, floating, rrule,"
        " rdates_json, exdates_json, window_start_utc, window_end_utc, status, color, source,"
        " remote_uid, remote_id, etag, remote_updated_at, remote_sequence, pending_push,"
        " pending_delete, raw_ical, version, created_by_member_id, created_at, updated_at,"
        " deleted_at) VALUES "
    )
    return [
        *_v0_1_0(),
        "INSERT INTO calendars (id, name, color, kind, owner_member_id, read_only,"
        " visible_on_display, version, remote_ref, sort, created_at, updated_at, deleted_at)"
        f" VALUES ('{KIDS}', 'Kids'' activities', 'iris', 'local', '{KID}', 0, 1, 3, NULL, 1,"
        " '2026-10-08 12:00:00', '2026-10-08 12:00:00', NULL)",
        timed + f"('{SOCCER}', '{KIDS}', NULL, NULL, 'Soccer practice', '', 'Field 3', 0,"
        " '2026-09-29 20:00:00', '2026-09-29 21:00:00', 'America/New_York', NULL, NULL, 0,"
        " 'FREQ=WEEKLY;BYDAY=TU,TH', '[]', '[\"2026-10-13T16:00:00\"]',"
        " '2026-09-29 20:00:00', '9999-12-31 00:00:00', 'confirmed', NULL, 'local', NULL, NULL,"
        f" NULL, NULL, NULL, 0, 0, NULL, 2, '{PARENT}', '2026-10-08 12:01:00',"
        " '2026-10-08 12:05:00', NULL)",
        timed
        + f"('{SOCCER_MOVED}', '{KIDS}', '{SOCCER}', '2026-10-08T16:00:00', 'Soccer practice',"
        " '', 'Field 3', 0, '2026-10-08 21:00:00', '2026-10-08 22:00:00', 'America/New_York',"
        " NULL, NULL, 0, NULL, '[]', '[]', '2026-10-08 21:00:00', '2026-10-08 22:00:00',"
        " 'confirmed', NULL, 'local', NULL, NULL, NULL, NULL, NULL, 0, 0, NULL, 1,"
        f" '{PARENT}', '2026-10-08 12:05:00', '2026-10-08 12:05:00', NULL)",
        timed + f"('{PAJAMAS}', '{KIDS}', NULL, NULL, 'Pajama day', '', '', 1, NULL, NULL, NULL,"
        " '2026-10-09', '2026-10-10', 0, NULL, '[]', '[]', '2026-10-09 00:00:00',"
        " '2026-10-11 00:00:00', 'confirmed', 'rose', 'local', NULL, NULL, NULL, NULL, NULL, 0,"
        f" 0, NULL, 1, '{PARENT}', '2026-10-08 12:02:00', '2026-10-08 12:02:00', NULL)",
        timed + f"('{VET}', '{KIDS}', NULL, NULL, 'Vet', '', '', 0, '2026-10-07 13:00:00',"
        " '2026-10-07 13:30:00', 'America/New_York', NULL, NULL, 0, NULL, '[]', '[]',"
        " '2026-10-07 13:00:00', '2026-10-07 13:30:00', 'confirmed', NULL, 'local', NULL, NULL,"
        f" NULL, NULL, NULL, 0, 0, NULL, 2, '{PARENT}', '2026-10-08 12:03:00',"
        " '2026-10-08 12:04:00', '2026-10-08 12:04:00')",
        "INSERT INTO event_members (event_id, member_id) VALUES "
        f"('{SOCCER}', '{KID}'), ('{SOCCER_MOVED}', '{KID}'), ('{VET}', '{PARENT}')",
        f"INSERT INTO event_reminders (event_id, minutes_before) VALUES ('{SOCCER}', 30)",
        "INSERT INTO event_revisions (id, series_id, action, before_json, created_ids_json,"
        " device_id, member_id, created_at, undone_at) VALUES"
        f" ('00000000-0000-7000-8000-000000000601', '{VET}', 'delete', '[]', '[]',"
        f" '{PHONE}', '{PARENT}', '2026-10-08 12:04:00', NULL)",
    ]


def _v0_3_0() -> list[Statement]:
    """0.3.0: 0.2.0's household plus a calendar address mapped to the kid (a synced calendar
    holding one synced event), the account's last sync run, and a sign-in nobody finished."""
    return [
        *_v0_2_0(),
        "INSERT INTO calendars (id, name, color, kind, owner_member_id, read_only,"
        " visible_on_display, version, remote_ref, sort, created_at, updated_at, deleted_at)"
        f" VALUES ('{SCHOOL}', 'School', 'olive', 'sync', '{KID}', 1, 1, 1,"
        " 'a calendar address', 1000, '2026-10-08 18:00:00', '2026-10-08 18:00:00', NULL)",
        "INSERT INTO events (id, calendar_id, parent_event_id, recurrence_id, title, description,"
        " location, all_day, start_utc, end_utc, tzid, start_date, end_date, floating, rrule,"
        " rdates_json, exdates_json, window_start_utc, window_end_utc, status, color, source,"
        " remote_uid, remote_id, etag, remote_updated_at, remote_sequence, pending_push,"
        " pending_delete, raw_ical, version, created_by_member_id, created_at, updated_at,"
        f" deleted_at) VALUES ('{FIELD_TRIP}', '{SCHOOL}', NULL, NULL, 'Field trip', '',"
        " 'Sample Farm', 0, '2026-10-15 13:00:00', '2026-10-15 17:00:00', 'America/New_York',"
        " NULL, NULL, 0, NULL, '[]', '[]', '2026-10-15 13:00:00', '2026-10-15 17:00:00',"
        " 'confirmed', NULL, 'sync', 'field-trip@school.example.com', NULL, NULL,"
        " '2026-10-08 17:00:00', 0, 0, 0, NULL, 1, NULL, '2026-10-08 18:00:00',"
        " '2026-10-08 18:00:00', NULL)",
        "INSERT INTO sync_accounts (id, provider, auth_mode, label, status, server_url, username,"
        " credentials_enc, config_json, allow_private, owner_member_id, interval_s, last_sync_at,"
        " last_success_at, next_sync_at, last_error, last_error_at, consecutive_failures,"
        " version, created_by_member_id, created_at, deleted_at) VALUES"
        f" ('{FEED}', 'ics', 'none', 'School', 'connected', 'school.example.com/school.ics',"
        f" NULL, 'sample-ciphertext', '{{}}', 0, '{KID}', 1800, '2026-10-08 18:30:00',"
        " '2026-10-08 18:30:00', '2026-10-08 19:00:00', NULL, NULL, 0, 1,"
        f" '{PARENT}', '2026-10-08 18:00:00', NULL)",
        "INSERT INTO remote_calendars (id, account_id, remote_id, name, color_hint, read_only,"
        " mapped, calendar_id, sync_token, ctag, last_synced_at, last_error, created_at) VALUES"
        f" ('{FEED_CALENDAR}', '{FEED}', 'feed-000000000000000000000001', 'School', NULL, 1, 1,"
        f" '{SCHOOL}', '{{\"etag\": \"\\\"1\\\"\"}}', NULL, '2026-10-08 18:30:00', NULL,"
        " '2026-10-08 18:00:00')",
        "INSERT INTO sync_runs (id, account_id, started_at, finished_at, outcome, fetched,"
        " created, updated, deleted, pushed, error, duration_ms) VALUES"
        f" ('00000000-0000-7000-8000-000000000801', '{FEED}', '2026-10-08 18:30:00',"
        " '2026-10-08 18:30:01', 'ok', 1, 0, 0, 0, 0, NULL, 140)",
        "INSERT INTO oauth_states (state_hash, provider, code_verifier, device_id, account_id,"
        f" created_at, expires_at, used_at) VALUES ('{'0' * 63}4', 'google', 'sample-verifier',"
        f" '{PHONE}', NULL, '2026-10-08 18:40:00', '2026-10-08 18:50:00', NULL)",
        "INSERT INTO plugin_state (plugin_id, enabled, settings_json, settings_version, "
        "plugin_version, enabled_at, disabled_at, updated_at) VALUES "
        "('calendar_sync', 1, '{\"google_client_id\": null, \"google_client_secret\": null}',"
        " 1, '1.0.0', '2026-10-08 18:00:00', NULL, '2026-10-08 18:00:00')",
    ]


GROCERIES = "00000000-0000-7000-8000-000000000901"
CAMPING = "00000000-0000-7000-8000-000000000902"  # removed, in Recently removed
DISHES = "00000000-0000-7000-8000-000000000a01"  # a daily chore that takes turns
FEED_FISH = "00000000-0000-7000-8000-000000000a02"  # the kid's own, needs a parent's yes
MOVIE = "00000000-0000-7000-8000-000000000a11"  # a reward
BEDTIME = "00000000-0000-7000-8000-000000000a21"  # the kid's routine
BRUSH = "00000000-0000-7000-8000-000000000a22"  # its first step


def _v0_4_0() -> list[Statement]:
    """0.4.0: 0.3.0's household plus Groceries (open, checked and cleared items), a removed
    packing list and a to-do with a day; a chore that takes turns (done) and the kid's own
    (waiting for a parent); stars given by hand, a reward asked for, and a bedtime routine
    with a step checked and the routine finished."""
    item = (
        "INSERT INTO list_items (id, list_id, text, note, quantity, due_date, assigned_member_id,"
        " checked_at, checked_by_member_id, position, version, created_by_member_id, created_at,"
        " updated_at, cleared_at, deleted_at) VALUES "
    )
    return [
        *_v0_3_0(),
        "INSERT INTO lists (id, name, kind, icon, sort, created_by_member_id, created_at,"
        " updated_at, deleted_at) VALUES"
        f" ('{GROCERIES}', 'Groceries', 'grocery', NULL, 0, '{PARENT}', '2026-10-08 19:00:00',"
        " '2026-10-08 19:00:00', NULL),"
        f" ('{CAMPING}', 'Packing: camping', 'packing', NULL, 1, '{KID}', '2026-10-08 19:00:00',"
        " '2026-10-08 19:30:00', '2026-10-08 19:30:00')",
        item + f"('00000000-0000-7000-8000-000000000911', '{GROCERIES}', 'Milk', NULL, '2',"
        f" NULL, NULL, NULL, NULL, 0, 1, '{PARENT}', '2026-10-08 19:01:00',"
        " '2026-10-08 19:01:00', NULL, NULL),"
        f" ('00000000-0000-7000-8000-000000000912', '{GROCERIES}', 'Bread', 'Whole wheat', NULL,"
        f" NULL, NULL, '2026-10-08 19:10:00', '{KID}', 1, 2, '{PARENT}', '2026-10-08 19:01:00',"
        " '2026-10-08 19:10:00', NULL, NULL),"
        f" ('00000000-0000-7000-8000-000000000913', '{GROCERIES}', 'Apples', NULL, NULL, NULL,"
        f" NULL, '2026-10-01 19:10:00', '{PARENT}', 2, 2, '{PARENT}', '2026-10-01 19:01:00',"
        " '2026-10-01 19:10:00', '2026-10-02 08:00:00', NULL),"
        f" ('00000000-0000-7000-8000-000000000914', '{GROCERIES}', 'Call the plumber', NULL,"
        f" NULL, '2026-10-09', '{PARENT}', NULL, NULL, 3, 1, '{PARENT}', '2026-10-08 19:02:00',"
        " '2026-10-08 19:02:00', NULL, NULL),"
        f" ('00000000-0000-7000-8000-000000000915', '{CAMPING}', 'Tent', NULL, NULL, NULL,"
        f" '{KID}', NULL, NULL, 0, 1, '{KID}', '2026-10-08 19:00:00', '2026-10-08 19:00:00',"
        " NULL, NULL)",
        "INSERT INTO chores (id, title, description, icon, points, rrule, start_date, due_time,"
        " assignee_mode, assignee_member_ids_json, rotation_index, requires_approval,"
        " skipped_dates_json, active, created_by_member_id, created_at, updated_at, deleted_at)"
        f" VALUES ('{DISHES}', 'Empty the dishwasher', NULL, 'plate', 1, 'FREQ=DAILY',"
        f" '2026-10-01', '19:00', 'rotate', '[\"{PARENT}\", \"{KID}\"]', 0, NULL,"
        f" '[\"2026-10-05\"]', 1, '{PARENT}', '2026-10-01 12:00:00', '2026-10-05 12:00:00',"
        f" NULL), ('{FEED_FISH}', 'Feed the fish', 'A pinch, not the whole jar.', NULL, 2,"
        f" 'FREQ=WEEKLY;BYDAY=MO,WE,FR', '2026-10-01', NULL, 'fixed', '[\"{KID}\"]', 0, 1,"
        f" '[]', 1, '{PARENT}', '2026-10-01 12:00:00', '2026-10-01 12:00:00', NULL)",
        "INSERT INTO chore_completions (id, chore_id, due_date, member_id, completed_at,"
        " completed_by_device_id, points_awarded, status, approved_by_member_id, approved_at)"
        f" VALUES ('00000000-0000-7000-8000-000000000a31', '{DISHES}', '2026-10-08', '{KID}',"
        f" '2026-10-08 23:10:00', '{SCREEN}', 1, 'done', NULL, NULL),"
        f" ('00000000-0000-7000-8000-000000000a32', '{FEED_FISH}', '2026-10-07', '{KID}',"
        f" '2026-10-07 21:00:00', '{SCREEN}', 2, 'pending', NULL, NULL)",
        "INSERT INTO point_adjustments (id, member_id, points, reason, by_member_id, created_at)"
        f" VALUES ('00000000-0000-7000-8000-000000000a41', '{KID}', 10, 'Helped with the"
        f" groceries', '{PARENT}', '2026-10-06 18:00:00')",
        "INSERT INTO rewards (id, title, cost_points, icon, active, sort, created_at, deleted_at)"
        f" VALUES ('{MOVIE}', 'Movie night', 30, 'film', 1, 0, '2026-10-01 12:00:00', NULL)",
        "INSERT INTO redemptions (id, reward_id, member_id, cost_points, status, requested_at,"
        f" decided_by_member_id, decided_at) VALUES ('00000000-0000-7000-8000-000000000a51',"
        f" '{MOVIE}', '{KID}', 30, 'requested', '2026-10-08 20:00:00', NULL, NULL)",
        "INSERT INTO routines (id, title, member_id, days_json, window_start, window_end, icon,"
        f" points, sort, active, created_at, deleted_at) VALUES ('{BEDTIME}', 'Bedtime routine',"
        f" '{KID}', '[0, 1, 2, 3, 4, 5, 6]', '19:30', '20:30', 'moon', 3, 0, 1,"
        " '2026-10-01 12:00:00', NULL)",
        "INSERT INTO routine_steps (id, routine_id, title, icon, position) VALUES"
        f" ('{BRUSH}', '{BEDTIME}', 'Brush teeth', 'toothbrush', 0),"
        f" ('00000000-0000-7000-8000-000000000a23', '{BEDTIME}', 'Into bed', 'bed', 1)",
        "INSERT INTO routine_checks (routine_step_id, member_id, day, checked_at) VALUES"
        f" ('{BRUSH}', '{KID}', '2026-10-08', '2026-10-08 23:35:00')",
        "INSERT INTO routine_finishes (routine_id, member_id, day, finished_at, points_awarded)"
        f" VALUES ('{BEDTIME}', '{KID}', '2026-10-07', '2026-10-07 23:50:00', 3)",
        "INSERT INTO plugin_state (plugin_id, enabled, settings_json, settings_version, "
        "plugin_version, enabled_at, disabled_at, updated_at) VALUES "
        "('lists', 1, '{\"auto_clear_days\": \"never\"}', 1, '1.0.0', '2026-10-08 19:00:00',"
        " NULL, '2026-10-08 19:00:00'),"
        ' (\'chores\', 1, \'{"stars": true, "rewards": true, "routines": true,'
        " \"approval\": false}', 2, '1.0.0', '2026-10-08 19:00:00', NULL,"
        " '2026-10-08 19:05:00')",
    ]


TACOS = "00000000-0000-7000-8000-000000000b01"  # a saved meal with ingredients
TACO_NIGHT = "00000000-0000-7000-8000-000000000b02"  # tonight's dinner, from it
SOUP = "00000000-0000-7000-8000-000000000b03"  # a dinner taken off its day
TRIP = "00000000-0000-7000-8000-000000000b11"  # a countdown, the kid's
INBOX = "00000000-0000-7000-8000-000000000b21"  # the photos folder


def _v0_5_0() -> list[Statement]:
    """0.5.0: 0.4.0's household plus a saved meal with ingredients, tonight's dinner made from
    it and a dinner removed; a yearly countdown for the kid and a surprise kept off the wall; the
    photos folder source; and a cached forecast for the household's place."""
    entry = (
        "INSERT INTO meal_entries (id, day, slot, position, text, emoji, recipe_url, note,"
        " member_id, saved_meal_id, source_url, created_by_member_id, created_at, updated_at,"
        " deleted_at) VALUES "
    )
    return [
        *_v0_4_0(),
        "UPDATE household SET location_label = 'Sample Town', latitude = 40.71, longitude = -74.01",
        "INSERT INTO saved_meals (id, text, emoji, recipe_url, ingredients_json, use_count,"
        " last_used_at, created_by_member_id, created_at, updated_at, deleted_at) VALUES"
        f" ('{TACOS}', 'Tacos', '🌮', 'https://recipes.example.com/tacos',"
        f" '[\"Tortillas\", \"Cheese\"]', 3, '2026-10-08 21:00:00', '{PARENT}',"
        " '2026-10-01 21:00:00', '2026-10-08 21:00:00', NULL)",
        entry + f"('{TACO_NIGHT}', '2026-10-08', 'dinner', 0, 'Tacos', '🌮',"
        f" 'https://recipes.example.com/tacos', 'Extra salsa', '{PARENT}', '{TACOS}', NULL,"
        f" '{PARENT}', '2026-10-08 21:00:00', '2026-10-08 21:00:00', NULL),"
        f" ('{SOUP}', '2026-10-09', 'dinner', 0, 'Soup', NULL, NULL, NULL, NULL, NULL, NULL,"
        f" '{KID}', '2026-10-08 21:05:00', '2026-10-08 21:10:00', '2026-10-08 21:10:00')",
        "INSERT INTO countdowns (id, title, emoji, color, date, time, repeat_yearly, member_id,"
        " show_on_display, created_by_member_id, created_at, updated_at, deleted_at) VALUES"
        f" ('{TRIP}', 'Beach day', '🏖️', 'sky', '2027-07-04', '09:00', 1, '{KID}', 1,"
        f" '{PARENT}', '2026-10-08 21:20:00', '2026-10-08 21:20:00', NULL),"
        " ('00000000-0000-7000-8000-000000000b12', 'Surprise party', '🎉', NULL, '2026-11-20',"
        f" NULL, 0, NULL, 0, '{PARENT}', '2026-10-08 21:21:00', '2026-10-08 21:21:00', NULL)",
        "INSERT INTO photo_sources (id, kind, label, config_json, credentials_enc, allow_private,"
        " enabled, last_scan_at, last_error, items_seen, created_at, deleted_at) VALUES"
        f" ('{INBOX}', 'inbox', 'Photos folder', '{{}}', NULL, 0, 1, '2026-10-08 21:30:00',"
        " NULL, 1, '2026-10-08 21:00:00', NULL)",
        "INSERT INTO weather_cache (id, latitude, longitude, units, payload_json, fetched_at,"
        " expires_at, last_error, last_error_at) VALUES (1, 40.71, -74.01, 'fahrenheit',"
        ' \'{"current": {"time": "2026-10-08T17:00", "temperature_2m": 61.0,'
        " \"weather_code\": 2, \"is_day\": 1}}', '2026-10-08 21:00:00', '2026-10-08 22:00:00',"
        " NULL, NULL)",
        "INSERT INTO plugin_state (plugin_id, enabled, settings_json, settings_version, "
        "plugin_version, enabled_at, disabled_at, updated_at) VALUES "
        "('meals', 1, '{\"slots\": [\"dinner\"], \"show_on_calendar\": true}', 2, '1.0.0',"
        " '2026-10-08 21:00:00', NULL, '2026-10-08 21:00:00'),"
        " ('countdowns', 1, '{\"birthdays\": true}', 1, '1.0.0', '2026-10-08 21:00:00', NULL,"
        " '2026-10-08 21:00:00'),"
        ' (\'screensaver\', 1, \'{"start_after": "10", "every": "30", "show_clock": true,'
        " \"shuffle\": true}', 1, '1.0.0', '2026-10-08 21:00:00', NULL, '2026-10-08 21:00:00'),"
        " ('weather', 0, '{\"units\": \"auto\"}', 1, '1.0.0', NULL, '2026-10-08 21:40:00',"
        " '2026-10-08 21:40:00')",
    ]


def _v0_6_0() -> list[Statement]:
    """0.6.0: 0.5.0's household with the evening dim set and the update check turned on."""
    return [
        *_v0_5_0(),
        "UPDATE household SET dim_from = '20:00', dim_level = 40, update_check = 1",
    ]


def _v0_7_0() -> list[Statement]:
    """0.7.0: 0.6.0's household with the Week board on Hours and the tips strip turned on."""
    return [
        *_v0_6_0(),
        "UPDATE household SET display_week_layout = 'hours', show_tips = 1",
    ]


def _v0_8_0() -> list[Statement]:
    """0.8.0 (M6 batch 2): 0.7.0's household with the rail folded to its icons and Small text;
    Meals 1.1.0's settings (a calendar choice per meal), and photos starting after 15 minutes."""
    return [
        *_v0_7_0(),
        "UPDATE household SET display_rail_compact = 1, text_size = 'small'",
        "UPDATE plugin_state SET plugin_version = '1.1.0', settings_json ="
        ' \'{"slots": ["dinner"], "calendar_slots": ["dinner"]}\' WHERE plugin_id = \'meals\'',
        'UPDATE plugin_state SET settings_json = \'{"start_after": "15", "every": "30",'
        ' "show_clock": true, "shuffle": true}\' WHERE plugin_id = \'screensaver\'',
    ]


def _v0_9_0() -> list[Statement]:
    """0.9.0 (M6 batch 3): 0.8.0's household opening at its home view after a restart, and an
    Apple calendar account, which 0.9.0 names "iCloud" as it connects."""
    return [
        *_v0_8_0(),
        "UPDATE household SET display_start = 'home'",
        "INSERT INTO sync_accounts (id, provider, auth_mode, label, status, server_url, username,"
        " credentials_enc, config_json, allow_private, owner_member_id, interval_s, last_sync_at,"
        " last_success_at, next_sync_at, last_error, last_error_at, consecutive_failures,"
        " version, created_by_member_id, created_at, deleted_at) VALUES"
        " ('00000000-0000-7000-8000-000000000a21', 'caldav', 'app_password',"
        " 'iCloud · sample@…', 'connected', 'https://caldav.icloud.com', 'sample@example.com',"
        " 'sample-ciphertext', '{}', 0, NULL, 300, '2026-10-13 19:30:00',"
        " '2026-10-13 19:30:00', '2026-10-13 19:35:00', NULL, NULL, 0, 1,"
        f" '{PARENT}', '2026-10-13 19:20:00', NULL)",
    ]


def _v0_10_0() -> list[Statement]:
    """0.10.0 (M6 batch 4): 0.9.0's rows, with the Apple account named as 0.10.0 names it."""
    return [
        *_v0_9_0(),
        "UPDATE sync_accounts SET label = 'Apple · sample@…'"
        " WHERE id = '00000000-0000-7000-8000-000000000a21'",
    ]


def _v0_11_0() -> list[Statement]:
    """0.11.0 (M6 batch 5): 0.10.0's rows, with the Week view on Rolling week."""
    return [
        *_v0_10_0(),
        "UPDATE household SET display_rolling_week = 1",
    ]


def _v0_12_0() -> list[Statement]:
    """0.12.0 (M6 batch 6): 0.11.0's rows, with a backup policy of the household's own."""
    return [
        *_v0_11_0(),
        "UPDATE household SET backups_keep_daily = 21, backups_keep_weekly = 4",
    ]


# Synthetic rows to insert, per released revision (the tables that exist at that revision).
def _v0_13_0() -> list[Statement]:
    """0.13.0 (M7 batch 1): 0.12.0's rows, with a fixed instance id (the migration makes a
    random one, and a fixture must come out the same every time it's built)."""
    return [
        *_v0_12_0(),
        "UPDATE app_meta SET instance_id = '00000000-0000-7000-8000-0000000000e1'",
    ]


LIBRARY = "00000000-0000-7000-8000-000000000b22"  # a photo library (Immich), needing its key
LIBRARY_PHOTO = "00000000-0000-7000-8000-000000000b23"  # core's copy of one of its photos


def _v0_14_0() -> list[Statement]:
    """0.14.0 (M6 batch 8): 0.13.0's rows, with a photo library: picks and choices in its
    config and cache, its key wiped by a new secret key (needs its key again), one photo
    brought in and one still waiting. Made-up ids and a pretend address only."""
    config = (
        '{"url": "http://immich.test", "picks": {"people": ["p-mia"], "albums": [],'
        ' "tags": []}, "limit": 500}'
    )
    options = (
        '{"people": [{"id": "p-mia", "name": "Sample Kid", "count": null, "has_thumb": true}],'
        ' "albums": [{"id": "a-beach", "name": "Beach 2026", "count": 2, "has_thumb": true}],'
        ' "tags": [], "unnamed_people": 1}'
    )
    return [
        *_v0_13_0(),
        (
            "INSERT INTO photo_sources (id, kind, label, config_json, credentials_enc,"
            " allow_private, enabled, last_scan_at, last_error, items_seen, created_at,"
            " deleted_at, status, options_json, options_at) VALUES (?, 'immich', 'Immich', ?,"
            " NULL, 0, 1, '2026-10-21 17:00:00', 'Sunroom can''t read this library''s saved"
            " key any more. Connect it again.', 1, '2026-10-21 16:00:00', NULL,"
            " 'needs_reconnect', ?, '2026-10-21 16:00:00')",
            (LIBRARY, config, options),
        ),
        "INSERT INTO photos (id, kind, source_key, original_name, taken_at, width, height, bytes,"
        f" sha256, created_at, hidden, deleted_at) VALUES ('{LIBRARY_PHOTO}', 'library',"
        f" 'source:{LIBRARY}', 'r-1.jpg', '2026-07-04 15:00:00', 1440, 960, 4096,"
        f" '{'0' * 63}2', '2026-10-21 16:01:00', 0, NULL)",
        "INSERT INTO photo_source_items (id, source_id, remote_id, photo_id, taken_at, seen_at,"
        " fetched_at, dropped_at, fetch_failures) VALUES"
        f" ('00000000-0000-7000-8000-000000000b24', '{LIBRARY}', 'r-1', '{LIBRARY_PHOTO}',"
        " '2026-07-04 15:00:00', '2026-10-21 17:00:00', '2026-10-21 16:01:00', NULL, 0),"
        f" ('00000000-0000-7000-8000-000000000b25', '{LIBRARY}', 'r-2', NULL,"
        " '2026-06-01 12:00:00', '2026-10-21 17:00:00', NULL, NULL, 1)",
    ]


SEEDS: dict[str, Callable[[], list[Statement]]] = {
    "202610071800": _v0_1_0,
    "202610081454": _v0_2_0,
    "202610081650": _v0_3_0,
    "202610081921": _v0_4_0,
    "202610082056": _v0_5_0,
    "202610082231": _v0_6_0,
    "202610091752": _v0_7_0,
    "202610121749": _v0_8_0,
    "202610131907": _v0_9_0,
    "202610141930": _v0_10_0,
    "202610151730": _v0_11_0,
    "202610161644": _v0_12_0,
    "202610201813": _v0_13_0,
    "202610211809": _v0_14_0,
}


def build(revision: str) -> Path:
    if revision not in SEEDS:
        raise SystemExit(f"add synthetic rows for {revision} to SEEDS first")
    out = HERE / f"{revision}.sql"
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "sunroom.db"
        engine = migrate.migration_engine(db)
        try:
            with engine.connect() as conn, conn.begin():
                config = migrate.alembic_config()
                config.attributes["connection"] = conn
                command.upgrade(config, revision)
                for statement in SEEDS[revision]():
                    if isinstance(statement, str):
                        conn.exec_driver_sql(statement)
                    else:
                        conn.exec_driver_sql(*statement)
        finally:
            engine.dispose()
        conn = sqlite3.connect(db)
        try:
            dump = "\n".join(conn.iterdump()) + "\n"
        finally:
            conn.close()
    out.write_text(dump)
    return out


if __name__ == "__main__":
    for name in sys.argv[1:]:
        print(f"wrote {build(name).relative_to(Path.cwd())}")
