/**
 * How Settings → Backup words its copies (UX §4, ADR 0034): when each was made, in the
 * household's zone and clock, what made it, and how big it is, in the page's language.
 */
import type { components } from "../../api/schema";
import { formatTime, monthDay, shortDate, zonedParts } from "../../lib/dates";
import { t, type Key } from "../../lib/lang";

export type BackupCopy = components["schemas"]["BackupFileOut"];

const KIND_WORDS: Record<BackupCopy["kind"], Key> = {
  nightly: "settings.backup.kind.nightly",
  "pre-migrate": "settings.backup.kind.pre_migrate",
  "pre-erase": "settings.backup.kind.pre_erase",
  "pre-restore": "settings.backup.kind.pre_restore",
};

/** "Wed, Oct 7, 3:30 AM". */
export function copyWhen(iso: string): string {
  const moment = new Date(iso);
  return `${shortDate(zonedParts(moment).day)}, ${formatTime(moment)}`;
}

/** "Oct 7", for the toast that says which went. */
export function copyDay(iso: string): string {
  return monthDay(zonedParts(new Date(iso)).day);
}

/** "820 KB", "4.2 MB", "1.3 GB". */
export function sizeWords(bytes: number): string {
  if (bytes < 1024 ** 2) {
    return t("settings.backup.size.kb", { n: String(Math.max(1, Math.round(bytes / 1024))) });
  }
  if (bytes < 1024 ** 3) return t("settings.backup.size.mb", { n: (bytes / 1024 ** 2).toFixed(1) });
  return t("settings.backup.size.gb", { n: (bytes / 1024 ** 3).toFixed(1) });
}

/** "Nightly · 4.2 MB", "Before an upgrade · 4.1 MB". */
export function copyDetail(copy: BackupCopy): string {
  return `${t(KIND_WORDS[copy.kind])} · ${sizeWords(copy.bytes)}`;
}

/** "14 days", "1 day"; "8 weeks", "None". */
export function daysWords(days: number): string {
  return t("settings.backup.days", { n: days });
}

export function weeksWords(weeks: number): string {
  return t("settings.backup.weeks", { n: weeks });
}
