/**
 * Every word the family reads comes from lang/ (ADR 0043, PLAN §14.6): the app in the pseudo
 * language (`localStorage["sunroom.language"] = "pseudo"`: English accented and a third longer,
 * in brackets) on the key screens of the wall, a phone and the screen's own pages. Every visible
 * text, label and placeholder either carries the pseudo marks or is the family's own data (what
 * the page loaded from the API: names, titles, places), a number, a date or time as `Intl`
 * writes it, or a brand. The failure lists what's left, by screen. Synthetic data only.
 */
import { readFileSync } from "node:fs";

import type { Page } from "@playwright/test";

import {
  expect,
  pairWall,
  PASSWORD,
  PIN,
  scriptedAccount,
  seed,
  settled,
  signInPhone,
  test,
} from "./fixtures";

const CSRF = { "X-Sunroom": "1" };
// Wednesday, October 7, 2026, 10:00 AM in New York: the same week of events on every run.
const WEDNESDAY_10AM = "2026-10-07T14:00:00Z";
const AGENT = "http://127.0.0.1:7800";
const ORIGIN = "http://127.0.0.1:4173";

/** lib/lang.ts's pseudo accents, to find a control by its pseudo name. */
const ACCENTS: Readonly<Record<string, string>> = {
  a: "á", b: "ƀ", c: "ç", d: "ð", e: "é", f: "ƒ", g: "ĝ", h: "ĥ", i: "í", j: "ĵ", k: "ķ",
  l: "ļ", m: "ɱ", n: "ñ", o: "ö", p: "þ", q: "ǫ", r: "ŕ", s: "š", t: "ţ", u: "ü", v: "ṽ",
  w: "ŵ", x: "ẋ", y: "ý", z: "ž", A: "Å", B: "Ɓ", C: "Ç", D: "Ð", E: "É", F: "Ƒ", G: "Ĝ",
  H: "Ĥ", I: "Î", J: "Ĵ", K: "Ķ", L: "Ļ", M: "Ṁ", N: "Ñ", O: "Ö", P: "Þ", Q: "Ǫ", R: "Ŕ",
  S: "Š", T: "Ţ", U: "Û", V: "Ṽ", W: "Ŵ", X: "Ẋ", Y: "Ý", Z: "Ž",
}; // prettier-ignore
const MARKS = new RegExp(`[\\[\\]~${Object.values(ACCENTS).join("")}]`, "u");

