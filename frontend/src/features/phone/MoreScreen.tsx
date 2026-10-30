import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import {
  ChevronRight,
  Info,
  MonitorSmartphone,
  Settings,
  Smartphone,
  UserRound,
} from "lucide-react";

import { qk } from "../../api/keys";
import { useT } from "../../lib/lang";
import { isStandalone } from "../../lib/platform";
import { fetchSession } from "../../lib/session";
import { PLUGIN_TABS } from "../../shell/PhoneShell";
import { Screen } from "../../ui/Screen";
import { usePluginRooms } from "../usePluginModules";

/** More (UX §5): the rooms not in the tab bar (Meals, Countdowns, Photos), then everything
 * else. */
export function MoreScreen() {
  const t = useT();
  const { data: session } = useQuery({ queryKey: qk.session(), queryFn: fetchSession });
  const rooms = usePluginRooms().slice(PLUGIN_TABS);
  const rowClass = "press-row flex min-h-14 items-center gap-3 px-4 text-row font-semibold";
  return (
    <Screen title={t("phone.more.title")}>
      {rooms.length ? (
        <ul className="mb-6 divide-y divide-line rounded-chip border border-line bg-surface">
          {rooms.map(({ key, label, icon: Icon }) => (
            <li key={key}>
              <Link to="/$room" params={{ room: key }} className={rowClass}>
                <Icon aria-hidden="true" />
                <span className="flex-1">{t(label)}</span>
                <ChevronRight aria-hidden="true" className="text-ink-soft" />
              </Link>
            </li>
          ))}
        </ul>
      ) : null}
      <ul className="divide-y divide-line rounded-chip border border-line bg-surface">
        <li>
          <Link to="/settings" className={rowClass}>
            <Settings aria-hidden="true" />
            <span className="flex-1">{t("settings.title")}</span>
            <ChevronRight aria-hidden="true" className="text-ink-soft" />
          </Link>
        </li>
        <li>
          <Link to="/who" search={{ from: "more" }} className={rowClass}>
            <UserRound aria-hidden="true" />
            <span className="flex flex-1 flex-col">
              {t("phone.more.who.title")}
              <span className="text-secondary font-normal text-ink-soft">
                {session?.member ? session.member.name : t("phone.more.who.nobody")}
              </span>
            </span>
            <ChevronRight aria-hidden="true" className="text-ink-soft" />
          </Link>
        </li>
        <li>
          <Link to="/pair" className={rowClass}>
            <MonitorSmartphone aria-hidden="true" />
            <span className="flex-1">{t("phone.pair.title")}</span>
            <ChevronRight aria-hidden="true" className="text-ink-soft" />
          </Link>
        </li>
        {!isStandalone() ? (
          <li>
            <Link to="/install" search={{ from: "more" }} className={rowClass}>
              <Smartphone aria-hidden="true" />
              <span className="flex-1">{t("phone.more.install.title")}</span>
              <ChevronRight aria-hidden="true" className="text-ink-soft" />
            </Link>
          </li>
        ) : null}
        <li>
          <Link to="/settings/$page" params={{ page: "about" }} className={rowClass}>
            <Info aria-hidden="true" />
            <span className="flex-1">{t("phone.more.about.title")}</span>
            <ChevronRight aria-hidden="true" className="text-ink-soft" />
          </Link>
        </li>
      </ul>
    </Screen>
  );
}
