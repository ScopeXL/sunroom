/**
 * The words the family reads, in their language (ADR 0043, docs/LANGUAGES.md). Every word lives
 * in `lang/en.json` under a key; the code names the key and `t` formats its ICU message
 * (`intl-messageformat`) in the page's language, falling back to English for a key that language
 * lacks. English is in the bundle; each other language is a chunk of its own, loaded when chosen
 * (the service worker keeps them all).
 *
 * The page's language, first found: this device's override (`localStorage["sunroom.language"]`:
 * the pseudo language's door, and a later per-device setting's), the household's (Settings →
 * Household → Language, remembered so the next paint starts in it), the first of the browser's
 * languages Sunroom has complete, English.
 *
 * `pseudo` is English made visibly foreign: every literal part accented, about a third longer,
 * between brackets, with placeholders, `#` and plural keywords untouched. A word on screen
 * without the brackets didn't come through here (e2e/lang.spec.ts).
 */
import { parse, TYPE, type MessageFormatElement } from "@formatjs/icu-messageformat-parser";
import { IntlMessageFormat } from "intl-messageformat";
import { createElement, Fragment, useCallback, useEffect, type ReactNode } from "react";

import en from "../../../lang/en.json";
import registry from "../../../lang/languages.json";
import { createStore, useStore } from "./store";

export type Key = keyof typeof en;
export type LanguageCode = keyof typeof registry;
export type PageLanguage = LanguageCode | "pseudo";
export type Params = Record<string, string | number | Date>;

export interface LanguageInfo {
  /** The language's own name for itself: "English", "Español". */
  name: string;
  /** For `Intl`: dates, numbers and plural rules. */
  locale: string;
  dir: "ltr" | "rtl";
  /** Only a complete language is offered; a preview is reached by the override. */
  status: "complete" | "preview";
  /** chrono-node's locale for quick add. */
  chrono: string;
  /** The wall keyboard's layout (lib/keyboards). */
  keyboard: string;
}

export const LANGUAGES = registry as Readonly<Record<LanguageCode, LanguageInfo>>;

/** This device's own choice, over the household's. */
export const OVERRIDE_KEY = "sunroom.language";
/** The household's language as this device last heard it, for the first paint. */
export const HOUSEHOLD_KEY = "sunroom.language.household";

const english: Readonly<Record<string, string>> = en;
const chunks = import.meta.glob<Record<string, string>>(
  ["../../../lang/*.json", "!../../../lang/en.json", "!../../../lang/languages.json"],
  { import: "default" },
);
const loaded = new Map<LanguageCode, Readonly<Record<string, string>>>([["en", english]]);
const languageStore = createStore<PageLanguage>("en");

function isLanguageCode(code: string): code is LanguageCode {
  return Object.hasOwn(LANGUAGES, code);
}

function known(code: string): PageLanguage | null {
  return code === "pseudo" || isLanguageCode(code) ? code : null;
}

/** A key the server or Sunroom Screen named, if this page knows it (an older page may not). */
export function isKey(value: string): value is Key {
  return Object.hasOwn(english, value);
}

/** The languages a family can pick, by their own names. */
export function completeLanguages(): { value: LanguageCode; label: string }[] {
  return (Object.keys(LANGUAGES) as LanguageCode[])
    .filter((code) => LANGUAGES[code].status === "complete")
    .map((code) => ({ value: code, label: LANGUAGES[code].name }));
}

export function getLanguage(): PageLanguage {
  return languageStore.get();
}

export function useLanguage(): PageLanguage {
  return useStore(languageStore);
}

/** What the page's language is called, in itself. */
export function languageName(language: PageLanguage): string {
  return language === "pseudo" ? "[Þšéüðö]" : LANGUAGES[language].name;
}

/** The `Intl` locale for the page's language. */
export function pageLocale(language: PageLanguage = languageStore.get()): string {
  return language === "pseudo" ? LANGUAGES.en.locale : LANGUAGES[language].locale;
}

// prettier-ignore
const ACCENTS: Readonly<Record<string, string>> = {
  a: "á", b: "ƀ", c: "ç", d: "ð", e: "é", f: "ƒ", g: "ĝ", h: "ĥ", i: "í", j: "ĵ", k: "ķ",
  l: "ļ", m: "ɱ", n: "ñ", o: "ö", p: "þ", q: "ǫ", r: "ŕ", s: "š", t: "ţ", u: "ü", v: "ṽ",
  w: "ŵ", x: "ẋ", y: "ý", z: "ž", A: "Å", B: "Ɓ", C: "Ç", D: "Ð", E: "É", F: "Ƒ", G: "Ĝ",
  H: "Ĥ", I: "Î", J: "Ĵ", K: "Ķ", L: "Ļ", M: "Ṁ", N: "Ñ", O: "Ö", P: "Þ", Q: "Ǫ", R: "Ŕ",
  S: "Š", T: "Ţ", U: "Û", V: "Ṽ", W: "Ŵ", X: "Ẋ", Y: "Ý", Z: "Ž",
};

function accented(text: string): string {
  return Array.from(text, (letter) => ACCENTS[letter] ?? letter).join("");
}

