/**
 * The weather's data (PLAN §11.3): the cached forecast for the household's place, the place
 * search, and setting the place (core settings: Settings → Household → Location). Searching and
 * setting are a parent's; the wall asks for the PIN.
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, unwrap } from "../../api/client";
import type { components } from "../../api/schema";
import { qk } from "../../api/keys";
import { t } from "../../lib/lang";
import { asParent } from "../../lib/parent";
import { showToast } from "../../lib/toast";

export type Weather = components["schemas"]["WeatherOut"];
export type Place = components["schemas"]["PlaceOut"];
export type WeatherDay = components["schemas"]["ForecastDayOut"];

export const weatherKeys = {
  now: () => ["weather"] as const,
  places: (q: string) => ["weather", "places", q] as const,
};

export function useWeather() {
  return useQuery({
    queryKey: weatherKeys.now(),
    queryFn: async () => unwrap(await api.GET("/api/weather")),
    staleTime: 5 * 60_000,
    // The server refreshes every 30 minutes and says so live; this catches a missed event.
    refetchInterval: 15 * 60_000,
  });
}

/** The day's forecast, if the week's has it. */
export function useWeatherDay(day: string): WeatherDay | undefined {
  const { data } = useWeather();
  return data?.status === "ok" ? data.daily.find((entry) => entry.date === day) : undefined;
}

export function usePlaces(q: string) {
  const words = q.trim();
  return useQuery({
    queryKey: weatherKeys.places(words),
    queryFn: async () =>
      asParent(async () =>
        unwrap(await api.GET("/api/weather/geocode", { params: { query: { q: words } } })),
      ),
    enabled: words.length >= 2,
    staleTime: Infinity,
    retry: false,
    // The field searches as you type: the last answer stays up until the next one arrives.
    placeholderData: keepPreviousData,
  });
}

/** Set (or clear) the household's place. */
export function useSetPlace() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (place: Place | null) =>
      asParent(async () =>
        unwrap(
          await api.PATCH("/api/settings", {
            body: place
              ? {
                  location_label: place.label,
                  latitude: place.latitude,
                  longitude: place.longitude,
                }
              : { location_label: null, latitude: null, longitude: null },
          }),
        ),
      ),
    onSuccess: async (_settings, place) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: qk.settings() }),
        queryClient.invalidateQueries({ queryKey: weatherKeys.now() }),
      ]);
      showToast(
        place
          ? t("weather.place.set.toast", { place: place.label })
          : t("weather.place.removed.toast"),
      );
    },
  });
}
