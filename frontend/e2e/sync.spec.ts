/**
 * Synced calendars end to end (PLAN §15 M2), against the test server's scripted calendar
 * server: an account's calendar mapped to a person shows on the wall in that person's color; a
 * change made on the wall goes out to the server; a refused password shows Needs Attention
 * and the events stay. Adding an account from any device (ADR 0028): a computer gets the steps in a
 * sheet, and Google's way back opens a new account's calendars; the wall types a password on
 * its own keyboard and hands Google's file and page to a phone. An account opens from its row
 * (ADR 0029): Sync, whose a calendar is and its color, Show on the screen, Remove account. An
 * account's calendar can be the Default calendar, where Add starts, and the household's last
 * calendar of its own stays (ADR 0032). The server's clock reads Wednesday, October 7, 2026,
 * 10:00 AM in New York. Synthetic data only.
 */
import type { APIRequestContext, Locator, Page } from "@playwright/test";

import {
  expect,
  pairWall,
  PASSWORD,
  pickView,
  scriptedAccount,
  seed,
  signInPhone,
  test,
  wall,
} from "./fixtures";

const CSRF = { "X-Sunroom": "1" };
const WEDNESDAY_10AM = "2026-10-07T14:00:00Z";

/** A scripted account with a School calendar holding Thursday's field trip, not mapped yet. */
async function accountWithFieldTrip(request: APIRequestContext): Promise<string> {
  const created = await request.post("/api/calendar-sync/_test/fake", { headers: CSRF });
  expect(created.status()).toBe(201);
  const { id } = (await created.json()) as { id: string };
  const scripted = await request.put(`/api/calendar-sync/_test/fake/${id}`, {
    headers: CSRF,
    data: {
      calendars: [["school", "School", false]],
      events: [
        {
          calendar: "school",
          uid: "field-trip@test",
          title: "Field trip",
          start: "2026-10-08T13:00:00Z",
          end: "2026-10-08T17:00:00Z",
        },
      ],
    },
  });
  expect(scripted.status()).toBe(200);
  return id;
}

async function syncNow(request: APIRequestContext, account: string): Promise<void> {
  const synced = await request.post(`/api/calendar-sync/accounts/${account}/sync`, {
    headers: CSRF,
  });
  expect([200, 409, 429]).toContain(synced.status());
}

async function mapToMia(request: APIRequestContext, account: string): Promise<void> {
  await mapTo(request, account, "Mia");
}

/** Map the account's one calendar, making it the named person's. */
async function mapTo(request: APIRequestContext, account: string, name: string): Promise<void> {
  const members = (await (await request.get("/api/members")).json()) as {
    id: string;
    name: string;
  }[];
  const owner = members.find((m) => m.name === name);
  let calendars: { id: string }[] = [];
  await expect(async () => {
    const accounts = (await (await request.get("/api/calendar-sync/accounts")).json()) as {
      id: string;
      calendars: { id: string }[];
    }[];
    calendars = accounts.find((a) => a.id === account)?.calendars ?? [];
    expect(calendars.length).toBe(1);
  }).toPass({ timeout: 10_000 });
  const mapped = await request.put(
    `/api/calendar-sync/accounts/${account}/calendars/${calendars[0]?.id ?? ""}`,
    { headers: CSRF, data: { mapped: true, owner_member_id: owner?.id } },
  );
  expect(mapped.status()).toBe(200);
}

function toast(page: Page, message: string): Locator {
  return page.locator("[data-toast]").filter({ hasText: message });
}

async function board(page: Page) {
  await pairWall(page);
  await page.goto("/display");
  const week = page.getByRole("region", { name: "This Week" });
  await expect(week).toBeVisible();
  return week;
}

test.beforeEach(async ({ request }, testInfo) => {
  test.skip(
    testInfo.project.name !== "display-1080p" && testInfo.project.name !== "desktop",
    "the wall screen at 1080p, and a computer",
  );
  const moved = await request.post("/api/_test/clock", {
    headers: CSRF,
    data: { set: WEDNESDAY_10AM },
  });
  expect(moved.status()).toBe(204);
  await seed(request);
  // A parent's phone, signed in with the household password (its cookie stays on `request`).
  const signedIn = await request.post("/api/auth/login", {
    headers: CSRF,
    data: { password: PASSWORD },
  });
  expect(signedIn.ok()).toBe(true);
});

