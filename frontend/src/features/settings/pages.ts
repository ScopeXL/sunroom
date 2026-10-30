import type { Key } from "../../lib/lang";

/** Core's Settings pages (UX §4 "Settings (display)", §5 "Settings (phone)"); plugins add
 * their own after Calendars & accounts (SettingsScreens). Each title is a key, said in the
 * page's language where it's shown (ADR 0043). */
export const SETTINGS_PAGES = [
  // Only on a wall run by Sunroom Screen (ADR 0035), and first there, apart from the household's
  // pages (ADR 0039): SettingsScreens drops it elsewhere.
  { key: "this-screen", title: "settings.this_screen.title" },
  { key: "family", title: "settings.family.title" },
  { key: "features", title: "settings.features.title" },
  { key: "calendars", title: "settings.calendars.title" },
  { key: "display", title: "settings.display.title" },
  { key: "household", title: "settings.household.title" },
  { key: "devices", title: "settings.devices.title" },
  { key: "removed", title: "settings.removed.title" },
  { key: "backup", title: "settings.backup.title" },
  { key: "support", title: "settings.support.title" },
  { key: "about", title: "settings.about.title" },
] as const satisfies readonly { key: string; title: Key }[];

export type SettingsPageKey = (typeof SETTINGS_PAGES)[number]["key"];
