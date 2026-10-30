import { usePlugins } from "../../lib/household";
import { useT } from "../../lib/lang";
import { Switch } from "../../ui/Switch";
import { Group } from "../settings/parts";
import { PluginSettingsForm, usePluginSettings } from "../settings/PluginSettingsForm";
import { SLOT_WORDS, type Slot } from "./data";

const SLOTS = Object.keys(SLOT_WORDS) as Slot[];

function slotsIn(value: unknown): Slot[] {
  const chosen = Array.isArray(value) ? (value as unknown[]) : [];
  return SLOTS.filter((slot) => chosen.includes(slot));
}

/**
 * Settings → Meals (UX §4): which meals the family plans, then a switch for each of those to
 * show it on the calendar. A meal that's no longer planned loses its switch but not its choice,
 * so planning it again brings the chips back.
 */
export function SettingsMeals() {
  const t = useT();
  const { data: plugins = [] } = usePlugins();
  const plugin = plugins.find((p) => p.id === "meals");
  const save = usePluginSettings("meals");
  if (!plugin) return null;
  const values = plugin.settings;
  const shown = slotsIn(values.calendar_slots);
  return (
    <Group>
      <PluginSettingsForm
        pluginId="meals"
        spec={plugin.settings_spec.filter((field) => field.key === "slots")}
        values={values}
      />
      {slotsIn(values.slots).map((slot) => (
        <Switch
          key={slot}
          label={t("meals.settings.show_slot.label", { slot })}
          checked={shown.includes(slot)}
          onChange={(on) => {
            const others = slotsIn(values.calendar_slots).filter((other) => other !== slot);
            save.mutate({
              ...values,
              calendar_slots: SLOTS.filter((s) => (s === slot ? on : others.includes(s))),
            });
          }}
        />
      ))}
    </Group>
  );
}
