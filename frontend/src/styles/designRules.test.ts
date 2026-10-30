/**
 * House rules that are easy to break by accident (UX §1, §2, §7, ADR 0007, 0043). Reads every
 * source file as text, and the English words in lang/en.json.
 */
import { parse, TYPE, type MessageFormatElement } from "@formatjs/icu-messageformat-parser";
import ts from "typescript";
import { describe, expect, it } from "vitest";

import en from "../../../lang/en.json";
import unswept from "../../scripts/unswept.json";

const sources = import.meta.glob<string>(
  ["../**/*.{ts,tsx}", "!../**/*.test.{ts,tsx}", "!../api/schema.d.ts"],
  { query: "?raw", import: "default", eager: true },
);

/** A source swept into lang/ (ADR 0043): out of scripts/unswept.json's ratchet. */
function swept(path: string): boolean {
  const file = path.replace(/^\.\.\//, "src/");
  return !unswept.some((entry) => (entry.endsWith("/") ? file.startsWith(entry) : file === entry));
}

/** A message's words each way it can come out: a placeholder as "#" (a word with no letters, as
 * a name), and every branch of a plural or a select. */
function messageWords(elements: MessageFormatElement[]): string[] {
  let words = [""];
  for (const element of elements) {
    let parts: string[];
    if (element.type === TYPE.literal) parts = [element.value];
    else if (element.type === TYPE.plural || element.type === TYPE.select) {
      parts = Object.values(element.options).flatMap((option) => messageWords(option.value));
    } else if (element.type === TYPE.tag) parts = messageWords(element.children);
    else parts = ["#"];
    words = words.flatMap((word) => parts.map((part) => word + part));
  }
  return words;
}

/** English's words for every key of a kind, each way: its last segment (`calendar.add.title`,
 * `settings.backup.run.action`), or the one before it for a group (`app.action.done`). */
function englishWords(kind: string): { key: string; words: string }[] {
  return Object.entries(en)
    .filter(([key]) => key.endsWith(`.${kind}`) || key.split(".").at(-2) === kind)
    .flatMap(([key, message]) =>
      messageWords(parse(message)).map((words) => ({ key, words: words.trim() })),
    );
}

function offenders(pattern: RegExp, except: string[] = []): string[] {
  return Object.entries(sources)
    .filter(([path, text]) => !except.includes(path) && pattern.test(text))
    .map(([path]) => path);
}

/** The words a title keeps lowercase in its middle (UX §2). */
const SMALL_WORDS = new Set([
  "a",
  "an",
  "the",
  "and",
  "or",
  "but",
  "of",
  "to",
  "in",
  "on",
  "at",
  "by",
  "for",
  "with",
  "from",
]);

/** Verbs whose "in" or "on" belongs to the verb, and may be capitalized: "Sign In Again". */
const PHRASAL = new Set(["sign", "signing", "log", "check", "turn"]);

/**
 * Title Case as UX §2 writes it: every word starts with a capital except the small words, which
 * stay lowercase unless they come first, last or after a colon. Words with no letters ("&", "·")
 * pass, and so does a name with a capital inside ("iCloud"). A verb's own "in" may be
 * capitalized ("Sign In Again"), or not, as Google writes Sign in with Google.
 */
function isTitleCase(title: string): boolean {
  const words = title.split(/\s+/).filter(Boolean);
  return words.every((raw, index) => {
    const word = raw.replace(/^[^\p{L}\p{N}]+|[^\p{L}\p{N}]+$/gu, "");
    const letter = /\p{L}/u.exec(word)?.[0];
    if (!letter) return true;
    const before = words[index - 1] ?? "";
    const edge = index === 0 || index === words.length - 1 || before.endsWith(":");
    if (!edge && SMALL_WORDS.has(word.toLowerCase())) {
      return word === word.toLowerCase() || PHRASAL.has(before.toLowerCase());
    }
    return letter !== letter.toLowerCase() || /\p{Lu}/u.test(word);
  });
}

/**
 * What an expression can show, each way it can come out: a string's words, a template with each
 * `${…}` as "#" (a word with no letters, such as a name), both sides of `a ? "x" : "y"` and of
 * `??` and `||`. Anything else is a value, "#".
 */
function alternatives(node: ts.Node): string[] {
  if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) return [node.text];
  if (ts.isTemplateExpression(node)) {
    return [node.head.text + node.templateSpans.map((span) => `#${span.literal.text}`).join("")];
  }
  if (ts.isParenthesizedExpression(node)) return alternatives(node.expression);
  if (ts.isJsxElement(node) || ts.isJsxFragment(node)) return childWords(node.children);
  if (ts.isJsxSelfClosingElement(node)) return [""];
  if (ts.isConditionalExpression(node)) {
    return [...alternatives(node.whenTrue), ...alternatives(node.whenFalse)];
  }
  if (
    ts.isBinaryExpression(node) &&
    [ts.SyntaxKind.QuestionQuestionToken, ts.SyntaxKind.BarBarToken].includes(
      node.operatorToken.kind,
    )
  ) {
    return [...alternatives(node.left), ...alternatives(node.right)];
  }
  return ["#"];
}

