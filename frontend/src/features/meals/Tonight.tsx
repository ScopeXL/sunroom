import { useNavigate } from "@tanstack/react-router";

import { zonedParts } from "../../lib/dates";
import { useMembers } from "../../lib/household";
import { useT } from "../../lib/lang";
import { useMinute } from "../../lib/time";
import { Avatar } from "../../ui/Avatar";
import { mealName, useWeek } from "./data";

/** Tonight's dinner, and who cooks. */
function useTonight() {
  const today = zonedParts(useMinute()).day;
  const { data } = useWeek(today, 1);
  const { data: members = [] } = useMembers();
  const dinner = data?.entries.find((entry) => entry.slot === "dinner");
  const cook = members.find((member) => member.id === dinner?.member_id) ?? null;
  return { dinner, cook };
}

/** The Today panel's Tonight (UX §1: a glance element): tonight's dinner and who cooks, on one
 * line in portrait's band. A tap opens Meals. Nothing shows when there's no dinner planned. */
export function TonightWall({ band = false }: { band?: boolean }) {
  const t = useT();
  const { dinner, cook } = useTonight();
  const navigate = useNavigate();
  if (!dinner) return null;
  return (
    <section aria-labelledby="today-tonight" className="flex flex-col gap-2">
      <h2 id="today-tonight" className="text-d-body font-bold text-ink-soft">
        {t("meals.tonight.title")}
      </h2>
      <button
        type="button"
        data-person={cook?.color ?? "everyone"}
        onClick={() => {
          void navigate({ to: "/$room", params: { room: "meals" } });
        }}
        className="press-row -mx-3 flex min-h-16 items-center gap-3 rounded-chip-d px-3 py-2 text-left"
      >
        <span
          className={`flex min-w-0 flex-1 ${band ? "flex-wrap items-baseline gap-x-3" : "flex-col"}`}
        >
          <span className={`${band ? "text-d-title" : "text-d-glance"} font-bold break-words`}>
            {mealName(dinner)}
          </span>
          {cook ? (
            <span className="text-d-secondary font-semibold text-ink-soft">
              {t("meals.cooks", { name: cook.name })}
            </span>
          ) : null}
        </span>
        {cook ? <Avatar member={cook} size="sm" /> : null}
      </button>
    </section>
  );
}

/** Today on a phone: "Tonight · Tacos · Sam cooks". */
export function TonightPhone() {
  const t = useT();
  const { dinner, cook } = useTonight();
  const navigate = useNavigate();
  if (!dinner) return null;
  return (
    <section aria-labelledby="phone-tonight" className="flex flex-col gap-1">
      <h2 id="phone-tonight" className="text-row font-bold text-ink-soft">
        {t("meals.tonight.title")}
      </h2>
      <button
        type="button"
        onClick={() => {
          void navigate({ to: "/$room", params: { room: "meals" } });
        }}
        className="press-row flex min-h-12 items-center justify-between gap-3 rounded-chip px-1 text-left"
      >
        <span className="text-row font-bold">{mealName(dinner)}</span>
        {cook ? (
          <span className="text-secondary text-ink-soft">
            {t("meals.cooks", { name: cook.name })}
          </span>
        ) : null}
      </button>
    </section>
  );
}
