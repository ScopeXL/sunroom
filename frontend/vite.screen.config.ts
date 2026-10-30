/// <reference types="vitest/config" />
import { readFileSync } from "node:fs";

import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig, searchForWorkspaceRoot } from "vite";

// The screen's own pages (src/screen, ADR 0035): the same tokens, type and parts as the wall,
// built into Sunroom Screen's package, which serves them on 127.0.0.1. No service worker: the
// agent is on the same machine, and these pages are what shows when Sunroom can't.
const version = readFileSync(new URL("../VERSION", import.meta.url), "utf8").trim();

export default defineConfig({
  define: {
    __APP_VERSION__: JSON.stringify(version),
  },
  plugins: [react(), tailwindcss()],
  // public/ holds the PWA's files (its worker, manifest and icons): none of them are the screen's.
  publicDir: false,
  build: {
    outDir: "../kiosk/agent/src/sunroom_kiosk/static",
    emptyOutDir: true,
    sourcemap: false,
    rollupOptions: { input: "screen.html" },
  },
  server: {
    // just kiosk-dev: Vite on 5174, the pretend agent on 7800 behind it.
    port: 5174,
    // The words live beside the app, in the repo's lang/ (ADR 0043).
    fs: { allow: [searchForWorkspaceRoot(process.cwd()), "../lang"] },
    proxy: {
      // The agent answers only its own Host; it lets this page's origin in with --dev.
      "/api/screen": { target: "http://127.0.0.1:7800", changeOrigin: true },
    },
  },
});
