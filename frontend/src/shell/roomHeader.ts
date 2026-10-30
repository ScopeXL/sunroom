/**
 * What the room on screen puts in the wall's header (shell/Header, UX §3, ADR 0030): its name, a
 * way back, and its own controls. A room the rail already names (Calendar, Lists, Tasks…) keeps
 * its name for screen readers only; a page the rail can't name (a list, Saved Meals) shows it,
 * on one line, after its way back. Nothing has a second line: a count or a span belongs in the
 * page. A store, not a portal: a portal
 * needs the header's node before the room first renders, and the kiosk remounts the shell
 * between /display and the rooms, which would blank it each time. A store set in a layout effect
 * is there before the first paint, lives outside React, and the header is its only subscriber.
 */
import { useLayoutEffect, type ReactNode } from "react";

import { createStore } from "../lib/store";

export interface RoomHeaderSpec {
  /** The page's h1. Read to a screen reader always; drawn only with `visibleTitle`. */
  title: string;
  /** Draw the title: a page the rail doesn't name (a list, Saved Meals, Stars & Rewards). */
  visibleTitle?: boolean | undefined;
  /** A quiet pill in the header for a moment ("Drop on a day"). */
  notice?: string | null | undefined;
  /** A link back to the room this one belongs to ("‹ Lists"), before the title. */
  back?: ReactNode;
  /** The room's own buttons; put `ml-auto` on what belongs at the right. */
  controls?: ReactNode;
}

export const roomHeader = createStore<RoomHeaderSpec | null>(null);

/** Hand this room's title and controls to the header for as long as the room is on screen. */
export function useRoomHeader(spec: RoomHeaderSpec): void {
  // Every render: the controls close over the room's latest state.
  useLayoutEffect(() => {
    roomHeader.set(spec);
  });
  // Leaving: cleared before the next room's own layout effect sets its title.
  useLayoutEffect(
    () => () => {
      roomHeader.set(null);
    },
    [],
  );
}

/** The same as an element, for a room whose title is fixed: `<RoomHeader title={t(…)} />`. */
export function RoomHeader(spec: RoomHeaderSpec): null {
  useRoomHeader(spec);
  return null;
}