test("an account's calendar shows on the wall in its person's color, and changes go back", async ({
  page,
  request,
}, testInfo) => {
  test.skip(testInfo.project.name !== "display-1080p", "the wall screen");
  const account = await accountWithFieldTrip(request);
  await syncNow(request, account);
  await mapToMia(request, account);
  const week = await board(page);
  const trip = week.getByRole("button", { name: /^Field trip, 9:00 AM to 1:00 PM, Mia, Thursday/ });
  await expect(trip).toBeVisible({ timeout: 15_000 });
  // On the Hours grid (a new household's layout, ADR 0042) the block inside wears the color.
  await expect(trip.locator("[data-person]").first()).toHaveAttribute("data-person", "rose");

  // Its sheet says where it comes from.
  await trip.click();
  const sheet = page.getByRole("dialog", { name: "Field trip" });
  await expect(sheet).toContainText("School");
  await sheet.getByRole("button", { name: "Change" }).click();
  const editor = page.getByRole("dialog", { name: "Change" });
  await editor.getByLabel("Title").fill("Field trip to the farm");
  await editor.getByRole("button", { name: "Save Changes" }).click();
  await expect(week.getByRole("button", { name: /^Field trip to the farm, / })).toBeVisible();

  // The server gets it within the next push (every minute, or a few seconds after an edit).
  await expect(async () => {
    const accounts = (await (await request.get("/api/calendar-sync/accounts")).json()) as {
      id: string;
      last_error: string | null;
    }[];
    expect(accounts.find((a) => a.id === account)?.last_error).toBeNull();
    const event = (await (
      await request.get("/api/calendar/occurrences", {
        params: { from: "2026-10-04", to: "2026-10-11" },
      })
    ).json()) as { occurrences: { title: string; pending: boolean }[] };
    expect(event.occurrences.find((o) => o.title === "Field trip to the farm")?.pending).toBe(
      false,
    );
  }).toPass({ timeout: 20_000 });
});