/** The words a run of JSX children shows, each way they can come out (icons show none). */
function childWords(children: readonly ts.JsxChild[]): string[] {
  let labels = [""];
  for (const child of children) {
    let parts: string[];
    if (ts.isJsxText(child)) parts = [child.text];
    else if (ts.isJsxExpression(child))
      parts = child.expression ? alternatives(child.expression) : [""];
    else if (ts.isJsxElement(child) || ts.isJsxFragment(child)) parts = childWords(child.children);
    else parts = [""];
    labels = labels.flatMap((label) => parts.map((part) => label + part));
  }
  return labels;
}

/** Elements whose words are a button's, and props that hand a button its words. */
const BUTTONS = new Set(["Button", "HeaderLink"]);
const BUTTON_PROPS = new Set(["action", "submit", "firstSave"]);

/**
 * Every button's words the sources write as literals (UX §2, ADR 0032): a `<Button>`'s or a
 * header link's children, a component's `action` or `submit` prop, and a toast's action (an
 * object with `label` and `onAction`), with where each one is.
 */
let labelsFound: { where: string; label: string }[] | undefined;
function buttonLabels(): { where: string; label: string }[] {
  if (labelsFound) return labelsFound;
  const found: { where: string; label: string }[] = [];
  for (const [path, text] of Object.entries(sources)) {
    const file = ts.createSourceFile(path, text, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
    const add = (node: ts.Node, labels: string[]) => {
      const line = file.getLineAndCharacterOfPosition(node.getStart(file)).line + 1;
      for (const raw of labels) {
        const label = raw.replace(/\s+/g, " ").trim();
        if (label && label !== "#") found.push({ where: `${path}:${String(line)}`, label });
      }
    };
    const visit = (node: ts.Node): void => {
      if (ts.isJsxElement(node) && BUTTONS.has(node.openingElement.tagName.getText(file))) {
        add(node, childWords(node.children));
      }
      if (ts.isJsxAttribute(node) && BUTTON_PROPS.has(node.name.getText(file))) {
        const value = node.initializer;
        if (value && ts.isStringLiteral(value)) add(node, [value.text]);
        else if (value && ts.isJsxExpression(value) && value.expression) {
          add(node, alternatives(value.expression));
        }
      }
      if (ts.isObjectLiteralExpression(node)) {
        const names = node.properties.map((property) => property.name?.getText(file));
        const label = node.properties.find(
          (property): property is ts.PropertyAssignment =>
            ts.isPropertyAssignment(property) && property.name.getText(file) === "label",
        );
        if (label && names.includes("onAction")) add(label, alternatives(label.initializer));
      }
      ts.forEachChild(node, visit);
    };
    visit(file);
  }
  labelsFound = found;
  return found;
}

/** Every title the sources write as a literal: `title="…"` on a component, an h1 to h3's own
 * text, and the Settings pages' names (core's and each plugin's). */
function literalTitles(): { where: string; title: string }[] {
  const titles: { where: string; title: string }[] = [];
  for (const [path, text] of Object.entries(sources)) {
    const found = [
      ...text.matchAll(/<[A-Z]\w*[^>]*\stitle="([^"]+)"/g),
      ...text.matchAll(/<h[1-3]\b[^>]*>([^<{]+)</g),
      ...(path === "../features/settings/pages.ts" || /^\.\.\/features\/\w+\/index\.ts$/.test(path)
        ? text.matchAll(/\btitle: "([^"]+)"/g)
        : []),
    ];
    for (const match of found) titles.push({ where: path, title: (match[1] ?? "").trim() });
  }
  return titles;
}

