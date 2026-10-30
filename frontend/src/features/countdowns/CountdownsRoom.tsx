import { Hourglass, Plus } from "lucide-react";
import { useState } from "react";

import { formatWallTime, shortDate } from "../../lib/dates";
import { useMembers, type Member } from "../../lib/household";
import { t, useT } from "../../lib/lang";
import { RoomHeader } from "../../shell/roomHeader";
import { Avatar } from "../../ui/Avatar";
import { Button } from "../../ui/Button";
import { EmptyState } from "../../ui/EmptyState";
import { Screen } from "../../ui/Screen";
import { Sheet } from "../../ui/Sheet";
import { useShell } from "../../ui/shell";
import { SidePanel } from "../../ui/SidePanel";
import { Pop } from "../../ui/Pop";
import { CountdownEditor } from "./CountdownEditor";
import { useCountdownChanges, useCountdowns, useUpcoming, type Upcoming } from "./data";
import { daysText, turningText } from "./words";

/** "Sat, Oct 10", or "Sat, Oct 10 · 3:00 PM" for a countdown with a time. */
function whenText(item: Upcoming): string {
  const day = shortDate(item.date);
  return item.time
    ? t("countdowns.tile.day_time", { day, time: formatWallTime(`${item.date}T${item.time}`) })
    : day;
}

/** One countdown's tile (UX §4 "Countdowns room"): the days at 72 px, the name, the day and
 * whose it is, in their color. */
function Tile({
  item,
  members,
  onOpen,
}: {
  item: Upcoming;
  members: Member[];
  onOpen: () => void;
}) {
  const t = useT();
  const display = useShell() === "display";
  const person = members.find((m) => m.id === item.member_id) ?? null;
  const color = item.color ?? person?.color ?? "everyone";
  const turning = person?.role === "kid" ? turningText(item.turning) : null;
  return (
    <button
      type="button"
      data-person={color}
      onClick={onOpen}
      className={`press flex w-full flex-col justify-between gap-3 rounded-panel border border-line text-left ${
        color !== "everyone" ? "border-l-[6px] border-l-p bg-p-tint" : "bg-surface"
      } ${display ? "min-h-[17.5rem] p-6" : "min-h-40 p-4"}`}
    >
      <Pop
        value={daysText(item.days)}
        roll
        className={`self-start ${display ? "text-d-big" : "text-[2.5rem] leading-none"} font-extrabold text-p-text`}
      />
      <span className="flex flex-col gap-1">
        <span className={`${display ? "text-d-title" : "text-row"} font-bold break-words`}>
          {item.emoji ? `${item.emoji} ` : ""}
          {item.title}
        </span>
        <span
          className={display ? "text-d-secondary text-ink-soft" : "text-secondary text-ink-soft"}
        >
          {whenText(item)}
          {turning ? ` · ${turning}` : ""}
        </span>
      </span>
      <span className="flex items-center gap-2">
        <Avatar member={person} size={display ? "sm" : "xs"} />
        <span
          className={display ? "text-d-secondary font-semibold" : "text-secondary font-semibold"}
        >
          {person?.name ?? t("ui.who.everyone")}
        </span>
      </span>
    </button>
  );
}

/** What a tapped tile opens: a countdown's Change and Remove, or where a birthday comes from. */
function Details({ item, onClose }: { item: Upcoming | null; onClose: () => void }) {
  const t = useT();
  const display = useShell() === "display";
  const { data: countdowns = [] } = useCountdowns();
  const changes = useCountdownChanges();
  const [changing, setChanging] = useState(false);
  const countdown = countdowns.find((c) => c.id === item?.countdown_id);
  const close = () => {
    setChanging(false);
    onClose();
  };
  const text = display ? "text-d-body" : "text-body";
  return (
    <SidePanel
      open={item !== null}
      title={changing ? t("countdowns.details.change.title") : (item?.title ?? "")}
      onClose={close}
      footer={
        countdown && !changing ? (
          <div className="flex flex-wrap gap-3">
            <Button
              variant="secondary"
              onClick={() => {
                setChanging(true);
              }}
            >
              {t("app.action.change")}
            </Button>
            <Button
              variant="quiet-danger"
              onClick={() => {
                changes.remove.mutate({ countdown }, { onSuccess: close });
              }}
            >
              {t("app.action.remove")}
            </Button>
          </div>
        ) : null
      }
    >
      {changing && countdown ? (
        <CountdownEditor countdown={countdown} onDone={close} />
      ) : item ? (
        <div className="flex flex-col gap-3">
          <p className={`${text} font-semibold`}>{`${daysText(item.days)} · ${whenText(item)}`}</p>
          {item.kind === "birthday" ? (
            <p className={`${text} text-ink-soft`}>{t("countdowns.details.birthday")}</p>
          ) : null}
          {countdown?.repeat_yearly ? (
            <p className={`${text} text-ink-soft`}>{t("countdowns.every_year")}</p>
          ) : null}
          {countdown && !countdown.show_on_display ? (
            <p className={`${text} text-ink-soft`}>{t("countdowns.details.hidden")}</p>
          ) : null}
        </div>
      ) : null}
    </SidePanel>
  );
}

