import { Chip, ChipRow } from "../../ui/Chip";
import { TextField } from "../../ui/TextField";

/** Where a screen might hang: suggestions, never assumptions (ADR 0042). */
export const PLACES = ["Kitchen", "Hallway", "Living room", "Office"] as const;

/** The chip a name reads as: a place's "Hallway screen", else Other (null: nothing chosen). */
export function placeOf(label: string | null): string | null {
  if (label === null) return null;
  return PLACES.find((place) => label === `${place} screen`) ?? "Other";
}

/**
 * A screen's name, as Name This Screen and Settings → Devices' Rename Screen ask it: the places
 * as chips ("Where is this screen?"), then Other, and a field for a name of its own ("What should
 * it be called?"), there only for Other (`field="other"`) or always, holding the current name
 * (`field="always"`). `label` null is nothing chosen yet; "" is Other with nothing typed.
 */
export function ScreenNameFields({
  label,
  onChange,
  field,
}: {
  label: string | null;
  onChange: (label: string) => void;
  field: "other" | "always";
}) {
  const chosen = placeOf(label);
  const showField = field === "always" || chosen === "Other";
  return (
    <>
      <ChipRow label="Where is this screen?" center={field === "other"}>
        {[...PLACES, "Other"].map((option) => (
          <Chip
            key={option}
            on={chosen === option}
            onClick={() => {
              onChange(option === "Other" ? "" : `${option} screen`);
            }}
          >
            {option}
          </Chip>
        ))}
      </ChipRow>
      {showField ? (
        <div className="w-full max-w-xl text-left">
          <TextField
            label="What should it be called?"
            value={label ?? ""}
            maxLength={80}
            onChange={(event) => {
              onChange(event.target.value);
            }}
          />
        </div>
      ) : null}
    </>
  );
}
