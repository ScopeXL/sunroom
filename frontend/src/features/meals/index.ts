/** The meals plugin's frontend (PLAN §6.5, UX §4 "Meals room", §5 "Meals"): the week's meals,
 * Saved meals, Tonight on Today, Meal in Add, dinner on the board when the household wants it,
 * and Settings → Meals. */
import { Utensils } from "lucide-react";

import type { PluginModule } from "../registry";
import { AddMeal } from "./MealEditor";
import { MealsRoom } from "./MealsRoom";
import { MealsTab } from "./MealsTab";
import { RemovedMealRows } from "./Removed";
import { SettingsMeals } from "./SettingsMeals";
import { TonightPhone, TonightWall } from "./Tonight";

const module: PluginModule = {
  id: "meals",
  rooms: [
    {
      key: "meals",
      label: "meals.room.title",
      icon: Utensils,
      order: 40,
      Display: MealsRoom,
      Phone: MealsTab,
    },
  ],
  today: [{ key: "tonight", order: 20, Display: TonightWall, Phone: TonightPhone }],
  add: [
    {
      key: "meal",
      label: "meals.add.label",
      icon: Utensils,
      order: 40,
      room: "meals",
      Editor: AddMeal,
    },
  ],
  calendarOverlays: [{ key: "meals", icon: Utensils, room: "meals" }],
  removed: RemovedMealRows,
  settingsPages: [{ key: "meals", title: "meals.settings.title", Page: SettingsMeals }],
};

export default module;
