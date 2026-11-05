/**
 * Meals end to end (PLAN §15 M4, UX §4 "Meals room"): Tonight on the Today panel; a dinner added
 * on the wall from a saved meal; Swap days; Copy last week with Undo; a saved meal's
 * ingredients put on Groceries; and a switch per planned meal to show it on the calendar. The server's clock reads Wednesday, October 7, 2026 in New
 * York; the Sample Family's meals come from the seed. Synthetic data only.
 */
import type { Locator, Page } from "@playwright/test";

import { expect, pairWall, seed, test } from "./fixtures";

const CSRF = { "X-Sunroom": "1" };
const WEDNESDAY_10AM = "2026-10-07T14:00:00Z";

function toast(page: Page, message: string): Locator {
  return page.locator("[data-toast]").filter({ hasText: message });
}

async function mealsRoom(page: Page): Promise<Locator> {
  await pairWall(page);
  await page.goto("/meals");
  await expect(page.getByRole("heading", { name: "Meals", level: 1 })).toBeVisible();
  // The header says no dates (ADR 0030): the rows carry them.
  await expect(page.getByRole("table").getByRole("row", { name: /Sun 4/ })).toBeVisible();
  return page.getByRole("table");
}

test.beforeEach(async ({ request }, testInfo) => {
  test.skip(testInfo.project.name !== "display-1080p", "the wall screen at 1080p");
  await request.post("/api/_test/clock", { headers: CSRF, data: { set: WEDNESDAY_10AM } });
  await seed(request);
});

test("Tonight shows today's dinner, and a saved meal fills an empty day", async ({ page }) => {
  await pairWall(page);
  await page.goto("/display");
  const tonight = page.getByRole("region", { name: "Tonight" });
  await expect(tonight).toContainText("Tacos");
  await expect(tonight).toContainText("Sam cooks");

  const grid = await mealsRoom(page);
  await grid.getByRole("button", { name: "Add dinner on Sat, Oct 10" }).click();
  const panel = page.getByRole("dialog", { name: "Add Dinner" });
  // One box (ADR 0030): what's typed is the meal's name and the search of the saved meals,
  // which sit under it as one row of chips. Opened from Saturday's cell, the day is one line.
  const what = panel.getByLabel("What’s cooking");
  await expect(panel.getByRole("textbox")).toHaveCount(1);
  await expect(panel.getByRole("button", { name: "Day: Sat, Oct 10" })).toBeVisible();
  const saved = panel.getByRole("group", { name: "Saved meals" }).getByRole("button");
  // The saved meals arrive a moment after the panel.
  await expect(panel.getByRole("button", { name: /Grilled cheese and soup/ })).toBeVisible();
  const all = await saved.count();
  expect(all).toBeGreaterThan(2);
  await what.fill("grilled");
  await expect(saved).toHaveCount(1);
  await panel.getByRole("button", { name: /Grilled cheese and soup/ }).click();
  await expect(what).toHaveValue("Grilled cheese and soup");
  await expect(panel.getByRole("button", { name: /Grilled cheese and soup/ })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  // The whole row is back, the picked meal first; changing the words lets go of it.
  await expect(saved).toHaveCount(all);
  await what.fill("Grilled cheese and soup, with pickles");
  await expect(
    panel.getByRole("group", { name: "Saved meals" }).getByRole("button", { pressed: true }),
  ).toHaveCount(0);
  // Typing a saved meal's name in full is the same as tapping it: Groceries is offered.
  await what.fill("tacos");
  await expect(panel.getByRole("switch", { name: /^Add 5 items to Groceries/ })).toBeVisible();
  await what.fill("grilled");
  await panel.getByRole("button", { name: /Grilled cheese and soup/ }).click();
  await panel.getByRole("button", { name: "Add Dinner" }).click();
  await expect(toast(page, "Added Grilled cheese and soup")).toBeVisible();
  await expect(grid.getByRole("row", { name: /Sat 10/ })).toContainText("Grilled cheese and soup");
});

test("Swap days trades two dinners, and Undo trades them back", async ({ page }) => {
  const grid = await mealsRoom(page);
  await grid.getByRole("button", { name: /Tacos/ }).click();
  const panel = page.getByRole("dialog", { name: /Tacos/ });
  await panel.getByRole("button", { name: "Swap Days" }).click();
  await panel.getByRole("button", { name: "Thu, Oct 8" }).click();
  await expect(toast(page, "Swapped Tacos and Leftovers")).toBeVisible();
  await expect(grid.getByRole("row", { name: /Thu 8/ })).toContainText("Tacos");
  await expect(grid.getByRole("row", { name: /Wed 7/ })).toContainText("Leftovers");
  await toast(page, "Swapped Tacos and Leftovers").getByRole("button", { name: "Undo" }).click();
  await expect(grid.getByRole("row", { name: /Wed 7/ })).toContainText("Tacos");
});

test("Copy last week fills next week, and Undo empties it again", async ({ page }) => {
  const grid = await mealsRoom(page);
  await page.getByRole("button", { name: "Next week" }).click();
  await expect(grid.getByRole("row", { name: /Sun 11/ })).toBeVisible();
  await page.getByRole("button", { name: "Copy Last Week" }).click();
  await expect(toast(page, "Copied 6 meals")).toBeVisible();
  await expect(grid.getByRole("row", { name: /Wed 14/ })).toContainText("Tacos");
  await toast(page, "Copied 6 meals").getByRole("button", { name: "Undo" }).click();
  await expect(grid.getByRole("row", { name: /Wed 14/ })).not.toContainText("Tacos");
});

test("a saved meal's ingredients go on Groceries", async ({ page }) => {
  const grid = await mealsRoom(page);
  await grid.getByRole("button", { name: /Tacos/ }).click();
  await page
    .getByRole("dialog", { name: /Tacos/ })
    .getByRole("button", { name: "Add Ingredients to Groceries" })
    .click();
  await expect(toast(page, "Added 5 items to Groceries")).toBeVisible();
  await page.goto("/lists");
  await page.getByRole("link", { name: /^Groceries/ }).click();
  await expect(page.getByRole("list", { name: "On Groceries" })).toContainText("Tortillas");
});

test("each meal the family plans has a switch that shows it on the calendar", async ({ page }) => {
  const set = (values: Record<string, string[]>) =>
    page.request.put("/api/plugins/meals/settings", { headers: CSRF, data: { values } });
  await pairWall(page);
  // The test server keeps plugin settings between tests: start from the defaults, and end there.
  expect((await set({ slots: ["dinner"], calendar_slots: [] })).ok()).toBe(true);
  try {
    await page.goto("/settings/meals");
    const switches = page.getByRole("switch", { name: /on the calendar$/ });
    await expect(switches).toHaveCount(1);
    await page
      .getByRole("group", { name: "Which meals" })
      .getByRole("button", { name: "Breakfast" })
      .click();
    await expect(switches).toHaveCount(2);
    await expect(
      page.getByRole("switch", { name: "Show breakfast on the calendar" }),
    ).not.toBeChecked();
    const dinner = page.getByRole("switch", { name: "Show dinner on the calendar" });
    await dinner.click();
    await expect(dinner).toBeChecked();
    // Tonight's dinner is on the board now; breakfast, whose switch is off, isn't.
    await page.goto("/display");
    const tacos = page
      .getByRole("region", { name: "This Week" })
      .getByRole("button", { name: /Tacos, / });
    await expect(tacos).toHaveAttribute("data-overlay", "meals");
  } finally {
    await set({ slots: ["dinner"], calendar_slots: [] });
  }
});
