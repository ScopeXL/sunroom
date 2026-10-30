import { useNavigate } from "@tanstack/react-router";

import { shortWeekday, zonedParts } from "../../lib/dates";
import { useMembers } from "../../lib/household";
import { t, useT } from "../../lib/lang";
import { useMinute } from "../../lib/time";
import { Avatar } from "../../ui/Avatar";
import { useTodo, type TodoItem } from "./data";

/** "Call the plumber · To do", "since Mon" for one that's late. */
function detailOf(item: TodoItem, today: string): string {
  const late =
    item.due_date && item.due_date < today
      ? t("lists.todo.since", { day: shortWeekday(item.due_date) })
      : "";
  return [item.list_name, late].filter(Boolean).join(" · ");
}

/** The Today panel's To do (UX §3): items due today, and late ones; a line opens its list. */
export function TodoBlockWall({ band = false }: { band?: boolean }) {
  const t = useT();
  const today = zonedParts(useMinute()).day;
  const { data } = useTodo(today);
  const { data: members = [] } = useMembers();
  const navigate = useNavigate();
  const items = data?.items ?? [];
  if (!items.length) return null;
  return (
    <section aria-labelledby="today-todo" className="flex flex-col gap-2">
      <h2 id="today-todo" className="text-d-body font-bold text-ink-soft">
        {t("lists.todo.title")}
      </h2>
      {items.map((item) => {
        const who = members.find((m) => m.id === item.assigned_member_id);
        return (
          <button
            key={item.id}
            type="button"
            onClick={() => {
              void navigate({ to: "/$room/$", params: { room: "lists", _splat: item.list_id } });
            }}
            className="press-row -mx-3 flex min-h-16 items-center gap-3 rounded-chip-d px-3 py-2 text-left"
          >
            <span className="flex min-w-0 flex-1 flex-col">
              <span className="text-d-body font-semibold break-words">{item.text}</span>
              {band ? null : (
                <span className="text-d-secondary text-ink-soft">{detailOf(item, today)}</span>
              )}
            </span>
            {who ? <Avatar member={who} size="sm" /> : null}
          </button>
        );
      })}
    </section>
  );
}

/** Today on a phone: the same To do (UX §5). */
export function TodoBlockPhone() {
  const t = useT();
  const today = zonedParts(useMinute()).day;
  const { data } = useTodo(today);
  const { data: members = [] } = useMembers();
  const navigate = useNavigate();
  const items = data?.items ?? [];
  if (!items.length) return null;
  return (
    <section aria-labelledby="phone-todo" className="flex flex-col gap-1">
      <h2 id="phone-todo" className="text-row font-bold text-ink-soft">
        {t("lists.todo.title")}
      </h2>
      <ul className="flex flex-col">
        {items.map((item) => {
          const who = members.find((m) => m.id === item.assigned_member_id);
          return (
            <li key={item.id}>
              <button
                type="button"
                onClick={() => {
                  void navigate({
                    to: "/$room/$",
                    params: { room: "lists", _splat: item.list_id },
                  });
                }}
                className="press-row flex min-h-14 w-full items-center gap-3 rounded-chip px-1 py-2 text-left"
              >
                <span className="flex min-w-0 flex-1 flex-col">
                  <span className="text-body font-semibold break-words">{item.text}</span>
                  <span className="text-secondary text-ink-soft">{detailOf(item, today)}</span>
                </span>
                {who ? <Avatar member={who} size="xs" /> : null}
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
