/**
 * House rules that are easy to break by accident (UX §1, §7, ADR 0007). Reads every source file
 * as text.
 */
import ts from "typescript";
import { describe, expect, it } from "vitest";

const sources = import.meta.glob<string>(
  ["../**/*.{ts,tsx}", "!../**/*.test.{ts,tsx}", "!../api/schema.d.ts"],
  { query: "?raw", import: "default", eager: true },
);

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
function literalTitles(): string[] {
  const titles: string[] = [];
  for (const [path, text] of Object.entries(sources)) {
    const found = [
      ...text.matchAll(/<[A-Z]\w*[^>]*\stitle="([^"]+)"/g),
      ...text.matchAll(/<h[1-3]\b[^>]*>([^<{]+)</g),
      ...(path === "../features/settings/pages.ts" || /^\.\.\/features\/\w+\/index\.ts$/.test(path)
        ? text.matchAll(/\btitle: "([^"]+)"/g)
        : []),
    ];
    for (const match of found) titles.push((match[1] ?? "").trim());
  }
  return titles;
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

  it("writes titles, headings and navigation in Title Case (UX §2, ADR 0028)", () => {
    const titles = literalTitles();
    expect(titles.length).toBeGreaterThan(60);
    expect(titles.filter((title) => !isTitleCase(title))).toEqual([]);
  });

  it("finds every button's words, however they're written", () => {
    const labels = buttonLabels().map(({ label }) => label);
    expect(labels.length).toBeGreaterThan(150);
    // Each way a conditional comes out, a template's value as "#", a toast's action.
    for (const label of ["Signing In…", "Add # Items", "Undo", "Take It Back"]) {
      expect(labels, label).toContain(label);
    }
  });

  it("writes every button of two to five words in Title Case (UX §2, ADR 0032)", () => {
    const wrong = buttonLabels().filter(({ label }) => {
      const count = label.split(" ").length;
      return count >= 2 && count <= 5 && !isTitleCase(label);
    });
    expect(wrong.map(({ where, label }) => `${where} ${label}`)).toEqual([]);
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
