"""The countdowns plugin object: its manifest, routes, overlay and jobs."""

from __future__ import annotations

from datetime import date
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter

from sunroom.core.lang import t_en
from sunroom.plugins.base import (
    Contributions,
    DisplayPanel,
    DisplayRoom,
    PhoneTab,
    PluginBase,
    PluginManifest,
)
from sunroom.plugins.context import PluginContext
from sunroom.plugins.countdowns.models import EXPORT_TABLES, TABLES
from sunroom.plugins.spec import ParamField

HOUR_S = 3600

MANIFEST = PluginManifest(
    id="countdowns",
    version="1.0.0",
    name=t_en("plugins.countdowns.name"),
    description=t_en("plugins.countdowns.description"),
    settings_spec=(
        ParamField(
            "birthdays",
            t_en("plugins.countdowns.settings.birthdays.label"),
            "bool",
            help=t_en("plugins.countdowns.settings.birthdays.help"),
            default=True,
        ),
        # Coming Up on the Today panel: a countdown someone added always shows, however far
        # out; a birthday, which everyone gets for free, only within this window (ADR 0032).
        ParamField(
            "birthdays_within",
            t_en("plugins.countdowns.settings.birthdays_within.label"),
            "choice",
            help=t_en("plugins.countdowns.settings.birthdays_within.help"),
            default="30",
            choices=("7", "14", "30", "90", "any"),
            choice_labels=(
                t_en("plugins.countdowns.settings.birthdays_within.choices.7"),
                t_en("plugins.countdowns.settings.birthdays_within.choices.14"),
                t_en("plugins.countdowns.settings.birthdays_within.choices.30"),
                t_en("plugins.countdowns.settings.birthdays_within.choices.90"),
                t_en("plugins.countdowns.settings.birthdays_within.choices.any"),
            ),
        ),
    ),
    tables=TABLES,
    export_tables=EXPORT_TABLES,
    contributes=Contributions(
        display_panels=(DisplayPanel("coming_up", t_en("plugins.countdowns.panels.coming_up")),),
        display_rooms=(
            DisplayRoom(
                "countdowns", t_en("plugins.countdowns.rooms.countdowns"), "hourglass", order=50
            ),
        ),
        phone_tabs=(
            PhoneTab(
                "countdowns",
                t_en("plugins.countdowns.tabs.countdowns"),
                "hourglass",
                "/countdowns",
                order=50,
            ),
        ),
    ),
    default_enabled=True,
)


class Countdowns(PluginBase):
    def __init__(self) -> None:
        self.manifest = MANIFEST
        self.ctx: PluginContext | None = None

    def register_routes(self, router: APIRouter) -> None:
        from sunroom.plugins.countdowns.router import build

        build(router, self)

    async def on_enable(self, ctx: PluginContext) -> None:
        from sunroom.plugins.countdowns import service

        self.ctx = ctx

        async def overlay(start: date, end: date, zone: ZoneInfo) -> list[Any]:
            return await service.overlay(ctx, start, end, zone)

        async def tidy() -> None:
            await service.tidy(ctx)

        ctx.calendar.register_overlay(overlay)
        ctx.every("tidy", HOUR_S, tidy)

    # No on_disable: the context stays, so routes keep answering while a failed job has the
    # plugin errored (PLAN §11.4); switched off, the framework's gate answers for them, and the
    # overlay answers nothing.

    async def seed_sample(self, ctx: PluginContext, people: dict[str, str]) -> None:
        from sunroom.plugins.countdowns.sample import seed

        await seed(ctx, people)


PLUGIN = Countdowns()
