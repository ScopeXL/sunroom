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
import { useT, type Key } from "../../lib/lang";
import { Menu, MenuRadio } from "../../ui/Menu";
import { VIEW_ART } from "./viewArt";

interface ViewChoice {
  value: BoardView;
  label: Key;
  /** One line on what it shows, under its name in the menu. */
  line: Key;
  icon: LucideIcon;
}

/** The board's views, in the menu's order (ADR 0042), with their words' keys. */
export const VIEWS: readonly ViewChoice[] = [
  {
    value: "week",
    label: "calendar.view.week.title",
    line: "calendar.view.week.hint",
    icon: CalendarRange,
  },
  {
    value: "rolling",
    label: "calendar.view.rolling.title",
    line: "calendar.view.rolling.hint",
    icon: CalendarSync,
  },
  {
    value: "day",
    label: "calendar.view.day.title",
    line: "calendar.view.day.hint",
    icon: Calendar1,
  },
  {
    value: "month",
    label: "calendar.view.month.title",
    line: "calendar.view.month.hint",
    icon: CalendarDays,
  },
  {
    value: "people",
    label: "calendar.view.people.title",
    line: "calendar.view.people.hint",
    icon: Users,
  },
  {
    value: "today",
    label: "calendar.view.today.title",
    line: "calendar.view.today.hint",
    icon: Sun,
  },
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
  const t = useT();
  const current = VIEWS.find((option) => option.value === view) ?? VIEWS[0];
  const CurrentIcon = current?.icon ?? CalendarRange;
  const name = current ? t(current.label) : "";
  return (
    <Menu
      label={t("calendar.view.menu.aria")}
      className="min-w-[30rem]"
      trigger={(props) => (
        // Not ui/Button: its padding is fixed, and this matches Filter's shape beside it.
        <button
          type="button"
          {...props}
          aria-label={t("calendar.view.button.aria", { view: name })}
          className="press inline-flex h-tap shrink-0 items-center gap-2 rounded-button-d border-2 border-line bg-surface px-5 text-d-body font-semibold active:bg-wall"
        >
          <CurrentIcon aria-hidden="true" className="size-8 shrink-0" />
          {name}
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
            detail={t(line)}
            onChoose={() => {
              onView(value);
            }}
          >
            {t(label)}
          </MenuRadio>
        );
      })}
    </Menu>
  );
}
