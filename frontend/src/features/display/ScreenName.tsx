import { t, useT, type Key } from "../../lib/lang";
import { Chip, ChipRow } from "../../ui/Chip";
import { TextField } from "../../ui/TextField";

type Place = "kitchen" | "hallway" | "living_room" | "office";

/** Where a screen might hang: suggestions, never assumptions (ADR 0042). Each place's word on
 * its chip, and the name a screen there is given, both in the page's language (ADR 0043): the
 * name is saved in the words shown. */
export const PLACES: readonly { place: Place; word: Key; name: Key }[] = [
  { place: "kitchen", word: "display.name.place.kitchen", name: "display.name.screen.kitchen" },
  { place: "hallway", word: "display.name.place.hallway", name: "display.name.screen.hallway" },
  {
    place: "living_room",
    word: "display.name.place.living_room",
    name: "display.name.screen.living_room",
  },
  { place: "office", word: "display.name.place.office", name: "display.name.screen.office" },
];

/** The chip a name reads as: the place whose name it is ("Hallway screen"), else Other (null:
 * nothing chosen). */
export function placeOf(label: string | null): Place | "other" | null {
  if (label === null) return null;
  return PLACES.find((one) => label === t(one.name))?.place ?? "other";
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
  const t = useT();
  const chosen = placeOf(label);
  const showField = field === "always" || chosen === "other";
  return (
    <>
      <ChipRow label={t("display.name.where.label")} center={field === "other"}>
        {PLACES.map((one) => (
          <Chip
            key={one.place}
            on={chosen === one.place}
            onClick={() => {
              onChange(t(one.name));
            }}
          >
            {t(one.word)}
          </Chip>
        ))}
        <Chip
          on={chosen === "other"}
          onClick={() => {
            onChange("");
          }}
        >
          {t("display.name.place.other")}
        </Chip>
      </ChipRow>
      {showField ? (
        <div className="w-full max-w-xl text-left">
          <TextField
            label={t("display.name.called.label")}
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
