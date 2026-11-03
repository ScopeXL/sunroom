# ha-sunroom: the Home Assistant integration for Sunroom (the 1.0 plan)

> **Status.** Planned on 2026-11-03, from a read of Sunroom at 0.18.0 plus the changes Sunroom
> 1.0 makes for connected apps (docs/V1.md, Phase C in the Sunroom repo), and from Home
> Assistant's developer docs as they stand for 2026.11 (released 2026-11-04). Written to be
> executed by an AI session (Opus 5.5) in its own repository, `ScopeXL/ha-sunroom`, checked out
> beside Sunroom's (`../sunroom` from there). This file is `docs/PLAN.md` there (the Sunroom
> repo keeps a copy as `docs/HA-SUNROOM.md` until 1.0 ships).
>
> **Maintenance rule.** When a task is built, tick it and add an "As built" line; when 1.0 ships,
> shrink this file to what is true (the architecture, the entities, the contract) and move what
> is left to do into `docs/ROADMAP.md`.

**How to work through this file.** Tasks go in order (T0 to T13); each names what it builds, the
files, its tests and its docs. The gate per task is the quick one: `just quick` (ruff, format,
pyright strict), `just test` for the tests the task touched, and nothing more. The full gate runs
once at the end (T13): `just check` (lint, types, every test, hassfest, the Marketplace action), the
live tests against a real Sunroom (T3), and a manual pass in the maintainer's own Home Assistant.
Commit after each task passes its gate: subject `area: summary`, the Co-Authored-By trailer.
Never read `.env`, `.private/` or `~/.config/sunroom/`; never commit anything from a real household;
the private-terms scan (copied from Sunroom) runs in the hooks. Every decision this plan leaves to
the owner is in §2 with its default, so the build can start without waiting.

## Contents

