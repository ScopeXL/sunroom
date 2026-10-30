import { fitRow } from "../lib/fit";
import type { Member } from "../lib/household";
import { useT } from "../lib/lang";
import { useRootScale, useWidth } from "../lib/useWidth";
import { Avatar } from "./Avatar";
import { useOverflow } from "./ScrollRow";
import { useShell } from "./shell";

// A cell is its avatar and 8 px either side: 64 or 56 px avatars on the wall, 48 or 40 on a
// phone (at Standard; they scale with the text size, as the avatars do).
const WALL = [
  { cell: 80, avatar: "lg" },
  { cell: 72, avatar: "tap" },
] as const;
const PHONE = [
  { cell: 56, avatar: "md" },
  { cell: 48, avatar: "sm" },
] as const;
const GAP = 8;

/**
 * The Who picker (UX §4, ADR 0029): avatars with their names under them, Everyone (a house mark)
 * first where it fits, then each person in household order. Chosen: an ink ring and the person's
 * tint, with aria-pressed. One person or several (`multiple`); kids-only for asking for a reward.
 *
 * It is always one row. The cells share the row's width; when the people don't fit at the
 * larger avatar they all take the smaller one (Everyone and five people keep 64 px on the wall,
 * a seventh cell makes everyone 56), and when even those don't fit the row scrolls sideways with
 * a fade at its edge. A name too long for its cell is cut with an ellipsis; the button's name
 * for a screen reader is always the whole name. `wrap` is the exception for a narrow column
 * ("Who did it?" on the Tasks board), where a second line beats a row that hides people.
 */
export function WhoPicker({
  label,
  members,
  value,
  onChange,
  multiple = false,
  everyone = true,
  everyoneLabel,
  kidsOnly = false,
  wrap = false,
}: {
  /** The group's name for screen readers: "Who", "Who did it?". */
  label: string;
  members: Member[];
  /** The chosen people; empty is Everyone. */
  value: string[];
  onChange: (ids: string[]) => void;
  multiple?: boolean;
  everyone?: boolean;
  /** What the first cell is called: "Everyone", or "Anyone" for a task. */
  everyoneLabel?: string;
  kidsOnly?: boolean;
  /** Wrap onto more lines instead of one row (a narrow column). */
  wrap?: boolean;
}) {
  const t = useT();
  const firstCell = everyoneLabel ?? t("ui.who.everyone");
  const display = useShell() === "display";
  const people = kidsOnly ? members.filter((member) => member.role === "kid") : members;
  const count = people.length + (everyone ? 1 : 0);
  const [widthRef, width] = useWidth<HTMLDivElement>();
  const scale = useRootScale();
  const sizes = display ? WALL : PHONE;
  const fit = fitRow(
    wrap ? 0 : width,
    count,
    sizes.map((size) => size.cell * scale),
    GAP * scale,
  );
  const size = sizes.find((candidate) => candidate.cell * scale === fit.cell) ?? sizes[0];
  const [scrollRef, overflow] = useOverflow<HTMLDivElement>(count, fit.scroll);

  // The ring has room all round: on the wall 8 px above the avatar and under the name, as at its
  // sides (ADR 0034); a phone's smaller cells already have 4 px every way.
  const option = `press select-fill flex min-w-0 flex-col items-center gap-1 rounded-button px-0.5 ${
    display ? "py-2" : "py-1"
  } aria-pressed:bg-p-tint aria-pressed:ring-[3px] aria-pressed:ring-ink aria-pressed:ring-inset`;
  // Wrapping, a cell is as wide as it was before the row became one line; in the row, the cells
  // share the width from the fitted size up (or keep it exactly, when the row scrolls).
  const cell = wrap ? (display ? "min-w-24" : "min-w-16") : "";
  const flex = wrap ? undefined : { flex: `${fit.scroll ? "0 0" : "1 1"} ${String(fit.cell)}px` };
  const name = (chosen: boolean) =>
    `w-full truncate text-center ${display ? "text-d-caption" : "text-caption"} ${
      chosen ? "font-bold" : "font-semibold"
    }`;
  return (
    <div ref={widthRef} className="min-w-0">
      <div
        ref={scrollRef}
        role="group"
        aria-label={label}
        data-overflow={fit.scroll ? overflow : undefined}
        className={`flex gap-2 ${
          wrap
            ? "flex-wrap"
            : fit.scroll
              ? "fade-x snap-x flex-nowrap overflow-x-auto [scrollbar-width:none] *:snap-start"
              : "flex-nowrap"
        }`}
      >
        {everyone ? (
          <button
            type="button"
            aria-pressed={value.length === 0}
            aria-label={firstCell}
            data-person="everyone"
            onClick={() => {
              onChange([]);
            }}
            className={`${option} ${cell}`}
            style={flex}
          >
            <Avatar member={null} size={size.avatar} />
            <span className={name(value.length === 0)}>{firstCell}</span>
          </button>
        ) : null}
        {people.map((member) => {
          const on = value.includes(member.id);
          return (
            <button
              key={member.id}
              type="button"
              aria-pressed={on}
              aria-label={member.name}
              data-person={member.color}
              onClick={() => {
                if (!multiple) onChange([member.id]);
                else onChange(on ? value.filter((id) => id !== member.id) : [...value, member.id]);
              }}
              className={`${option} ${cell}`}
              style={flex}
            >
              <Avatar member={member} size={size.avatar} />
              <span className={name(on)}>{member.name}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
