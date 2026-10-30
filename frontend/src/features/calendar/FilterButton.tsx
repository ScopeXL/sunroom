import { ListFilter } from "lucide-react";

import type { Member } from "../../lib/household";
import { useT } from "../../lib/lang";
import { Avatar } from "../../ui/Avatar";
import { Menu, MenuCheck, MenuGroup, MenuRadio } from "../../ui/Menu";

const SHOWN = 3;

/**
 * Filter, in the wall's header (UX §3, ADR 0030): one button for whose events the board shows,
 * with room for more kinds of filter later. It opens a menu under itself: Everyone, then each
 * person with a check, several at once. Choosing a person keeps the menu open for the next;
 * Everyone clears the filter and closes it. While people are chosen the button shows their
 * avatars and says their names, so a filtered board never looks like an empty week. The word
 * "Filter" is written out only where the header has the room (112rem of its own width).
 * Nothing at all in a household of one.
 */
export function FilterButton({
  members,
  people,
  onPeople,
}: {
  members: Member[];
  /** The chosen people's ids; none means everyone. */
  people: string[];
  onPeople: (people: string[]) => void;
}) {
  const t = useT();
  if (members.length < 2) return null;
  // In the household's order, whatever order they were tapped in.
  const chosen = members.filter((member) => people.includes(member.id));
  const names = chosen.map((member) => member.name).join(", ");
  return (
    <Menu
      label={t("calendar.filter.action")}
      trigger={(props) => (
        // Not ui/Button: its padding is fixed, and this is a square until it has something to say.
        <button
          type="button"
          {...props}
          aria-label={
            chosen.length
              ? t("calendar.filter.chosen.aria", { names })
              : t("calendar.filter.action")
          }
          data-filtered={chosen.length ? "" : undefined}
          className={`press inline-flex h-tap min-w-tap shrink-0 items-center justify-center gap-2 rounded-button-d border-2 bg-surface text-d-body font-semibold active:bg-wall @min-[112rem]/header:px-5 ${
            chosen.length ? "border-ink px-3" : "border-line"
          }`}
        >
          <ListFilter aria-hidden="true" className="size-8 shrink-0" />
          <span className="hidden @min-[112rem]/header:inline">{t("calendar.filter.action")}</span>
          {chosen.length ? (
            <span aria-hidden="true" className="flex items-center -space-x-2">
              {chosen.slice(0, SHOWN).map((member) => (
                <Avatar key={member.id} member={member} size="xs" />
              ))}
              {chosen.length > SHOWN ? (
                <span className="pl-3 text-d-caption">{`+${String(chosen.length - SHOWN)}`}</span>
              ) : null}
            </span>
          ) : null}
        </button>
      )}
    >
      <MenuGroup label={t("calendar.filter.people.label")}>
        <MenuRadio
          check
          checked={chosen.length === 0}
          onChoose={() => {
            onPeople([]);
          }}
        >
          <Avatar member={null} size="sm" />
          {t("calendar.everyone")}
        </MenuRadio>
        {members.map((member) => (
          <MenuCheck
            key={member.id}
            checked={people.includes(member.id)}
            onChange={(on) => {
              // Kept in the household's order, and without anyone who has since left it.
              onPeople(
                members
                  .filter((other) => (other.id === member.id ? on : people.includes(other.id)))
                  .map((kept) => kept.id),
              );
            }}
          >
            <Avatar member={member} size="sm" />
            {member.name}
          </MenuCheck>
        ))}
      </MenuGroup>
    </Menu>
  );
}
