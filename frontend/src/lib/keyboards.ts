/**
 * The wall keyboard's layouts (ui/Keyboard, UX §1), one per language's `keyboard` in the registry
 * (lang/languages.json, ADR 0043): its rows of letters, its numbers-and-symbols page, and the
 * accents a held letter offers. Data, not words: a key's name is the character it types.
 */
import { LANGUAGES, type PageLanguage } from "./lang";

export interface KeyboardKeys {
  /** The letters page, top row first; the shift and delete keys go around the last row. */
  letters: readonly string[];
  /** The page behind 123; delete goes after the last row. */
  symbols: readonly string[];
  /** What holding a letter offers. */
  accents: Readonly<Record<string, string>>;
}

const ACCENTS: Readonly<Record<string, string>> = {
  a: "àáâäãå",
  e: "èéêë",
  i: "ìíîï",
  o: "òóôöõø",
  u: "ùúûü",
  n: "ñ",
  c: "ç",
  s: "ß",
  y: "ÿ",
};

const QWERTY: KeyboardKeys = {
  letters: ["qwertyuiop", "asdfghjkl", "zxcvbnm"],
  symbols: ["1234567890", '-/:;()$&@"', ".,?!'#%*+="],
  accents: ACCENTS,
};

/** Spanish: ñ after l, and ¿ ¡ before ? and ! (in place of * and =, so the row still fits). */
const QWERTY_ES: KeyboardKeys = {
  letters: ["qwertyuiop", "asdfghjklñ", "zxcvbnm"],
  symbols: ["1234567890", '-/:;()$&@"', ".,¿?¡!'#%+"],
  accents: ACCENTS,
};

export const KEYBOARDS: Readonly<Record<string, KeyboardKeys>> = {
  qwerty: QWERTY,
  "qwerty-es": QWERTY_ES,
};

/** The page's language's keyboard; English's for the pseudo language, or a layout not here. */
export function keyboardFor(language: PageLanguage): KeyboardKeys {
  const name = language === "pseudo" ? LANGUAGES.en.keyboard : LANGUAGES[language].keyboard;
  return KEYBOARDS[name] ?? QWERTY;
}
