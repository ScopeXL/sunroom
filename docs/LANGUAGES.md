# Languages

Every word a family reads on a wall, a device or the screen's own pages lives in
[`lang/en.json`](../lang/en.json), under a key; the code names the key, never the English
(ADR 0043). This page says how to add a word and how a language is added. (M10's T9 completes it:
the glossary and each language's style.)

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
   `screen` (the screen's own pages), `agent` (Sunroom Screen's sentences), `api` (the server's),
   `quickadd` (quick add's word lists, below).
   The last segment says what it is where it matters: `.title` (Title Case), `.action` (a
   button), `.toast`, `.hint`, `.label`, `.empty`, `.error`, `.aria` (a screen reader's only). A
   group of buttons shares a segment: `app.action.done` (buttons only; every other kind is the
   last segment).
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

## The server's words

The server says English and names each sentence beside it (`core/lang.py`, ADR 0043):

- **A refusal** is `AppError(status, code, "api.<area>.<name>", params={…})`; the envelope is
  `{"error": {"code", "message", "key", "params"}}`, `message` being the key's English with its
  values. The page says the key in the family's language (`errorMessage`), and the server's
  English for a key it doesn't know (an older page after an update). An exception that carries a
  sentence to a refusal (`OutboundError`, `SyncError`, `LibraryError`, `RestoreError`,
  `RecurrenceError`, which holds only the key: `domain/` stays standard library) has `key` and
  `params`, and `message` is its English. A helper that words an error returns `Words(key,
  params)`.
- **Needs Attention**: each problem's `key` and `params` beside its English `title`.
- **A plugin's words**: `plugins.<id>.…` (docs/PLUGINS.md).
- **Plain `{name}`s only**: no plural or select, so `t_en` is a substitution. A count is two
  keys, one for one and one for more (`api.photos.inbox.unreadable_one`); a word chosen by a case
  ("Apple" or "the server") is a whole sentence per case, never a piece glued in. Change a
  message's placeholders, and give it a new key: an older page still holds the old one.
- A sentence kept as English in a row (the photo inbox's last line) is named by its key again
  with `match_english`.
- `api.testing.*` are the test server's own (test mode only): a translation may leave them out.
- **Not yet keys**: what's kept as English in a row and shown as it was kept (an account's or a
  photo library's last error, a sync's run, the update check's line, how the last restore went,
  the weather's error line), names the server gives things (a device's, a new calendar's, "No
  title"), and the settings form's list of problems. Each needs its key stored or sent beside it.

## Dates, times and numbers

Nothing to translate: `lib/dates.ts` and `lib/lang`'s `formatNumber` write them with `Intl` in the
registry's `locale` ("jue 9", "4–10 oct", "16:00", "4:00–5:00 p. m.", "1234,5"), every digit
Latin, as the wall's digit boxes draw them. The household's 12- or 24-hour clock and first day of
the week stay its settings, and a range's dash is UX §2's: closed between two plain values, spaced
when either end has a space. Pick the `locale` whose `Intl` reads right on a wall. The words
around them ("Today", "until {time}", "{n} days") are keys like any other.

## Quick add's words

Quick add reads a line ("Dentist Thu 2:30pm Mia") with chrono for dates and times, and its own
grammar for repeats, lengths, people and the casual day words. The grammar's words are
`quickadd.words.*`, and each is a **list**, not a sentence: words joined by `|` ("every|each"), no
placeholder, no empty word, no case rules (matching ignores case; a space matches any spaces;
`just lang` checks the shape). A key is one word's forms or the words that play one part:

- **Words:** `every`, `other` ("every other week"), `week`, `month`, `day` and `year` (after
  every), `daily`, `weekly`, `fortnightly`, `monthly`, `yearly`, `weekday`, `weekdays`, `weekend`,
  `weekends`, `all_day`, `noon`, `midnight`, `today` (today, tonight), `tomorrow`,
  `day_after_tomorrow`, `next`, `last`, `the`, `on`, `of`, `and`, `with`, `for`, `a` (one, as an
  article), `about`, the lengths' units (`hour`, `hour_short`, `minute`, `minute_short`,
  `hour_and_a_half`, `half_hour`), each weekday (`monday`: "mon|monday", its shortest word being
  the one an acronym looks like) and its every-week form (`mondays`), `months` (every month's
  names and short forms), `numbers` (one to twelve, in order), `ordinals` (second to sixth, in
  order), `ordinal_numbers` (2nd to 6th) and `ordinal_suffixes` (st, nd, rd, th).
- **Parts:** `joining` (words that only join a title to what was taken out: "Dentist on
  [Oct 9]"), `ends_time` and `ends_day` (before a time or a day that ends something: "until 5pm"),
  `between_days` (between the days of a list or a range: "Sat and Sun"), `when_before` and
  `when_after` (around a number that says when, not how long: "in 30 min", "2 hours later").

The shapes stay English's ("every other week on Tue", "for an hour"): a language reads what fits
them, and a list it doesn't have is English's. chrono reads with the registry's `chrono` locale;
Sunroom wires `en` and `es` (`CHRONO` in `features/calendar/quickAdd.ts`, with what that locale
needs respelled: "@ 4" as its word for at, English's "tues" as "tue"), and another reads with
English's, which knows every date and time written in numbers. Numeric dates follow the locale:
10/9 is the 10th of September in Spanish.

## The wall's keyboard

The registry's `keyboard` names a layout in `frontend/src/lib/keyboards.ts`: the rows of
letters, the symbols behind 123 and the accents a held letter offers (data, not words). `qwerty`
is English's; `qwerty-es` has ñ after l, and ¿ and ¡ before ? and !. A language adds its own there
(ten keys to a row at most, and seven letters between shift and delete) or names one that fits.

## Fonts

Lexend covers Latin and Latin Extended. A language in another script needs a fallback face first
(not yet).

## Adding a language

Copy `lang/en.json` to `lang/<code>.json`, add its entry to `lang/languages.json` as a
`preview`, translate, run `just lang` for the count, and mark it `complete` at 100 %. To see a
preview language, or the pseudo language that shows every word that slipped past the system, set
`localStorage["sunroom.language"]` to its code (or `pseudo`) in the browser and reload.

## What stays English

The installers' and the commands' output, the logs, the Discord message Send Feedback posts, the
docs and the CHANGELOG, and the names Sunroom, Sunroom Screen, Discord, Apple and Google.
