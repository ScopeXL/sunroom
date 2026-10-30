# Adding a plugin

How to add a feature to Sunroom as an in-repo plugin, in seven steps, for an AI session (or a
developer) changing the code. Families see plugins as **Features** in Settings, each with a
switch and its own settings. Read PLAN §6,
[ADR 0002](adr/0002-in-repo-plugins-with-runtime-switches.md),
[ADR 0026](adr/0026-m4-meals-countdowns-photos-weather.md) and CLAUDE.md's gotchas first.

A plugin is one backend package, `backend/src/sunroom/plugins/<id>/`, and one frontend folder,
`frontend/src/features/<folder>/`, each listed by hand in a registry. There is no discovery and no
third-party code; PLAN §6.4 lists what third-party plugins would need. The framework is
`plugins/base.py` (the contract), `plugins/context.py` (`PluginContext`), `plugins/manager.py`
(one task per plugin), `plugins/spec.py` (`ParamField`) and `plugins/router.py` (`/api/plugins`
and the gate); nothing else goes at the top of `plugins/`
(`test_the_framework_folder_holds_only_the_framework`).

**The model to copy is `countdowns`**, the smallest complete plugin: read
`backend/src/sunroom/plugins/countdowns/`, `backend/tests/countdowns/`,
`frontend/src/features/countdowns/` and `frontend/e2e/countdowns.spec.ts` end to end before
starting. The examples below use the id `notes`; use your own.

## The rules that keep plugins independent

