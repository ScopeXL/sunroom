import { defineConfig, devices } from "@playwright/test";

const PORT = 4173;
const BASE_URL = `http://127.0.0.1:${PORT}`;
const ci = Boolean(process.env.CI);

/**
 * End-to-end tests run against the production build served by the real backend (test mode,
 * throwaway data). The wall screen at 1080p and in portrait (touch, Chromium), phones on WebKit
 * and Chromium, and a laptop (PLAN §14.6). Tests share one server and reset it before each
 * test, so they run one at a time.
 */
export default defineConfig({
  testDir: "e2e",
  outputDir: "test-results",
  fullyParallel: false,
  workers: 1,
  forbidOnly: ci,
  retries: 0, // a test that fails once gets fixed, not retried
  // GitHub's 4-CPU runner is several times slower than the build Mac: the long journeys (each
  // marks itself slow, three times this) timed out at Playwright's default 30 s there.
  timeout: 60_000,
  // Locally one line that shows a failure when it happens; CI keeps a test per line and a report.
  reporter: ci ? [["list"], ["html", { open: "never" }]] : "line",
  use: {
    baseURL: BASE_URL,
    trace: "retain-on-failure",
    // The household's zone in these runs; the setup wizard suggests the browser's own.
    timezoneId: "America/New_York",
    locale: "en-US",
  },
  projects: [
    {
      name: "display-1080p",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1920, height: 1080 },
        hasTouch: true,
      },
    },
    {
      name: "display-portrait",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1080, height: 1920 },
        hasTouch: true,
      },
    },
    {
      name: "phone-webkit",
      use: { ...devices["iPhone 13"], viewport: { width: 390, height: 844 } },
    },
    {
      name: "phone-chromium",
      use: { ...devices["Pixel 7"], viewport: { width: 390, height: 844 } },
    },
    {
      name: "desktop",
      use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } },
    },
  ],
  webServer: {
    command: "../scripts/e2e-server.sh",
    url: `${BASE_URL}/api/health`,
    reuseExistingServer: !ci,
    timeout: 60_000,
  },
});
