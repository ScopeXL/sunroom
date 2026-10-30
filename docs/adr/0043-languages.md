# ADR 0043: Languages: the words live in `lang/en.json`

- **Status:** Accepted
- **Date:** 2026-10-30

## Context

- The owner's notes of 2026-10-30 asked for language support: not a translation, but the file
  tree, the runtime, the setting and the checks that let Sunroom be translated, English the
  default, every word the family reads moved out of the code into one English file, and
  instructions so that every later change keeps the languages whole. `docs/M10.md` sets out how
  other self-hosted apps do it (Answer A), five ways to do it here with a recommendation
  (Answer B), and the tasks; this ADR keeps the decisions a later session must not rediscover. It
  was started with the batch's first language task (T1) and gains a row with each task after.
- Three programs say words a family reads: the page (both shells and the screen's own pages),
  the server (its errors, Needs Attention, the plugins' names, the repeat sentence) and Sunroom
  Screen's agent (its toasts, refusals and steps).

## Decision

| Question | Decision |
|---|---|
| How the words are kept | **Plain ICU JSON, one formatter, Sunroom's own thin layer** (M10 Answer B, row 5): `lang/` at the repo's root holds `en.json` (the source: flat keys, sorted, two-space JSON, ICU MessageFormat messages), one file per other language with the same keys, and `languages.json`, the registry (each language's own name, its `Intl` locale, `dir`, chrono's locale, the keyboard's layout, and `complete` or `preview`). `es.json` ships as a preview with three keys, the example of the format. The page formats with `intl-messageformat` (12.x) behind `frontend/src/lib/lang.ts`, so a later swap (i18next) touches one file. Nothing is generated or compiled |
| Keys | `<area>.<place>.<thing>[.<kind>]`, lowercase, dots and underscores. The last segment says what a message is where it matters, and the design rules read it: `.title` (Title Case), `.action` (a button: Title Case up to five words), `.toast`, `.hint`, `.label`, `.empty`, `.error`, `.aria` (a screen reader's only). A group of buttons shares a segment instead: `app.action.done`, `app.action.back` (the design rules read the segment before the last too) |
| The runtime (T1) | `lib/lang.ts`: `Key` is `keyof typeof en` (`tsc` refuses a key English lacks); the page's language in a store; `t(key, params)` and `useT()` (a component draws again when the language changes); `tRich` for a message with tagged parts; a missing key or value throws in tests and shows English in production; one compiled message per language and key; English bundled, each other language a chunk (`import.meta.glob`) the service worker keeps. The page's language, first found: this device's override (`localStorage["sunroom.language"]`), the household's as last heard (`sunroom.language.household`), the first of the browser's languages that is complete, English. `pseudo` is English with every literal part accented, a third longer and between brackets, placeholders untouched: the way to see what slipped past |
| The setting (T1) | `household.language` (one migration, `en` for every household so far), in `SettingsOut` and `SettingsUpdate` (any code in the registry), `SetupIn` (the page's language at setup's household step), `GET /api/setup/status` and `GET /api/discover` (the household's once it's set up, so Pair This Screen and the screen's own pages speak it before they can read the settings). Settings → Household's first row, **Language**; setup's household step asks it first; Welcome to Sunroom, Set Up Sunroom and Pair This Screen have a quiet globe button with the page's language that opens **Choose a Language**. Only `complete` languages are offered; every page of the household follows the setting at once (`settings.changed`) unless the device has its own |
| The server's words | `core/lang.py` reads the same `en.json` (`sunroom/lang/` inside the package, which the image and the server wheel copy in; the checkout's `lang/` otherwise): `t_en(key, **params)` is a plain `{name}` substitution, so the server's (`api.*`) and the agent's (`agent.*`) messages have no plural or select (`just lang` checks) |
| The checks (T1) | `tsc` (typed keys); `eslint-plugin-i18next`'s `no-literal-string` in `jsx-only` mode on JSX text and the props that carry words, with a ratchet (`frontend/scripts/unswept.json`, the folders not yet swept, which each sweep task shortens); `just lang` (`frontend/scripts/lang.mjs`: valid, sorted, ICU that parses, no apostrophe that quotes by accident, the server's and agent's messages plain, other languages with English's keys, placeholders and tags, every key the code names in English and every English key named, the registry sane, a complete language at 100 %, each language's count printed), run by `just quick`, `just check` and CI's contract job; the design-rules test reads English's `.title` and `.action` words, and asserts no button, title or toast literal in a swept folder |
| The sweep (T2 to T4) | Every folder of `frontend/src` names keys, in its own area (`calendar.*`, `settings.<page>.*`, `tasks.*` for the chores plugin, `photos.*` for the screensaver); a plugin's room, Add type and Settings page names are `Key`s in its `index.ts`, translated where the shell shows them; shared buttons are `app.action.*`, shared counts and lengths `dates.*`. The English is unchanged, slips included, except "1 hour" for "1 hours" in This Screen's uptime and a comma in counts of a thousand or more. Words that become the household's data (the suggested screen names, the household name ideas) are saved in the page's language. The GitHub feedback link's frame stays English, as the Discord message does |
| The screen and Sunroom Screen (T6) | The screen's own pages name `screen.*` keys and speak this screen's override, else the household's language once the screen's Sunroom said it (`ScreenSunroomOut.language` from `/api/discover`), else the browser's. The agent's sentences are `agent.*` keys (`words.py`, the wheel's `sunroom_kiosk/lang`): its errors, refusals, toasts and progress steps carry their key and values beside the English, and `lib/lang.ts`'s `tSaid` says a key the page knows and the English for one it doesn't |

## Consequences

- **One migration**, `202610301744_household_language`: `household.language`, `String(16)`, not
  null, server default `en`. Tested from the 0.17.0 fixture (`202610282014.sql`).
- New in the API: `SettingsOut.language`, `SettingsUpdate.language`, `SetupIn.language`,
  `SetupStatusOut.language`, `DiscoverOut.language`. New in the backend: `core/lang.py`
  (`lang_dir`, `english`, `languages`, `known_language`, `t_en`). In the frontend: `lib/lang.ts`,
  `useHouseholdLanguage` (`lib/household`), `features/onboarding/LanguageButton.tsx`
  (`LanguageButton`, `LanguagePicker`), `scripts/lang.mjs`, `scripts/unswept.json`; the
  dependencies `intl-messageformat` and `@formatjs/icu-messageformat-parser` (the formatter's own
  parser, which the pseudo language and the checks read), and the dev dependency
  `eslint-plugin-i18next`.
- The image copies `lang/` twice (into the web stage for the page's build, and into the
  backend's package); `.dockerignore` lets it in; `scripts/server_wheel.py` copies it into the
  server wheel and checks it's there.