test("a title names its people, on top of the calendar's person, in all their colors", async ({
  page,
  request,
}, testInfo) => {
  test.skip(testInfo.project.name !== "display-1080p", "the wall screen");
  const created = await request.post("/api/calendar-sync/_test/fake", { headers: CSRF });
  const { id: account } = (await created.json()) as { id: string };
  const scripted = await request.put(`/api/calendar-sync/_test/fake/${account}`, {
    headers: CSRF,
    data: {
      calendars: [["school", "School", false]],
      events: [
        {
          calendar: "school",
          uid: "swim@test",
          title: "Mia & Leo's swim",
          start: "2026-10-07T20:00:00Z",
          end: "2026-10-07T21:00:00Z",
        },
      ],
    },
  });
  expect(scripted.status()).toBe(200);
  await syncNow(request, account);
  // Ana's calendar: the swim is hers, and Mia's and Leo's, whom its title names (ADR 0034).
  await mapTo(request, account, "Ana");
  const week = await board(page);
  const swim = week.getByRole("button", { name: /^Mia & Leo's swim, .*, Ana, Mia, Leo, / });
  await expect(swim).toBeVisible({ timeout: 15_000 });
  // A neutral tint, and the bar in the three people's colors.
  await expect(swim.locator(".edge-3")).toHaveCount(1);
  await pickView(page, "People");
  const people = page.getByRole("region", { name: "People" });
  for (const name of ["Ana", "Mia", "Leo"]) {
    await expect(people.getByRole("region", { name })).toContainText("Mia & Leo's swim");
  }
  await expect(people.getByRole("region", { name: "Sam" })).not.toContainText("swim");
});

test("a refused password shows the attention icon, and the sheet names the account", async ({
  page,
  request,
}, testInfo) => {
  test.skip(testInfo.project.name !== "display-1080p", "the wall screen");
  const account = await accountWithFieldTrip(request);
  await syncNow(request, account);
  await mapToMia(request, account);
  const week = await board(page);
  await expect(week.getByRole("button", { name: /^Field trip, / })).toBeVisible({
    timeout: 15_000,
  });
  // Nothing wrong: no icon at all (ADR 0034).
  const attention = page.getByRole("banner").getByRole("button", { name: /^Needs attention/ });
  await expect(attention).toHaveCount(0);
  const failing = await request.put(`/api/calendar-sync/_test/fake/${account}`, {
    headers: CSRF,
    data: { fail_next: ["auth"] },
  });
  expect(failing.status()).toBe(200);
  await request.post("/api/_test/clock", { headers: CSRF, data: { advance_minutes: 2 } });
  await syncNow(request, account);
  await expect(attention).toBeVisible({ timeout: 15_000 });
  await expect(attention).toHaveAccessibleName("Needs attention: 1 thing");
  // The events stay.
  await expect(week.getByRole("button", { name: /^Field trip, / })).toBeVisible();
  await attention.click();
  const sheet = page.getByRole("dialog", { name: "Needs Attention" });
  await expect(sheet).toContainText("Test server needs its password again.");
  await sheet.getByRole("button", { name: "Open Calendars & Accounts" }).click();
  await expect(page).toHaveURL(/\/settings\/calendars$/);
  // The page that fixes it is marked in Settings' list.
  await expect(
    page
      .getByRole("navigation", { name: "Settings" })
      .getByRole("link", { name: "Calendars & Accounts, needs attention" }),
  ).toBeVisible();
});

test("a computer adds an account in a sheet, and Google's way back opens its calendars", async ({
  page,
  request,
}, testInfo) => {
  test.skip(testInfo.project.name !== "desktop", "a computer");
  await signInPhone(page);
  await page.goto("/settings/calendars");
  await page.getByRole("button", { name: "Add an Account" }).click();
  const sheet = page.getByRole("dialog", { name: "Add an Account" });
  // Apple first, then Google, Holidays, Another calendar and A calendar server (ADR 0032).
  await expect(sheet.getByRole("listitem")).toHaveText([
    /^Apple/,
    /^Google/,
    /^Holidays/,
    /^Another calendar/,
    /^A calendar server/,
  ]);
  await expect(sheet.getByText("Or add it from a device")).toHaveCount(0);
  await sheet.getByRole("button", { name: /^Google/ }).click();
  const google = page.getByRole("dialog", { name: "Google" });
  await expect(google.getByText("From a device")).toHaveCount(0);
  await google.getByRole("button", { name: /^Share with a Sunroom helper/ }).click();
  const helper = page.getByRole("dialog", { name: "Google: Share with a Helper" });
  await expect(helper.getByLabel("Upload the Key File")).toBeVisible();
  await helper.getByRole("button", { name: "Close" }).click();
  await expect(helper).toBeHidden();

  // Google's sign-in sends the browser back with a new account: here, the scripted one.
  const account = await scriptedAccount(request, { mapped: false });
  await page.goto(`/settings/calendars?google=connected&account=${account}`);
  const pick = page.getByRole("dialog", { name: "Pick Calendars" });
  await expect(pick).toBeVisible();
  await expect(toast(page, "Connected Google")).toBeVisible();
  await expect(page).toHaveURL(/\/settings\/calendars$/);
  await pick
    .getByRole("group", { name: "Whose is School" })
    .getByRole("button", { name: "Mia" })
    .click();
  await pick.getByRole("button", { name: "Done" }).click();
  await expect(toast(page, "Connected Test server · 1 calendar")).toBeVisible();
  await expect(pick).toBeHidden();
  // The account is a row now; its sheet has the calendar under Sync, and the calendar's own
  // page says it's Mia's.
  await page.getByRole("button", { name: "Edit Test server" }).click();
  const edit = page.getByRole("dialog", { name: "Edit Test server" });
  await expect(edit.getByRole("switch", { name: "Sync School" })).toBeChecked();
  await edit.getByRole("button", { name: "Edit School" }).click();
  const school = page.getByRole("dialog", { name: "Edit School" });
  await expect(
    school.getByRole("group", { name: "Whose is School" }).getByRole("button", { name: "Mia" }),
  ).toHaveAttribute("aria-pressed", "true");
  await school.getByRole("button", { name: "Close" }).click();
  await expect(school).toBeHidden();

  // A sign-in that didn't finish says so, in the app's words, and the address comes clean.
  await page.goto("/settings/calendars?google=denied");
  await expect(toast(page, "Google didn't finish signing in. Try again.")).toBeVisible();
  await expect(page).toHaveURL(/\/settings\/calendars$/);
  await expect(page.getByRole("dialog")).toHaveCount(0);
});

test("an account opens from its row: Sync, whose and color, Show on the screen, Remove account", async ({
  page,
  browser,
  watch,
}, testInfo) => {
  test.skip(testInfo.project.name !== "desktop", "a computer");
  await signInPhone(page);
  // A fifth person, so more of the twelve colors are somebody's.
  const added = await page.request.post("/api/members", {
    headers: CSRF,
    data: { name: "Zoe", role: "kid" },
  });
  expect(added.status()).toBe(201);
  const id = await scriptedAccount(page.request);
  const calendar = async () => {
    const accounts = (await (await page.request.get("/api/calendar-sync/accounts")).json()) as {
      id: string;
      calendars: { mapped: boolean; color: string | null; visible_on_display: boolean }[];
    }[];
    return accounts.find((account) => account.id === id)?.calendars[0];
  };

  await page.goto("/settings/calendars");
  const row = page.getByRole("button", { name: "Edit Test server" });
  await expect(row).toContainText("1 calendar");
  await row.click();
  const sheet = page.getByRole("dialog", { name: "Edit Test server" });
  await expect(sheet.getByRole("button", { name: "Refresh Now" })).toBeVisible();
  await expect(sheet.getByRole("heading", { name: "Sync" })).toBeVisible();
  // No screen is paired yet: nothing to show a calendar on.
  await expect(sheet.getByRole("heading", { name: /^Show on/ })).toHaveCount(0);

  // The calendar's own page: it's everyone's, so it has a color, the free ones first.
  await sheet.getByRole("button", { name: "Edit School" }).click();
  const school = page.getByRole("dialog", { name: "Edit School" });
  await expect(
    school
      .getByRole("group", { name: "Whose is School" })
      .getByRole("button", { name: "Everyone" }),
  ).toHaveAttribute("aria-pressed", "true");
  const members = (await (await page.request.get("/api/members")).json()) as { color: string }[];
  const taken = new Set(members.map((member) => member.color));
  const all = [
    "clay",
    "olive",
    "moss",
    "sea",
    "sky",
    "iris",
    "berry",
    "rose",
    "copper",
    "bark",
    "slate",
    "lime",
  ];
  expect(taken.size).toBe(5);
  const colors = school.getByRole("group", { name: "Color" }).getByRole("radio");
  await expect(colors).toHaveCount(12);
  expect(
    await colors.evaluateAll((radios) => radios.map((radio) => (radio as HTMLInputElement).value)),
  ).toEqual([
    ...all.filter((color) => !taken.has(color)),
    ...all.filter((color) => taken.has(color)),
  ]);
  // The first is free; the last says whose it is.
  const first = school.getByRole("group", { name: "Color" }).locator("label").first();
  await expect(first).not.toContainText("'s");
  await expect(school.getByRole("group", { name: "Color" }).locator("label").last()).toContainText(
    /\w's$/,
  );
  await first.click();
  await expect
    .poll(async () => (await calendar())?.color)
    .toBe(all.find((color) => !taken.has(color)));
  await school.getByRole("button", { name: "Back to Test server" }).click();
  await expect(sheet.getByRole("heading", { name: "Sync" })).toBeVisible();

  // A screen is paired: its name heads the switches that show each synced calendar on it.
  const { page: screen, context } = await wall(browser, watch);
  await pairWall(screen);
  const shown = sheet.getByRole("switch", { name: "School", exact: true });
  await expect(sheet.getByRole("heading", { name: "Show on Wall screen" })).toBeVisible();
  await expect(shown).toBeChecked();
  await shown.click();
  await expect(shown).not.toBeChecked();
  await expect.poll(async () => (await calendar())?.visible_on_display).toBe(false);

  // Sync off: the calendar leaves the board, and has no page or screen switch any more.
  await sheet.getByRole("switch", { name: "Sync School" }).click();
  await expect.poll(async () => (await calendar())?.mapped).toBe(false);
  await expect(sheet.getByRole("button", { name: "Edit School" })).toHaveCount(0);
  await expect(sheet.getByRole("heading", { name: /^Show on/ })).toHaveCount(0);

  // Remove account asks first.
  await sheet.getByRole("button", { name: "Remove Account" }).click();
  const asking = page.getByRole("dialog", { name: "Remove Test server?" });
  await asking.getByRole("button", { name: "Keep It" }).click();
  await sheet.getByRole("button", { name: "Remove Account" }).click();
  await asking.getByRole("button", { name: "Remove Test server" }).click();
  await expect(toast(page, "Removed Test server")).toBeVisible();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Edit Test server" })).toHaveCount(0);
  await context.close();
});

test("an account's calendar can be the default: Add starts with it, and one of Sunroom's own stays", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== "desktop", "a computer");
  await signInPhone(page);
  await scriptedAccount(page.request);
  await page.goto("/settings/calendars");
  // Home is the default until another is picked, and its row says so.
  const home = page.getByRole("button", { name: "Edit Home" });
  await expect(home).toContainText("Default calendar");
  await page.getByRole("button", { name: "Default calendar: Home" }).click();
  // A synced calendar names its account first, so two of one name can be told apart.
  await page
    .getByRole("radiogroup", { name: "Default calendar" })
    .getByRole("radio", { name: /· School$/ })
    .click();
  await expect(page.getByRole("button", { name: /^Default calendar: .+ · School$/ })).toBeVisible();
  await expect(page.getByText("Saved", { exact: true })).toBeVisible();
  await expect(home).not.toContainText("Default calendar");

  // Add starts with it, and an event added without picking another goes there.
  await page.getByRole("button", { name: "Add", exact: true }).click();
  const add = page.getByRole("dialog", { name: "Add" });
  await expect(add.getByRole("button", { name: /^Calendar: .+ · School$/ })).toBeAttached();
  await add.getByLabel("What, when, who").fill("Dentist Thu 2:30pm");
  await add.getByRole("button", { name: "Add Event" }).click();
  await expect(add).toBeHidden();
  const calendars = (await (await page.request.get("/api/calendar/calendars")).json()) as {
    id: string;
    name: string;
  }[];
  const found = (await (
    await page.request.get("/api/calendar/occurrences", {
      params: { from: "2026-10-04", to: "2026-10-11" },
    })
  ).json()) as { occurrences: { title: string; calendar_id: string }[] };
  expect(found.occurrences.find((o) => o.title === "Dentist")?.calendar_id).toBe(
    calendars.find((c) => c.name === "School")?.id,
  );

  // Sunroom keeps one calendar of its own: with Kids' activities removed, Home can't go too,
  // and its sheet says why.
  await page.goto("/settings/calendars");
  await page.getByRole("button", { name: /^Edit Kids/ }).click();
  const kids = page.getByRole("dialog", { name: /^Edit Kids/ });
  await kids.getByRole("button", { name: /^Remove Kids/ }).click();
  await expect(toast(page, "Removed Kids")).toBeVisible();
  await expect(kids).toBeHidden();
  await home.click();
  const homeSheet = page.getByRole("dialog", { name: "Edit Home" });
  await expect(homeSheet).toContainText(
    "Sunroom keeps one calendar of its own, so this one stays.",
  );
  await expect(homeSheet.getByRole("button", { name: "Remove Home" })).toHaveCount(0);
});

