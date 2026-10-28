/// <reference types="vitest/config" />
import { readFileSync } from "node:fs";

import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { VitePWA } from "vite-plugin-pwa";

// The single source of truth for the version is the repo's VERSION file (Dinner Bell's ADR 0019).
const version = readFileSync(new URL("../VERSION", import.meta.url), "utf8").trim();

export default defineConfig({
  define: {
    __APP_VERSION__: JSON.stringify(version),
  },
  plugins: [
    react(),
    tailwindcss(),
    VitePWA({
      strategies: "injectManifest",
      srcDir: "src",
      filename: "sw.ts",
      registerType: "prompt",
      injectRegister: false,
      injectManifest: {
        globPatterns: ["**/*.{js,css,html,woff2,png,svg,webmanifest}"],
      },
      devOptions: { enabled: false },
      manifest: {
        name: "Sunroom",
        short_name: "Sunroom",
        description: "The family calendar on the wall, and on everyone's devices.",
        start_url: "/",
        scope: "/",
        display: "standalone",
        background_color: "#f5f5f2",
        theme_color: "#f5f5f2",
        icons: [
          { src: "/icons/icon-192.png", sizes: "192x192", type: "image/png" },
          { src: "/icons/icon-512.png", sizes: "512x512", type: "image/png" },
          {
            src: "/icons/icon-maskable-512.png",
            sizes: "512x512",
            type: "image/png",
            purpose: "maskable",
          },
        ],
      },
    }),
  ],
  server: {
    port: 5173,
    proxy: {
      // The Host rule accepts localhost:5173, and the CSRF check compares Origin with it.
      "/api": { target: "http://127.0.0.1:8080", changeOrigin: false },
      // The photo files only: /photos itself is the Photos room, which Vite serves.
      "^/photos/": { target: "http://127.0.0.1:8080", changeOrigin: false },
    },
  },
  build: {
    sourcemap: false,
  },
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.{ts,tsx}"],
    // tokens.test.ts reads tokens.css?raw; Vitest otherwise replaces CSS with an empty module.
    css: { include: [/tokens\.css/] },
  },
});
