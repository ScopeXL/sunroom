"""Public holidays (PLAN §8.1), made offline by the ``holidays`` package: no address, no
network. A country, and optionally a state or region, gives one read-only calendar from last
year to two years ahead, made again when the year turns, and when the household's language
changes: the holidays are named in it where the package has it for that country (ADR 0043)."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Mapping
from datetime import date, datetime, timedelta
from functools import cache

import holidays as holidays_lib

from sunroom.calendar.synced import PendingSeries, SyncedEvent, SyncedSeries
from sunroom.core.lang import languages
from sunroom.domain.recurrence import Timing
from sunroom.plugins.calendar_sync.providers.base import (
    Changes,
    ErrorKind,
    Pushed,
    RemoteCalendar,
    SyncError,
)

GENERATION = 1  # bump to make every holidays calendar again after a change here
READ_ONLY = "api.sync.holidays.read_only"


def supported() -> dict[str, list[str]]:
    """Country codes and their state or region codes."""
    return {
        code: sorted(subdivisions)
        for code, subdivisions in holidays_lib.list_supported_countries().items()
        if len(code) == 2
    }


@cache
def _offered(country: str) -> tuple[str | None, tuple[str, ...]]:
    """The country's own language for its holidays, and every language the package has them in
    (``("es", ("ca", "en_US", "es", "th", "uk"))`` for Spain)."""
    try:
        made = holidays_lib.country_holidays(country)
    except NotImplementedError, KeyError:
        return None, ()
    return made.default_language, tuple(made.supported_languages)


def holiday_language(country: str, language: str | None) -> str | None:
    """The package's language for this country's holidays in the household's ``language`` (a
    code from lang/languages.json), or None for the country's own: when the country already
    speaks it (British English stays British), or the package doesn't have it there."""
    if not language:
        return None
    default, offered = _offered(country.upper())
    if default is None or default.split("_")[0] == language:
        return None
    if language in offered:
        return language
    info = languages().get(language)
    locale = info["locale"].replace("-", "_") if info else ""
    if locale in offered:
        return locale
    return next((code for code in offered if code.split("_")[0] == language), None)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "holiday"


class HolidaysProvider:
    def __init__(
        self,
        country: str,
        subdivision: str | None,
        now_of: Callable[[], datetime],
        language_of: Callable[[], Awaitable[str]] | None = None,
    ):
        self._country = country.upper()
        self._subdivision = subdivision.upper() if subdivision else None
        self._now_of = now_of
        self._language_of = language_of  # the household's language, asked at each sync

    def remote_id(self) -> str:
        return f"holidays-{self._country}" + (f"-{self._subdivision}" if self._subdivision else "")

    async def calendars(self) -> list[RemoteCalendar]:
        return [RemoteCalendar(self.remote_id(), "Holidays", None, read_only=True)]

    def days(self, years: list[int], language: str | None = None) -> dict[date, list[str]]:
        try:
            found = holidays_lib.country_holidays(
                self._country, subdiv=self._subdivision, years=years, language=language
            )
        except (NotImplementedError, KeyError) as exc:
            raise SyncError(ErrorKind.BAD_DATA, "api.sync.holidays.no_place") from exc
        out: dict[date, list[str]] = {}
        for day, names in found.items():
            out[day] = [name.strip() for name in str(names).split(";") if name.strip()]
        return out

    async def changes(
        self, calendar: RemoteCalendar, cursor: str | None, known: Mapping[str, str | None]
    ) -> Changes:
        year = self._now_of().year
        wanted = await self._language_of() if self._language_of is not None else None
        language = holiday_language(self._country, wanted)
        # A new language is a new cursor: the names are made again in it at this sync.
        fresh = f"{GENERATION}:{self.remote_id()}:{year}" + (f":{language}" if language else "")
        if cursor == fresh:
            return Changes()
        series: list[SyncedSeries] = []
        for day, names in sorted(self.days([year - 1, year, year + 1, year + 2], language).items()):
            for name in names:
                series.append(
                    SyncedSeries(
                        uid=f"{day.isoformat()}-{_slug(name)}@holidays.sunroom",
                        master=SyncedEvent(
                            title=name,
                            timing=Timing(
                                all_day=True, start_date=day, end_date=day + timedelta(days=1)
                            ),
                        ),
                        etag=f"{GENERATION}:{name}",
                    )
                )
        return Changes(series=series, complete=True, cursor=fresh)

    async def push(self, calendar: RemoteCalendar, pending: PendingSeries) -> Pushed:
        raise SyncError(ErrorKind.REFUSED, READ_ONLY)

    async def delete(self, calendar: RemoteCalendar, pending: PendingSeries) -> None:
        raise SyncError(ErrorKind.REFUSED, READ_ONLY)