/** A toast's words written as a literal: `showToast("Saved")`, or a template's words. */
function literalToasts(): { where: string; words: string }[] {
  const found: { where: string; words: string }[] = [];
  for (const [path, text] of Object.entries(sources)) {
    for (const match of text.matchAll(/\bshowToast\(\s*(["'`])((?:(?!\1)[^\\]|\\.)*?)\1/g)) {
      if (/\p{L}/u.test(match[2] ?? "")) found.push({ where: path, words: match[2] ?? "" });
    }
  }
  return found;
}

describe("design rules", () => {
  it("reads the sources as text", () => {
    expect(Object.keys(sources).length).toBeGreaterThan(40);
    expect(offenders(/export function Button\(/)).toEqual(["../ui/Button.tsx"]);
  });

  it("paints with tokens only: no raw hex colors in components (UX §7)", () => {
    expect(offenders(/#[0-9a-fA-F]{3,8}\b(?![\w-])/, ["../lib/theme.ts"])).toEqual([]);
  });

  it("uses no title= tooltips on elements: they never appear on touch (PLAN §4)", () => {
    expect(offenders(/<[a-z][a-z0-9]*\b[^>]*\stitle=/)).toEqual([]);
  });

  it("injects no styles at runtime, so the strict CSP holds (ADR 0007)", () => {
    expect(
      offenders(
        /createElement\(\s*["']style["']|insertRule\(|adoptedStyleSheets|new CSSStyleSheet/,
      ),
    ).toEqual([]);
    expect(offenders(/dangerouslySetInnerHTML/)).toEqual([]);
  });

  it("never uses view transitions, which add styles without the nonce (ADR 0007)", () => {
    expect(offenders(/import[^;]*\b(AnimateView|animateView)\b|startViewTransition\(/)).toEqual([]);
  });

  it("keeps every motion component under MotionConfig with the nonce", () => {
    const users = offenders(/from "motion\/react"/);
    expect(users).toContain("../lib/motion.tsx");
    expect(offenders(/<MotionConfig/)).toEqual(["../lib/motion.tsx"]);
    for (const shell of ["../shell/DisplayShell.tsx", "../shell/PhoneShell.tsx"]) {
      expect(sources[shell], shell).toMatch(/<MotionProvider/);
    }
  });

  it("knows Title Case when it sees it (UX §2)", () => {
    for (const title of [
      "Who's Using This",
      "Take Your Data with You",
      "Google: The Secret Address",
      "Calendars & Accounts",
      "Tasks · This Week",
      "All Done!",
      "Set a Parent PIN?",
      "Connect iCloud",
      "In This Version",
      "Sign In Again",
      "Sign in with Google",
      "Add # Items",
      "Back to #",
    ]) {
      expect(isTitleCase(title), title).toBe(true);
    }
    for (const title of [
      "Take your data with you",
      "Take Your Data With You",
      "Calendars & accounts",
      "Who lives here?",
      "Erase everything…",
      "Yes, it's done",
      "Show In the Room",
    ]) {
      expect(isTitleCase(title), title).toBe(false);
    }
  });

  it("reads English's words each way a message can come out", () => {
    expect(messageWords(parse("Add {n} Items"))).toEqual(["Add # Items"]);
    expect(messageWords(parse("{n, plural, one {Add # Item} other {Add # Items}}"))).toEqual([
      "Add # Item",
      "Add # Items",
    ]);
    expect(englishWords("title").length).toBeGreaterThan(0);
    expect(englishWords("action").length).toBeGreaterThan(0);
  });

  it("writes titles, headings and navigation in Title Case (UX §2, ADR 0028)", () => {
    const titles = [
      ...literalTitles().map(({ title }) => title),
      ...englishWords("title").map(({ words }) => words),
    ];
    expect(titles.length).toBeGreaterThan(60);
    expect(titles.filter((title) => !isTitleCase(title))).toEqual([]);
  });

  it("finds every button's words, however they're written", () => {
    const labels = [
      ...buttonLabels().map(({ label }) => label),
      ...englishWords("action").map(({ words }) => words),
    ];
    expect(labels.length).toBeGreaterThan(150);
    // Each way a conditional comes out, a template's value as "#", a toast's action.
    for (const label of ["Signing In…", "Add # Items", "Undo", "Take It Back"]) {
      expect(labels, label).toContain(label);
    }
  });

  it("writes every button of two to five words in Title Case (UX §2, ADR 0032)", () => {
    const wrong = [
      ...buttonLabels(),
      ...englishWords("action").map(({ key, words }) => ({ where: key, label: words })),
    ].filter(({ label }) => {
      const count = label.split(" ").length;
      return count >= 2 && count <= 5 && !isTitleCase(label);
    });
    expect(wrong.map(({ where, label }) => `${where} ${label}`)).toEqual([]);
  });

  it("leaves no words in a swept folder's code: buttons, titles and toasts name keys (ADR 0043)", () => {
    const left = [
      ...buttonLabels().map(({ where, label }) => `${where} ${label}`),
      ...literalTitles().map(({ where, title }) => `${where} ${title}`),
      ...literalToasts().map(({ where, words }) => `${where} ${words}`),
    ].filter((found) => swept(found.split(":")[0]?.split(" ")[0] ?? ""));
    expect(left).toEqual([]);
  });

  it("writes no all-caps labels (UX §1 What never appears)", () => {
    expect(
      offenders(/\buppercase\b/, [
        "../features/auth/SignInScreen.tsx",
        "../features/phone/PairCode.tsx",
        "../features/onboarding/SetupWizard.tsx",
      ]),
    ).toEqual([]);
  });
});
