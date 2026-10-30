import js from "@eslint/js";
import pluginQuery from "@tanstack/eslint-plugin-query";
import pluginRouter from "@tanstack/eslint-plugin-router";
import { defineConfig } from "eslint/config";
import i18next from "eslint-plugin-i18next";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";
import tseslint from "typescript-eslint";

export default defineConfig(
  {
    ignores: [
      "dist",
      "dev-dist",
      "node_modules",
      "playwright-report",
      "test-results",
      "src/api/schema.d.ts",
      "src/api/screen-schema.d.ts",
    ],
  },
  js.configs.recommended,
  tseslint.configs.strictTypeChecked,
  tseslint.configs.stylisticTypeChecked,
  {
    languageOptions: {
      parserOptions: { projectService: true, tsconfigRootDir: import.meta.dirname },
      globals: globals.browser,
    },
  },
  reactHooks.configs.flat["recommended-latest"],
  pluginQuery.configs["flat/recommended"],
  pluginRouter.configs["flat/recommended"],
  {
    rules: {
      "@typescript-eslint/restrict-template-expressions": ["error", { allowNumber: true }],
      // TanStack Router's redirect() is meant to be thrown from beforeLoad.
      "@typescript-eslint/only-throw-error": [
        "error",
        { allow: [{ from: "package", package: "@tanstack/router-core", name: "Redirect" }] },
      ],
    },
  },
  {
    // Every word the family reads comes from lang/en.json through t() (ADR 0043,
    // docs/LANGUAGES.md): JSX text and the props that carry words are never literals, anywhere
    // in src/ (e2e/lang.spec.ts looks at the screens themselves, in the pseudo language).
    files: ["src/**/*.tsx"],
    ignores: ["src/**/*.test.tsx"],
    plugins: { i18next },
    rules: {
      "i18next/no-literal-string": [
        "error",
        {
          mode: "jsx-only",
          "jsx-attributes": {
            include: [
              "aria-label",
              "aria-valuetext",
              "placeholder",
              "alt",
              "label",
              "lead",
              "hint",
              "note",
              "title",
              "heading",
              "name",
              "text",
              "act",
              "keep",
              "action",
              "submit",
              "options",
              "choices",
            ],
          },
          words: {
            exclude: [
              // Digits, punctuation and the glyphs the app writes between words (· — … × →).
              "[\\s0-9!-/:-@[-`{-~·—–…%×→←↑↓✕−]+",
              "[A-Z_-]+",
              /^\p{Emoji}+$/u,
            ],
          },
          callees: { exclude: ["t", "tRich", "tPlugin", "tFamily", "require", "includes"] },
        },
      ],
    },
  },
  {
    files: [
      "vite.config.ts",
      "vite.screen.config.ts",
      "playwright.config.ts",
      "e2e/**",
      "scripts/**",
    ],
    languageOptions: { globals: globals.node },
  },
  {
    files: ["**/*.js", "**/*.mjs"],
    extends: [tseslint.configs.disableTypeChecked],
    languageOptions: { globals: globals.node },
  },
  {
    // A classic script the page loads before anything paints (public/theme-boot.js).
    files: ["public/**/*.js"],
    languageOptions: { globals: globals.browser, sourceType: "script" },
  },
);
