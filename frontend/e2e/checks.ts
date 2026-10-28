/**
 * The accessibility checks every screen gets (PLAN §14.6, UX §1 and §10), shared by the specs:
 * no serious or critical axe findings, tap targets of 56 px on the wall screen and 44 px on a
 * phone with 8 px between neighbours on a line, and no typing field under 16 px.
 */
import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";

import { expect, settled } from "./fixtures";

const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];

/** iPhones zoom into any typing field under 16 px: none may be smaller, anywhere. */
async function typingFieldsAtLeast16px(page: Page, where: string): Promise<void> {
  const small = await page.evaluate(() =>
    Array.from(
      document.querySelectorAll(
        "input:not([type=checkbox]):not([type=radio]):not([type=file]):not([type=hidden]), select, textarea",
      ),
    )
      .filter((field) => {
        const box = field.getBoundingClientRect();
        return box.width > 1 && box.height > 1 && parseFloat(getComputedStyle(field).fontSize) < 16;
      })
      .map((field) => field.outerHTML.slice(0, 120)),
  );
  expect(small, `typing fields under 16 px on ${where}`).toEqual([]);
}

/**
 * Tap targets (UX §1): 56 px on the wall screen (and a laptop, which gets its shell), 44 px on a
 * phone; 8 px between neighbours on the same line. Links inside a sentence don't count, nor do
 * the options of one segmented control or one tab bar (marked data-segmented), which read as a
 * single control with large cells. A control covered where it would be tapped (a chip under the
 * open side panel, a row scrolled under the tab bar) still has to be big enough, but it isn't
 * anyone's neighbour until it's uncovered; nor is the board across the side panel's edge, whose
 * 24 px padding keeps its own controls clear of the board. A control whose end facing another is
 * under something else (a chip's end under the Hours zoom's panel) is measured from what covers
 * it: that end takes no tap. While a menu is open only the menu and its button count: the rest
 * of the page takes no taps until it closes.
 */
export async function tapTargets(page: Page, where: string): Promise<void> {
  const problems = await page.evaluate(() => {
    const display = document.querySelector("[data-shell=display]") !== null;
    const least = display ? 56 : 44;
    // With a sheet or dialog open, the page behind it can't be tapped. Nor with a menu open
    // (the header's View and Filter): a tap anywhere else only closes it (ui/Menu).
    const scope =
      document.querySelector("dialog:modal") ??
      document.querySelector("[role=menu]")?.parentElement ??
      document;
    const controls = Array.from(
      scope.querySelectorAll("button, a[href], select, summary, [role=checkbox]"),
    ).filter((control) => {
      if (control.closest("[inert], [aria-hidden='true']")) return false;
      const style = getComputedStyle(control);
      const box = control.getBoundingClientRect();
      if (style.visibility === "hidden" || box.width <= 1 || box.height <= 1) return false;
      if (control.tagName === "A" && style.display === "inline") return false;
      return true;
    });
    const name = (control: Element) => {
      const box = control.getBoundingClientRect();
      const text = (control.getAttribute("aria-label") ?? control.textContent).trim().slice(0, 40);
      return `${control.tagName.toLowerCase()} "${text}" ${String(Math.round(box.width))}x${String(Math.round(box.height))}`;
    };
    // Covered at its middle, or along its top or bottom edge (a row half under the tab bar).
    const covered = (control: Element) => {
      const box = control.getBoundingClientRect();
      const x = box.left + box.width / 2;
      return [box.top + 2, box.top + box.height / 2, box.bottom - 2].some((y) => {
        if (x < 0 || y < 0 || x >= window.innerWidth || y >= window.innerHeight) return false;
        const hit = document.elementFromPoint(x, y);
        return hit !== null && !control.contains(hit) && !hit.contains(control);
      });
    };
    // The end of `control` that faces `other`, a few pixels in, is under something that is
    // neither of them: a third thing covers it (the other one overlapping still counts).
    const endCovered = (control: Element, other: Element, near: DOMRect, far: DOMRect) => {
      const x = near.left < far.left ? near.right - 3 : near.left + 3;
      const y = (Math.max(near.top, far.top) + Math.min(near.bottom, far.bottom)) / 2;
      const hit = document.elementFromPoint(x, y);
      return hit !== null && !control.contains(hit) && !other.contains(hit);
    };
    const found: string[] = [];
    for (const control of controls) {
      const box = control.getBoundingClientRect();
      if (box.width < least - 0.5 || box.height < least - 0.5) {
        found.push(`under ${String(least)} px: ${name(control)}`);
      }
    }
    const open = controls.filter((control) => !covered(control));
    for (const [index, a] of open.entries()) {
      const one = a.getBoundingClientRect();
      for (const b of open.slice(index + 1)) {
        if (a.contains(b) || b.contains(a)) continue;
        const segmented = a.closest("[data-segmented]");
        if (segmented && segmented === b.closest("[data-segmented]")) continue;
        if (a.closest("[data-panel]") !== b.closest("[data-panel]")) continue;
        const two = b.getBoundingClientRect();
        const shared = Math.min(one.bottom, two.bottom) - Math.max(one.top, two.top);
        if (shared < Math.min(one.height, two.height) / 2) continue; // not on one line
        const gap = Math.max(two.left - one.right, one.left - two.right);
        // Chips stacked in one Hours column: the later one sits on the earlier one's tail, the
        // way a Month cell holds its day; the zoom is what makes a short one bigger (UX §1).
        const dense = a.closest("[data-dense]");
        if (gap < 0 && dense && dense === b.closest("[data-dense]")) continue;
        if (gap < 7.5 && (endCovered(a, b, one, two) || endCovered(b, a, two, one))) continue;
        if (gap < 7.5) found.push(`${String(Math.round(gap))} px apart: ${name(a)} and ${name(b)}`);
      }
    }
    return found;
  });
  expect(problems, `tap targets on ${where}`).toEqual([]);
}

export async function check(page: Page, where: string): Promise<void> {
  await settled(page);
  await typingFieldsAtLeast16px(page, where);
  await tapTargets(page, where);
  const results = await new AxeBuilder({ page }).withTags(TAGS).analyze();
  // A11Y_ALL=1 fails on every finding, for a full review; normally only serious and critical.
  const blocking = results.violations.filter(
    (violation) =>
      process.env.A11Y_ALL === "1" ||
      violation.impact === "serious" ||
      violation.impact === "critical",
  );
  for (const violation of results.violations) {
    if (blocking.includes(violation)) continue;
    console.log(`${where}: ${violation.impact ?? "?"} ${violation.id}: ${violation.help}`);
  }
  expect(
    blocking.map(
      (violation) =>
        `${violation.id} (${violation.impact ?? "?"}): ${violation.help} → ${violation.nodes
          .map((node) => node.target.join(" "))
          .join(", ")}`,
    ),
    `axe on ${where}`,
  ).toEqual([]);
}