/** A control's pseudo name, as a pattern: `p("Settings")` finds "[Šéţţíñĝš~~~]". */
function p(english: string): RegExp {
  const accented = Array.from(english, (letter) => ACCENTS[letter] ?? letter).join("");
  return new RegExp(accented.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
}

// Words that are never translated (docs/LANGUAGES.md): each language's own name, the brands,
// and what Intl writes for dates and times in the pseudo language's locale (en-US).
const LANGUAGE_NAMES = Object.values(
  JSON.parse(readFileSync("../lang/languages.json", "utf-8")) as Record<string, { name: string }>,
).map((language) => language.name);
const BRANDS = [
  ...LANGUAGE_NAMES,
  "Sunroom",
  "Sunroom Screen",
  "Google",
  "Apple",
  "iCloud",
  "Immich",
  "Discord",
  "Patreon",
  "GitHub",
  "Open-Meteo",
  "Raspberry Pi",
];
const DATE_WORDS = new Set(
  [
    ..."Monday Tuesday Wednesday Thursday Friday Saturday Sunday".split(" "),
    ..."Mon Tue Wed Thu Fri Sat Sun".split(" "),
    ..."January February March April May June July August September October November December".split(
      " ",
    ),
    ..."Jan Feb Mar Apr May Jun Jul Aug Sep Sept Oct Nov Dec".split(" "),
    "AM",
    "PM",
  ].map((word) => word.toLowerCase()),
);

/** What the family typed or the server keeps for them: every string in the API's answers the
 * page loaded, except the server's own English sentences (said by their keys) and the plugins'
 * and problems' words (keys too). */
function collectData(page: Page): Set<string> {
  const data = new Set<string>();
  const skipKeys = new Set(["message", "repeat_text", "step"]);
  const walk = (value: unknown, key: string | null) => {
    if (typeof value === "string") {
      if (key !== null && skipKeys.has(key)) return;
      const text = value.replace(/\s+/g, " ").trim();
      data.add(text);
      data.add(text.replace(/_/g, " ")); // a time zone as it's shown: America/New York
    } else if (Array.isArray(value)) {
      for (const item of value) walk(item, key);
    } else if (value && typeof value === "object") {
      for (const [name, item] of Object.entries(value)) walk(item, name);
    }
  };
  page.on("response", (response) => {
    const url = new URL(response.url());
    const api = url.pathname.startsWith("/api/") || url.origin === AGENT;
    if (!api || /^\/api\/(plugins|problems)$/.test(url.pathname)) return;
    if (!(response.headers()["content-type"] ?? "").includes("application/json")) return;
    response
      .json()
      .then((body: unknown) => {
        walk(body, null);
      })
      .catch(() => undefined);
  });
  return data;
}

/** Whether a text the page shows is fine untranslated (see the file's comment). */
function fine(text: string, data: Set<string>): boolean {
  if (!/\p{L}/u.test(text) || MARKS.test(text)) return true;
  // A title after its emoji ("🌮 Tacos"): the emoji is the family's too.
  const bare = text.replace(/^[^\p{L}\p{N}]+/u, "");
  if (data.has(text) || data.has(bare) || BRANDS.includes(text)) return true;
  if (
    /^(https?:\/\/|[\w.-]+@[\w-]+\.)/.test(text) ||
    /^[\w-]+(\.[\w-]+)+(:\d+)?(\/\S*)?$/.test(text)
  ) {
    return true; // an address
  }
  if (/^\p{L}$/u.test(text)) return true; // a key of the wall's keyboard
  // Pieces joined by the page's own marks: each a piece of data, a brand or a date.
  const pieces = text.split(/\s*(?:·|•|,|–|—|\/|\||:|\(|\))\s*/u).filter((piece) => piece);
  return pieces.every((piece) => {
    if (!/\p{L}/u.test(piece) || data.has(piece) || BRANDS.includes(piece)) return true;
    const words = piece.match(/\p{L}+/gu) ?? [];
    return words.every((word) => DATE_WORDS.has(word.toLowerCase()));
  });
}

/** Everything this page says right now: its visible texts, labels and placeholders. */
async function texts(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const said: string[] = [];
    const add = (value: string | null | undefined) => {
      const text = value?.replace(/\s+/g, " ").trim();
      if (text) said.push(text);
    };
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      const parent = node.parentElement;
      if (!parent || parent.closest("script, style, noscript, template")) continue;
      if (!parent.checkVisibility({ visibilityProperty: true })) continue;
      add(node.textContent);
    }
    for (const element of document.querySelectorAll<HTMLElement>(
      "[aria-label], [placeholder], [title], img[alt]",
    )) {
      if (!element.checkVisibility({ visibilityProperty: true })) continue;
      add(element.getAttribute("aria-label"));
      add(element.getAttribute("placeholder"));
      add(element.getAttribute("title"));
      add(element.getAttribute("alt"));
    }
    return said;
  });
}

/** The words still in English on this screen, kept under its name for the test's end. */
async function look(
  page: Page,
  data: Set<string>,
  where: string,
  found: Map<string, Set<string>>,
): Promise<void> {
  // The live stream keeps the network busy: let the screen and the answers it read settle.
  await settled(page);
  await page.waitForTimeout(400);
  for (const text of await texts(page)) {
    if (fine(text, data)) continue;
    const seen = found.get(where) ?? new Set<string>();
    seen.add(text);
    found.set(where, seen);
  }
}

function report(found: Map<string, Set<string>>): string[] {
  return [...found].map(([where, words]) => `${where}: ${[...words].join(" | ")}`);
}

async function pseudo(page: Page): Promise<void> {
  await page.addInitScript(() => {
    localStorage.setItem("sunroom.language", "pseudo");
  });
}

/** The wall's own Sunroom Screen, pretend (as this-screen.spec.ts's), for This Screen; what it
 * says of itself is the family's data. */
