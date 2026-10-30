import {
  ArrowLeftRight,
  BookOpen,
  ChevronLeft,
  ChevronRight,
  Copy,
  Plus,
  ShoppingBasket,
} from "lucide-react";
import { useState, type ReactNode } from "react";

import { addDays, shortDate, shortWeekday, dayNumber, weekOf, zonedParts } from "../../lib/dates";
import { useMembers, useSettings, type Member } from "../../lib/household";
import { tRich, useT } from "../../lib/lang";
import { usePageTurn } from "../../lib/motion";
import { useMinute } from "../../lib/time";
import { HeaderLink } from "../../shell/HeaderLinks";
import { RoomHeader } from "../../shell/roomHeader";
import { Avatar } from "../../ui/Avatar";
import { Button } from "../../ui/Button";
import { Chip, ChipRow } from "../../ui/Chip";
import { QuietLine } from "../../ui/EmptyState";
import { useShell } from "../../ui/shell";
import { SidePanel } from "../../ui/SidePanel";
import {
  SLOT_WORDS,
  mealName,
  useAddToGroceries,
  useListsOn,
  useMealChanges,
  useWeek,
  type Entry,
  type Slot,
} from "./data";
import { MealEditor } from "./MealEditor";
import { SavedMeals } from "./SavedMeals";

/** What's open beside the grid: a meal, or an empty spot being filled. */
export type MealPanel =
  | { kind: "meal"; entry: Entry }
  | { kind: "add"; day: string; slot: Slot }
  | { kind: "change"; entry: Entry }
  | null;

/** An empty spot's words, "Add dinner", with the day for a screen reader ("… on Sat, Oct 10"). */
export function addSlotWords(slot: Slot, day: string): ReactNode {
  return tRich("meals.week.add_slot", {
    slot,
    day: shortDate(day),
    sr: (words) => <span className="sr-only">{words}</span>,
  });
}

/** The week the room shows: this week, or `offset` weeks away. */
export function useMealWeek(offset: number) {
  const { data: settings } = useSettings();
  const today = zonedParts(useMinute()).day;
  const days = weekOf(addDays(today, offset * 7), settings?.week_starts_on ?? 6);
  return { today, days, start: days[0] ?? today };
}

/** The Meals room on the wall screen (UX §4): the week's days as rows, the household's meals as
 * columns, today's row lit; or Saved meals. */
export function MealsRoom({ path }: { path: string[] }) {
  return path[0] === "saved" ? <SavedMeals /> : <MealsWeek />;
}

