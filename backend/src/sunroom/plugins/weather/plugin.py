"""The weather plugin object: its manifest, routes and the refresh job."""

from __future__ import annotations

from fastapi import APIRouter

from sunroom.core.lang import t_en
from sunroom.plugins.base import (
    Contributions,
    DisplayPanel,
    HubEvent,
    PluginBase,
    PluginManifest,
)
from sunroom.plugins.context import PluginContext
from sunroom.plugins.spec import ParamField
from sunroom.plugins.weather.models import EXPORT_TABLES, TABLES

REFRESH_S = 30 * 60

MANIFEST = PluginManifest(
    id="weather",
    version="1.0.0",
    name=t_en("plugins.weather.name"),
    description=t_en("plugins.weather.description"),
    settings_spec=(
        ParamField(
            "units",
            t_en("plugins.weather.settings.units.label"),
            "choice",
            help=t_en("plugins.weather.settings.units.help"),
            default="auto",
            choices=("auto", "fahrenheit", "celsius"),
            choice_labels=(
                t_en("plugins.weather.settings.units.choices.auto"),
                t_en("plugins.weather.settings.units.choices.fahrenheit"),
                t_en("plugins.weather.settings.units.choices.celsius"),
            ),
        ),
    ),
    tables=TABLES,
    export_tables=EXPORT_TABLES,
    contributes=Contributions(
        display_panels=(DisplayPanel("weather", t_en("plugins.weather.panels.weather")),)
    ),
    default_enabled=True,
    # The household's place (core settings) or this plugin's units changed: fetch again.
    subscribes=("settings.changed", "plugins.changed"),
)


class Weather(PluginBase):
    def __init__(self) -> None:
        self.manifest = MANIFEST
        self.ctx: PluginContext | None = None

    def register_routes(self, router: APIRouter) -> None:
        from sunroom.plugins.weather.router import build

        build(router, self)

    async def on_enable(self, ctx: PluginContext) -> None:
        from sunroom.plugins.weather import service

        self.ctx = ctx

        async def refresh() -> None:
            await service.refresh(ctx)

        ctx.every("refresh", REFRESH_S, refresh)

    async def on_event(self, ctx: PluginContext, event: HubEvent) -> None:
        from sunroom.plugins.weather import service

        if event.type == "plugins.changed" and event.payload.get("id") != MANIFEST.id:
            return
        await service.refresh(ctx)

    # No on_disable: the context stays, so routes keep answering while a failed job has the
    # plugin errored (PLAN §11.4); switched off, the framework's gate answers for them.

    async def seed_sample(self, ctx: PluginContext, people: dict[str, str]) -> None:
        """The Sample Family lives in Sample Town (the core seed sets it): its forecast now, from
        the test server's made-up one."""
        from sunroom.plugins.weather import service

        await service.refresh(ctx, force=True)


PLUGIN = Weather()