async function pretendAgent(page: Page, data: Set<string>): Promise<void> {
  const cors = {
    "Access-Control-Allow-Origin": ORIGIN,
    "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE",
    "Access-Control-Allow-Headers": "Content-Type, X-Sunroom-Screen",
    "Access-Control-Allow-Private-Network": "true",
    Vary: "Origin",
  };
  const state = {
    version: "0.18.0",
    platform: "pi",
    model: "Raspberry Pi 5 Model B",
    session: "wayland",
    capabilities: ["restart", "shutdown", "update", "wifi", "rotate", "brightness"],
    sunroom: {
      url: "http://192.168.1.20:7867",
      id: "00000000-0000-7000-8000-0000000000e1",
      name: "The Sample Family",
      found: "discovered",
      reachable: true,
    },
    network: { kind: "wifi", ssid: "HomeNet", ip: "192.168.1.30", strength: 82 },
    update: {
      check: "nightly",
      state: "available",
      installed: "0.18.0",
      latest: "0.18.1",
      checked_at: null,
      message: null,
      needs_terminal: "curl -fsSL https://sunroom.day/install.sh | bash",
    },
    display: { rotation: 0, brightness_method: "ddc" },
    open_url: `${ORIGIN}/display?dimmer=screen&screen=7800`,
  };
  for (const value of [state.model, state.network.ssid, state.update.needs_terminal]) {
    data.add(value);
  }
  await page.route(`${AGENT}/api/screen**`, async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (request.method() === "OPTIONS") {
      await route.fulfill({ status: 204, headers: cors });
      return;
    }
    if (path === "/api/screen/events") {
      await route.fulfill({
        status: 200,
        headers: { ...cors, "Content-Type": "text/event-stream" },
        body: `retry: 2000\n\nevent: state\ndata: ${JSON.stringify(state)}\n\n`,
      });
      return;
    }
    const body = path === "/api/screen" ? state : { ok: true };
    await route.fulfill({
      status: 200,
      headers: { ...cors, "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  });
}

const SAY = "words outside lang/ (fix each by docs/LANGUAGES.md's recipe)";

/** Open a sheet by its button, look at it, and close it. */
async function sheet(
  page: Page,
  data: Set<string>,
  button: string,
  where: string,
  found: Map<string, Set<string>>,
): Promise<void> {
  await page
    .getByRole("button", { name: p(button) })
    .first()
    .click();
  await expect(page.getByRole("dialog"), where).toBeVisible();
  await look(page, data, where, found);
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog"), where).toBeHidden();
}

test("the wall in the pseudo language says only what lang/ holds", async ({
  page,
  request,
}, testInfo) => {
  test.skip(testInfo.project.name !== "display-1080p", "the wall screen");
  test.slow();
  const found = new Map<string, Set<string>>();
  const data = collectData(page);
  await request.post("/api/_test/clock", { headers: CSRF, data: { set: WEDNESDAY_10AM } });
  await pseudo(page);

  await page.goto("/display");
  await expect(page.getByRole("heading", { name: p("Set Up Sunroom") })).toBeVisible();
  await look(page, data, "Set Up Sunroom", found);
  await seed(request, { pin: PIN });
  await page.reload();
  await expect(page.getByTestId("pair-code")).toBeVisible();
  await look(page, data, "Pair This Screen", found);

  await pairWall(page);
  await pretendAgent(page, data);
  await page.goto("/display?dimmer=screen&screen=7800");
  await expect(page.getByRole("region", { name: p("This Week") })).toBeVisible();
  await look(page, data, "the week board", found);

  const banner = page.getByRole("banner");
  await banner.getByRole("button", { name: p("View") }).click();
  await look(page, data, "the View menu", found);
  await page.keyboard.press("Escape");
  await banner.getByRole("button", { name: p("Filter") }).click();
  await look(page, data, "the Filter menu", found);
  await page.keyboard.press("Escape");

  await page
    .getByRole("button", { name: p("Add") })
    .first()
    .click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.getByRole("dialog").getByRole("textbox").first().click();
  await look(page, data, "Add, with the keyboard", found);
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toBeHidden();

  await page
    .getByRole("button", { name: /\bVet, / })
    .first()
    .click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await look(page, data, "an event's sheet", found);
  await page.keyboard.press("Escape");

  for (const room of ["Lists", "Tasks", "Meals", "Photos"]) {
    await page
      .getByRole("navigation", { name: p("Rooms") })
      .getByRole("link", { name: p(room) })
      .click();
    await page.waitForTimeout(300);
    await look(page, data, `the ${room} room`, found);
  }

  // Needs Attention: an account whose password was refused (a parent's session on `request`).
  const signedIn = await request.post("/api/auth/login", {
    headers: CSRF,
    data: { password: PASSWORD },
  });
  expect(signedIn.ok()).toBe(true);
  const account = await scriptedAccount(request);
  const attention = banner.getByRole("button", { name: p("Needs attention") });
  await expect(async () => {
    await request.put(`/api/calendar-sync/_test/fake/${account}`, {
      headers: CSRF,
      data: { fail_next: ["auth"] },
    });
    await request.post("/api/_test/clock", { headers: CSRF, data: { advance_minutes: 2 } });
    await request.post(`/api/calendar-sync/accounts/${account}/sync`, { headers: CSRF });
    await expect(attention).toBeVisible({ timeout: 5_000 });
  }).toPass({ timeout: 45_000 });
  await attention.click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await look(page, data, "Needs Attention", found);
  await page.keyboard.press("Escape");

  await page
    .getByRole("button", { name: p("Settings") })
    .first()
    .click();
  const pin = page.getByRole("dialog");
  for (const digit of PIN) await pin.getByRole("button", { name: digit, exact: true }).click();
  await expect(pin).toBeHidden();
  await look(page, data, "This Screen", found);
  for (const button of ["Update Now", "Shut Down", "Change Wi-Fi", "Help"]) {
    await sheet(page, data, button, `This Screen: ${button}`, found);
  }
  const nav = page.getByRole("navigation").last();
  const count = await nav.getByRole("link").count();
  for (let index = 1; index < count; index += 1) {
    await nav.getByRole("link").nth(index).click();
    await page.waitForTimeout(300);
    const title = await page.getByRole("heading", { level: 2 }).first().innerText();
    await look(page, data, `Settings: ${title}`, found);
  }

  expect(report(found), SAY).toEqual([]);
});

test("a phone in the pseudo language says only what lang/ holds", async ({
  page,
  request,
}, testInfo) => {
  test.skip(testInfo.project.name !== "phone-webkit", "a phone");
  test.slow();
  const found = new Map<string, Set<string>>();
  const data = collectData(page);
  await request.post("/api/_test/clock", { headers: CSRF, data: { set: WEDNESDAY_10AM } });
  await seed(request, { pin: PIN });
  // Signed in the usual way (fixtures' signInPhone reads English), then seen in pseudo.
  await signInPhone(page);
  await page.evaluate(() => {
    localStorage.setItem("sunroom.language", "pseudo");
  });
  for (const [path, where] of [
    ["/", "Today"],
    ["/calendar", "Calendar"],
    ["/lists", "Lists"],
    ["/chores", "Tasks"],
    ["/more", "More"],
    ["/meals", "Meals"],
    ["/countdowns", "Countdowns"],
    ["/photos", "Photos"],
    ["/settings", "Settings"],
    ["/settings/household", "Settings: Household"],
    ["/settings/family", "Settings: Family"],
    ["/settings/devices", "Settings: Devices"],
    ["/pair", "Pair a Display"],
  ] as const) {
    await page.goto(path);
    await expect(page.locator("main").first()).toBeVisible();
    await look(page, data, where, found);
  }
  await page.context().clearCookies();
  await page.goto("/sign-in");
  await expect(page.getByRole("button", { name: p("Sign In") })).toBeVisible();
  await look(page, data, "sign in", found);
  expect(report(found), SAY).toEqual([]);
});

test("the screen's own pages in the pseudo language say only what lang/ holds", async ({
  page,
  request,
}, testInfo) => {
  test.skip(testInfo.project.name !== "display-1080p", "the wall screen");
  const screen = "http://127.0.0.1:4174";
  const change = { "X-Sunroom-Screen": "1" };
  const reset = await request.post(`${screen}/api/screen/_test/reset`, { headers: change });
  expect(reset.status()).toBe(204);
  const found = new Map<string, Set<string>>();
  const data = collectData(page);
  await seed(request);
  await pseudo(page);
  for (const [path, where] of [
    ["/", "Welcome"],
    ["/find", "Where Is Your Sunroom?"],
    ["/settings", "This Screen's twin"],
  ] as const) {
    await page.goto(`${screen}${path}`);
    await expect(page.getByRole("heading").first()).toBeVisible();
    await look(page, data, where, found);
  }
  await request.post(`${screen}/api/screen/_test/fake`, {
    headers: change,
    data: { sunroom: "http://198.51.100.20:7867" },
  });
  await page.goto(`${screen}/cant-reach`);
  await expect(page.getByRole("heading").first()).toBeVisible();
  await look(page, data, "Can't Reach", found);
  expect(report(found), SAY).toEqual([]);
});
