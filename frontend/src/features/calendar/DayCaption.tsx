import { longDate } from "../../lib/dates";
import { useT } from "../../lib/lang";

/**
 * The day over a one-day board on the wall (the Day and People views, UX §4): "Thursday,
 * October 8", and "today" beside it on today, because the header doesn't say which day (ADR
 * 0030). Where the room's h1 already names the day (the Day view's "Thu, Oct 8") it's hidden from
 * a screen reader; People's h1 says only "People", so there it's read.
 */
export function DayCaption({
  day,
  today,
  spoken = false,
}: {
  day: string;
  today: boolean;
  spoken?: boolean;
}) {
  const t = useT();
  return (
    <p aria-hidden={spoken ? undefined : true} className="flex items-baseline gap-3 pb-1">
      <span className="text-d-title leading-tight font-bold">{longDate(day)}</span>
      {today ? (
        <span className="text-d-secondary font-semibold text-ink-soft">
          {t("calendar.board.today")}
        </span>
      ) : null}
    </p>
  );
}