function Tiles({ onAdd }: { onAdd: () => void }) {
  const t = useT();
  const display = useShell() === "display";
  const { data, isSuccess } = useUpcoming();
  const { data: members = [] } = useMembers();
  const [open, setOpen] = useState<Upcoming | null>(null);
  const items = data?.items ?? [];
  return (
    <>
      {isSuccess && items.length === 0 ? (
        <EmptyState
          icon={Hourglass}
          line={t("countdowns.empty")}
          note={t("countdowns.empty_note")}
          // A phone's bottom bar already has Add Countdown.
          action={
            display ? <Button onClick={onAdd}>{t("countdowns.add.action")}</Button> : undefined
          }
        />
      ) : (
        <ul
          aria-label={t("countdowns.room.title")}
          className={`grid gap-6 ${
            display
              ? "grid-cols-[repeat(auto-fill,minmax(25rem,1fr))]"
              : "grid-cols-1 gap-3 sm:grid-cols-2"
          }`}
        >
          {items.map((item) => (
            <li key={item.key}>
              <Tile
                item={item}
                members={members}
                onOpen={() => {
                  setOpen(item);
                }}
              />
            </li>
          ))}
        </ul>
      )}
      <Details
        item={open}
        onClose={() => {
          setOpen(null);
        }}
      />
    </>
  );
}

/** The Countdowns room on the wall screen (UX §4): tiles, soonest first. */
export function CountdownsRoom() {
  const t = useT();
  const [adding, setAdding] = useState(false);
  return (
    <section aria-label={t("countdowns.room.title")} className="flex min-h-0 flex-1 flex-col">
      <RoomHeader
        title={t("countdowns.room.title")}
        controls={
          <Button
            variant="secondary"
            className="ml-auto"
            onClick={() => {
              setAdding(true);
            }}
          >
            <Plus aria-hidden="true" className="size-7" />
            {t("countdowns.add.action")}
          </Button>
        }
      />
      <div className="min-h-0 flex-1 overflow-y-auto p-6" tabIndex={0}>
        <Tiles
          onAdd={() => {
            setAdding(true);
          }}
        />
      </div>
      <SidePanel
        open={adding}
        title={t("countdowns.add.title")}
        onClose={() => {
          setAdding(false);
        }}
      >
        {adding ? (
          <CountdownEditor
            onDone={() => {
              setAdding(false);
            }}
          />
        ) : null}
      </SidePanel>
    </section>
  );
}

/** Countdowns on a phone (from More): the same tiles, and Add countdown. An event's "Add a
 * countdown" opens it at new/<day>/<title>, with those filled in. */
export function CountdownsTab({ path }: { path: string[] }) {
  const t = useT();
  const [verb, day, title] = path;
  const [adding, setAdding] = useState(verb === "new");
  return (
    <Screen
      title={t("countdowns.room.title")}
      back="/more"
      actions={
        <Button
          block
          onClick={() => {
            setAdding(true);
          }}
        >
          {t("countdowns.add.action")}
        </Button>
      }
    >
      <Tiles
        onAdd={() => {
          setAdding(true);
        }}
      />
      <Sheet
        open={adding}
        title={t("countdowns.add.title")}
        onClose={() => {
          setAdding(false);
        }}
      >
        {adding ? (
          <CountdownEditor
            startDay={verb === "new" && day ? day : null}
            startTitle={verb === "new" && title ? decodeURIComponent(title) : ""}
            onDone={() => {
              setAdding(false);
            }}
          />
        ) : null}
      </Sheet>
    </Screen>
  );
}
