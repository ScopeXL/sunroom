// `just lang` (ADR 0043, docs/LANGUAGES.md): the words in lang/ and the code that names them stay
// in step. `just lang --fix` sorts and formats the files first; it never drops a word.
//
// Checks: every language file is a flat JSON object of strings, sorted, two-space, with no key
// twice; every message parses as ICU; the server's and Sunroom Screen's messages (`api.*`,
// `agent.*`) are plain `{name}` substitutions; an apostrophe never quotes by accident; every
// other language has only English's keys, and only English's placeholders and tags; every key the
// code names exists in English, and every English key is named by the code (a family by the
// members it is built from); the registry is sane; a complete language has every key.
import { readdirSync, readFileSync, writeFileSync } from "node:fs";
import { join, relative } from "node:path";
import { fileURLToPath } from "node:url";

import { parse, TYPE } from "@formatjs/icu-messageformat-parser";

const REPO = fileURLToPath(new URL("../..", import.meta.url));
const LANG = join(REPO, "lang");
const KEY = /^[a-z0-9_]+(\.[a-z0-9_]+)+$/;
const fix = process.argv.includes("--fix");
const problems = [];

function problem(text) {
  problems.push(text);
}

/** Every file under a folder whose name passes the test, skipping what never holds words. */
function files(folder, test) {
  const found = [];
  const walk = (dir) => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      if (["node_modules", "__pycache__", ".venv", "static", "lang"].includes(entry.name)) continue;
      const path = join(dir, entry.name);
      if (entry.isDirectory()) walk(path);
      else if (test(entry.name)) found.push(path);
    }
  };
  walk(folder);
  return found;
}

// The page's sources (not tests: they keep English), the server's and Sunroom Screen's.
const pageSources = files(
  join(REPO, "frontend", "src"),
  (name) => /\.tsx?$/.test(name) && !/\.test\.tsx?$/.test(name) && !/schema\.d\.ts$/.test(name),
).map((path) => ({ path, text: readFileSync(path, "utf8") }));
const pythonSources = [
  ...files(join(REPO, "backend", "src", "sunroom"), (name) => name.endsWith(".py")),
  ...files(join(REPO, "kiosk", "agent", "src", "sunroom_kiosk"), (name) => name.endsWith(".py")),
].map((path) => ({ path, text: readFileSync(path, "utf8") }));

/**
 * Keys built from a code rather than written out: each `*` member comes from the code's own list,
 * so a member without its key, or a key whose member is gone, fails here. The sweep adds them as
 * it meets them.
 */
const FAMILIES = [];

// ---- the files -------------------------------------------------------------------------------

function readLanguage(code) {
  const path = join(LANG, `${code}.json`);
  const text = readFileSync(path, "utf8");
  const seen = new Map();
  for (const match of text.matchAll(/^\s*"((?:[^"\\]|\\.)*)"\s*:/gm)) {
    seen.set(match[1], (seen.get(match[1]) ?? 0) + 1);
  }
  const twice = [...seen].filter(([, count]) => count > 1).map(([key]) => key);
  let words;
  try {
    words = JSON.parse(text);
  } catch (error) {
    problem(`lang/${code}.json isn't JSON: ${error.message}`);
    return {};
  }
  if (typeof words !== "object" || words === null || Array.isArray(words)) {
    problem(`lang/${code}.json must be one object of keys and words.`);
    return {};
  }
  for (const key of twice) problem(`lang/${code}.json has ${key} more than once.`);
  for (const [key, value] of Object.entries(words)) {
    if (!KEY.test(key)) problem(`lang/${code}.json: ${key} isn't a key (lowercase, dots, _).`);
    if (typeof value !== "string") problem(`lang/${code}.json: ${key} must be words, flat.`);
  }
  const canonical = `${JSON.stringify(Object.fromEntries(Object.entries(words).sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))), null, 2)}\n`;
  if (text !== canonical) {
    if (fix && twice.length === 0) writeFileSync(path, canonical);
    else problem(`lang/${code}.json isn't sorted and formatted: run just lang --fix.`);
  }
  return words;
}

const registry = JSON.parse(readFileSync(join(LANG, "languages.json"), "utf8"));
const codes = Object.keys(registry);
const onDisk = readdirSync(LANG)
  .filter((name) => name.endsWith(".json") && name !== "languages.json")
  .map((name) => name.slice(0, -".json".length));
for (const code of onDisk) {
  if (!codes.includes(code)) problem(`lang/${code}.json has no entry in lang/languages.json.`);
}
const languages = Object.fromEntries(
  codes.filter((code) => onDisk.includes(code)).map((code) => [code, readLanguage(code)]),
);
const english = languages.en ?? {};
const englishKeys = Object.keys(english);

// ---- the registry ------------------------------------------------------------------------------