test("the wall adds an account itself, and hands Google's file and page to a phone", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== "display-1080p", "the wall screen");
  await pairWall(page);
  await page.goto("/settings/calendars");
  const add = page.getByRole("button", { name: "Add an Account" });
  await add.click();
  const sheet = page.getByRole("dialog", { name: "Add an Account" });
  await expect(sheet.getByText("Or add it from a device")).toBeVisible();
  await expect(
    sheet.getByRole("img", { name: "A code that opens Add an Account on a device" }),
  ).toBeVisible();

  // Apple: the password is a masked field, typed on the screen's own keyboard.
  await sheet.getByRole("button", { name: /^Apple/ }).click();
  const apple = page.getByRole("dialog", { name: "Apple" });
  await expect(apple.getByRole("link")).toHaveCount(0);
  const password = apple.getByLabel("App-specific password");
  await expect(password).toHaveAttribute("type", "password");
  await password.click();
  const keyboard = page.getByRole("group", { name: "On-screen keyboard" });
  for (const key of ["a", "b", "c"]) {
    await keyboard.getByRole("button", { name: key, exact: true }).click();
  }
  await expect(password).toHaveValue("abc");
  const keys = await keyboard.boundingBox();
  const field = await password.boundingBox();
  expect(keys && field && field.y + field.height <= keys.y).toBe(true);
  await keyboard.getByRole("button", { name: "Done" }).click();
  await apple.getByRole("button", { name: "Close" }).click();
  await expect(apple).toBeHidden();

  // Google: the secret address runs here; the helper's key file and Google's page need a phone.
  await add.click();
  await sheet.getByRole("button", { name: /^Google/ }).click();
  const google = page.getByRole("dialog", { name: "Google" });
  await expect(google.getByRole("button", { name: /^Paste the secret address/ })).not.toContainText(
    "From a device",
  );
  await expect(google.getByRole("button", { name: /^Share with a Sunroom helper/ })).toContainText(
    "From a device",
  );
  await expect(google.getByRole("button", { name: /^Sign in with Google/ })).toContainText(
    "From a device",
  );
  await google.getByRole("button", { name: /^Sign in with Google/ }).click();
  const signIn = page.getByRole("dialog", { name: "Sign in with Google" });
  await expect(signIn).toContainText("Do this from a device");
  await expect(
    signIn.getByRole("img", { name: "A code that opens Add an Account on a device" }),
  ).toBeVisible();
  await expect(signIn.getByRole("button", { name: "Sign in with Google" })).toHaveCount(0);
  // A tap on the backdrop still closes it (a press that started there).
  await page.mouse.click(40, 540);
  await expect(signIn).toBeHidden();
});

