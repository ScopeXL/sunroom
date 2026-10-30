import { ChevronDown } from "lucide-react";
import { useState } from "react";

import { formatTime, formatWallTime, shortWeekday, zonedParts } from "../../lib/dates";
import { t, tRich, useT } from "../../lib/lang";
import { useMinute } from "../../lib/time";
import { Sheet } from "../../ui/Sheet";
import { useShell } from "../../ui/shell";
import type { RailPlace } from "../registry";
import { useWeather, useWeatherDay, type Weather, type WeatherDay } from "./data";
import { degrees, highLow, placeWithoutCountry, rainChance, sky } from "./sky";

/** When an old forecast is from ("9:10 AM"), once it's over 3 hours old (PLAN §11.4). */
function staleTime(weather: Weather): string | null {
  return weather.stale && weather.fetched_at ? formatTime(new Date(weather.fetched_at)) : null;
}

/** "as of 9:10" once the forecast is over 3 hours old (PLAN §11.4). */
function staleText(weather: Weather): string | null {
  const time = staleTime(weather);
  return time ? t("weather.as_of", { time }) : null;
}

/** The forecast's first line, the weather now: "Partly cloudy, 64° now. High 72°, low 55°.",
 * with ", as of 9:10 AM" after "now" when the forecast is old. */
function nowLine(weather: Weather, day: WeatherDay | undefined): string | null {
  if (!weather.current) return null;
  const { words } = sky(weather.current.code, weather.current.is_day);
  const facts = { sky: t(words), temp: degrees(weather.current.temperature) };
  const time = staleTime(weather);
  const now = time
    ? t("weather.forecast.now_stale", { ...facts, time })
    : t("weather.forecast.now", facts);
  return day
    ? `${now} ${t("weather.forecast.high_low", { high: degrees(day.high), low: degrees(day.low) })}`
    : now;
}

/**
 * The weather by the clock (UX §3). In the wall's header, a round outlined pill like This Week
 * and Filter beside it: the sky's icon, the temperature (or, when the forecast is old, when it's
 * from) and a chevron that says it opens something (ADR 0033); the day's high and low are the
 * forecast's first line, and in the pill's spoken name. At the top of a phone's Today, the icon
 * and the temperature with the high and low under them. A tap opens the forecast: Today and the
 * days ahead. Nothing shows until there's a forecast.
 */
export function WeatherBlock({ place }: { place: RailPlace }) {
  const t = useT();
  const { data } = useWeather();
  const today = zonedParts(useMinute()).day;
  const day = useWeatherDay(today);
  const [open, setOpen] = useState(false);
  if (data?.status !== "ok" || !data.current) return null;
  const { icon: Icon, words } = sky(data.current.code, data.current.is_day);
  const stale = staleText(data);
  const facts = [
    t("weather.pill.now", { sky: t(words), temp: degrees(data.current.temperature) }),
    day ? highLow(day.high, day.low) : null,
    stale,
  ]
    .filter(Boolean)
    .join(". ");
  const label = t("weather.pill.aria", { facts });
  const show = () => {
    setOpen(true);
  };
  const forecast = (
    <Forecast
      weather={data}
      day={day}
      open={open}
      onClose={() => {
        setOpen(false);
      }}
    />
  );
  if (place === "header") {
    // 12 px after the chevron, not 16: its glyph keeps room of its own, so the two ends read
    // even, and the header's worst case stays one row at 1920 Standard (ADR 0033).
    return (
      <>
        <button
          type="button"
          aria-label={label}
          onClick={show}
          className="press inline-flex min-h-tap shrink-0 items-center gap-2 rounded-full border-2 border-line bg-surface pr-3 pl-4 whitespace-nowrap"
        >
          <Icon aria-hidden="true" className="size-7 shrink-0" strokeWidth={2} />
          {/* A three-hour-old number shouldn't read as now: when it's from takes its place. */}
          {stale ? (
            <span className="text-d-caption font-semibold text-ink-soft">{stale}</span>
          ) : (
            <span className="text-d-body font-semibold">{degrees(data.current.temperature)}</span>
          )}
          <ChevronDown aria-hidden="true" className="size-7 shrink-0 text-ink-soft" />
        </button>
        {forecast}
      </>
    );
  }
  return (
    <>
      <button
        type="button"
        aria-label={label}
        onClick={show}
        className="press flex min-h-11 items-center gap-3 self-start rounded-chip px-1 text-left"
      >
        <span className="flex items-center gap-2">
          <Icon aria-hidden="true" className="size-7" strokeWidth={2} />
          <span className="text-title font-bold whitespace-nowrap">
            {degrees(data.current.temperature)}
          </span>
        </span>
        {day || stale ? (
          <span className="text-secondary font-semibold whitespace-nowrap text-ink-soft">
            {day ? `${degrees(day.high)} / ${degrees(day.low)}` : null}
            {day && stale ? " · " : null}
            {stale}
          </span>
        ) : null}
      </button>
      {forecast}
    </>
  );
}

