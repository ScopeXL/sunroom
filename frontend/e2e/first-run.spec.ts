/**
 * M0's flow (PLAN §15 M0 Verify): first run on a phone, then the wall screen paired from More
 * (the wizard has no pairing step, ADR 0030), the PIN gate on the wall, sign out. One test drives both: a phone context and the wall (this project's page).
 * First run on the wall itself (ADR 0039): Set Up Here, the steps on its keyboard, a paired
 * screen at the end, and a phone joining after.
 * And the way back to a first run (ADR 0029): Erase everything, from a computer and never from
 * the wall. Synthetic names only.
 */
import { expect, pairWall, phone, PIN, PASSWORD, seed, signInPhone, test, wall } from "./fixtures";

const ONLY = "display-1080p";
const WHY = "drives its own phone and wall contexts";

test("first run on a phone, the wall paired, Settings behind the PIN, then sign out", async ({
  page,
  browser,
  watch,
}, testInfo) => {
  test.skip(testInfo.project.name !== ONLY, WHY);
  test.setTimeout(60_000);
  // Before setup, the wall offers to set Sunroom up there or on another device (ADR 0039).
  await page.goto("/display");
  await expect(page.getByRole("heading", { name: "Set Up Sunroom", exact: true })).toBeVisible();
  const elsewhere = page.getByRole("region", { name: "On Another Device" });
  await expect(elsewhere.getByText("http://sunroom.local:4173")).toBeVisible();
  await expect(elsewhere.getByRole("img", { name: /A code that opens/ })).toBeVisible();

  const { page: phonePage, context } = await phone(browser, watch);
  await phonePage.goto("/");
  await expect(phonePage).toHaveURL(/\/setup/);
  await phonePage.getByRole("button", { name: "Start" }).click();
  // A phone shows how far along it is as a bar, not the list (ADR 0032).
  const progress = phonePage.getByRole("progressbar", { name: "Setup" });
  await expect(progress).toHaveAttribute("aria-valuenow", "1");
  await expect(phonePage.getByRole("list", { name: "Setup steps" })).toBeHidden();
  await phonePage.getByLabel("Household password").fill(PASSWORD);
  await phonePage.getByRole("button", { name: "Next" }).click();
  // The name starts as Home (ADR 0034); the theme shows on the page as soon as it's picked.
  await expect(phonePage.getByLabel("Household name")).toHaveValue("Home");
  await phonePage.getByLabel("Household name").fill("Sample Family");
  await phonePage.getByRole("button", { name: "Monday" }).click();
  await expect(phonePage.getByRole("button", { name: "Auto" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await phonePage.getByRole("button", { name: "Light" }).click();
  await expect(phonePage.locator("html")).toHaveAttribute("data-theme", "light");
  await phonePage.getByRole("button", { name: "Next" }).click();

  // Where's home? The field searches as it's typed into, from two letters; there is no Search
  // button. The test server's place search knows Sample Town.
  await expect(phonePage.getByRole("heading", { name: "Where’s home?" })).toBeVisible();
  await expect(phonePage.getByRole("button", { name: "Search" })).toHaveCount(0);
  await phonePage.getByLabel("Your city").fill("S");
  await expect(phonePage.getByText("Keep typing…")).toBeVisible();
  await phonePage.getByLabel("Your city").fill("Sample T");
  await expect(phonePage.getByRole("list", { name: "Places" })).toBeVisible();
  await phonePage.getByRole("button", { name: /^Sample Town/ }).click();

  // Who lives here? Start with you, then a child.
  await expect(phonePage.getByRole("heading", { name: "Who lives here?" })).toBeVisible();
  await phonePage.getByLabel("Your name").fill("Ana");
  await phonePage.getByRole("button", { name: "Add Me" }).click();
  await phonePage.getByLabel("Name", { exact: true }).fill("Mia");
  await phonePage.getByRole("button", { name: "Child", exact: true }).click();
  // One row: the name, Child, Add. The name clears for the next person; Child stays chosen.
  await phonePage.getByRole("button", { name: "Add", exact: true }).click();
  await expect(phonePage.getByRole("listitem").filter({ hasText: "Mia" })).toContainText("Child");
  await expect(phonePage.getByLabel("Name", { exact: true })).toHaveValue("");
  await expect(phonePage.getByRole("button", { name: "Child", exact: true })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await expect(phonePage.getByRole("button", { name: "Add Another" })).toHaveCount(0);
  await phonePage.getByRole("button", { name: "Next", exact: true }).click();

  await phonePage.getByLabel("PIN (4 to 6 digits)").fill(PIN);
  await phonePage.getByRole("button", { name: "Set a PIN" }).click();

  // No pairing step (ADR 0030): the wizard goes on to calendars, then All Done! (ADR 0042).
  await expect(phonePage.getByRole("heading", { name: "Bring in your calendars" })).toBeVisible();
  await expect(phonePage.getByText("6 of 6")).toBeVisible();
  await expect(progress).toHaveAttribute("aria-valuenow", "6");
  await phonePage.getByRole("button", { name: "Skip for Now" }).click();
  await expect(phonePage.getByRole("heading", { name: "All done!" })).toBeVisible();
  await expect(phonePage.getByText("Sunroom is ready for your family.")).toBeVisible();
  await expect(
    phonePage.getByText("Everyone at home signs in with the household password."),
  ).toBeVisible();
  const settings = (await (await phonePage.request.get("/api/settings")).json()) as {
    theme: string;
  };
  expect(settings.theme).toBe("light");
  await phonePage.getByRole("button", { name: "Open Sunroom" }).click();
  await expect(phonePage.getByRole("heading", { name: "Up next" })).toBeVisible();

  // The wall shows its pair code by itself once setup is done; the phone types it in More.
  await expect(page.getByRole("heading", { name: "Pair This Screen" })).toBeVisible({
    timeout: 15_000,
  });
  const code = (await page.getByTestId("pair-code").textContent()) ?? "";
  expect(code).toMatch(/^[A-Z2-9]{3} [A-Z2-9]{3}$/);
  await phonePage.getByRole("link", { name: "More" }).click();
  await phonePage.getByRole("link", { name: "Pair a Display" }).click();
  await phonePage.getByLabel("The code on the screen").fill(code);
  await phonePage.getByRole("button", { name: "Pair", exact: true }).click();
  await expect(
    phonePage.locator("[data-toast]").filter({ hasText: "Wall screen paired" }),
  ).toBeVisible();

  // The wall moves on by itself: name it, then the board. No place is chosen for it, so Done
  // keeps the name it was paired with (ADR 0042).
  await expect(page.getByRole("heading", { name: "Name this screen" })).toBeVisible();
  for (const place of ["Kitchen", "Hallway", "Living room", "Office", "Other"]) {
    await expect(page.getByRole("button", { name: place })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  }
  await page.getByRole("button", { name: "Done" }).click();
  const board = page.getByRole("region", { name: "This Week" });
  await expect(board).toBeVisible();
  await expect(board.locator("[aria-current=date]")).toContainText("today");
  // The board measures with an invisible copy of each column; the visible line is the one.
  await expect(board.getByText(/^now \d{1,2}:\d{2}/).filter({ visible: true })).toBeVisible();
  await expect(page.getByRole("banner")).toContainText(/\d{1,2}:\d{2}/);
  // The household starts its week on Monday now.
  await expect(board.getByRole("heading", { level: 2 }).first()).toContainText("Mon");

  // Settings on the wall are behind the PIN.
  await page.getByRole("button", { name: "Settings" }).click();
  const pin = page.getByRole("dialog", { name: "Parent PIN" });
  await expect(pin).toBeVisible();
  for (const digit of "1357") await pin.getByRole("button", { name: digit, exact: true }).click();
  await expect(pin.getByRole("alert")).toHaveText("That PIN didn't match. Try again.");
  for (const digit of PIN) await pin.getByRole("button", { name: digit, exact: true }).click();
  await expect(pin).toBeHidden();
  await expect(page.getByRole("heading", { name: "Family", level: 2 })).toBeVisible();
  await expect(page.getByRole("button", { name: "Edit Mia" })).toBeVisible();
  await page.getByRole("button", { name: "Lock" }).click();
  await expect(board).toBeVisible();
  // Locked again: Settings asks for the PIN once more.
  await page.getByRole("button", { name: "Settings" }).click();
  await expect(page.getByRole("dialog", { name: "Parent PIN" })).toBeVisible();
  await page
    .getByRole("dialog", { name: "Parent PIN" })
    .getByRole("button", { name: "Cancel" })
    .click();

  // The phone signs itself out from Devices.
  await phonePage.getByRole("link", { name: "More", exact: true }).click();
  await phonePage.getByRole("link", { name: "Settings" }).click();
  await phonePage.getByRole("link", { name: "Devices" }).click();
  await expect(phonePage.getByText("Wall screen", { exact: true })).toBeVisible();
  await phonePage.getByRole("button", { name: "Sign Out of This Phone" }).click();
  await expect(phonePage).toHaveURL(/\/sign-in/);
  await context.close();
});

test("first run on the wall itself: its own keyboard, a paired screen, and a phone after", async ({
  page,
  browser,
  watch,
}, testInfo) => {
  test.skip(testInfo.project.name !== ONLY, WHY);
  test.setTimeout(60_000);
  await page.goto("/display");
  const here = page.getByRole("region", { name: "On This Screen" });
  await here.getByRole("button", { name: "Set Up Here" }).click();
  // The six steps beside the form, the wall's keyboard under the field; Back goes back.
  await expect(page.getByRole("list", { name: "Setup steps" })).toBeVisible();
  await page.getByRole("button", { name: "Back" }).click();
  await here.getByRole("button", { name: "Set Up Here" }).click();
  const password = page.getByLabel("Household password");
  await password.click();
  const keyboard = page.getByRole("group", { name: "On-screen keyboard" });
  await expect(keyboard).toBeVisible();
  await keyboard.getByRole("button", { name: "e", exact: true }).click();
  await expect(password).toHaveValue("e"); // a password: no automatic capital
  await password.fill(PASSWORD);
  await page.getByRole("button", { name: "Next" }).click();
  await page.getByLabel("Household name").fill("Sample Family");
  await page.getByRole("button", { name: "Next" }).click();
  await expect(page.getByRole("heading", { name: "Where’s home?" })).toBeVisible();
  await page.getByRole("button", { name: "Later" }).click();
  await page.getByLabel("Your name").fill("Ana");
  await page.getByRole("button", { name: "Add Me" }).click();
  await expect(page.getByRole("listitem").filter({ hasText: "Ana" })).toContainText("Parent");
  await page.getByRole("button", { name: "Next", exact: true }).click();
  // The PIN it sets opens its ten minutes, so the calendars step is still a parent's.
  await page.getByLabel("PIN (4 to 6 digits)").fill(PIN);
  await page.getByRole("button", { name: "Set a PIN" }).click();
  await expect(page.getByRole("heading", { name: "Bring in your calendars" })).toBeVisible();
  const unlocked = (await (await page.request.get("/api/auth/session")).json()) as {
    is_parent: boolean;
    grant_expires_at: string | null;
  };
  expect(unlocked.is_parent).toBe(true);
  expect(unlocked.grant_expires_at).not.toBeNull();
  await page.getByRole("button", { name: "Skip for Now" }).click();
  // It names itself, then All Done! says how other devices join.
  await expect(page.getByRole("heading", { name: "Name this screen" })).toBeVisible();
  await page.getByRole("button", { name: "Hallway" }).click();
  await page.getByRole("button", { name: "Next" }).click();
  await expect(page.getByRole("heading", { name: "All done!" })).toBeVisible();
  await expect(page.getByRole("img", { name: /A code that opens/ })).toBeVisible();
  await page.getByRole("button", { name: "Open Sunroom" }).click();
  await expect(page.getByRole("region", { name: "This Week" })).toBeVisible();

  // A paired screen, not a phone, and nobody's in particular.
  const session = (await (await page.request.get("/api/auth/session")).json()) as {
    device_kind: string;
    device_label: string;
    member: unknown;
  };
  expect(session).toMatchObject({ device_kind: "kiosk", device_label: "Hallway screen" });
  expect(session.member).toBeNull();

  // A phone joins with the password typed on the wall.
  const { page: phonePage, context } = await phone(browser, watch);
  await signInPhone(phonePage, "Ana");
  await context.close();
});

test("the wall's own setup goes back to Set Up Sunroom after ten idle minutes", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== ONLY, WHY);
  await page.clock.install();
  await page.goto("/display");
  await page.getByRole("button", { name: "Set Up Here" }).click();
  await page.getByLabel("Household password").fill(PASSWORD);
  await page.getByRole("button", { name: "Next" }).click();
  await expect(page.getByLabel("Household name")).toBeVisible();
  await page.clock.fastForward("10:01");
  await expect(page.getByRole("heading", { name: "Set Up Sunroom", exact: true })).toBeVisible();
  // What was typed is gone: the steps start again at an empty password.
  await page.getByRole("button", { name: "Set Up Here" }).click();
  await expect(page.getByLabel("Household password")).toHaveValue("");
});

test("a wall screen typed in with the password, and a toast that leaves under the CSP", async ({
  request,
  browser,
  watch,
}, testInfo) => {
  test.skip(testInfo.project.name !== ONLY, WHY);
  await request.post("/api/_test/seed", { headers: { "X-Sunroom": "1" }, data: { pin: PIN } });
  const { page: screen, context } = await wall(browser, watch);
  await screen.goto("/display");
  await screen.getByRole("button", { name: "Type the household password here instead" }).click();
  const field = screen.getByLabel("Household password");
  await field.click();
  // The on-screen keyboard rises; type the first letters with it, the rest directly.
  const keyboard = screen.getByRole("group", { name: "On-screen keyboard" });
  await expect(keyboard).toBeVisible();
  await keyboard.getByRole("button", { name: "e", exact: true }).click();
  await expect(field).toHaveValue("e"); // a password: no automatic capital
  await field.fill(PASSWORD);
  await screen.getByRole("button", { name: "Pair This Screen" }).click();
  await expect(screen.getByRole("heading", { name: "Name this screen" })).toBeVisible();
  await screen.getByRole("button", { name: "Done" }).click();
  await expect(screen.getByRole("region", { name: "This Week" })).toBeVisible();

  // From here on the service worker answers the page, and asks the server for it (ADR 0034):
  // two reloads give two nonces, each in its own CSP header. The copy it saved at install would
  // give the same one twice.
  await screen.waitForFunction(() => navigator.serviceWorker.controller !== null);
  const nonces: string[] = [];
  for (let round = 0; round < 2; round++) {
    const response = await screen.reload();
    expect(response?.fromServiceWorker()).toBe(true);
    await expect(screen.getByRole("region", { name: "This Week" })).toBeVisible();
    const nonce = (await screen.locator('meta[name="csp-nonce"]').getAttribute("content")) ?? "";
    expect(nonce).toMatch(/^[\w+/=-]{16,}$/);
    expect((await response?.allHeaders())?.["content-security-policy"]).toContain(nonce);
    nonces.push(nonce);
  }
  expect(nonces[1]).not.toBe(nonces[0]);

  // Settings → Family → remove Mia, then Undo: the toast rises and leaves with `motion`, whose
  // style block carries the page's nonce, while the CSP guard watches (ADR 0007).
  await screen.getByRole("button", { name: "Settings" }).click();
  const pin = screen.getByRole("dialog", { name: "Parent PIN" });
  for (const digit of PIN) await pin.getByRole("button", { name: digit, exact: true }).click();
  await screen.getByRole("button", { name: "Edit Mia" }).click();
  const sheet = screen.getByRole("dialog", { name: "Edit Mia" });
  await sheet.getByRole("button", { name: "Remove Mia" }).click();
  await sheet.getByRole("button", { name: "Remove Mia" }).click();
  const toast = screen.locator("[data-toast]").filter({ hasText: "Removed Mia" });
  await expect(toast).toBeVisible();
  await toast.getByRole("button", { name: "Undo" }).click();
  await expect(toast).toHaveCount(0);
  await expect(screen.getByRole("button", { name: "Edit Mia" })).toBeVisible();
  await context.close();
});

test("offline, a wall screen still opens from the copy its service worker saved", async ({
  request,
  browser,
  watch,
}, testInfo) => {
  // Chromium's setOffline reaches a service worker's own fetches; WebKit's doesn't.
  test.skip(testInfo.project.name !== ONLY, WHY);
  await seed(request, { pin: PIN });
  const { page: screen, context } = await wall(browser, watch);
  await pairWall(screen);
  await screen.goto("/display");
  await expect(screen.getByRole("region", { name: "This Week" })).toBeVisible();
  await screen.waitForFunction(() => navigator.serviceWorker.controller !== null);

  await context.setOffline(true);
  const offline = await screen.reload();
  expect(offline?.fromServiceWorker()).toBe(true);
  expect(offline?.ok()).toBe(true);
  // The saved page and its files: the wall's frame, waiting for the server (DisplayEntry).
  await expect(screen.locator('main[data-shell="display"]')).toBeVisible();
  expect(await screen.locator('meta[name="csp-nonce"]').getAttribute("content")).toMatch(
    /^[\w+/=-]{16,}$/,
  );

  await context.setOffline(false);
  await screen.reload();
  await expect(screen.getByRole("region", { name: "This Week" })).toBeVisible();

  // A reverse proxy's 502 while the container restarts counts as no answer too: the saved page
  // opens, and here (only the page itself refused) the board comes up. The route answers the
  // worker's own fetch (Chromium), so count that it did.
  let gateway = 0;
  await context.route("**/display", (route) => {
    gateway += 1;
    return route.fulfill({ status: 502, body: "Bad Gateway" });
  });
  const proxied = await screen.reload();
  expect(gateway).toBeGreaterThan(0);
  expect(proxied?.fromServiceWorker()).toBe(true);
  expect(proxied?.ok()).toBe(true);
  await expect(screen.getByRole("region", { name: "This Week" })).toBeVisible();
  await expect(screen.getByText("Bad Gateway")).toHaveCount(0);
  await context.unrouteAll();

  // The server down with the network up: the screen waits for it and comes back as itself, by
  // itself. Giving up showed Pair This Screen, though it was still paired.
  await context.route("**/api/**", (route) => route.abort("connectionrefused"));
  await screen.reload();
  await expect(screen.locator('main[data-shell="display"]')).toBeVisible();
  await screen.waitForTimeout(5000); // past the two quick retries every other request gets
  await context.unrouteAll();
  await expect(screen.getByRole("region", { name: "This Week" })).toBeVisible({ timeout: 30_000 });
  await expect(screen.getByRole("heading", { name: "Pair This Screen" })).toHaveCount(0);
  await context.close();
});

test("Erase everything starts Sunroom over: from a computer, never from the wall", async ({
  page,
  request,
  browser,
  watch,
}, testInfo) => {
  test.skip(testInfo.project.name !== "desktop", "a computer, with a wall screen beside it");
  await seed(request);
  // The wall's Backup page has no Start Over (no PIN here, so it opens Settings itself).
  const { page: screen, context } = await wall(browser, watch);
  await pairWall(screen);
  await screen.goto("/settings/backup");
  await expect(screen.getByRole("heading", { name: "Backups", exact: true })).toBeVisible();
  await expect(screen.getByRole("button", { name: "Back Up Now" })).toBeVisible();
  await expect(screen.getByRole("heading", { name: "Start Over" })).toHaveCount(0);
  await expect(screen.getByRole("button", { name: /^Erase everything/ })).toHaveCount(0);
  // Nor a line saying to do any of it elsewhere (ADR 0034).
  await expect(screen.getByRole("heading", { name: "Take Your Data with You" })).toHaveCount(0);
  await expect(screen.getByText(/from a (phone|computer|device)/i)).toHaveCount(0);
  await screen.goto("/display");
  await expect(screen.getByRole("region", { name: "This Week" })).toBeVisible();

  // A computer has it, with the downloads the wall can't use.
  await signInPhone(page);
  await page.goto("/settings/backup");
  await page.getByRole("button", { name: "Download…" }).click();
  const which = page.getByRole("dialog", { name: "Download Which?" });
  await expect(which.getByRole("link", { name: "Data & Photos" })).toHaveAttribute(
    "href",
    "/api/admin/backups/full.zip",
  );
  await which.getByRole("button", { name: "Close" }).click();
  await expect(which).toBeHidden();
  await page.getByRole("button", { name: "Erase Everything…" }).click();
  const sheet = page.getByRole("dialog", { name: "Erase Everything?" });
  await expect(sheet.getByText("Keep a copy first?")).toBeVisible();
  await expect(sheet.getByRole("link", { name: "Download Everything" })).toHaveAttribute(
    "href",
    "/api/admin/backups/full.zip",
  );
  await sheet.getByRole("button", { name: "I Have a Copy" }).click();
  const password = sheet.getByLabel("Household password");
  await password.fill("not-the-household-password");
  await sheet.getByRole("button", { name: "Erase Everything" }).click();
  await expect(sheet.getByText("That password didn't match. Try again.")).toBeVisible();
  await password.fill(PASSWORD);
  await sheet.getByRole("button", { name: "Erase Everything" }).click();

  // This computer lands on a first run, and so does the wall, by itself.
  await expect(page.getByRole("heading", { name: "Welcome to Sunroom" })).toBeVisible();
  await expect(page).toHaveURL(/\/setup/);
  await expect(screen.getByRole("heading", { name: "Set Up Sunroom", exact: true })).toBeVisible();
  const status = (await (await request.get("/api/setup/status")).json()) as {
    setup_complete: boolean;
  };
  expect(status.setup_complete).toBe(false);
  // A computer's setup lists the six steps beside the form (ADR 0032), the current one marked.
  await page.getByRole("button", { name: "Start" }).click();
  const steps = page.getByRole("list", { name: "Setup steps" }).getByRole("listitem");
  await expect(steps).toHaveCount(6);
  await expect(steps.nth(0)).toHaveAttribute("aria-current", "step");
  await expect(steps.nth(0)).toContainText("Household password");
  await expect(page.getByRole("progressbar")).toBeHidden();
  await context.close();
});
