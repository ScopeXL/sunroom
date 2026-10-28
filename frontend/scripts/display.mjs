/**
 * `just display`: the built app's wall screen in a Chromium window with touch, for review
 * (PLAN §14.5). It starts the end-to-end server (test mode, a throwaway data folder) unless one
 * is already answering on its port, resets it, loads the synthetic Sample Family, pairs the
 * window as a wall screen and opens the board.
 *
 *   --portrait   1080 × 1920 instead of 1920 × 1080
 *   --unpaired   stop at the pair code (pair it from a phone at the printed address)
 *   --fresh      a server that has never been set up
 *
 * Close the window (or press Ctrl+C) to stop.
 */
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";

import { chromium } from "@playwright/test";

const BASE = "http://127.0.0.1:4173";
const CSRF = { "X-Sunroom": "1" };
// Synthetic, the end-to-end runs' own (also in .gitleaks.toml's allowlist).
const PASSWORD = "e2e-household-passphrase";
const PIN = "2468";
const options = new Set(process.argv.slice(2));
const portrait = options.has("--portrait");
const fresh = options.has("--fresh");
const unpaired = fresh || options.has("--unpaired");

async function answering() {
  try {
    return (await fetch(`${BASE}/api/health`)).ok;
  } catch {
    return false;
  }
}

async function post(path, body = {}) {
  const response = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { ...CSRF, "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw new Error(`${path} answered ${String(response.status)}`);
}

let server;
function stop() {
  server?.kill("SIGTERM");
}
for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => {
    stop();
    process.exit(130);
  });
}

if (!(await answering())) {
  const script = fileURLToPath(new URL("../../scripts/e2e-server.sh", import.meta.url));
  server = spawn(script, { stdio: "inherit" });
  for (let tries = 0; tries < 120 && !(await answering()); tries += 1) {
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  if (!(await answering())) {
    stop();
    throw new Error("The server didn't start; see its output above.");
  }
}

await post("/api/_test/reset");
if (!fresh) await post("/api/_test/seed", { pin: PIN });

const browser = await chromium.launch({ headless: false });
const context = await browser.newContext({
  baseURL: BASE,
  viewport: portrait ? { width: 1080, height: 1920 } : { width: 1920, height: 1080 },
  hasTouch: true,
});
if (!unpaired) {
  const response = await context.request.post("/api/auth/kiosk/pair-with-password", {
    headers: CSRF,
    data: { password: PASSWORD, label: "Wall screen" },
  });
  if (!response.ok()) throw new Error(`Pairing answered ${String(response.status())}`);
}
const page = await context.newPage();
await page.goto("/display");

console.log(
  fresh
    ? `The wall screen is open. Set Sunroom up at ${BASE}/setup in another browser.`
    : `The wall screen is open. Household password: ${PASSWORD}; parent PIN: ${PIN}.` +
        (unpaired ? ` Pair it from ${BASE}/pair after signing in.` : ""),
);
console.log("Close the window to stop.");

await new Promise((resolve) => {
  page.on("close", resolve);
  browser.on("disconnected", resolve);
});
await browser.close().catch(() => undefined);
stop();
