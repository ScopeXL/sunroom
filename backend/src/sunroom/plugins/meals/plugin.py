"""The meals plugin object: its manifest, routes, overlay and jobs."""

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
    SettingsSection,
)
from sunroom.plugins.context import PluginContext
from sunroom.plugins.meals.models import EXPORT_TABLES, TABLES
from sunroom.plugins.spec import ParamField

HOUR_S = 3600

MANIFEST = PluginManifest(
    id="meals",
    version="1.1.0",  # 1.1.0: calendar_slots replaced show_on_calendar (upgrade_settings)
    name=t_en("plugins.meals.name"),
    description=t_en("plugins.meals.description"),
    settings_spec=(
        ParamField(
            "slots",
            t_en("plugins.meals.settings.slots.label"),
            "multichoice",
            help=t_en("plugins.meals.settings.slots.help"),
            default=["dinner"],
            choices=("breakfast", "lunch", "dinner", "snack"),
            choice_labels=(
                t_en("plugins.meals.settings.slots.choices.breakfast"),
                t_en("plugins.meals.settings.slots.choices.lunch"),
                t_en("plugins.meals.settings.slots.choices.dinner"),
                t_en("plugins.meals.settings.slots.choices.snack"),
            ),
        ),
        ParamField(
            "calendar_slots",
            t_en("plugins.meals.settings.calendar_slots.label"),
            "multichoice",
            help=t_en("plugins.meals.settings.calendar_slots.help"),
            default=[],
            choices=("breakfast", "lunch", "dinner", "snack"),
            choice_labels=(
                t_en("plugins.meals.settings.calendar_slots.choices.breakfast"),
                t_en("plugins.meals.settings.calendar_slots.choices.lunch"),
                t_en("plugins.meals.settings.calendar_slots.choices.dinner"),
                t_en("plugins.meals.settings.calendar_slots.choices.snack"),
            ),
        ),
    ),
    tables=TABLES,
    export_tables=EXPORT_TABLES,
    contributes=Contributions(
        display_panels=(DisplayPanel("tonight", t_en("plugins.meals.panels.tonight")),),
        display_rooms=(
            DisplayRoom("meals", t_en("plugins.meals.rooms.meals"), "utensils", order=40),
        ),
        phone_tabs=(
            PhoneTab("meals", t_en("plugins.meals.tabs.meals"), "utensils", "/meals", order=40),
        ),
        settings_sections=(SettingsSection("meals", t_en("plugins.meals.sections.meals")),),
    ),
    default_enabled=True,
)


class Meals(PluginBase):
    def __init__(self) -> None:
        self.manifest = MANIFEST
        self.ctx: PluginContext | None = None

    def register_routes(self, router: APIRouter) -> None:
        from sunroom.plugins.meals.router import build

        build(router, self)

    async def on_enable(self, ctx: PluginContext) -> None:
        from sunroom.plugins.meals import service

        self.ctx = ctx

        async def overlay(start: date, end: date, zone: ZoneInfo) -> list[Any]:
            return await service.overlay(ctx, start, end, zone)

        async def prune() -> None:
            await service.prune(ctx)

        ctx.calendar.register_overlay(overlay)
        ctx.every("prune", HOUR_S, prune)

    # No on_disable: the context stays, so routes keep answering while a failed job has the
    # plugin errored (PLAN §11.4); switched off, the framework's gate answers for them, and the
    # overlay answers nothing.

    def upgrade_settings(self, raw: dict[str, Any], from_version: str) -> dict[str, Any]:
        """Before 1.1.0 one switch, "Show dinner on the calendar", did what ``calendar_slots``
        does per meal: a household that had it on keeps dinner on its board."""
        if "calendar_slots" in raw or "show_on_calendar" not in raw:
            return raw
        carried = {key: value for key, value in raw.items() if key != "show_on_calendar"}
        carried["calendar_slots"] = ["dinner"] if raw["show_on_calendar"] is True else []
        return carried

    async def validate_settings(self, ctx: PluginContext, values: dict[str, Any]) -> list[str]:
        if not values.get("slots"):
            return [t_en("api.meals.pick_a_meal")]
        return []

    async def seed_sample(self, ctx: PluginContext, people: dict[str, str]) -> None:
        from sunroom.plugins.meals.sample import seed

        await seed(ctx, people)


PLUGIN = Meals()
