"""The chores plugin object: its manifest, routes and jobs (ADR 0019, ADR 0025).

Shown to the family as Tasks (M6 batch 2, ADR 0029): only the words changed. The plugin id
`chores`, its routes, tables and events stay.
"""

from __future__ import annotations

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
from sunroom.plugins.chores.models import EXPORT_TABLES, TABLES
from sunroom.plugins.context import PluginContext
from sunroom.plugins.spec import ParamField

HOUR_S = 3600

MANIFEST = PluginManifest(
    id="chores",
    version="1.0.0",
    name=t_en("plugins.chores.name"),
    description=t_en("plugins.chores.description"),
    settings_spec=(
        ParamField(
            "stars",
            t_en("plugins.chores.settings.stars.label"),
            "bool",
            help=t_en("plugins.chores.settings.stars.help"),
            default=True,
        ),
        ParamField(
            "rewards",
            t_en("plugins.chores.settings.rewards.label"),
            "bool",
            help=t_en("plugins.chores.settings.rewards.help"),
            default=True,
        ),
        ParamField(
            "routines",
            t_en("plugins.chores.settings.routines.label"),
            "bool",
            help=t_en("plugins.chores.settings.routines.help"),
            default=True,
        ),
        ParamField(
            "approval",
            t_en("plugins.chores.settings.approval.label"),
            "bool",
            help=t_en("plugins.chores.settings.approval.help"),
            default=False,
        ),
    ),
    tables=TABLES,
    export_tables=EXPORT_TABLES,
    contributes=Contributions(
        display_panels=(DisplayPanel("today", t_en("plugins.chores.panels.today")),),
        display_rooms=(
            DisplayRoom("chores", t_en("plugins.chores.rooms.chores"), "check", order=30),
        ),
        phone_tabs=(
            PhoneTab("chores", t_en("plugins.chores.tabs.chores"), "check", "/chores", order=30),
        ),
        settings_sections=(SettingsSection("chores", t_en("plugins.chores.sections.chores")),),
    ),
    default_enabled=True,
)


class Chores(PluginBase):
    def __init__(self) -> None:
        self.manifest = MANIFEST
        self.ctx: PluginContext | None = None

    def register_routes(self, router: APIRouter) -> None:
        from sunroom.plugins.chores.router import build

        build(router, self)

    async def on_enable(self, ctx: PluginContext) -> None:
        from sunroom.plugins.chores import service

        self.ctx = ctx

        async def prune() -> None:
            await service.prune(ctx)

        ctx.every("prune", HOUR_S, prune)

    # No on_disable: the context stays, so routes keep answering while a failed job has the
    # plugin errored (PLAN §11.4); switched off, the framework's gate answers for them.

    async def seed_sample(self, ctx: PluginContext, people: dict[str, str]) -> None:
        from sunroom.plugins.chores.sample import seed

        await seed(ctx, people)


PLUGIN = Chores()
