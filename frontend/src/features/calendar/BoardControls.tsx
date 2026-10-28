import { ChevronLeft, ChevronRight, Clock3, List } from "lucide-react";

import type { BoardView, WeekLayout } from "../../lib/displayState";
import type { Member } from "../../lib/household";
import { Button } from "../../ui/Button";
import { IconSegmented, type IconSegmentOption } from "../../ui/Segmented";
import { FilterButton } from "./FilterButton";
import { ViewSwitch } from "./ViewSwitch";

const LAYOUTS: IconSegmentOption<WeekLayout>[] = [
  { value: "agenda", label: "Agenda", icon: List },
  { value: "hours", label: "Hours", icon: Clock3 },
];

/**
 * The Calendar room's part of the wall's header (UX §3, ADR 0030, ADR 0042). After today: the
 * arrows around "This Week" (or Today on the Day and People views, This Month) and, on the two
 * week views, their layout as two icons (Agenda · Hours), beside the arrows because they change
 * the same board they page. At the right: Filter (the people), then the View button, on every
 * view. No month and no span: the day heads carry the dates, and the Month, Day and People views
 * name their own. People and Today don't filter; the Today view has no arrows (`paging`): it is
 * always today and the six days after.
 */
export function BoardControls({
  view,
  onView,
  paging = true,
  homeLabel,
  atHome,
  onPage,
  onHome,
  layout,
  onLayout,
  members,
  people,
  onPeople,
}: {
  view: BoardView;
  onView: (view: BoardView) => void;
  /** The arrows and the quick jump; off where there's nothing to page (ADR 0036). */
  paging?: boolean;
  homeLabel: string;
  atHome: boolean;
  onPage: (step: -1 | 1) => void;
  onHome: () => void;
  layout: WeekLayout;
  onLayout: (layout: WeekLayout) => void;
  members: Member[];
  people: string[];
  onPeople: (people: string[]) => void;
}) {
  // The arrows say what they step: People pages a day, as Day does.
  const span = view === "month" ? "month" : view === "day" || view === "people" ? "day" : "week";
  return (
    <>
      {paging ? (
        <div className="flex items-center gap-2">
          <Button
            variant="secondary"
            icon
            aria-label={`Previous ${span}`}
            onClick={() => {
              onPage(-1);
            }}
          >
            <ChevronLeft aria-hidden="true" className="size-8" />
          </Button>
          <Button variant="secondary" disabled={atHome} onClick={onHome}>
            {homeLabel}
          </Button>
          <Button
            variant="secondary"
            icon
            aria-label={`Next ${span}`}
            onClick={() => {
              onPage(1);
            }}
          >
            <ChevronRight aria-hidden="true" className="size-8" />
          </Button>
        </div>
      ) : null}
      {view === "week" || view === "rolling" ? (
        <IconSegmented label="Week layout" value={layout} onChange={onLayout} options={LAYOUTS} />
      ) : null}
      <div className="ml-auto flex items-center gap-4">
        {view !== "people" && view !== "today" ? (
          <FilterButton members={members} people={people} onPeople={onPeople} />
        ) : null}
        <ViewSwitch view={view} onView={onView} />
      </div>
    </>
  );
}
