/**
 * What a photo library says (UX §4 "Photo Libraries", ADR 0036): the sentence under What to Show,
 * which says plainly what the screensaver shows, and the line under a library's name. The words
 * are lang/en.json's (ADR 0043).
 */
import { formatTime } from "../../lib/dates";
import { t } from "../../lib/lang";

interface Choice {
  id: string;
  name: string;
}

interface Picks {
  people: readonly string[];
  albums: readonly string[];
  tags: readonly string[];
}

interface Choices {
  people: readonly Choice[];
  albums: readonly Choice[];
  tags: readonly Choice[];
}

/** "1,000" */
export function count(value: number): string {
  return value.toLocaleString("en-US");
}

/** "Mia", "Mia or Leo", "Mia, Leo or Sam". */
function orList(names: readonly string[]): string {
  if (names.length <= 1) return names[0] ?? "";
  return t("photos.picks.or", { names: names.slice(0, -1).join(", "), last: names.at(-1) ?? "" });
}

/** The picks' names from the choices; an id the library no longer has is "one that's gone". */
function named(ids: readonly string[], from: readonly Choice[]): string {
  const names = ids.flatMap((id) => from.find((choice) => choice.id === id)?.name ?? []);
  const gone = ids.length - names.length;
  if (gone) names.push(t("photos.picks.gone", { n: gone }));
  return orList(names);
}

/**
 * What the screensaver shows from a library, in a sentence: "Showing every photo, newest first,
 * up to 500. Pick people, albums or tags to narrow it." or "Showing photos of Mia or Leo, or in
 * Beach 2026, or tagged Wall, newest first, up to 500." (any pick matches).
 */
export function picksSentence(picks: Picks, choices: Choices | undefined, limit: number): string {
  if (!picks.people.length && !picks.albums.length && !picks.tags.length) {
    return t("photos.picks.every", { limit });
  }
  const parts: string[] = [];
  if (picks.people.length) {
    parts.push(t("photos.picks.people", { names: named(picks.people, choices?.people ?? []) }));
  }
  if (picks.albums.length) {
    parts.push(t("photos.picks.albums", { names: named(picks.albums, choices?.albums ?? []) }));
  }
  if (picks.tags.length) {
    parts.push(t("photos.picks.tags", { names: named(picks.tags, choices?.tags ?? []) }));
  }
  // "of Mia, or in Beach 2026, or tagged Wall": any of them matches.
  const either = parts.reduce((all, part) => t("photos.picks.also", { picks: all, more: part }));
  return t("photos.picks.showing", { picks: either, limit });
}

interface LibraryState {
  status: string;
  checking: boolean;
  pending: number;
  photo_count: number;
  last_scan_at: string | null;
  last_error: string | null;
}

/**
 * The line under a library's name: how it's doing. ``trouble`` when it's a problem a parent can
 * fix (drawn in red): "Needs its key again", the server's silence, a full disk.
 */
export function libraryLine(library: LibraryState): { text: string; trouble: boolean } {
  if (library.status === "needs_reconnect") {
    return { text: t("photos.library.line.needs_key"), trouble: true };
  }
  if (library.status === "error") {
    return { text: library.last_error ?? t("photos.library.line.no_answer"), trouble: true };
  }
  if (library.pending > 0) {
    return {
      text: t("photos.library.line.bringing", {
        done: library.photo_count,
        total: library.photo_count + library.pending,
      }),
      trouble: false,
    };
  }
  if (library.checking) return { text: t("photos.library.line.checking"), trouble: false };
  if (library.last_error) return { text: library.last_error, trouble: true };
  if (!library.last_scan_at) return { text: t("photos.not_checked"), trouble: false };
  return {
    text: t("photos.library.line.checked", {
      time: formatTime(new Date(library.last_scan_at)),
      n: library.photo_count,
    }),
    trouble: false,
  };
}

/** "Connected · Immich 2.7 · 12,345 photos" (the count when the server said). */
export function connectedLine(
  library: { version: string | null; library_photos: number | null },
  kindName: string,
): string {
  const server = library.version
    ? `${kindName} ${library.version.split(".").slice(0, 2).join(".")}`
    : kindName;
  return library.library_photos !== null
    ? t("photos.library.connected_count", { server, n: library.library_photos })
    : t("photos.library.connected", { server });
}
