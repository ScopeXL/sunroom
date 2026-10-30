import { COLORS, type PersonColor } from "../lib/colors";
import { useT } from "../lib/lang";
import { useFieldLabel } from "./Field";
import { useShell } from "./shell";

/** Whose each taken color is, by color: `{ rose: "Mia" }`. */
export type UsedColors = Partial<Record<PersonColor, string>>;

/** The colors nobody has yet first, then the taken ones, each part in the list's own order. */
export function colorOrder(used: UsedColors): typeof COLORS {
  return [
    ...COLORS.filter((color) => !used[color.value]),
    ...COLORS.filter((color) => used[color.value]),
  ];
}

/** Each person's color with their name, for `used`; `except` leaves one person out (their own
 * color isn't taken, for them). Two people with one color: the first is named. */
export function usedBy(
  members: readonly { id: string; name: string; color: PersonColor }[],
  except?: string,
): UsedColors {
  const used: UsedColors = {};
  for (const member of members) {
    if (member.id !== except) used[member.color] ??= member.name;
  }
  return used;
}

/**
 * Pick one of the twelve colors (UX §4 Settings): a grid of named swatches, the ones nobody uses
 * first, then the taken ones, each saying whose it is ("Mia's"), so a new calendar or person
 * lands on a free color without anyone counting. A taken color can still be picked. `initial`
 * draws a letter in each swatch, as a person's circle will look.
 */
export function ColorPicker({
  name,
  value,
  onChange,
  used = {},
  label: given,
  initial,
}: {
  /** The radios' group name: unique among the pickers on screen. */
  name: string;
  /** None yet for a synced calendar nobody has given a color. */
  value: PersonColor | null;
  onChange: (color: PersonColor) => void;
  used?: UsedColors;
  label?: string;
  initial?: string;
}) {
  const t = useT();
  const label = given ?? t("ui.color.label");
  const display = useShell() === "display";
  const labelClass = useFieldLabel();
  return (
    <fieldset className="@container flex flex-col gap-2">
      <legend className={`mb-2 ${labelClass}`}>{label}</legend>
      <div className="grid grid-cols-2 gap-2 @xl:grid-cols-4">
        {colorOrder(used).map((option) => {
          const owner = used[option.value];
          return (
            <label
              key={option.value}
              data-person={option.value}
              className={`press flex cursor-pointer items-center gap-2 rounded-button border-2 border-line bg-surface px-2 py-1 has-checked:border-ink has-checked:ring-2 has-checked:ring-ink has-focus-visible:outline-[3px] has-focus-visible:outline-offset-2 has-focus-visible:outline-ink ${
                display ? "min-h-16 text-d-secondary" : "min-h-12 text-secondary"
              }`}
            >
              <input
                type="radio"
                name={name}
                value={option.value}
                checked={value === option.value}
                onChange={() => {
                  onChange(option.value);
                }}
                className="sr-only"
              />
              <span
                aria-hidden="true"
                className={`flex shrink-0 items-center justify-center rounded-full bg-p font-bold text-on-ink ${
                  initial ? "size-8" : "size-6"
                }`}
              >
                {initial}
              </span>
              <span className="flex min-w-0 flex-col leading-tight">
                <span className="font-semibold">{t(option.word)}</span>
                {owner ? <span className="truncate text-ink-soft">{`${owner}'s`}</span> : null}
              </span>
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}
