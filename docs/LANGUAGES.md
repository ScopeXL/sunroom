# Languages

Every word a family reads on a wall, a device or the screen's own pages lives in
[`lang/en.json`](../lang/en.json), under a key; the code names the key, never the English
(ADR 0043). This page says how to add a word and how a language is added. (M10's T9 completes it:
the glossary, each language's style, quick add's words and the keyboards.)

## The files

- `lang/en.json`: the source. One flat object, keys sorted, two-space JSON, UTF-8.
- `lang/<code>.json`: a language, the same keys translated. A key it lacks shows English.
- `lang/languages.json`: the registry: each language's own `name`, its `locale` for `Intl`, `dir`,
  `chrono` (quick add's parser), `keyboard` (the wall keyboard's layout), and `status`:
  `complete` (offered in Settings → Household → Language) or `preview` (not offered yet).

## Adding a word

1. Pick its key: `<area>.<place>.<thing>[.<kind>]`, lowercase, dots and underscores. Areas:
   `app`, `ui`, `calendar`, `auth`, `setup`, `display`, `settings.<page>`, `problems`, `tips`,
   `dates`, `plugins.<id>`, `lists`, `tasks`, `meals`, `countdowns`, `photos`, `weather`, `sync`,
   `screen` (the screen's own pages), `agent` (Sunroom Screen's sentences), `api` (the server's).
   The last segment says what it is where it matters: `.title` (Title Case), `.action` (a
   button), `.toast`, `.hint`, `.label`, `.empty`, `.error`, `.aria` (a screen reader's only). A
   group of buttons shares a segment: `app.action.done`.
2. Write the English in `lang/en.json` as UX §2 says, as an ICU message: `{name}` for a value,
   `{n, plural, one {# day} other {# days}}` for a count, `{kind, select, idea {…} other {…}}`
   for a choice of words, `<b>…</b>` for a part drawn differently (`tRich`). A whole sentence,
   never pieces glued together: word order differs between languages. Write an apostrophe as
   `’` or `''` when it comes right before `{`, `}`, `#`, `<` or `|` (ICU quotes with `'`).
3. In a component, `const t = useT()` and `t("settings.household.name.label")`; elsewhere (a
   toast in a callback) the module's `t`. The server says `t_en("api.…")` (`core/lang.py`) and
   sends the key and its values beside the English; the page speaks it. The server's and the
   agent's messages are plain `{name}`s: no plural or select.
4. `just lang --fix` sorts the file; `just lang` checks everything (a key nothing names fails, so
   a key is added as it is used, never ahead).

## Adding a language

Copy `lang/en.json` to `lang/<code>.json`, add its entry to `lang/languages.json` as a
`preview`, translate, run `just lang` for the count, and mark it `complete` at 100 %. To see a
preview language, or the pseudo language that shows every word that slipped past the system, set
`localStorage["sunroom.language"]` to its code (or `pseudo`) in the browser and reload.

## What stays English

The installers' and the commands' output, the logs, the Discord message Send Feedback posts, the
docs and the CHANGELOG, and the names Sunroom, Sunroom Screen, Discord, Apple and Google.