/**
 * The forecast, from the weather by the clock (UX §3, ADR 0033): titled with the place without
 * its country, on one line; **Today**, a line on the weather now with the day's high and low,
 * then the next twelve hours; **Forecast**, the days ahead.
 */
function Forecast({
  weather,
  day,
  open,
  onClose,
}: {
  weather: Weather;
  /** Today's forecast, for its high and low. */
  day: WeatherDay | undefined;
  open: boolean;
  onClose: () => void;
}) {
  const t = useT();
  const display = useShell() === "display";
  const text = display ? "text-d-body" : "text-body";
  const soft = display ? "text-d-secondary text-ink-soft" : "text-secondary text-ink-soft";
  const today = weather.daily[0]?.date;
  const now = nowLine(weather, day);
  return (
    <Sheet
      open={open}
      title={placeWithoutCountry(weather.location_label) ?? t("weather.forecast.title")}
      oneLineTitle
      onClose={onClose}
    >
      <div className="flex flex-col gap-6">
        <section aria-label={t("weather.forecast.today.title")} className="flex flex-col gap-3">
          <h3 className={`${text} font-bold`}>{t("weather.forecast.today.title")}</h3>
          {now ? <p className={soft}>{now}</p> : null}
          <ul className="grid grid-cols-4 gap-3 sm:grid-cols-6">
            {weather.hourly.slice(0, 12).map((hour) => {
              const { icon: Icon, words } = sky(hour.code);
              const rain = rainChance(hour.precipitation);
              return (
                <li key={hour.time} className="flex flex-col items-center gap-1 text-center">
                  <span className={soft}>{formatWallTime(hour.time, { compact: true })}</span>
                  <Icon aria-label={t(words)} role="img" className="size-7" />
                  <span className={`${text} font-semibold`}>{degrees(hour.temperature)}</span>
                  {rain ? (
                    <span className={soft}>
                      {tRich("weather.forecast.rain", {
                        percent: rain,
                        sr: (chunk) => <span className="sr-only">{chunk}</span>,
                      })}
                    </span>
                  ) : null}
                </li>
              );
            })}
          </ul>
        </section>
        <section aria-label={t("weather.forecast.days.title")} className="flex flex-col gap-1">
          <h3 className={`${text} font-bold`}>{t("weather.forecast.days.title")}</h3>
          <ul className="flex flex-col divide-y divide-line">
            {weather.daily.map((day) => {
              const { icon: Icon, words } = sky(day.code);
              const rain = rainChance(day.precipitation);
              return (
                <li
                  key={day.date}
                  className={`flex items-center gap-4 ${display ? "min-h-16" : "min-h-12"}`}
                >
                  <span className={`w-20 ${text} font-semibold`}>
                    {day.date === today ? t("weather.forecast.day.today") : shortWeekday(day.date)}
                  </span>
                  <Icon aria-hidden="true" className="size-7 shrink-0" />
                  <span className={`flex-1 ${soft}`}>
                    {rain
                      ? t("weather.forecast.day.rain", { sky: t(words), percent: rain })
                      : t(words)}
                  </span>
                  <span className={`${text} font-semibold whitespace-nowrap`}>
                    {degrees(day.high)} <span className="text-ink-soft">{degrees(day.low)}</span>
                  </span>
                </li>
              );
            })}
          </ul>
        </section>
        <p className={soft}>{t("weather.forecast.credit")}</p>
      </div>
    </Sheet>
  );
}

/** A day's sky, as an icon in the board's day header (UX §3; only for days the forecast
 * reaches). The forecast itself is a tap on the header's weather away. */
export function WeatherDayMark({ day }: { day: string }) {
  const forecast = useWeatherDay(day);
  if (!forecast) return null;
  const { icon: Icon } = sky(forecast.code);
  return (
    <Icon
      aria-hidden="true"
      className="ml-auto size-7 shrink-0 self-center text-ink-soft portrait:ml-0"
      strokeWidth={2}
    />
  );
}

/** The weather beside the date on the screensaver: "☼ 64°". */
export function WeatherSaverCorner() {
  const t = useT();
  const { data } = useWeather();
  if (data?.status !== "ok" || !data.current) return null;
  const { icon: Icon, words } = sky(data.current.code, data.current.is_day);
  return (
    <span className="inline-flex items-center gap-2">
      <Icon aria-label={t(words)} role="img" className="size-10" strokeWidth={2} />
      {degrees(data.current.temperature)}
    </span>
  );
}
