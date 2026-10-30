/** The countdowns plugin's frontend (PLAN §6.5, UX §4 "Countdowns room"): tiles soonest first,
 * Coming up on Today, Countdown in Add and on an event's sheet, and a star on the board's day. */
import { Hourglass, Star } from "lucide-react";

import type { PluginModule } from "../registry";
import { AddCountdownFromEvent, ComingUpPhone, ComingUpWall } from "./ComingUp";
import { AddCountdown } from "./CountdownEditor";
import { CountdownsRoom, CountdownsTab } from "./CountdownsRoom";
import { RemovedCountdownRows } from "./Removed";

const module: PluginModule = {
  id: "countdowns",
  rooms: [
    {
      key: "countdowns",
      label: "countdowns.room.title",
      icon: Hourglass,
      order: 50,
      Display: CountdownsRoom,
      Phone: CountdownsTab,
    },
  ],
  today: [{ key: "coming-up", order: 40, Display: ComingUpWall, Phone: ComingUpPhone }],
  add: [
    {
      key: "countdown",
      label: "countdowns.add.label",
      icon: Hourglass,
      order: 50,
      room: "countdowns",
      Editor: AddCountdown,
    },
  ],
  calendarOverlays: [{ key: "countdowns", icon: Star, room: "countdowns" }],
  eventAction: AddCountdownFromEvent,
  removed: RemovedCountdownRows,
};

export default module;
