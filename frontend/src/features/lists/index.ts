/** The lists plugin's frontend (PLAN §6.5, UX §4 "Lists room", §5 "Lists"). */
import { ListChecks } from "lucide-react";

import type { PluginModule } from "../registry";
import { AddItem } from "./AddItem";
import { ListsRoom } from "./ListsRoom";
import { ListsTab } from "./ListsTab";
import { RemovedListRows } from "./Removed";
import { TodoBlockPhone, TodoBlockWall } from "./TodoBlock";

const module: PluginModule = {
  id: "lists",
  rooms: [
    {
      key: "lists",
      label: "lists.room.title",
      icon: ListChecks,
      order: 20,
      Display: ListsRoom,
      Phone: ListsTab,
    },
  ],
  today: [{ key: "todo", order: 30, Display: TodoBlockWall, Phone: TodoBlockPhone }],
  add: [
    {
      key: "item",
      label: "lists.add.label",
      icon: ListChecks,
      order: 20,
      room: "lists",
      Editor: AddItem,
    },
  ],
  removed: RemovedListRows,
};

export default module;
