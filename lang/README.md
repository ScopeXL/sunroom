# Sunroom's words

- `en.json`: every word the family reads, in English: the source. The app names each by its key.
- `es.json` and the others: one file per language, the same keys translated (a missing key shows English).
- `languages.json`: the registry: each language's own name, locale, direction, keyboard, and whether it's `complete` (shown in the picker) or a `preview`.
- `just lang` checks them all; `just lang --fix` sorts them.
- How to add or translate a language, and the rules for keys and messages: [docs/LANGUAGES.md](../docs/LANGUAGES.md).
