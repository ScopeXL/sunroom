"""The screensaver plugin object: its manifest, routes and jobs."""

from __future__ import annotations

from fastapi import APIRouter

from sunroom.core.lang import t_en
from sunroom.plugins.base import (
    Contributions,
    DisplayRoom,
    PhoneTab,
    PluginBase,
    PluginManifest,
    Problem,
    SettingsSection,
)
from sunroom.plugins.context import PluginContext
from sunroom.plugins.screensaver.models import EXPORT_COLUMN_EXCLUDED, EXPORT_TABLES, TABLES
from sunroom.plugins.spec import ParamField

INBOX_SCAN_S = 5 * 60
THUMB_BACKLOG_S = 10 * 60
LIBRARY_SYNC_S = 30 * 60

MANIFEST = PluginManifest(
    id="screensaver",
    version="1.0.0",
    name=t_en("plugins.screensaver.name"),
    description=t_en("plugins.screensaver.description"),
    settings_spec=(
        ParamField(
            "start_after",
            t_en("plugins.screensaver.settings.start_after.label"),
            "choice",
            help=t_en("plugins.screensaver.settings.start_after.help"),
            # 10 minutes was a choice until 0.8.0: a stored "10" reads as this default.
            default="15",
            choices=("never", "5", "15", "30", "60"),
            choice_labels=(
                t_en("plugins.screensaver.settings.start_after.choices.never"),
                t_en("plugins.screensaver.settings.start_after.choices.5"),
                t_en("plugins.screensaver.settings.start_after.choices.15"),
                t_en("plugins.screensaver.settings.start_after.choices.30"),
                t_en("plugins.screensaver.settings.start_after.choices.60"),
            ),
        ),
        ParamField(
            "every",
            t_en("plugins.screensaver.settings.every.label"),
            "choice",
            default="30",
            choices=("15", "30", "60", "120", "300"),
            choice_labels=(
                t_en("plugins.screensaver.settings.every.choices.15"),
                t_en("plugins.screensaver.settings.every.choices.30"),
                t_en("plugins.screensaver.settings.every.choices.60"),
                t_en("plugins.screensaver.settings.every.choices.120"),
                t_en("plugins.screensaver.settings.every.choices.300"),
            ),
        ),
        ParamField(
            "show_clock",
            t_en("plugins.screensaver.settings.show_clock.label"),
            "bool",
            default=True,
        ),
        ParamField(
            "shuffle",
            t_en("plugins.screensaver.settings.shuffle.label"),
            "bool",
            default=True,
        ),
    ),
    tables=TABLES,
    export_tables=EXPORT_TABLES,
    export_column_excluded=EXPORT_COLUMN_EXCLUDED,
    contributes=Contributions(
        display_rooms=(
            DisplayRoom("photos", t_en("plugins.screensaver.rooms.photos"), "image", order=60),
        ),
        phone_tabs=(
            PhoneTab(
                "photos", t_en("plugins.screensaver.tabs.photos"), "image", "/photos", order=60
            ),
        ),
        settings_sections=(
            SettingsSection("screensaver", t_en("plugins.screensaver.sections.screensaver")),
        ),
        display_overlay=True,
    ),
    default_enabled=True,
)


class Screensaver(PluginBase):
    def __init__(self) -> None:
        self.manifest = MANIFEST
        self.ctx: PluginContext | None = None

    def register_routes(self, router: APIRouter) -> None:
        from sunroom.plugins.screensaver.router import build

        build(router, self)

    async def problems(self, ctx: PluginContext) -> list[Problem]:
        """The inbox when it fails, and a photo library that needs its key again or stopped
        answering (Needs Attention, ADR 0034, 0036)."""
        from sunroom.plugins.screensaver import libraries, service

        return [*await service.problems(ctx), *await libraries.problems(ctx)]

    async def on_enable(self, ctx: PluginContext) -> None:
        from sunroom.plugins.screensaver import libraries, service

        self.ctx = ctx
        await service.ensure_inbox(ctx)

        async def inbox_scan() -> None:
            await service.scan_inbox(ctx)

        async def thumb_backlog() -> None:
            await service.thumb_backlog(ctx)

        async def library_sync() -> None:
            # Each library's pass runs in a task of its own, so a slow one never holds up the
            # inbox, and a failing one stays inside it (hard rule 7).
            await libraries.sync_all(ctx)

        ctx.every("inbox-scan", INBOX_SCAN_S, inbox_scan)
        ctx.every("thumb-backlog", THUMB_BACKLOG_S, thumb_backlog)
        ctx.every("library-sync", LIBRARY_SYNC_S, library_sync)

    # No on_disable: the context stays, so routes keep answering while a failed job has the
    # plugin errored (PLAN §11.4); switched off, the framework's gate answers for them.

    async def seed_sample(self, ctx: PluginContext, people: dict[str, str]) -> None:
        from sunroom.plugins.screensaver.sample import seed

        await seed(ctx, people)


PLUGIN = Screensaver()