function pseudoElements(elements: MessageFormatElement[]): MessageFormatElement[] {
  return elements.map((element) => {
    switch (element.type) {
      case TYPE.literal:
        return { ...element, value: accented(element.value) };
      case TYPE.plural:
      case TYPE.select:
        return {
          ...element,
          options: Object.fromEntries(
            Object.entries(element.options).map(([choice, option]) => [
              choice,
              { ...option, value: pseudoElements(option.value) },
            ]),
          ),
        };
      case TYPE.tag:
        return { ...element, children: pseudoElements(element.children) };
      default:
        return element;
    }
  });
}

/** English made visibly foreign, as a parsed message: `[Ðöñé~~]`. */
export function pseudoMessage(source: string): MessageFormatElement[] {
  const padding = "~".repeat(Math.ceil(source.length * 0.3));
  return [
    { type: TYPE.literal, value: "[" },
    ...pseudoElements(parse(source)),
    { type: TYPE.literal, value: `${padding}]` },
  ];
}

const compiled = new Map<string, IntlMessageFormat>();

function message(language: PageLanguage, key: string): IntlMessageFormat {
  const id = `${language}\u0000${key}`;
  const found = compiled.get(id);
  if (found) return found;
  const own = language === "pseudo" ? undefined : loaded.get(language)?.[key];
  const source = own ?? english[key];
  if (source === undefined) throw new Error(`No English for the key ${key}`);
  // A fallback is English's message, so English's plural rules read it.
  const locale = own === undefined ? LANGUAGES.en.locale : pageLocale(language);
  const made = new IntlMessageFormat(
    language === "pseudo" ? pseudoMessage(source) : source,
    locale,
  );
  compiled.set(id, made);
  return made;
}

function format(language: PageLanguage, key: Key, params?: Params): string {
  try {
    return String(message(language, key).format(params));
  } catch (error) {
    // Tests stop at a missing key or value; a family sees English, or at worst the key.
    if (import.meta.env.MODE === "test") throw error;
    console.error(error);
    return english[key] ?? key;
  }
}

/** The key's words in the page's language as it is now (a toast, a mutation's callback). */
export function t(key: Key, params?: Params): string {
  return format(languageStore.get(), key, params);
}

/** `t` for a component: it draws again when the language changes. */
export function useT(): (key: Key, params?: Params) => string {
  const language = useLanguage();
  return useCallback((key: Key, params?: Params) => format(language, key, params), [language]);
}

type RichValue = string | number | Date | ReactNode | ((chunk: ReactNode) => ReactNode);

/**
 * A message with parts drawn differently (`"Or open <b>{address}</b> on any device."`): each
 * tag's function gets its words as one node, and the result is one fragment.
 */
export function tRich(key: Key, values: Record<string, RichValue>): ReactNode {
  const ready = Object.fromEntries(
    Object.entries(values).map(([name, value]) => [
      name,
      typeof value === "function"
        ? (chunks: ReactNode[]) => value(createElement(Fragment, null, ...chunks))
        : value,
    ]),
  );
  try {
    const parts = message(languageStore.get(), key).format<ReactNode>(ready);
    return Array.isArray(parts) ? createElement(Fragment, null, ...parts) : parts;
  } catch (error) {
    if (import.meta.env.MODE === "test") throw error;
    console.error(error);
    return english[key] ?? key;
  }
}

function read(name: string): string | null {
  try {
    return localStorage.getItem(name);
  } catch {
    return null;
  }
}

function write(name: string, value: string): void {
  try {
    localStorage.setItem(name, value);
  } catch {
    // Private mode or blocked storage: the next paint starts in English, then follows.
  }
}

/** This device's own language, when it has one (the pseudo language, a later setting). */
export function languageOverride(): PageLanguage | null {
  const chosen = read(OVERRIDE_KEY);
  return chosen ? known(chosen) : null;
}

/**
 * Switch the page to a language: its chunk loaded, `<html lang>` and `dir` set, every `useT`
 * drawn again. `remember` keeps it as the household's for the next paint (setup's and Choose a
 * Language's choice, the household's setting); a code Sunroom doesn't have is English.
 */
export async function setLanguage(code: string, { remember = true } = {}): Promise<void> {
  const language = known(code) ?? "en";
  if (language !== "pseudo" && !loaded.has(language)) {
    const load = chunks[`../../../lang/${language}.json`];
    if (load) loaded.set(language, await load());
  }
  if (remember && language !== "pseudo") write(HOUSEHOLD_KEY, language);
  const root = document.documentElement;
  root.lang = language === "pseudo" ? "en-XA" : language;
  root.dir = language === "pseudo" ? "ltr" : LANGUAGES[language].dir;
  languageStore.set(language);
}

/** The page's language at its start, before the first paint (main.tsx, screen.tsx). */
export async function startLanguage(): Promise<void> {
  const override = languageOverride();
  if (override) return setLanguage(override, { remember: false });
  const household = read(HOUSEHOLD_KEY);
  if (household && isLanguageCode(household)) return setLanguage(household, { remember: false });
  const browser = navigator.languages
    .map((tag) => tag.split("-")[0]?.toLowerCase() ?? "")
    .find((code) => isLanguageCode(code) && LANGUAGES[code].status === "complete");
  return setLanguage(browser ?? "en", { remember: false });
}

/** Follow the household's language as the server says it, unless this device has its own. */
export function useFollowLanguage(code: string | null | undefined): void {
  useEffect(() => {
    if (!code || languageOverride()) return;
    void setLanguage(code);
  }, [code]);
}