| Rule | Enforced by |
|---|---|
| **It works with every other plugin off** (CLAUDE.md hard rule 7) | Its own tests run an app that has only this plugin |
| **It imports no other plugin**, and never the engine (`sunroom.db.engine`), app state (`sunroom.state`), `sunroom.app` or `sunroom.boot`. Core modules are fine: `sunroom.auth.deps`, `sunroom.core.errors`, `sunroom.db.base`, `sunroom.db.types`, `sunroom.domain.*`, `sunroom.calendar.schemas` | `tests/plugins/test_contract.py::test_plugin_code_keeps_to_the_context` |
| **It owns its tables and reads no one else's.** Its foreign keys point only at core tables or its own | `test_every_table_is_owned_by_exactly_one_of_core_or_a_plugin`, `test_plugin_models_reference_only_core_tables_or_their_own` |
| **The rest of Sunroom comes through `PluginContext`**: `ctx.now()` and `ctx.zone()`, `ctx.settings()`, `ctx.read()` and `ctx.write()` (the write transaction has `tx.publish`), the facades `ctx.household`, `ctx.members`, `ctx.calendar` and `ctx.photos`, `ctx.http()`, `ctx.encrypt()` and `ctx.decrypt()`, `ctx.every()` and `ctx.spawn()`, `ctx.enabled(other_id)` | The import rule above |
| **Cross-plugin needs go through core**: the facades, board overlays (`ctx.calendar.register_overlay`), core live-update events (`manifest.subscribes`, such as `("members.",)`), or, in the frontend only, another plugin's public API, offered only while that plugin is on, with the feature complete without it (Meals → Lists, ADR 0026). Backends never meet | Review; the import and table rules |
| **Off means off, and the data stays.** The framework's gate answers every route with 404 `plugin_disabled`, jobs stop within 10 s, the overlay answers nothing (the facade wraps it), and the frontend hides every part. Turned back on, everything is there | `test_every_plugin_route_is_gated`, and its own switched-off test (step 6) |
| **A failure stays inside.** A job, event or `on_enable` that raises marks only this plugin errored (a parent sees Retry) and its routes keep answering. Handle expected trouble (a server that doesn't answer) with plain words; let the rest raise | `tests/plugins/test_manager.py` |
| **Settings are `ParamField`s, never a migration.** They are stored as JSON, coerced against the spec on every read and write, and drawn by the generic form in Settings → Features, which has no Save button: a switch, choice or chip saves as it changes and a typed field when it's left (ADR 0029). `secret` fields are write-only: they read back as `***`, writing `***` keeps the stored value and an empty string clears it, and the export masks them too; rules across fields go in `validate_settings`. A stored value the spec can no longer read falls back to its default, and a key it no longer has is dropped: when a setting is renamed or reshaped, bump the manifest's `version` and carry the old value over in `upgrade_settings(raw, from_version)`, which the manager calls once at boot with the stored JSON, before any of that (Meals 1.1.0 turned `show_on_calendar` into `calendar_slots` this way) | `test_spec_defaults_round_trip` |
| **Outbound HTTP only through `ctx.http()`**, the guarded client; private addresses only with `allow_private` (PLAN §12.6) | `tests/test_netguard.py::test_only_core_http_makes_an_http_client` |
| **Pure rules live in `domain/<id>.py`**: standard library only, `now` passed in. Time comes from `ctx.now()` (the app's clock); the household's today is `to_local(ctx.now(), ctx.zone()).date()` | `tests/test_purity.py` |

## 1. The backend package

`backend/src/sunroom/plugins/notes/`:

| File | What goes in it |
|---|---|
| `__init__.py` | A docstring only. `db/models.py` imports every plugin's models, so an `__init__` that imports its own modules drags them all in (CLAUDE.md gotchas) |
| `models.py` | SQLAlchemy models on `sunroom.db.base.Base`, with `sunroom.db.types`: `String(36)` ids from `new_id()` (UUIDv7), `UTCDateTime`, `IsoDate`, `utcnow`; `deleted_at` for removals that Undo and Recently removed can put back. Then `TABLES` (every table, parents first) and `EXPORT_TABLES` |
| `plugin.py` | `MANIFEST`, the plugin class, and `PLUGIN = Notes()` |
| `schemas.py` | Pydantic shapes. **Every class name must be unique across the whole API**: FastAPI names schemas after their class, and two classes with one name both become `sunroom__plugins__…__ItemOut`, renaming types the frontend already uses. Prefix them with the plugin's noun (`NoteIn`, `NoteOut`, `NotePatch`, `RemovedNoteOut`) and check the names in `frontend/src/api/openapi.json` |
| `service.py` | The rules. Writes go in `async with ctx.write() as tx:`, stamp times with `ctx.now()`, and publish from the same transaction: `tx.publish("notes.changed", {"id": row.id})` (delivered after commit). Errors are `AppError(status, code, "api.notes.gone")`: the key of a sentence in `lang/en.json`, in plain words (UX §2: say what happened and what to do; never an ID), with `params={"name": …}` for a value in it. The server's sentences are plain `{name}`s, never a plural: one key for one and one for more (ADR 0043, docs/LANGUAGES.md) |
| `router.py` | `build(router, plugin)`: routes on the router the framework hands over, already prefixed `/api/<url prefix>` and gated. `ActorDep` for anyone signed in, `ParentDep` for parents only (`Actor` also says whether it's the wall screen, and who tapped there). Static paths before `/{note_id}`; a `ctx()` helper answering 503 `api.notes.starting` ("Notes are still starting. Try again.") until `on_enable` has run |
| `sample.py` | `seed(ctx, people)`: the synthetic Sample Family's rows (`people` maps Ana, Sam, Mia and Leo to member ids), added only when the plugin's tables are empty. The test server's `POST /api/_test/seed` (`just seed`, end-to-end runs, screenshots) calls it for each enabled plugin |

The manifest (`plugins/base.py` has every field):

```python
MANIFEST = PluginManifest(
    id="notes",  # ^[a-z][a-z0-9_]{1,30}$; the URL prefix is the id with "-" for "_"
    version="1.0.0",  # the plugin's API and settings shape
    name=t_en("plugins.notes.name"),  # Settings → Features, and "Notes is turned off. …"
    description=t_en("plugins.notes.description"),
    settings_spec=(
        ParamField(
            "pinned_first",
            t_en("plugins.notes.settings.pinned_first.label"),
            "bool",
            default=True,
        ),
    ),
    tables=TABLES,
    export_tables=EXPORT_TABLES,
    contributes=Contributions(
        display_rooms=(
            DisplayRoom("notes", t_en("plugins.notes.rooms.notes"), "sticky-note", order=70),
        ),
        phone_tabs=(
            PhoneTab("notes", t_en("plugins.notes.tabs.notes"), "sticky-note", "/notes", order=70),
        ),
    ),
    default_enabled=True,
)
```

`contributes` is what `GET /api/plugins` reports; the frontend draws from its own module (step 5),
so keep the two in step.

**Every word is a key** (ADR 0043, docs/LANGUAGES.md). The manifest's words come from
`lang/en.json` through `t_en` (`sunroom.core.lang`), each key written out in the plugin's code so
`just lang` sees it: `plugins.<id>.name` and `.description`; a field's `.settings.<key>.label`,
`.help` and `.choices.<value>` (the value lowercased, anything else `_`); and `.panels.<key>`,
`.rooms.<key>`, `.tabs.<key>`, `.sections.<key>`. The page finds each word in the family's
language by the same key; `test_every_word_a_manifest_says_is_its_key_s_english` holds the two
together. A refusal names its key (`api.notes.gone`), and so does a `Problem` (`key`, `params`).

The class follows countdowns: it extends `PluginBase` (a no-op default for every hook);
`register_routes` imports `router.py` and calls `build(router, self)`; `on_enable(ctx)` keeps
`self.ctx = ctx`, then registers jobs (`ctx.every("tidy", 3600, job)` runs now and then every
hour, never overlapping the plugin's other callbacks) and overlays
(`ctx.calendar.register_overlay(provider)`, keyed by the plugin id unless a key is given);
`seed_sample` calls `sample.seed`. Skip `on_disable` unless something must be released: the
context stays, so the routes keep answering while the plugin is errored.

## 2. Register it

- `backend/src/sunroom/plugins/registry.py`: import `PLUGIN as NOTES` from
  `sunroom.plugins.notes.plugin` and add `NOTES.manifest.id: NOTES` at the end of `REGISTRY`. The
  dict's order is the order of `GET /api/plugins`, Settings → Features and the export. Update the
  module docstring's line about which milestone added what.
- `backend/src/sunroom/db/models.py`: import `models as notes_models` from `sunroom.plugins.notes`
  and add `"notes_models"` to `__all__` (alphabetical), so `Base.metadata` (Alembic, the export,
  the tests) has the tables whether or not the plugin is on.

## 3. One migration

- From the repo root, `just db-revision "notes tables"`. It migrates a throwaway database to
  head, then writes `backend/src/sunroom/migrations/versions/<YYYYMMDDHHMM>_notes_tables.py`.
  The slug comes from the message and **must start with the plugin id** (PLAN §6.4). There is one
  history for core and plugins, and a plugin's tables exist whether or not it's on.
- Read the generated file: it should create only your tables and indexes, and its `downgrade()`
  raises (migrations are forward-only). `test_models_match_migrations` fails while models and
  migrations differ: while it's unreleased, change the models and generate the migration again
  rather than hand-editing it. Once `just bump` has listed it in `released.lock`, never touch it;
  a later change gets a new migration (CLAUDE.md hard rule 3).
- **The fixture-database rule.** `backend/tests/fixtures/db/<revision>.sql` holds each release's
  schema with synthetic rows in every table, and
  `test_released_databases_upgrade_to_head_keeping_every_row` upgrades each to head, keeping
  every row. Before your migration goes in, the last release's fixture must exist
  (`test_unreleased_migrations_are_tested_against_the_last_release` prints the command). After the
  release that ships the plugin, that release's seed in `backend/tests/fixtures/db/build.py`
  (`SEEDS`, keyed by the release's head revision) must give the plugin's tables synthetic rows
  too, because the test refuses an empty table. Build it with
  `cd backend && uv run python -m tests.fixtures.db.build <revision>`.

## 4. The export, and the lists that pin the plugins

- **Export.** The manifest's `export_tables` are the household's data (Settings → Backup →
  Export everything); the rest of `tables` are left out (caches, run logs, sign-in states, such as
  `weather_cache`, `sync_runs` and `oauth_states`). Every column ending in `_enc`, `_hash` or
  `_fp` in an exported table goes in `export_column_excluded`, for example
  `{"notes": frozenset({"credentials_enc"})}` (`test_secret_columns_never_reach_the_export`).
- **Stored secrets** go in a column named exactly `credentials_enc` (`ctx.encrypt()`), next to a
  `status` column if the plugin can show "connect again" (`needs_reconnect`): a new
  `APP_SECRET_KEY` wipes every `credentials_enc` at boot and sets that status. `ctx.decrypt()`
  raises `PluginDecryptError` for a secret it can no longer read. Add the table to
  `backend/tests/test_boot.py::test_every_real_credentials_table_is_wiped_when_the_key_changes`.
  (`sync_accounts` and, since 0.14.0, `photo_sources` have their status: a photo library asks for
  its key again, ADR 0036.)
- `backend/tests/test_export.py`: add the exported tables to the expected list, after the last
  plugin's (core's tables first, then each plugin's in registry order).
- `backend/tests/plugins/test_manager.py::test_the_real_registry_turns_its_plugins_on`: add
  `("notes", True)` at the end (`False` when `default_enabled` is off).
- `scripts/image_common.sh`, in `set_up()`: add `notes:running` (or `notes:disabled`) at the end
  of the plugin list, and the exported tables to the export's list of tables, which is in
  alphabetical order. `just smoke-image` fails otherwise (CLAUDE.md gotchas).

## 5. The frontend

- **The folder**, `frontend/src/features/notes/`, with an `index.ts` that default-exports a
  `PluginModule` (`features/registry.ts`) whose `id` is the manifest's id:

  ```ts
  import { StickyNote } from "lucide-react";

  import type { PluginModule } from "../registry";
  import { NotesRoom, NotesTab } from "./NotesRoom";

  const module: PluginModule = {
    id: "notes",
    rooms: [
      {
        key: "notes",
        label: "Notes",
        icon: StickyNote,
        order: 70,
        Display: NotesRoom,
        Phone: NotesTab,
      },
    ],
  };

  export default module;
  ```

- **The registry**, `frontend/src/features/registry.ts`: add `notes: () => import("./notes"),` at
  the end of `plugins`, and update its docstring's milestone line. The shell loads the modules of
  the plugins the server lists as enabled; nothing else needs changing for that.
- **The slots** (`PluginModule` in `features/registry.ts` documents each):

  | Slot | Where it shows |
  |---|---|
  | `rooms` | A room on the wall's rail and a phone tab (or a row in More) at `/<key>`; `Display` and `Phone` get the rest of the address as `path`. Orders so far: Lists 20, Tasks 30, Meals 40, Countdowns 50, Photos 60. A room's `Display` draws no title row of its own: it hands its title, a quiet line, a way back and its buttons to the wall's header with `<RoomHeader title="Lists" controls={…} />` (or `useRoomHeader`, from `shell/roomHeader`; `HeaderBack` and `HeaderLink` in `shell/HeaderLinks` for links), and puts `ml-auto` on what belongs at the right (ADR 0029). `Phone` keeps its own `ui/Screen` title. The key must not be an address core already uses (`frontend/src/router.tsx`), nor `api` or `assets` |
  | `today` | A block of the wall's Today panel and a section of a phone's Today. Orders so far: Tasks Today 10, Tonight 20, To do 30, Coming up 40 |
  | `add` | A kind of thing the Add panel makes beside Event; with `room`, it's the first choice in that room |
  | `calendarOverlays` | Quiet chips on the board; `key` is the overlay's key on the backend (the plugin id unless given) |
  | `removed` | Rows in Settings → Household → Recently removed; it reports how many with `onCount` |
  | `settingsPages` | A page of its own in Settings, after Calendars & accounts. A plugin that has one shows only its switch and a row to that page on Features: its fields live on its page, so no form is drawn twice |
  | `settings.household` | A section in Settings → Household |
  | `settings.features`, `ownSettingGroups` | What the plugin draws itself under its switch on Settings → Features (calendar_sync: the Sign in with Google row and its sheet), and the `group`s of its settings spec that this covers, which the generic form then leaves out |
  | `personColumn`, `railBlock`, `dayHeader`, `saverCorner`, `eventAction`, `boardPill`, `overlay` | Under a person in the People view; by the clock (in the wall's header since ADR 0029, `place="header"`; at the top of a phone's Today); in a board day's header; on the screensaver's date line; a button on an event's sheet; a pill in the board's toolbar; over the whole wall |
  | `onboarding`, `settings.accounts` | **Not generic.** `features/onboarding/SetupWizard.tsx` asks for a plugin by id (weather in step 3, calendar_sync in step 7), and `CalendarsPage.tsx` shows only calendar_sync's accounts. A new first-run step means changing the wizard, and UX §6 |

- **Data.** A `data.ts` with TanStack Query hooks. Every call goes through the generated client
  (`api.GET(...)`, `unwrap`), with types from `components["schemas"]`. Run `just api-types` after
  any route or schema change: `just check` fails while `frontend/src/api/schema.d.ts` is stale.
  Query keys start with the plugin's word (`["notes", …]`).
- **Live updates.** Add `case "notes.changed": invalidate(["notes"]); break;` to
  `frontend/src/lib/eventRouter.ts`, with `invalidate(["occurrences"])` too when the plugin has a
  board overlay.
- **Another plugin's API** only behind `usePlugins()` (that plugin enabled), and the feature
  still complete without it (ADR 0026).
- **The screens** follow CLAUDE.md and UX: `ui/` primitives and design tokens only (no raw hex);
  plain words, Title Case for titles, headings and navigation and sentence case for the rest
  (UX §2); a toast that repeats the button's verb, with Undo; a visible
  button for every action; fields from `ui/TextField`, which opens the wall's own keyboard; tap
  targets of 56 px on the wall and 44 px on phones. Rooms sit in the wall's shell, which gives
  them a way back and returns home when idle; a room that must keep the screen calls `holdIdle()`,
  as the routine runner does.

## 6. Tests

- **Its own**, in `backend/tests/notes/`, copied from `backend/tests/countdowns/`: a `conftest.py`
  whose app has only this plugin (`create_app(settings, clock=clock, plugins={"notes": Notes()})`),
  which also shows it works with every other plugin off; helpers; time from the `FakeClock`;
  sockets are disabled; the Sample Family only. Cover every route (status, body, the plain error
  messages), parents-only actions and children's devices, the wall screen's `X-Sunroom-Member`, the
  live-update event, jobs and overlays called through the plugin's context (countdowns'
  `running()` helper), and `seed_sample` adding the Sample Family's rows once (seeding twice adds
  nothing).
- **Switched off**: disable it, then every route answers 404 `plugin_disabled` with "Notes is
  turned off. A parent can turn it on in Settings.", its overlay answers nothing, and after
  enabling it the data is back (countdowns'
  `test_off_every_route_is_404_and_on_again_the_data_is_there`). List the routes from a fresh
  `APIRouter` passed to `register_routes`, or from `app.openapi()["paths"]`, and assert their
  count; never loop over `app.routes`, which holds included routers since FastAPI 0.142 and would
  check nothing.
- **The contract**: `backend/tests/plugins/test_contract.py` checks every registered plugin by
  itself (the manifest, table ownership, foreign keys, imports, secret columns, the gate, settings
  defaults). Nothing to add; it must pass.
- **Domain rules**: `backend/tests/domain/test_notes.py` for `domain/notes.py`.
- **Frontend**: Vitest beside pure helpers and words (`words.test.ts`); an end-to-end spec,
  `frontend/e2e/notes.spec.ts`, against the test server (seed the Sample Family, set the server's
  clock with `POST /api/_test/clock`); and the plugin's screens added to `frontend/e2e/a11y.spec.ts`
  and `frontend/e2e/screenshots.spec.ts`.
- **Run** `cd backend && uv run pytest -q`, `just check`, `just e2e`, and `just screenshots`
  (review 1920×1080, 1080×1920 and 390×844, light and dark, against UX §10).

## 7. Docs and the changelog

- **PLAN**: §9 (the plugins table), §10.3 (its tables), §11.3 (its endpoints), §6.5 (room and
  Today orders), and §5.3's layout.
- **UX**: its screens and words (the room, Today blocks, Add, empty states).
- **An ADR** for any decision made on the way, such as where a part lives or how it reaches
  another plugin (ADR 0026 is the model), listed in `docs/adr/README.md`.
- **PRIVACY.md** when the plugin sends anything off the server or keeps something new about
  people.
- **CHANGELOG.md**: a plain-English line under `[Unreleased]`, written for the family: what they
  can do now.
- **CLAUDE.md**: the status line when the milestone is done, and a gotcha line for anything that
  cost time.

Then CLAUDE.md's definition of done: `just check` and `just e2e` green, screenshots reviewed, docs
and the changelog updated, `just scan` clean, committed.

## Every file a new plugin touches

- `backend/src/sunroom/plugins/notes/` (`__init__`, `models`, `plugin`, `schemas`, `service`,
  `router`, `sample`), and `backend/src/sunroom/domain/notes.py` for pure rules
- `backend/src/sunroom/plugins/registry.py` and `backend/src/sunroom/db/models.py`
- `backend/src/sunroom/migrations/versions/<YYYYMMDDHHMM>_notes_….py`
- `backend/tests/notes/`, `backend/tests/domain/test_notes.py`, `backend/tests/test_export.py`,
  `backend/tests/plugins/test_manager.py`, and `backend/tests/test_boot.py` when it stores secrets
- after the release that ships it: `backend/tests/fixtures/db/build.py` and the new fixture `.sql`
- `scripts/image_common.sh`
- `frontend/src/features/notes/`, `frontend/src/features/registry.ts`,
  `frontend/src/lib/eventRouter.ts`, and `frontend/src/api/openapi.json` with
  `frontend/src/api/schema.d.ts` (through `just api-types`)
- `frontend/e2e/notes.spec.ts`, `frontend/e2e/a11y.spec.ts`, `frontend/e2e/screenshots.spec.ts`
- `docs/PLAN.md`, `docs/UX.md`, `docs/adr/`, `CHANGELOG.md`, and `PRIVACY.md` when it applies