if (registry.en?.status !== "complete") problem("lang/languages.json: English must be complete.");
for (const [code, info] of Object.entries(registry)) {
  const where = `lang/languages.json: ${code}`;
  if (!/^[a-z]{2,3}(-[A-Z][a-z]{3})?$/.test(code)) problem(`${where} isn't a language code.`);
  if (!onDisk.includes(code)) problem(`${where} has no lang/${code}.json.`);
  for (const field of ["name", "locale", "dir", "status", "chrono", "keyboard"]) {
    if (typeof info[field] !== "string" || !info[field]) problem(`${where} needs a ${field}.`);
  }
  if (!["ltr", "rtl"].includes(info.dir)) problem(`${where}'s dir is ltr or rtl.`);
  if (!["complete", "preview"].includes(info.status)) {
    problem(`${where}'s status is complete or preview.`);
  }
  try {
    Intl.getCanonicalLocales(info.locale);
  } catch {
    problem(`${where}'s locale ${info.locale} isn't one Intl knows.`);
  }
}

// ---- the messages ------------------------------------------------------------------------------

/** A message's placeholders and tags, everywhere in it. */
function shape(elements, found = { names: new Set(), tags: new Set() }) {
  for (const element of elements) {
    if (element.type === TYPE.tag) {
      found.tags.add(element.value);
      shape(element.children, found);
    } else if (element.type !== TYPE.literal && element.type !== TYPE.pound) {
      found.names.add(element.value);
      if (element.type === TYPE.plural || element.type === TYPE.select) {
        for (const option of Object.values(element.options)) shape(option.value, found);
      }
    }
  }
  return found;
}

const parsed = {};
for (const [code, words] of Object.entries(languages)) {
  parsed[code] = {};
  for (const [key, message] of Object.entries(words)) {
    if (typeof message !== "string") continue;
    if (/'[{}#<|]/.test(message)) {
      problem(`lang/${code}.json: ${key}: an apostrophe before {, }, #, < or | quotes it in ICU.`);
    }
    try {
      parsed[code][key] = parse(message);
    } catch (error) {
      problem(`lang/${code}.json: ${key} isn't an ICU message: ${error.message}`);
      continue;
    }
    const plain = parsed[code][key].every(
      (element) => element.type === TYPE.literal || element.type === TYPE.argument,
    );
    if (/^(api|agent)\./.test(key) && !plain) {
      problem(`lang/${code}.json: ${key}: the server's and the agent's words are plain {name}s.`);
    }
  }
}

// A translation may leave a placeholder or tag out ("El Sunroom de {name}" needs no `ends`), but
// never brings one English doesn't give it.
const within = (ours, theirs) => [...ours].every((item) => theirs.has(item));
for (const [code, words] of Object.entries(languages)) {
  if (code === "en") continue;
  for (const key of Object.keys(words)) {
    if (!(key in english)) {
      problem(`lang/${code}.json: ${key} isn't in English.`);
      continue;
    }
    if (!parsed[code][key] || !parsed.en[key]) continue;
    const ours = shape(parsed[code][key]);
    const theirs = shape(parsed.en[key]);
    if (!within(ours.names, theirs.names) || !within(ours.tags, theirs.tags)) {
      problem(`lang/${code}.json: ${key} has placeholders or tags that English's doesn't.`);
    }
  }
}

// ---- the code ----------------------------------------------------------------------------------

const where = (path) => relative(REPO, path);
for (const { path, text } of pageSources) {
  for (const match of text.matchAll(/\b(?:t|tRich)\(\s*(["'`])([^"'`$]+)\1/g)) {
    if (!(match[2] in english)) problem(`${where(path)} names ${match[2]}, which English lacks.`);
  }
}
for (const { path, text } of pythonSources) {
  for (const match of text.matchAll(/(["'])((?:api|agent)\.[a-z0-9_.]+)\1/g)) {
    if (!(match[2] in english)) problem(`${where(path)} names ${match[2]}, which English lacks.`);
  }
}

const named = new Set();
for (const { text } of [...pageSources, ...pythonSources]) {
  for (const match of text.matchAll(/(["'`])([a-z0-9_]+(?:\.[a-z0-9_]+)+)\1/g)) named.add(match[2]);
}
for (const family of FAMILIES) {
  const [before, after] = family.pattern.split("*");
  const members = new Set(family.members());
  for (const member of members) {
    const key = `${before}${member}${after}`;
    if (key in english) named.add(key);
    else problem(`English lacks ${key} (${family.pattern} for ${family.from}).`);
  }
  for (const key of englishKeys) {
    if (!key.startsWith(before) || !key.endsWith(after)) continue;
    const member = key.slice(before.length, key.length - after.length);
    if (!member.includes(".") && !members.has(member)) {
      problem(`English has ${key}, but ${family.from} has no ${member}.`);
    }
  }
}
for (const key of englishKeys) {
  if (!named.has(key)) problem(`English has ${key}, which nothing names: remove it.`);
}

// ---- how far each language is ------------------------------------------------------------------

for (const code of Object.keys(languages)) {
  const have = englishKeys.filter((key) => key in languages[code]).length;
  const percent = englishKeys.length ? Math.floor((have / englishKeys.length) * 100) : 100;
  const status = registry[code]?.status ?? "?";
  console.log(
    `${code}  ${String(have)} of ${String(englishKeys.length)} (${String(percent)}%)  ${status}`,
  );
  if (status === "complete" && have < englishKeys.length) {
    problem(`${code} is marked complete with ${String(englishKeys.length - have)} keys to go.`);
  }
}

if (problems.length) {
  console.error(
    `\n${problems.join("\n")}\n\n${String(problems.length)} to fix (docs/LANGUAGES.md).`,
  );
  process.exit(1);
}
console.log("The words are in step.");