test("Google's keys are asked for inside Sign in with Google: saved masked, kept out of the export, removable", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== "desktop", "a computer");
  await signInPhone(page);
  const keys = async () => {
    const plugins = (await (await page.request.get("/api/plugins")).json()) as {
      id: string;
      settings: { google_client_id: string | null; google_client_secret: string | null };
    }[];
    return plugins.find((plugin) => plugin.id === "calendar_sync")?.settings;
  };
  // Features has no row for them any more, and none of their fields (ADR 0030).
  await page.goto("/settings/features");
  await expect(page.getByRole("heading", { name: "Features", level: 2 })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Synced Calendars", level: 3 })).toBeVisible();
  await expect(page.getByText("Sign in with Google")).toHaveCount(0);
  await expect(page.getByLabel("Google app's client ID")).toHaveCount(0);

  // They're in the one step that uses them: Add an account → Google → Sign in with Google.
  await page.goto("/settings/calendars");
  await page.getByRole("button", { name: "Add an Account" }).click();
  await page
    .getByRole("dialog", { name: "Add an Account" })
    .getByRole("button", { name: /^Google/ })
    .click();
  await page
    .getByRole("dialog", { name: "Google" })
    .getByRole("button", { name: /^Sign in with Google/ })
    .click();
  const step = page.getByRole("dialog", { name: "Sign in with Google" });
  await expect(step).toContainText("Paste the client ID and secret below.");
  // No keys yet: the two fields, and no way to sign in until they're saved.
  const save = step.getByRole("button", { name: "Save Keys and Continue" });
  await expect(save).toBeDisabled();
  await expect(step.getByRole("button", { name: "Sign in with Google" })).toHaveCount(0);
  await step.getByLabel("Google app's client ID").fill("sample-id.apps.example.com");
  await step.getByLabel("Google app's client secret").fill("sample-secret-0001");
  await save.click();
  await expect(toast(page, "Keys saved")).toBeVisible();
  await expect(step.locator("p", { hasText: /^Keys saved$/ })).toBeVisible();
  await expect(step.getByLabel("Google app's client ID")).toHaveCount(0);
  await expect(step.getByRole("button", { name: "Sign in with Google" })).toBeEnabled();
  expect(await keys()).toEqual({
    google_client_id: "sample-id.apps.example.com",
    google_client_secret: "***",
  });
  // Export everything says a secret is set, never what it is.
  const exported = await (await page.request.get("/api/export")).text();
  expect(exported).toContain("sample-id.apps.example.com");
  expect(exported).not.toContain("sample-secret-0001");

  // Change keys: the ID is there to edit, the secret never comes back; Cancel leaves them be.
  await step.getByRole("button", { name: "Change Keys" }).click();
  await expect(step.getByLabel("Google app's client ID")).toHaveValue("sample-id.apps.example.com");
  await expect(step.getByLabel("Google app's client secret")).toHaveValue("");
  await expect(step.getByText("Saved. Type a new one to replace it.")).toBeVisible();
  await step.getByRole("button", { name: "Cancel" }).click();
  await expect(step.locator("p", { hasText: /^Keys saved$/ })).toBeVisible();
  // Remove keys clears both, and the step asks for them again.
  await step.getByRole("button", { name: "Remove Keys" }).click();
  await expect(toast(page, "Removed Google's keys")).toBeVisible();
  await expect(step.getByRole("button", { name: "Save Keys and Continue" })).toBeVisible();
  await expect(step.getByRole("button", { name: "Sign in with Google" })).toHaveCount(0);
  expect(await keys()).toEqual({ google_client_id: null, google_client_secret: null });
});