1. [What it is, who it's for, what 1.0 does](#1-what-it-is-who-its-for-what-10-does)
2. [Decisions](#2-decisions)
3. [What Sunroom gives the integration (the API contract)](#3-what-sunroom-gives-the-integration-the-api-contract)
4. [Architecture](#4-architecture)
5. [What the integration provides](#5-what-the-integration-provides)
6. [The card](#6-the-card)
7. [Setting it up: discovery, the config flow, reauth, options](#7-setting-it-up-discovery-the-config-flow-reauth-options)
8. [Repository, tooling, CI, releases, the Marketplace](#8-repository-tooling-ci-releases-the-marketplace)
9. [CLAUDE.md, and staying in step with Sunroom](#9-claudemd-and-staying-in-step-with-sunroom)
10. [Tasks](#10-tasks)
11. [Documentation for people who install it](#11-documentation-for-people-who-install-it)
12. [Limits, risks, and what comes after 1.0](#12-limits-risks-and-what-comes-after-10)
13. [Research notes](#13-research-notes)

---

## 1. What it is, who it's for, what 1.0 does

Sunroom is a self-hosted family wall calendar: one container or one program at home, a touch
screen on the wall, everyone's devices as the second screen, no account anywhere. `ha-sunroom` is
the bridge to Home Assistant for the households that run both: it lets a family see and change
their Sunroom calendars and lists inside Home Assistant, and lets Home Assistant automations act
on the wall screen (wake it when someone walks in, dim it at bedtime, show tonight's dinner when
the oven turns on) and on the family's data (add "batteries" to Groceries when the smoke alarm
chirps, mark "Feed the dog" done when the NFC tag by the food bin is tapped).

It is for homelab people who already run Home Assistant and want control, and it must still be
plain enough that a parent sets it up in two minutes: find Sunroom on the network, type the
household password once, done. It never replaces Sunroom's own screens; it is a second way in.

**1.0 does:**

1. **Finds and connects.** Discovery by mDNS where Sunroom announces itself, a typed address
   otherwise; the household password once; reconnect by itself when the token is revoked or the
   address changes.
2. **Calendars, both ways.** Every Sunroom calendar is a Home Assistant calendar entity that Home
   Assistant's own calendar panel and card can read, add to, change and delete from (recurring
   events included), with Sunroom's people and colors as attributes.
3. **Lists, both ways.** Every Sunroom list is a to-do entity.
4. **The wall screen as a device.** Each paired screen is a device with sensors (online, asleep,
   screensaver, view, room, brightness) and controls (wake, sleep, screensaver, brightness, view,
   room, Today panel, rail), plus actions for everything else the screen can do (show an event,
   a list, a person's tasks, say a line on the wall).
5. **The household's glance data as sensors.** What's next, what's on now, tonight's dinner, the
   next countdown, each person's tasks today and stars, Needs Attention, Sunroom's version and
   whether an update is out.
6. **Events on Home Assistant's bus** for automations: a task completed, an event changed, a
   screen's state changed, an update available.
7. **A card.** A clean list of what's coming up, in Sunroom's own colors, for people who don't
   want another calendar card; Calendar Card Pro and Home Assistant's calendar card keep working
   beside it on the calendar entities.
8. **A listing in the Marketplace** (Home Assistant's built-in HACS since 2026.11), installable
   from a My Home Assistant link.

**Priorities when trade-offs collide** (Sunroom's, in this project's terms): (1) a parent can set
it up and use it without reading anything; (2) the calendar is correct: times, zones, recurrences
and scopes match what Sunroom shows; (3) nothing private leaves the home and nothing from a real
household lands in this public repo; (4) it behaves like a core-quality integration (the quality
scale rules, even where the scale isn't enforced for custom integrations); (5) easy for a future
session to change safely; (6) breadth.

## 2. Decisions

| # | Decision | Default (the plan is written with it) | Why |
|---|---|---|---|
| D1 | Domain and names | Domain `sunroom`, name "Sunroom", repo `ScopeXL/ha-sunroom`, PyPI nothing (the client lives in the integration; §4) | One word the family knows; no separate library to publish for 1.0 |
| D2 | How Home Assistant gets its token | The config flow asks for the household password once and calls Sunroom's `POST /api/auth/apps/connect`; it stores only the token | No token to copy; the same thing a phone does |
| D3 | Minimum Home Assistant | `2026.11.0` (the Marketplace, `pytest-homeassistant`, probatio, `DeviceInfo` as a class) | Building for 2026.10 would mean two test stacks and the old HACS |
| D4 | Where the card lives | Inside this repository, served and registered by the integration (`add_extra_js_url`); not a second Marketplace item | One install, one version; the Marketplace allows one item per repository |
| D5 | Lists as to-do entities | Yes, every list, writable | The API exists and `todo.add_item` is what automations use |
| D6 | Per-person task and star sensors | Created, as diagnostic entities, with an option to turn them off | Automations for children's tasks are the point; diagnostic keeps dashboards clean |
| D7 | `sunroom.set_sleep_schedule` | Included (it changes a household setting) | Bedtime automations are the most-asked case; the docs say it changes the setting for every screen |
| D8 | Minimum Sunroom | 1.0.0 (`X-Sunroom-API: 1`); older servers get a repair issue "Update Sunroom" | Connected apps and the screens API arrive in 1.0 |
| D9 | Versioning | Its own semantic versions from 1.0.0, released by its own deploy skill; a release notes the Sunroom version it needs | Sunroom releases never force one here, and the other way round, unless the contract changes |
| D10 | Catalog submission | After Sunroom 1.0 is public; until then "custom repository" with the My link | The catalog review takes months and needs the repository to be stable |
| D11 | Brand images | Sunroom's own mark (the window icon) in `brand/` | The Marketplace shows it |
| D12 | A Home Assistant add-on (Sunroom inside Home Assistant OS) | Not in this repository; a later `sunroom-addon` repo (Sunroom's ROADMAP) | Different thing: packaging, not integration |

## 3. What Sunroom gives the integration (the API contract)

Everything below is Sunroom 1.0's API as `docs/API.md` in the Sunroom repo describes it; the
integration never reads anything else. Field names are exact. Sunroom's own frontend uses the
same routes, so they are exercised every day. `X-Sunroom-API: 1` on every response is the
contract version; the integration refuses a higher major with a repair issue (§5.9).

### 3.1 Connecting

- **Finding a Sunroom.** mDNS `_sunroom._tcp.local.`, announced by a Pi that runs Sunroom (avahi)
  and by a computer that runs it as a program (TXT `id`, `v`, `path`); a Sunroom in Docker on a
  server is not announced (its network keeps mDNS in) and is typed by hand, or announced by the
  host's own avahi file (Sunroom's KIOSK.md shows it). `GET /api/discover` (public) answers
  `{sunroom: true, id, version, setup_complete, name|null, url|null, language|null}`: `id` is the
  instance id, stable across backups and restores, the config entry's `unique_id`; `name` (the
  household's) comes only to a local address.
- **A token.** `POST /api/auth/apps/connect {password, label}` (public; rate-limited like sign-in)
  → `201 {device_id, label, token}`. The household password is used once and never stored; the
  token is. `Authorization: Bearer <token>` afterwards; `X-Sunroom: 1` on every POST, PUT,
  PATCH and DELETE; no `Origin` header. `401 app_revoked` means the family disconnected the app
  in Settings → Devices → Connected Apps: reauth. A token is parent-level, except the refusals
  in API.md (erase, restore, backups, PIN, password, devices, accounts, setup, language), which
  answer `403 app_not_allowed`; the integration never calls them.
- **Errors.** `{"error": {"code", "message", "key", "params", …}}`; `message` is plain English for
  a log, `key`/`params` for a translated sentence (the integration shows its own strings and
  logs `code`). `404 plugin_disabled` while a feature (lists, tasks, meals, countdowns) is off:
  the matching entities go unavailable, not missing.

### 3.2 Reading and writing the calendar

- `GET /api/calendar/calendars` → `[{id, name, color, kind: local|sync, owner_member_id,
  read_only, visible_on_display, version, is_default, deleted, source_label}]`.
- `GET /api/calendar/occurrences?from=YYYY-MM-DD&to=YYYY-MM-DD[&calendar_ids=…]` (household-zone
  dates, `[from, to)`, 93 days at most) → `{from_date, to_date, timezone, calendar_versions:
  {id: int}, occurrences: [{key, event_id, recurrence_id, calendar_id, title, location, all_day,
  start_utc, end_utc, start_local, end_local, start_date, end_date (exclusive), member_ids,
  color, calendar_color, is_recurring, is_override, read_only, source, pending, status,
  overlay, reminders, reminders_off, version}]}`. Overlays (`birthdays`, `meals`, `countdowns`)
  are asked for only by the card's websocket command (§6), never for calendar entities.
- `GET /api/calendar/events/{id}` → `EventOut` (`description`, `rrule`, `tzid`, `exdates`, the
  rest); `POST /api/calendar/events` with `{calendar_id, title, description, location, all_day,
  start, end (wall times in tzid), start_date, end_date (exclusive), tzid, rrule, member_ids}` →
  `201 {event, revision_id}`; `PATCH /api/calendar/events/{id}` (the series) and
  `PATCH …/{id}/occurrences/{recurrence_id}` with `scope: this|following|all`;
  `DELETE /api/calendar/events/{id}` and `DELETE …/occurrences/{recurrence_id}?scope=…`.
  `recurrence_id` is the occurrence's original start, `YYYY-MM-DDTHH:MM:SS` (wall time) or
  `YYYY-MM-DD`. `409 calendar_read_only` for a synced read-only calendar; `409 version_conflict`
  when `expected_version` is stale.
- `GET /api/members` → `[{id, name, role, color, color_word, birthday, avatar_url, archived}]`.
- `GET /api/settings` → `timezone`, `household_name`, `language`, `week_starts_on`, `time_format`
  and the display settings (read only here).

### 3.3 Lists and tasks

- Lists: `GET /api/lists`, `GET /api/lists/{id}/items` → `{list, items, done, usuals}`, `POST
  …/items {items: [{text, note, quantity, due_date, assigned_member_id}]}`, `PATCH …/items/{id}
  {text, note, due_date, clear_due_date, assigned_member_id, checked}`, `DELETE …/items/{id}`.
- Tasks: `GET /api/chores/today?date=` → `{date, stars_on, columns: [{member_id, done, total,
  boxes: [{chore_id, title, icon, points, due_time, due_date, owner_id, turn_id, needs_approval,
  completion}]}], stars: [{member_id, balance, …}]}`; `POST /api/chores/{id}/complete {due_date,
  member_id}` and `…/undo`; `GET /api/chores` for the catalogue.

### 3.4 Screens

- `GET /api/screens` → `[{id, label, online, last_seen_at, state: {room, view, week_offset,
  panel_shown, rail_compact, asleep, screensaver, brightness_applied}|null, display: {screen,
  brightness, reason, awake_until}, agent: {version, capabilities}|null}]`.
- `POST /api/screens/{id}/command` and `POST /api/screens/command` (all) with `{command: wake |
  sleep | screensaver | brightness | view | room | panel | rail | go_home | show_event |
  show_list | show_tasks | say | reload, …fields}` → `204` (Sunroom's API.md table).
- `GET /api/display/state` (public) → the household's sleep and dim schedule and the current
  rule; `PATCH /api/settings` for `sleep_from`, `sleep_to`, `sleep_mode`, `dim_from`, `dim_level`.

### 3.5 Live events

`GET /api/events?since=<epoch>:<seq>` (bearer; server-sent events): `hello {mode: live|replay|
resync, epoch, seq, server_time, version, api}`, `ping` every 15 s, then `calendars.changed
{calendar_id}`, `events.changed {calendar_id, event_ids, calendar_version}`, `members.changed`,
`settings.changed`, `lists.changed {list_id}`, `chores.changed`, `points.changed {member_id}`,
`meals.changed`, `countdowns.changed`, `screens.changed {id}`, `devices.changed`, `sync.changed
{account_id, status}`, `update.available {version}`, `server.updating`, `server.restarting`,
`session.expired` (then the stream closes: the token was revoked or the epoch changed). A
`resync` hello means "refetch everything". The integration keeps `epoch:seq` and reconnects with
backoff (1 s doubling to 60 s), falling back to a 60-second poll of the coordinator while the
stream is down.

### 3.6 Everything else it reads

`GET /api/version` (public) `{version, revision}`; `GET /api/health` (public); `GET /api/problems`
→ `{problems: [{id, title, detail, since, page, source, severity}]}`; `GET /api/meals/week?start=`
and `GET /api/countdowns/upcoming` (shapes in API.md) for the sensors; `GET /api/calendar-sync/accounts`
(status only) for the sync sensors.
## 4. Architecture

```
custom_components/sunroom/
  manifest.json      domain, name, version, config_flow, iot_class local_push, integration_type hub,
                     zeroconf [{"type": "_sunroom._tcp.local."}], categories, codeowners,
                     documentation, issue_tracker, dependencies ["http", "websocket_api", "frontend"],
                     requirements [] (aiohttp comes with core), quality_scale "silver" (self-declared)
  __init__.py        async_setup (actions, websocket commands, the card's static path), async_setup_entry
                     (client → coordinator → first refresh → platforms → the stream task), async_unload_entry
  const.py           DOMAIN, PLATFORMS, CONF_*, the command and view vocabularies
  api.py             SunroomClient: aiohttp over the shared session; bearer; X-Sunroom; typed results;
                     every route of §3; errors as SunroomAuthError / SunroomConnectionError / SunroomApiError
  models.py          frozen dataclasses: Household, Calendar, Occurrence, Event, Member, List, ListItem,
                     TaskColumn, Screen, Problem, Version; parsers from JSON (no pydantic: core doesn't ship it)
  coordinator.py     SunroomCoordinator(DataUpdateCoordinator[SunroomData]); SunroomData holds everything
                     the entities read; refreshed by the stream, polled every 60 s as a fallback
  stream.py          the SSE listener (a background task per entry): reconnects, replays, maps each event
                     to a targeted refresh and to a bus event
  entity.py          SunroomEntity(CoordinatorEntity): has_entity_name, the household DeviceInfo;
                     SunroomScreenEntity: the screen's DeviceInfo via_device_id → the household
  config_flow.py     user, zeroconf, discovery_confirm, reauth, reconfigure, options
  calendar.py todo.py sensor.py binary_sensor.py switch.py number.py select.py button.py
  services.py        the sunroom.* actions (registered in async_setup), their schemas (probatio)
  websocket.py       sunroom/upcoming, sunroom/subscribe (for the card)
  diagnostics.py repairs.py
  services.yaml icons.json
  translations/en.json (and es.json, started)
  brand/icon.png logo.png dark_icon.png dark_logo.png (+@2x)
  frontend/sunroom-card.js   built from card/ (T9), committed so the Marketplace ZIP has it
card/                        the card's source: Lit 3, TypeScript, Vite library build → one ES2022 module
tests/                       pytest-homeassistant: unit tests with aioclient_mock, snapshots (syrupy),
                             100 % of config_flow.py; tests/live/ against a real Sunroom (T3)
docs/                        PLAN.md (this), UX.md (the card and the words), adr/, EXAMPLES.md, ROADMAP.md
```

**The client** (`api.py`) is the only place that knows URLs and JSON. It takes the shared
`aiohttp` session (`async_get_clientsession(hass)`), the base URL and the token; sets
`Authorization: Bearer`, `X-Sunroom: 1`, `User-Agent: ha-sunroom/<version>`; never sends an
`Origin`; raises `SunroomAuthError` on 401 (`app_revoked` → reauth), `SunroomApiError(code,
message, key)` on any other error envelope, `SunroomConnectionError` on transport failures and
timeouts (10 s per call). It reads `X-Sunroom-API` on every response and keeps the highest major
seen; a major above 1 raises `SunroomApiTooNewError` once per entry (a repair issue, §5.7).

**The coordinator** keeps one `SunroomData`: settings (zone, household name, language), members,
calendars, the next 48 hours of occurrences (`from` today, `to` the day after tomorrow, with the
`birthdays` and `countdowns` overlays off: those become sensors from their own routes), lists with
items, today's task columns and stars, tonight's and tomorrow's meals, upcoming countdowns, the
screens, the problems, the version and the update status. `_async_update_data` fetches them in a
`TaskGroup`, tolerating a `plugin_disabled` for lists, tasks, meals or countdowns (that part
becomes `None` and its entities go unavailable). `update_interval` is 60 s as a fallback; the
stream calls `async_request_refresh()` on a change (debounced 500 ms, so a burst of
`events.changed` is one fetch) and, for screens, applies the change straight into the data with
`async_set_updated_data`.

**The stream** (`stream.py`) is one background task per entry (`entry.async_create_background_task`)
that holds `GET /api/events?since=<position>` open with `ClientTimeout(total=None, sock_connect=10,
sock_read=90)` (pings come every 15 s, so 90 s of silence means the connection is dead), parses
`id:`/`data:` lines, remembers the last `epoch:seq`, and on `hello mode=resync` or any reconnect
with a gap asks for a full refresh. It maps events: `events.changed`, `calendars.changed`,
`members.changed`, `settings.changed`, `lists.changed`, `chores.changed`, `points.changed`,
`meals.changed`, `countdowns.changed`, `devices.changed`, `sync.changed`, `update.available` →
refresh; `screens.changed` → a screens fetch; `session.expired` → `entry.async_start_reauth(hass)`;
`server.updating` / `server.restarting` → mark unavailable for up to two minutes, then reconnect.
Backoff 1, 2, 4 … 60 s. Each mapped event also fires `sunroom_event` on the bus (§5.6) after the
refresh, so the bus event carries fresh data (the task's title, the person's name).

**Devices.** The household device: `identifiers={(DOMAIN, instance_id)}`, `name=household_name`,
`manufacturer="Sunroom"`, `model="Sunroom"`, `sw_version=version`, `configuration_url=base_url`,
`entry_type=None`. A screen: `identifiers={(DOMAIN, f"{instance_id}:screen:{screen_id}")}`,
`name=label`, `model="Sunroom Screen"` when `agent` is present else `"Screen"`, `sw_version=agent
version`, `via_device_id=<the household DeviceEntry.id>` (resolved through the device registry at
platform setup, as 2026.11 asks; never the deprecated `via_device`). Screens come and go: the
platforms watch the coordinator and add entities for a new screen (`dynamic-devices`); a screen
unpaired in Sunroom gets its device removed on the next refresh (`stale-devices`, through
`device_registry.async_update_device(remove_config_entry_id=...)`).

**Words.** Entity names, action names and every sentence come from `translations/en.json` with
Sunroom's vocabulary (Tasks not chores, People, Wall screen, Today panel, Rolling Week), in Home
Assistant's sentence case for entity names and Title Case for nothing (Home Assistant's own
convention wins inside Home Assistant). A Spanish file is started from Sunroom's `lang/es.json`
where the words exist.

## 5. What the integration provides

One config entry per Sunroom (a household). Devices in Home Assistant's registry: **the
household** ("Sunroom · Sample Family": manufacturer Sunroom, model "Sunroom", `sw_version`
from `/api/version`, `configuration_url` the Sunroom address) and **one device per paired screen**
("Wall screen", via the household device, model "Sunroom Screen" with the agent's version when
it has one, else "Screen"). Entity ids follow `has_entity_name`: `calendar.sample_family_home`,
`switch.wall_screen_screensaver`, and so on. Every entity below names its platform, its unique id
(`<instance id>:<kind>:<id>`), what it reads, and what it writes.

### 5.1 Calendars (platform `calendar`)

One `CalendarEntity` per Sunroom calendar that is not deleted, named for it, with the calendar's
color as an attribute (`color`, Sunroom's color word, and `color_hex` from Sunroom's token table
for cards). `async_get_events(start, end)` → occurrences from `/api/calendar/occurrences` in
≤93-day windows, each mapped to `CalendarEvent(uid=event_id, recurrence_id=recurrence_id,
summary=title, start, end, description, location, rrule)`: a timed occurrence gives aware
datetimes from `start_utc`/`end_utc`, an all-day one gives `start_date`/`end_date` (Home Assistant
also treats `end` as exclusive). `event` (the current or next occurrence) comes from the
coordinator's 48-hour window. The entity's extra attributes: `people` (member names), `member_ids`,
`pending` (a synced event not yet pushed). Cancelled occurrences are left out.

Writing, with `CalendarEntityFeature.CREATE_EVENT | UPDATE_EVENT | DELETE_EVENT` on calendars whose
`read_only` is false:
- `async_create_event(**kwargs)`: `dtstart`/`dtend` → `start`/`end` in the household's `tzid`
  (or `start_date`/`end_date` for dates), `summary` → `title`, `description`, `location`, `rrule`;
  Sunroom decides the people from the title (its rule) unless the service call passed
  `member_ids` (the custom service below).
- `async_update_event(uid, event, recurrence_id, recurrence_range)`: no `recurrence_id` → `PATCH
  /events/{uid}` (the series); with one → `PATCH …/occurrences/{recurrence_id}` with `scope:
  this` (no range) or `following` (`THISANDFUTURE`).
- `async_delete_event(uid, recurrence_id, recurrence_range)`: the same mapping onto `DELETE`.
- `409 calendar_read_only` → `HomeAssistantError("This calendar is synced from <source> and is
  read-only in Sunroom")`; `409 version_conflict` → fetch and retry once.
So Home Assistant's own calendar panel and the built-in calendar card can add, move and remove
Sunroom events; the integration adds nothing of its own for that.

### 5.2 Lists (platform `todo`)

One `TodoListEntity` per Sunroom list, with `TodoListEntityFeature.CREATE_TODO_ITEM |
UPDATE_TODO_ITEM | DELETE_TODO_ITEM | SET_DUE_DATE_ON_ITEM | SET_DESCRIPTION_ON_ITEM | MOVE_TODO_ITEM`.
Items: open ones in Sunroom's order then done ones; `TodoItem(uid=item id, summary=text,
status=needs_action|completed, due=due_date, description=note)`; `quantity` folded into the
summary ("Milk · 2"). Create → `POST …/items`, update → `PATCH …/items/{id}` (`checked`,
`due_date`/`clear_due_date`, `note`), delete → `DELETE …/items/{id}`, move → `PATCH {position}`.
Home Assistant's to-do panel then edits the family's groceries, and `todo.add_item` works in
automations ("add 'Buy batteries' to Groceries when the smoke alarm reports low battery").

### 5.3 Sensors (platform `sensor`, `binary_sensor`)

Household device:
- `sensor.<household>_next_event`: the next occurrence's title (state), with `start`, `end`,
  `people`, `calendar`, `location`, `all_day`, `event_key`, `color` as attributes; `sensor.…_now`
  the one in progress or `none`.
- `sensor.<household>_tonight`: tonight's dinner (`none` when nothing is planned), attribute
  `cook` (the person), from `/api/meals/week`; unavailable while Meals is off.
- `sensor.<household>_next_countdown`: "Camping trip" with `days`, `date`, `emoji`; unavailable
  while Countdowns is off.
- `sensor.<household>_needs_attention`: the count, with the problems' titles as attributes.
- `sensor.<household>_version`: Sunroom's version, attribute `latest` and `update_available`
  (from `update.available` events and `/api/admin/update`): `binary_sensor.…_update_available`.
- `binary_sensor.<household>_sync_ok`: false when any account's `status` is `needs_reconnect`
  or `errored`, with the account labels as attributes.
- Per person (`/api/members`, active, not archived): `sensor.<person>_tasks_today` ("2 of 3",
  numeric state = tasks left, attributes `done`, `total`, `next_due`, the open task titles) and
  `sensor.<person>_stars` (the balance) when stars are on. Diagnostic category, so a dashboard
  doesn't fill with them unasked.
Per screen device:
- `binary_sensor.<screen>_online` (connectivity class), `binary_sensor.<screen>_asleep`,
  `binary_sensor.<screen>_screensaver`, `sensor.<screen>_view` (week, rolling, day, month,
  people, today), `sensor.<screen>_room`, `sensor.<screen>_brightness` (%), attribute `reason`
  (day, dim, sleep, awake, override), `sensor.<screen>_agent_version` (diagnostic).

### 5.4 Controls for a screen (platforms `switch`, `number`, `select`, `button`)

- `switch.<screen>_screensaver` (on → `screensaver on`, off → `screensaver off`; reflects the
  screen's state), `switch.<screen>_awake` (on → `wake 120`, off → `sleep`), `switch.<screen>_today_panel`
  (`panel`), `switch.<screen>_compact_rail` (`rail`).
- `number.<screen>_brightness` (10–100, step 5, slider; `brightness {level, minutes: 60}`; the
  state follows `display.brightness`).
- `select.<screen>_view` (Week, Rolling Week, Day, Month, People, Today) and
  `select.<screen>_room` (Calendar, Lists, Tasks, Meals, Countdowns, Photos).
- `button.<screen>_wake` (`wake`), `button.<screen>_go_home`, `button.<screen>_refresh`
  (`reload`; diagnostic), `button.<screen>_show_photos`.
A screen that is offline makes its controls unavailable, never silently ignored.

### 5.5 Services (`services.yaml`, with strings and selectors)

All take `config_entry_id` (or a device/entity target) and are registered on the domain:
- `sunroom.screen_command`: `screen` (device target, or all screens), `command` (select),
  and its fields (`view`, `room`, `level`, `minutes`, `on`, `event_key`, `list_id`, `member`,
  `text`, `seconds`). The raw door to every command in §3.4 for people who want it.
- `sunroom.say`: `screen` (optional), `text`, `seconds` → a toast on the wall ("The washing
  machine is done").
- `sunroom.show_event`: `screen`, `event_key` (from the sensors' attributes or the card).
- `sunroom.add_event`: `calendar` (entity), `title`, `start`, `end` (or `date` for all day),
  `people` (member names, optional), `location`, `description`, `rrule` → the richer form of
  `calendar.create_event`, with people.
- `sunroom.complete_task`: `task` (a chore, selected by title), `person` (optional; Sunroom's
  rule picks otherwise), `date` (default today) → `POST /api/chores/{id}/complete`. Supports
  `response: optional` returning `stars` and `all_done`.
- `sunroom.add_list_item`: `list`, `text`, `quantity`, `due_date`, `person` (the richer form
  of `todo.add_item`).
- `sunroom.set_sleep_schedule`: `sleep_from`, `sleep_to`, `mode` (dim clock / screen off),
  `dim_from`, `dim_level` → `PATCH /api/settings` (a parent-level change; documented as such).

### 5.6 Events on Home Assistant's bus

`sunroom_event` with `type` and the payload, fired from the stream for things an automation
wants to react to: `task_completed` (`chore_id`, `title`, `member_id`, `member`, `stars`,
`all_done`), `event_changed` (`calendar_id`, `event_ids`), `list_changed` (`list_id`),
`screen_changed` (`screen_id`, `online`, `asleep`, `screensaver`), `needs_attention`
(`problems`), `update_available` (`version`). Routine finished and reward asked arrive as
`chores.changed` in 1.0 without detail; the roadmap names richer events as a Sunroom API addition.

### 5.7 Diagnostics and repairs

`diagnostics.py` dumps the config entry (token redacted), `/api/version`, `/api/settings`
(location redacted), the screens, the calendars, the last 20 stream events and the coordinator
timings. Repair issues: `api_version_too_new` (Sunroom's `X-Sunroom-API` major is above what this
version knows: update the integration), `sunroom_update_available` (Sunroom itself has a newer
version, with the family's own words for how to update), `token_revoked` (reauth).

### 5.8 Options

Options flow: which calendars become entities (all by default), whether to create the per-person
task sensors (on), the poll interval while the stream is down (60 s), and the window the
`next_event` sensor looks at (48 h).

### 5.9 Availability rules

The coordinator marks everything unavailable after three failed polls or a closed stream older
than two minutes; a `404 plugin_disabled` marks only that feature's entities unavailable; a
screen without a live stream is `online: false` and its controls unavailable. Nothing is ever
deleted from the registry by the integration: a calendar or list removed in Sunroom leaves an
entity the user removes (Home Assistant's "restored" state), as other integrations do.
## 6. The card

`type: custom:sunroom-card`: the next few days of the family's calendar as one clean list, in
Sunroom's people colors, for a household that wants the wall's "Coming Up" on a dashboard without
installing another calendar card. It is deliberately small; Calendar Card Pro is the big one and
works on the same calendar entities.

**What it shows.** A header with the household's name (or `title`) and today's date; an optional
**Now** line (the event in progress); then days (**Today**, **Tomorrow**, then "Thu 9"), each with
its events: the time (or "all day"), the title, the people as small colored chips with their
initials (the color from Sunroom, mapped to the card's palette from Sunroom's token values; a
synced calendar's event with no person shows the calendar's color bar), the location in a second
line when `show_location`; the next event is marked with a left bar. Under today, when on:
**Tonight** (the dinner and who cooks) and **Tasks** ("Mia 1 of 2 · Leo all done"). A quiet dot
and a line when Sunroom has something in Needs Attention. Empty: "Nothing coming up." The card
follows Home Assistant's theme (`ha-card`, `--primary-text-color`, `--secondary-text-color`,
`--divider-color`, `--ha-font-*`), light and dark.

**Config** (all optional):

```yaml
type: custom:sunroom-card
entry: auto            # a config entry id when there are several Sunrooms
title: Sample Family   # default: the household's name
days: 7                # 1–31
max_events: 12         # the list stops here with "+3 more"
show_now: true
show_location: true
show_tonight: true     # needs Meals on in Sunroom
show_tasks: true       # needs Tasks on
show_attention: true
time_format: auto      # auto (the household's), 12h, 24h
calendars: []          # ids or names to include; empty = all visible ones
people: []             # member names to include; empty = everyone
tap_action: more-info  # more-info opens the calendar entity's dialog; none; or
                       # {action: call-service, service: sunroom.show_event} with a screen target
```

A visual editor (`getConfigForm`, the schema form the core cards use) edits every option; `getStubConfig`
returns `{}`; `getGridOptions` gives 6 columns × rows by `max_events`.

**Data.** The card never scrapes entity attributes: it calls the integration's websocket command
`sunroom/upcoming {entry_id?, days, limit, calendars?, people?}` →
`{household, timezone, time_format, now: Occurrence|null, days: [{date, label, items:
[Occurrence]}], tonight: {title, cook}|null, tasks: [{member, name, color, done, total}],
problems: int, more: int}` where `Occurrence` has `key, title, start_local, end_local, all_day,
location, people: [{name, initial, color}], color, calendar`. Then `sunroom/subscribe {entry_id}`
for push: the integration sends `{type: "changed"}` after any coordinator refresh, and the card
re-asks (coalesced). Both commands are registered in `async_setup` (`websocket_api.async_register_command`),
need no admin, and resolve the entry (`entry: auto` = the first loaded one).

**Build and ship.** `card/` is Lit 3 + TypeScript 5, built by Vite in library mode to
`custom_components/sunroom/frontend/sunroom-card.js` (ES2022, one file, no external imports; the
build is deterministic and the output is committed so a Marketplace ZIP carries it). The integration
serves it at `/sunroom/sunroom-card.js?v=<version>` (`async_register_static_paths`, cache headers
on) and registers it with `add_extra_js_url(hass, url)` in `async_setup`, so it is loaded on every
dashboard with no resource to add; `remove_extra_js_url` on the last unload. `window.customCards`
gets the picker entry (name "Sunroom", description "What's coming up, from your family's Sunroom",
`preview: true`, `documentationURL`). The card uses `hass.formatEntityName` nowhere (it names
nothing by entity), and `hass.locale` for dates.

**Tests.** `card/` has Vitest tests for the day grouping, the "+N more" cap and the config
validation; the Python side has tests for both websocket commands (`hass_ws_client`) and for the
static path and the extra module URL being registered and removed.

## 7. Setting it up: discovery, the config flow, reauth, options

`ConfigFlow` with `VERSION = 1`, `MINOR_VERSION = 1`; every form passes `step_id`; data holds
`CONF_URL` (the base address, scheme included, no trailing slash), `CONF_TOKEN`, `CONF_INSTANCE_ID`;
the unique id is Sunroom's instance id.

- **`zeroconf`.** Matched on `_sunroom._tcp.local.`. From `discovery_info`: the address
  (`http://{host}:{port}` with `path` from TXT, else `/`), then `GET /api/discover` to read `id`,
  `name`, `version`, `setup_complete`. `async_set_unique_id(id)`; `_abort_if_unique_id_configured
  (updates={CONF_URL: url})` (a Sunroom that moved updates the stored address and reloads: Gold
  `discovery-update-info`); `setup_complete: false` → abort `not_set_up` ("Finish setting Sunroom up
  on a phone or the wall first"); then `title_placeholders = {"name": name or "Sunroom"}` and
  `discovery_confirm`, a form with the household password (`TextSelector(type=PASSWORD)`), which
  calls `connect` (below).
- **`user`.** A form with the address (`TextSelector(type=URL)`, suggested `http://sunroom.local:8080`)
  and the household password; `GET /api/discover` on the address (errors: `cannot_connect`,
  `not_sunroom` when the answer has no `sunroom: true`, `not_set_up`), unique id from `id` with
  `raise_on_progress=False`, abort if configured, then `connect`.
- **`connect`** (shared): `POST /api/auth/apps/connect {password, label: "Home Assistant"}`
  → the token; errors `invalid_auth` (401) and `rate_limited` (429, with the minutes in a
  placeholder); then `async_create_entry(title=name, data={url, token, instance_id})`. The
  password is never stored.
- **`reauth`** (`ConfigEntryAuthFailed` from the coordinator or the stream's `session.expired`):
  `reauth_confirm` asks for the password again, calls `connect`, `_abort_if_unique_id_mismatch
  (reason="wrong_household")`, `async_update_reload_and_abort(entry, data_updates={token})`.
- **`reconfigure`.** The address only (prefilled); `discover` must answer the same instance id
  (`wrong_household` otherwise); `async_update_reload_and_abort`.
- **Options** (`OptionsFlowWithReload`): calendars to create (a multi-select of the calendars,
  all by default), per-person sensors (on), the fallback poll interval (60 s; 30–600), the next-event
  window (48 h; 6–168), the list of screens to control (all).
- **Strings.** `config.step.user`, `discovery_confirm`, `reauth_confirm`, `reconfigure` with
  `data` and `data_description` for every field; `config.error.*`; `config.abort.*`
  (`already_configured`, `not_set_up`, `wrong_household`, `reauth_successful`,
  `reconfigure_successful`); `config.flow_title: "{name}"`.
- **Tests.** 100 % of `config_flow.py`: the user flow end to end, every error then success,
  zeroconf with a new id and with a known one (the address updated), `not_set_up`, reauth,
  reconfigure with the wrong id, options.

## 8. Repository, tooling, CI, releases, the Marketplace

- **Layout.** `custom_components/sunroom/`, `card/`, `tests/`, `docs/`, `hacs.json`
  (`{"name": "Sunroom", "homeassistant": "2026.11.0"}`), `README.md`, `CHANGELOG.md` (Keep a
  Changelog), `LICENSE` (MIT, exists), `SECURITY.md`, `PRIVACY.md` (what the integration sends
  where: only to the family's Sunroom), `CONTRIBUTING.md`, `CLAUDE.md`, `.github/`, `justfile`,
  `pyproject.toml` (uv-managed; `requires-python = ">=3.14.2"`; dev deps `homeassistant==2026.11.x`,
  `pytest-homeassistant==2026.11.x` (never beside `pytest-homeassistant-custom-component`), `ruff`,
  `pyright`, `pre-commit` not used: the git hooks are the repo's own, as Sunroom's), `.gitleaks.toml`
  and `scripts/private_scan.py` copied from Sunroom, `.githooks/`.
- **Commands** (the justfile): `just setup` (uv sync, pnpm install in `card/`, hooks, the private
  terms list), `just quick` (ruff check + format, pyright strict on the integration, tsc on the
  card), `just test [ARGS]` (pytest, `asyncio_mode=auto`, `-p no:respx`), `just card` (build the
  card into `frontend/`; `just check` fails if the committed file differs), `just live [IMAGE]`
  (T3: the live tests against a Sunroom started from the released server wheel), `just hassfest`
  and `just marketplace` (the two validation containers, when Docker is there), `just check`
  (everything but live), `just scan`, `just bump <level>`, `just release-tag`, `just github-release`
  (the same shapes as Sunroom's `scripts/release.py`, trimmed: VERSION is `manifest.json`'s
  `version` and `card/package.json`'s), `just release <level>`.
- **CI** (`.github/workflows/ci.yml`, on push and PRs): lint and types; tests on Python 3.14 against
  the pinned Home Assistant and against `homeassistant` latest stable (a second matrix row that may
  fail without blocking, so a new monthly release shows what it breaks); `home-assistant/actions/hassfest`;
  `hacs/action` with `category: integration`; the card build diff; gitleaks over the whole history.
  `live.yml` (weekly and on demand): T3's live tests against the newest Sunroom release.
  `release.yml` (on a `v*` tag): builds the ZIP `sunroom.zip` of `custom_components/sunroom` and
  attaches it (so `hacs.json` can use `zip_release` later; 1.0 installs from the tag), writes
  `SHA256SUMS`.
- **Releases.** `version` in `manifest.json` equals the tag; a GitHub Release with the CHANGELOG
  section as notes is what the Marketplace installs (a tag alone is ignored). Pre-releases
  (`v1.1.0-rc.1`) for testing, offered only to people who enable them.
- **The Marketplace.** Until the catalog lists it: README's install is the My link
  `https://my.home-assistant.io/redirect/marketplace_repository/?owner=ScopeXL&repository=ha-sunroom&category=integration`
  (custom repositories need the GitHub connection in 2026.11; the README says so in one line),
  then `https://my.home-assistant.io/redirect/config_flow_start/?domain=sunroom`. Catalog
  submission (D10): a PR to `hacs/default` adding `ScopeXL/ha-sunroom` to `integration`, with the
  passing action runs; the owner's step after Sunroom 1.0.
- **Brand.** `custom_components/sunroom/brand/icon.png` (256) and `@2x`, `logo.png`, dark
  variants, from Sunroom's `frontend/public/icons` (synthetic, the project's own mark).

## 9. CLAUDE.md, and staying in step with Sunroom

`CLAUDE.md` in the repo root, under 10 KB, written in T0 with this shape:

```
# ha-sunroom — working rules for AI sessions

ha-sunroom is the Home Assistant integration for Sunroom (../sunroom): calendars and lists both
ways, the wall screens as devices, a card. Python 3.14, Home Assistant 2026.11+, uv, ruff, pyright
strict; the card in Lit + TypeScript. Built and maintained with AI sessions.

**Read first:** docs/PLAN.md (what and how), docs/UX.md (the card and the words), docs/adr/, and
Sunroom's docs/API.md (the contract: ../sunroom/docs/API.md, read-only).

## Priorities … (§1's six)

## Hard rules
1. Privacy: nothing from a real household in the repo (no addresses, names, tokens, calendar text);
   fixtures are the Sample Family; `just scan` before every commit (the hook runs it).
2. Never read .env, .private/, ~/.config/sunroom/ or Home Assistant's own config of the maintainer.
3. Sunroom is read-only from here: never edit ../sunroom; a needed API change is a task written
   into ../sunroom/docs/plans/<name>.md for the Sunroom session, and this plan waits for the release.
4. The contract: only routes in Sunroom's docs/API.md; `X-Sunroom-API` major above the one this
   version knows → a repair issue, never a crash. Minimum Sunroom version in manifest's docs and README.
5. Home Assistant's rules: config flow only (no YAML), unique ids everywhere, has_entity_name,
   runtime_data, actions registered in async_setup, translations complete (en.json), every
   sentence a user reads in translations, never a token in logs or diagnostics.
6. Words: Sunroom's vocabulary (Tasks, People, Wall screen, Today panel); entity names in sentence
   case; no ID, code or stack trace reaches a user.
7. Failing checks are never skipped.
8. Deploy only through the deploy skill when the owner says so (deploy, release, ship it).

## Commands … (§8)
## Architecture map … (§4)
## Conventions … (the client is the only place that knows URLs; dataclasses; snapshots; probatio)
## Definition of done … (the quick gate per task, the full gate per batch, CHANGELOG line, docs)

## Connected projects
| Project | Where | What changes here when it changes | Its plan |
|---|---|---|---|
| Sunroom (the server, public) | ../sunroom | docs/API.md, /api/events, /api/discover, the screen commands, connected-app tokens | ../sunroom/docs/plans/ |
A plan for Sunroom that touches those names its ha-sunroom task in this repo's docs/plans/<same
name>.md; both are built in the same batch and released the same day (Sunroom first).
```

The deploy skill (`.claude/skills/deploy/SKILL.md`) is Sunroom's, trimmed: gate (`just check`,
`just live` against the Sunroom release it needs), bump, tag and push, the GitHub Release with
the CHANGELOG notes and the ZIP, the Marketplace's own check (the action), the report (version,
tag, the My link, the Sunroom version it needs). `.claude/settings.json` denies the private
paths and allows the `just` commands, and gives `additionalDirectories: ["../sunroom/"]` for
reading the contract.

## 10. Tasks

Each task: **Build**, **Tests**, **Docs**, then the quick gate and a commit. Estimated effort is
for one session; T5 and T9 are the long ones.

### T0 The repository

- **Build.** `pyproject.toml` (uv; the dev dependencies of §8), `justfile` (§8's commands),
  `.githooks/` and `scripts/private_scan.py` and `.gitleaks.toml` from Sunroom (the sibling-list
  wiring removed), `.github/workflows/{ci,live,release}.yml`, `.github/dependabot.yml` (uv, npm,
  actions, weekly, grouped), `hacs.json`, `CLAUDE.md` (§9), `.claude/settings.json` and the deploy
  skill, `README.md` (a skeleton with the install link and "not released yet"), `CHANGELOG.md` with
  `[Unreleased]`, `SECURITY.md`, `PRIVACY.md`, `CONTRIBUTING.md`, `docs/` (this plan, `UX.md` for
  the card and the words, `adr/README.md` with the first records: 0001 the integration's shape
  (coordinator plus stream), 0002 the token comes from the password, 0003 the card lives in the
  integration), `custom_components/sunroom/manifest.json` and the empty package with `const.py`,
  `brand/` images, `translations/en.json` with the `title`.
- **Tests.** `tests/conftest.py` with the `hass` fixture conventions, a `mock_config_entry`
  fixture, `tests/fixtures/` (the Sample Family's `discover.json`, `settings.json`, `members.json`,
  `calendars.json`, `occurrences.json`, `lists.json`, `today.json`, `screens.json`, `problems.json`,
  `version.json`, captured from a seeded Sunroom and scrubbed by hand to the synthetic names).
  `just check` runs green on the empty integration (hassfest and the Marketplace action pass on
  the manifest and the repo shape).
- **Docs.** README's skeleton; `docs/adr/0001-0003`.

### T1 The client and the models

- **Build.** `api.py` (`SunroomClient`: `discover(url)`, `connect(url, password, label)`,
  `version()`, `settings()`, `members()`, `calendars()`, `occurrences(start, end, calendar_ids)`,
  `event(id)`, `create_event(...)`, `update_event(id, fields, recurrence_id, scope)`,
  `delete_event(id, recurrence_id, scope)`, `lists()`, `list_items(id)`, `add_items`,
  `patch_item`, `delete_item`, `tasks_today(date)`, `complete_task`, `undo_task`, `meals_week(start)`,
  `countdowns_upcoming()`, `screens()`, `screen_command(id | None, command, **fields)`,
  `problems()`, `update_status()`, `sync_accounts()`), the three error classes, the API-major
  check; `models.py` with the dataclasses and `from_json` parsers (dates and datetimes parsed
  with `dt_util`, `tzid` kept, `end_date` exclusive kept).
- **Tests.** `tests/test_api.py` with `aioclient_mock` over the fixtures: every method, the
  headers (bearer, `X-Sunroom`, no Origin), each error class, the API-major rule, a timeout.
- **Docs.** `docs/adr/0004` (dataclasses, not pydantic).

### T2 The config flow, reauth, reconfigure, options

- **Build.** `config_flow.py` as §7; `strings`/`translations/en.json` for `config` and `options`.
- **Tests.** `tests/test_config_flow.py`, 100 % coverage of the file (§7's list).
- **Docs.** README "Set it up" with the two screenshots' words (no screenshots of a real home).

### T3 The live tests: a real Sunroom

- **Build.** `tests/live/conftest.py` starts Sunroom from the released server wheel: downloads
  `sunroom-<version>-py3-none-any.whl` and its constraints from Sunroom's GitHub Release (the
  version from `tests/live/SUNROOM_VERSION`), installs them in a temporary venv with uv, runs
  `sunroom serve --host 127.0.0.1 --port <free>` with `SUNROOM_TEST_MODE=1` and a temporary
  `DATA_DIR`, waits for `/api/health`, seeds the Sample Family through `POST /api/_test/seed`,
  and connects an app with the seed's household password. (The Docker image refuses test mode by
  design, so the wheel is the harness.) `tests/live/test_contract.py`: every client method
  against it, the calendar round trip (create, move, change one occurrence, delete following),
  the list round trip, a screen command accepted, the stream's hello and an `events.changed`
  after a write. `just live` runs it; CI's `live.yml` weekly.
- **Tests.** Itself. Skipped in `just test` (marker `live`).
- **Docs.** CONTRIBUTING: how to run it; `docs/adr/0005` (the wheel as the harness).

### T4 Setup, the coordinator, the stream, diagnostics, repairs

- **Build.** `__init__.py` (`async_setup` with `CONFIG_SCHEMA = cv.config_entry_only_config_schema`,
  `async_setup_entry` → client, coordinator, `async_config_entry_first_refresh`, the device for
  the household, `async_forward_entry_setups`, the stream task; `async_unload_entry` with
  `async_unload_platforms_or_raise` and the task cancelled by the entry; `async_remove_entry`
  nothing: the token stays valid until the family disconnects it, and the README says so),
  `coordinator.py`, `stream.py`, `entity.py`, `diagnostics.py` (redacting the token, the address,
  latitude and longitude, the household name), `repairs.py` (`api_version_too_new`,
  `sunroom_update_available` with the family's own "how" sentence as a placeholder, both fixable
  by "I've updated" or dismiss).
- **Tests.** `tests/test_init.py` (setup, unload, `ConfigEntryNotReady` on a dead server,
  `ConfigEntryAuthFailed` on 401), `tests/test_coordinator.py` (a partial failure keeps the rest,
  `plugin_disabled` nulls one part), `tests/test_stream.py` (a scripted SSE server: hello, events,
  resync, a drop and reconnect with `since`, `session.expired` → reauth), `tests/test_diagnostics.py`
  (snapshot, nothing sensitive), `tests/test_repairs.py`.
- **Docs.** `docs/adr/0006` (push with a polling fallback).

### T5 Calendars

- **Build.** `calendar.py` as §5.1 (`PARALLEL_UPDATES = 1`): entities from the coordinator's
  calendars (options filter), `async_get_events` fetching from the client in ≤93-day windows
  (the coordinator's 48-hour data serves `event`), the three write methods with the scope mapping,
  the error translations (`calendar_read_only`, `version_conflict`), `_attr_initial_color` from
  the calendar's color, `async_update_event_listeners()` after each stream change.
- **Tests.** `tests/test_calendar.py` with snapshots: the entity states and attributes, events
  in a range (timed, all-day, multi-day, recurring with an override and a cancelled instance),
  `calendar.create_event` and `calendar.get_events`, the websocket `calendar/event/update` and
  `delete` with `recurrence_range: THISANDFUTURE`, a read-only calendar's refusal, the household
  zone vs Home Assistant's zone (fixtures in `America/New_York` with Home Assistant in
  `Europe/Madrid`).
- **Docs.** README's "Calendars" section; `docs/adr/0007` (scope mapping).

### T6 Lists

- **Build.** `todo.py` as §5.2 (`PARALLEL_UPDATES = 1`).
- **Tests.** `tests/test_todo.py`: items and order, `todo.add_item`, `update_item` (rename,
  status, due), `remove_item`, `move_item`, `remove_completed_items`, a list that disappears.
- **Docs.** README "Lists".

### T7 Sensors

- **Build.** `sensor.py` and `binary_sensor.py` as §5.3 (`PARALLEL_UPDATES = 0`; diagnostic
  categories where said; `SensorDeviceClass.TIMESTAMP` for `last_seen`, `ENUM` with `options`
  for view and room; `BinarySensorDeviceClass.CONNECTIVITY` for online, `UPDATE` for update
  available, `PROBLEM` for needs attention and sync); `icons.json` for every key.
- **Tests.** `tests/test_sensor.py`, `tests/test_binary_sensor.py` with snapshots; the per-person
  sensors appear and disappear with members; a plugin off makes its sensor unavailable.
- **Docs.** README's entity table.

### T8 Screen controls, actions, bus events

- **Build.** `switch.py`, `number.py`, `select.py`, `button.py` as §5.4 (`PARALLEL_UPDATES = 1`;
  config category for the controls; unavailable while the screen is offline); `services.py` with
  §5.5's actions (probatio schemas, selectors in `services.yaml`, `supports_response` where
  said, `ServiceValidationError` for a unknown task or list by name, `HomeAssistantError` with a
  translation for an offline screen); the bus events of §5.6 from `stream.py`.
- **Tests.** One test per entity kind (state and the command it sends, offline unavailable); one
  per action (the HTTP call it makes, the validation errors, the response); the bus events.
- **Docs.** README "Automations" with the four examples of §11; `docs/adr/0008` (why switches
  and a number, not a light).

### T9 The card

- **Build.** `card/` (Lit, TypeScript, Vite library build, Vitest), the card of §6, the editor
  form, the picker entry; `websocket.py` with `sunroom/upcoming` and `sunroom/subscribe`; the
  static path and `add_extra_js_url` in `async_setup`, removal on the last unload; the built file
  committed.
- **Tests.** `card/src/*.test.ts` (grouping, cap, config); `tests/test_websocket.py`
  (`hass_ws_client`: both commands, the entry resolution, the subscription's event);
  `tests/test_frontend.py` (the path and the module URL registered). A manual check in a real
  Home Assistant (T13).
- **Docs.** `docs/UX.md` (the card's words and layout at phone and desktop widths), README
  "The card" with the config block.

### T10 Translations, icons, brand, the words

- **Build.** `translations/en.json` complete (title, config, options, entity names and states,
  services with every field, exceptions, issues); `es.json` started from Sunroom's Spanish where
  the same words exist; `icons.json` for entities and actions; `brand/` images.
- **Tests.** A test that every `translation_key`, action and exception key used in code exists
  in `en.json` and that `services.yaml`'s actions and fields all have strings (hassfest checks
  part of this; the test checks the rest).
- **Docs.** CONTRIBUTING "Translating".

### T11 Documentation

- **Build.** README (§11), `docs/EXAMPLES.md`, CHANGELOG's 1.0.0 notes under `[Unreleased]`,
  SECURITY.md (reporting; what the token can and can't do), PRIVACY.md.
- **Tests.** `scripts/check_docs.py` (links resolve; no private terms; README names every
  action and entity kind).

### T12 Release machinery and the first release

- **Build.** `scripts/release.py` (bump `manifest.json` and `card/package.json`, roll the
  CHANGELOG, tag, push, the GitHub Release with notes), `release.yml` attaching `sunroom.zip`
  and `SHA256SUMS`, the deploy skill. Then, when the owner says so: `just release minor` → 1.0.0,
  after Sunroom 1.0.0 is out (its token route must exist).
- **Tests.** `release.yml` on a `v1.0.0-rc.1` pre-release first.
- **Docs.** `docs/RELEASING.md` (short).

### T13 Wrap-up

The full gate (`just check`, `just live` against Sunroom 1.0.0, hassfest, the Marketplace
action), a manual pass in the maintainer's Home Assistant (install from the custom repository
through the My link, discovery of a Sunroom on the network, the calendar panel adding and moving
an event, a to-do edit, a screen woken from an automation, the card on a dashboard in light and
dark), the ADR index, this file's ticks and "As built" notes, the CHANGELOG, and the report.

## 11. Documentation for people who install it

README.md, for a Home Assistant user, under 10 KB:

1. **What it does** in five bullets and one screenshot of the card (synthetic data).
2. **Install.** The My link (custom repository until the catalog lists it, with the one line
   about the GitHub connection), restart, then the setup link; or manually: copy
   `custom_components/sunroom` into `config/custom_components/`.
3. **Set it up.** "Home Assistant finds Sunroom on your network and asks for the household
   password. If it doesn't, add the integration and type Sunroom's address (the one you open on
   your phone)." The two-minute version; what to do when Sunroom runs in Docker on a server (type
   the address; the optional avahi file, linked to Sunroom's docs).
4. **What you get.** A table: calendars (two-way), lists (two-way), the sensors, the screen
   devices and their controls, the actions (one line each), the events.
5. **Automations.** Four examples in YAML: wake the kitchen screen when the hallway motion sensor
   fires between 06:00 and 22:00; show tonight's dinner on the wall when the oven turns on
   (`sunroom.say`); add "batteries" to Groceries when a smoke alarm reports low battery; mark a
   task done from an NFC tag. Each short and copy-pasteable.
6. **The card.** The config block of §6 and what each option does.
7. **When something's wrong.** Reauth, "Sunroom is older than this integration needs", the
   screen shows "unavailable" (it isn't connected to Sunroom), where the logs are.
8. **Privacy and security**, **Contributing**, **License**, the Discord.

`docs/EXAMPLES.md` keeps a longer list of automations and template sensors.

## 12. Limits, risks, and what comes after 1.0

- **Needs Sunroom 1.0.** Connected-app tokens, the screens API and the API version header arrive
  there; against 0.18 the config flow stops at "Update Sunroom to 1.0 first".
- **mDNS and Docker.** A Sunroom in a container on a bridge network isn't announced; the typed
  address is the normal path and the README says so first, not as a footnote.
- **Two time zones.** Sunroom's household zone and Home Assistant's can differ; every datetime
  the integration hands to Home Assistant is aware (from `start_utc`/`end_utc`), and writes go
  back in the household's `tzid`. The live tests pin this.
- **Scope edits.** Home Assistant has only "this" and "this and future"; Sunroom's "all" is the
  series PATCH; a `recurrence_id` the user edits from the calendar panel always targets one
  occurrence first. Documented in README's known limits.
- **A screen's state is as fresh as its last post**: a screen whose page froze reports stale
  state until its stream drops; `online` follows the stream, which is the truth.
- **Rate limits.** Sunroom's login limiter counts bad tokens; a misconfigured HA could lock the
  family's sign-in for 15 minutes. The client never retries a 401.
- **After 1.0** (`docs/ROADMAP.md`): richer bus events from Sunroom (routine finished, reward
  asked, reminder due); a `sunroom.add_countdown` action; meals as a to-do-like weekly entity;
  the photo frame; a `sunroom-card` grid view; the Home Assistant add-on in its own repository;
  translations beyond Spanish; the catalog listing.

## 13. Research notes

Facts checked on 2026-11-03 against Home Assistant's developer documentation
(`https://contributors.home-assistant.io/`, where `developers.home-assistant.io` now redirects),
the core source at tag 2026.11.0b4, the Marketplace docs and PyPI. The implementer re-checks any of
these against the live docs before relying on it; what changes monthly is listed first.

- Home Assistant 2026.11 (2026-11-04): Python `>=3.14.2`; HACS is the built-in **Marketplace**
  (Settings → Marketplace; standalone HACS no longer installs); `hacs.json` and the HACS action are
  unchanged (`category: integration`); custom repositories need a GitHub connection; the My link
  is `marketplace_repository` (the old `hacs_repository` redirects).
- `probatio` replaced voluptuous in core 2026.9 (`import voluptuous as vol` still works through an
  alias; new code uses `probatio`). The test package is `pytest-homeassistant` (PyPI; pinned to the
  matching core version, 2026.11 first), replacing `pytest-homeassistant-custom-component`; the
  `hass` fixture enables custom integrations by default; `asyncio_mode = "auto"`, `-p no:respx`.
- 2026.11 rules: `async_setup_entry`/`async_unload_entry` return `None` and raise `ConfigEntry*`
  exceptions (`async_unload_platforms_or_raise`); `step_id` is required in every `async_show_*`;
  `DeviceInfo` is a keyword-only dataclass; `via_device` is deprecated for `via_device_id`;
  manifest `categories` (1–3 values; `productivity_information.calendars_todos` fits); brand
  images in `custom_components/<domain>/brand/`; `hass.formatEntityName` in cards, not
  `friendly_name`; `--ha-font-*` CSS variables, not `--mdc-typography-*`.
- Manifest: `version` is required for custom integrations; `iot_class: local_push`;
  `integration_type: hub`; `zeroconf: [{"type": "_sunroom._tcp.local."}]` (object form allows
  `properties` guards; values are matched lowercased with fnmatch); `requirements` pinned exact;
  `quality_scale` optional and unenforced for custom integrations (`quality_scale.yaml` kept as a
  self-checklist).
- Config flow: `async_set_unique_id`, `_abort_if_unique_id_configured(updates=…)` (reloads the
  entry with the new address), `_set_confirm_only()` for `discovery_confirm`, `_get_reauth_entry()`,
  `_abort_if_unique_id_mismatch(reason=…)`, `async_update_reload_and_abort(entry, data_updates=…)`,
  `OptionsFlowWithReload` (no constructor argument; `self.config_entry` as a property).
- Calendar platform: `CalendarEvent(start, end, summary, description, location, uid,
  recurrence_id, rrule, status)`; `CalendarEntityFeature.CREATE_EVENT | DELETE_EVENT | UPDATE_EVENT`;
  `async_get_events(hass, start_date, end_date)`; `async_create_event(**kwargs)` with RFC 5545
  names (`dtstart`, `dtend`, `summary`, `description`, `location`, `rrule`);
  `async_update_event(uid, event, recurrence_id, recurrence_range)`; `async_delete_event(uid,
  recurrence_id, recurrence_range)`; `recurrence_range` is `""`/`None` or `"THISANDFUTURE"`;
  the frontend shows Add/Edit/Delete by those feature flags; `_attr_initial_color`; after a push
  change call `async_update_event_listeners()`; reference implementations `local_calendar`,
  `caldav`, `google` in core.
- To-do platform: `TodoItem(summary, uid, status, due, description)`, `TodoListEntityFeature.*`,
  `async_create_todo_item`, `async_update_todo_item`, `async_delete_todo_items(uids)`,
  `async_move_todo_item(uid, previous_uid)`.
- Screen controls: Fully Kiosk Browser is the core analog (switches for screensaver and screen,
  numbers for brightness as config entities, buttons, connectivity binary sensors).
- Actions: register in `async_setup` with `hass.services.async_register(DOMAIN, name, handler,
  schema, supports_response)`; `services.yaml` plus `services.<name>` translations and
  `icons.json`; `ServiceValidationError` for user mistakes; `HomeAssistantError(translation_domain,
  translation_key)` otherwise.
- The card: `customElements.define`, `setConfig`, `set hass`, `getCardSize`, `getGridOptions`,
  `getStubConfig`, `getConfigForm` (schema editor) or `getConfigElement`; `window.customCards`;
  `hass.callWS`, `hass.connection.subscribeMessage`; served with
  `hass.http.async_register_static_paths([StaticPathConfig(url_path, path, cache_headers)])` and
  loaded with `frontend.add_extra_js_url(hass, url)` / `remove_extra_js_url`; websocket commands
  with `@websocket_api.websocket_command({...})` + `@websocket_api.async_response`, registered by
  `websocket_api.async_register_command(hass, handler)`; subscriptions through
  `connection.subscriptions[msg["id"]]` and `websocket_api.event_message`. The Marketplace
  registers dashboard resources only for dashboard repositories, so an integration ships and
  registers its own card.
- Calendar Card Pro (`alexpfau/calendar-card-pro`): list, column and grid views, per-calendar
  colors and labels, days to show, compact caps, 36 languages, HA's event dialog for edits. The
  Sunroom card is a subset by design: one list, Sunroom's own colors and people.
- HTTP: `async_get_clientsession(hass)`; aiohttp has no SSE client, so a `readline()` loop with
  `ClientTimeout(total=None, sock_connect=…, sock_read=…)` in a background task
  (`entry.async_create_background_task`), as the Nanoleaf integration does.
- Tests: `MockConfigEntry`, `aioclient_mock`, `hass_ws_client`, syrupy snapshots with the Home
  Assistant extension; config-flow tests through `hass.config_entries.flow.async_init` /
  `async_configure`; 100 % of `config_flow.py`, >95 % overall for Silver.
