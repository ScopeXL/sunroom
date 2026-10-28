import {
  Calendar1,
  CalendarDays,
  CalendarRange,
  ChevronDown,
  CalendarSync,
  Sun,
  Users,
  type LucideIcon,
} from "lucide-react";

import type { BoardView } from "../../lib/displayState";
import { Menu, MenuRadio } from "../../ui/Menu";
import { VIEW_ART } from "./viewArt";

interface ViewChoice {
  value: BoardView;
  label: string;
  /** One line on what it shows, under its name in the menu. */
  line: string;
  icon: LucideIcon;
}

/** The board's views, in the menu's order (ADR 0042). */
export const VIEWS: readonly ViewChoice[] = [
  {
    value: "week",
    label: "Week",
    line: "The calendar week, a column for each day.",
    icon: CalendarRange,
  },
  {
    value: "rolling",
    label: "Rolling Week",
    line: "Yesterday, today and the five days after.",
    icon: CalendarSync,
  },
  { value: "day", label: "Day", line: "One day, hour by hour.", icon: Calendar1 },
  {
    value: "month",
    label: "Month",
    line: "The whole month. Tap a day to open it.",
    icon: CalendarDays,
  },
  {
    value: "people",
    label: "People",
    line: "A column for each person, one day at a time.",
    icon: Users,
  },
  { value: "today", label: "Today", line: "Today at a glance, then the days ahead.", icon: Sun },
];

/**
 * The board's views in the wall's header (UX §3, ADR 0042): one **View** button in every width,
 * the Filter button's shape, with the view's icon, its word and a chevron, named "View: Week".
 * It opens a menu of the six views, each with a small drawing of the board, its name and one
 * line; the chosen one is filled with ink. Today is among them, so a screen on Today can leave it
 * from the header.
 */
export function ViewSwitch({
  view,
  onView,
}: {
  view: BoardView;
  onView: (view: BoardView) => void;
}) {
  const current = VIEWS.find((option) => option.value === view) ?? VIEWS[0];
  const CurrentIcon = current?.icon ?? CalendarRange;
  return (
    <Menu
      label="View"
      className="min-w-[30rem]"
      trigger={(props) => (
        // Not ui/Button: its padding is fixed, and this matches Filter's shape beside it.
        <button
          type="button"
          {...props}
          aria-label={`View: ${current?.label ?? ""}`}
          className="press inline-flex h-tap shrink-0 items-center gap-2 rounded-button-d border-2 border-line bg-surface px-5 text-d-body font-semibold active:bg-wall"
        >
          <CurrentIcon aria-hidden="true" className="size-8 shrink-0" />
          {current?.label}
          <ChevronDown aria-hidden="true" className="size-7 shrink-0 text-ink-soft" />
        </button>
      )}
    >
      {VIEWS.map(({ value, label, line }) => {
        const Art = VIEW_ART[value];
        return (
          <MenuRadio
            key={value}
            checked={value === view}
            drawing={<Art />}
            detail={line}
            onChoose={() => {
              onView(value);
            }}
          >
            {label}
          </MenuRadio>
        );
      })}
    </Menu>
  );
}