function MealsWeek() {
  const t = useT();
  const [offset, setOffset] = useState(0);
  const pages = usePageTurn();
  const { today, days, start } = useMealWeek(offset);
  const { data: week, isSuccess } = useWeek(start);
  const { data: members = [] } = useMembers();
  const changes = useMealChanges();
  const [panel, setPanel] = useState<MealPanel>(null);
  const slots = week?.slots ?? ["dinner"];
  const entries = week?.entries ?? [];
  const at = (day: string, slot: Slot) =>
    entries.find((entry) => entry.day === day && entry.slot === slot);
  const close = () => {
    setPanel(null);
  };
  return (
    <section aria-label={t("meals.room.title")} className="flex min-h-0 flex-1 flex-col">
      <RoomHeader
        title={t("meals.room.title")}
        controls={
          <>
            <div className="flex items-center gap-2">
              <Button
                variant="secondary"
                icon
                aria-label={t("meals.week.last.aria")}
                onClick={() => {
                  pages.turn(-1);
                  setOffset(offset - 1);
                }}
              >
                <ChevronLeft aria-hidden="true" className="size-8" />
              </Button>
              <Button
                variant="secondary"
                disabled={offset === 0}
                onClick={() => {
                  pages.turn(-offset);
                  setOffset(0);
                }}
              >
                {t("meals.week.this.action")}
              </Button>
              <Button
                variant="secondary"
                icon
                aria-label={t("meals.week.next.aria")}
                onClick={() => {
                  pages.turn(1);
                  setOffset(offset + 1);
                }}
              >
                <ChevronRight aria-hidden="true" className="size-8" />
              </Button>
            </div>
            <div className="ml-auto flex flex-wrap items-center gap-3">
              <Button
                variant="secondary"
                pending={changes.copyWeek.isPending}
                onClick={() => {
                  changes.copyWeek.mutate({ from: addDays(start, -7), to: start });
                }}
              >
                <Copy aria-hidden="true" className="size-7" />
                {t("meals.week.copy.action")}
              </Button>
              <HeaderLink to="/$room/$" params={{ room: "meals", _splat: "saved" }}>
                <BookOpen aria-hidden="true" className="size-7" />
                {t("meals.saved.title")}
              </HeaderLink>
            </div>
          </>
        }
      />
      <div className="min-h-0 flex-1 overflow-y-auto" tabIndex={0}>
        {isSuccess && entries.length === 0 ? (
          <div className="px-6 pt-2">
            <QuietLine>{t("meals.week.empty")}</QuietLine>
          </div>
        ) : null}
        <table {...pages.attrs} className="w-full table-fixed border-collapse">
          <caption className="sr-only">
            {t("meals.week.caption", { day: shortDate(start) })}
          </caption>
          <thead>
            <tr className="border-b border-line">
              <th scope="col" className="w-48">
                <span className="sr-only">{t("meals.week.day.aria")}</span>
              </th>
              {slots.map((slot) => (
                <th
                  key={slot}
                  scope="col"
                  className="px-4 py-3 text-left text-d-secondary font-semibold text-ink-soft"
                >
                  {t(SLOT_WORDS[slot])}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {days.map((day) => (
              <tr
                key={day}
                aria-current={day === today ? "date" : undefined}
                className={`h-30 border-b border-line ${day === today ? "bg-lit" : ""}`}
              >
                <th scope="row" className="px-6 text-left align-middle">
                  <span
                    className={`text-d-title ${day === today ? "font-bold" : "font-semibold text-ink-soft"}`}
                  >
                    {shortWeekday(day)} {dayNumber(day)}
                  </span>
                  {day === today ? (
                    <span className="sr-only"> {t("meals.week.today.aria")}</span>
                  ) : null}
                </th>
                {slots.map((slot) => {
                  const entry = at(day, slot);
                  return (
                    <td key={slot} className="px-2 py-2 align-middle">
                      {entry ? (
                        <MealCell
                          entry={entry}
                          members={members}
                          onOpen={() => {
                            setPanel({ kind: "meal", entry });
                          }}
                        />
                      ) : (
                        <button
                          type="button"
                          onClick={() => {
                            setPanel({ kind: "add", day, slot });
                          }}
                          className="press flex min-h-16 w-full items-center gap-2 rounded-chip-d border-2 border-dashed border-line px-4 text-d-body font-semibold text-ink-soft"
                        >
                          <Plus aria-hidden="true" className="size-6" />
                          {addSlotWords(slot, day)}
                        </button>
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <MealSidePanel panel={panel} days={days} onPanel={setPanel} onClose={close} />
    </section>
  );
}

/** A filled spot: the meal at body size and who cooks. */
function MealCell({
  entry,
  members,
  onOpen,
}: {
  entry: Entry;
  members: Member[];
  onOpen: () => void;
}) {
  const display = useShell() === "display";
  const cook = members.find((m) => m.id === entry.member_id) ?? null;
  return (
    <button
      type="button"
      data-person={cook?.color ?? "everyone"}
      onClick={onOpen}
      className={`press flex w-full items-center gap-3 rounded-chip-d px-4 text-left ${
        cook ? "border-l-[6px] border-p bg-p-tint" : "bg-line/50"
      } ${display ? "min-h-16 py-2" : "min-h-12 py-2"}`}
    >
      <span
        className={`min-w-0 flex-1 break-words ${display ? "text-d-body" : "text-body"} font-semibold`}
      >
        {mealName(entry)}
      </span>
      {cook ? (
        <span className="flex shrink-0 items-center gap-2">
          <Avatar member={cook} size="xs" />
          <span
            className={display ? "text-d-secondary font-semibold" : "text-secondary font-semibold"}
          >
            {cook.name}
          </span>
        </span>
      ) : null}
    </button>
  );
}

/** Beside the grid: a meal (Change, Swap days, Add ingredients to Groceries, Remove), or Add. */
export function MealSidePanel({
  panel,
  days,
  onPanel,
  onClose,
}: {
  panel: MealPanel;
  days: string[];
  onPanel: (panel: MealPanel) => void;
  onClose: () => void;
}) {
  const t = useT();
  const display = useShell() === "display";
  const { data: members = [] } = useMembers();
  const changes = useMealChanges();
  const groceries = useAddToGroceries();
  const listsOn = useListsOn();
  const [swapping, setSwapping] = useState(false);
  const close = () => {
    setSwapping(false);
    onClose();
  };
  const entry = panel?.kind === "meal" || panel?.kind === "change" ? panel.entry : null;
  const cook = members.find((m) => m.id === entry?.member_id) ?? null;
  const text = display ? "text-d-body" : "text-body";
  const title =
    panel?.kind === "add"
      ? t("meals.panel.add.title", { slot: panel.slot })
      : panel?.kind === "change"
        ? t("meals.panel.change.title")
        : entry
          ? mealName(entry)
          : "";
  const footer =
    panel?.kind === "meal" && entry && !swapping ? (
      <div className="flex flex-wrap gap-3">
        <Button
          variant="secondary"
          onClick={() => {
            onPanel({ kind: "change", entry });
          }}
        >
          {t("app.action.change")}
        </Button>
        <Button
          variant="secondary"
          onClick={() => {
            setSwapping(true);
          }}
        >
          <ArrowLeftRight aria-hidden="true" className={display ? "size-7" : "size-5"} />
          {t("meals.panel.swap.action")}
        </Button>
        {listsOn && entry.ingredients.length ? (
          <Button
            variant="secondary"
            pending={groceries.isPending}
            onClick={() => {
              groceries.mutate({ items: entry.ingredients }, { onSuccess: close });
            }}
          >
            <ShoppingBasket aria-hidden="true" className={display ? "size-7" : "size-5"} />
            {t("meals.panel.groceries.action")}
          </Button>
        ) : null}
        <Button
          variant="quiet-danger"
          onClick={() => {
            changes.remove.mutate({ entry }, { onSuccess: close });
          }}
        >
          {t("app.action.remove")}
        </Button>
      </div>
    ) : null;
  return (
    <SidePanel open={panel !== null} title={title} onClose={close} footer={footer}>
      {panel?.kind === "add" ? (
        <MealEditor
          key={`${panel.day}|${panel.slot}`}
          startDay={panel.day}
          startSlot={panel.slot}
          onDone={close}
        />
      ) : panel?.kind === "change" ? (
        <MealEditor key={panel.entry.id} entry={panel.entry} onDone={close} />
      ) : entry ? (
        <div className="flex flex-col gap-4">
          <p className={`${text} font-semibold`}>
            {t("meals.panel.when", { slot: t(SLOT_WORDS[entry.slot]), day: shortDate(entry.day) })}
          </p>
          {cook ? (
            <p className={`flex items-center gap-2 ${text}`}>
              <Avatar member={cook} size="xs" />
              {t("meals.cooks", { name: cook.name })}
            </p>
          ) : null}
          {entry.recipe_url ? (
            <a
              href={entry.recipe_url}
              target="_blank"
              rel="noreferrer noopener"
              className={`${text} font-semibold underline`}
            >
              {t("meals.panel.recipe")}
            </a>
          ) : null}
          {entry.note ? <p className={text}>{entry.note}</p> : null}
          {listsOn && entry.ingredients.length ? (
            <p
              className={
                display ? "text-d-secondary text-ink-soft" : "text-secondary text-ink-soft"
              }
            >
              {entry.ingredients.join(", ")}
            </p>
          ) : null}
          {swapping ? (
            <div className="flex flex-col gap-3">
              <p className={`${text} font-semibold`}>{t("meals.panel.swap.ask")}</p>
              <ChipRow label={t("meals.panel.swap.aria")}>
                {days
                  .filter((day) => day !== entry.day)
                  .map((day) => (
                    <Chip
                      key={day}
                      on={false}
                      onClick={() => {
                        changes.move.mutate({ entry, day }, { onSuccess: close });
                      }}
                    >
                      {shortDate(day)}
                    </Chip>
                  ))}
              </ChipRow>
              <Button
                variant="quiet"
                onClick={() => {
                  setSwapping(false);
                }}
              >
                {t("app.action.cancel")}
              </Button>
            </div>
          ) : null}
        </div>
      ) : null}
    </SidePanel>
  );
}
