/** The chores plugin's frontend (PLAN §6.5, UX §4 "Chores room", "Stars & rewards", "Routine
 * runner", §5 "Chores", ADR 0019, ADR 0025). */
import { SquareCheckBig } from "lucide-react";

import type { PluginModule } from "../registry";
import { AddChore } from "./ChoreEditor";
import { ChoresRoom } from "./ChoresRoom";
import { ChoresTab } from "./ChoresTab";
import { RemovedChoreRows } from "./Removed";
import { SettingsChores } from "./SettingsChores";
import { ChoresPersonColumn, ChoresTodayPhone, ChoresTodayWall } from "./TodayBlocks";

const module: PluginModule = {
  id: "chores",
  rooms: [
    {
      key: "chores",
      label: "tasks.room.title",
      icon: SquareCheckBig,
      order: 30,
      Display: ChoresRoom,
      Phone: ChoresTab,
    },
  ],
  today: [{ key: "chores", order: 10, Display: ChoresTodayWall, Phone: ChoresTodayPhone }],
  add: [
    {
      key: "chore",
      label: "tasks.add.label",
      icon: SquareCheckBig,
      order: 30,
      room: "chores",
      Editor: AddChore,
    },
  ],
  personColumn: ChoresPersonColumn,
  removed: RemovedChoreRows,
  settingsPages: [{ key: "chores", title: "tasks.settings.title", Page: SettingsChores }],
};

export default module;
