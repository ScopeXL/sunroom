import { act, render, renderHook, screen } from "@testing-library/react";
import { createElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  completeLanguages,
  formatNumber,
  getLanguage,
  HOUSEHOLD_KEY,
  intlLocale,
  isKey,
  OVERRIDE_KEY,
  setLanguage,
  startLanguage,
  t,
  tRich,
  useT,
  wordList,
  type Key,
} from "./lang";

// Three messages of the shapes the app's words take, beside the real English file.
vi.mock("../../../lang/en.json", async (importOriginal) => {
  const actual = await importOriginal<{ default: Record<string, string> }>();
  return {
    default: {
      ...actual.default,
      "test.days": "{n, plural, one {# day} other {# days}}",
      "test.hello": "Hello, {name}!",
      "test.open": "Or open <b>{place}</b> on any device.",
    },
  };
});

const HELLO = "test.hello" as Key;
const DAYS = "test.days" as Key;
const OPEN = "test.open" as Key;

function browserLanguages(languages: string[]) {
  vi.spyOn(navigator, "languages", "get").mockReturnValue(languages);
}

beforeEach(async () => {
  localStorage.clear();
  await setLanguage("en", { remember: false });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("t", () => {
  it("formats English's messages, with placeholders and plurals", () => {
    expect(t("app.action.done")).toBe("Done");
    expect(t(HELLO, { name: "Mia" })).toBe("Hello, Mia!");
    expect(t(DAYS, { n: 1 })).toBe("1 day");
    expect(t(DAYS, { n: 3 })).toBe("3 days");
  });

  it("stops a test at a value that wasn't given", () => {
    expect(() => t(HELLO)).toThrow();
  });

  it("falls back to English for a key the language lacks", async () => {
    await setLanguage("es");
    expect(t("app.action.done")).toBe("Listo");
    expect(t("app.action.back")).toBe("Back");
    expect(t(DAYS, { n: 2 })).toBe("2 days");
  });

  it("knows the keys English has, for what the server names", () => {
    expect(isKey("app.action.done")).toBe(true);
    expect(isKey("api.nothing.here")).toBe(false);
  });

  it("draws a message's tagged part as the caller asks", () => {
    render(
      createElement(
        "p",
        null,
        tRich(OPEN, {
          place: "sunroom.local",
          b: (words) => createElement("strong", null, words),
        }),
      ),
    );
    expect(screen.getByText("sunroom.local").tagName).toBe("STRONG");
    expect(document.body.textContent).toBe("Or open sunroom.local on any device.");
  });
});

describe("the page's language", () => {
  it("sets <html lang> and dir, and remembers the household's for the next paint", async () => {
    await setLanguage("es");
    expect(document.documentElement.lang).toBe("es");
    expect(document.documentElement.dir).toBe("ltr");
    expect(localStorage.getItem(HOUSEHOLD_KEY)).toBe("es");
    await setLanguage("pseudo");
    expect(document.documentElement.lang).toBe("en-XA");
    expect(localStorage.getItem(HOUSEHOLD_KEY)).toBe("es");
    await setLanguage("xx");
    expect(getLanguage()).toBe("en");
  });

  it("starts in this device's override, then the household's, the browser's, English", async () => {
    browserLanguages(["es-MX", "en-GB"]);
    localStorage.setItem(OVERRIDE_KEY, "pseudo");
    localStorage.setItem(HOUSEHOLD_KEY, "es");
    await startLanguage();
    expect(getLanguage()).toBe("pseudo");
    localStorage.removeItem(OVERRIDE_KEY);
    await startLanguage();
    expect(getLanguage()).toBe("es");
    localStorage.removeItem(HOUSEHOLD_KEY);
    // Spanish is a preview: the browser's next complete language is English.
    await startLanguage();
    expect(getLanguage()).toBe("en");
    browserLanguages(["fr-CA"]);
    await startLanguage();
    expect(getLanguage()).toBe("en");
    expect(localStorage.getItem(HOUSEHOLD_KEY)).toBeNull();
  });

  it("offers only the complete languages, by their own names", () => {
    expect(completeLanguages()).toEqual([{ value: "en", label: "English" }]);
  });

  it("draws a component again when the language changes", async () => {
    const { result } = renderHook(() => useT());
    expect(result.current("app.action.done")).toBe("Done");
    await act(() => setLanguage("es"));
    expect(result.current("app.action.done")).toBe("Listo");
  });
});

describe("dates, numbers and word lists (T7)", () => {
  it("writes numbers in the page's language, with Latin digits", async () => {
    expect(intlLocale()).toBe("en-US-u-nu-latn");
    expect(formatNumber(1234.5)).toBe("1,234.5");
    await setLanguage("es");
    expect(intlLocale()).toBe("es-ES-u-nu-latn");
    expect(formatNumber(1234.5)).toBe("1234,5");
    expect(formatNumber(12345)).toBe("12.345");
  });

  it("reads a grammar's word list from the language's file, English where it has none", async () => {
    expect(wordList("quickadd.words.every")).toEqual(["every", "each"]);
    expect(wordList("quickadd.words.when_after")).toContain("from now");
    await setLanguage("es");
    expect(wordList("quickadd.words.today")).toEqual(["hoy", "esta noche"]);
    expect(wordList("quickadd.words.every")).toEqual(["every", "each"]);
    // The pseudo language types English, not its own accented words.
    await setLanguage("pseudo");
    expect(wordList("quickadd.words.today")).toEqual(["today", "tonight"]);
  });
});

describe("the pseudo language", () => {
  it("accents every word and pads it, keeping placeholders, # and plural keywords", async () => {
    await setLanguage("pseudo");
    const hello = t(HELLO, { name: "Mia" });
    expect(hello).toMatch(/^\[Ĥéļļö, Mia!~+\]$/);
    expect(hello.length).toBeGreaterThan("Hello, Mia!".length * 1.3);
    expect(t(DAYS, { n: 1 })).toMatch(/^\[1 ðáý~+\]$/);
    expect(t(DAYS, { n: 4 })).toMatch(/^\[4 ðáýš~+\]$/);
  });
});
