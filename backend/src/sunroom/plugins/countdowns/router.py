"""The countdowns plugin's routes, under /api/countdowns (PLAN §11.3). Every route answers 404
plugin_disabled while the plugin is off (the framework gates them).

Any signed-in device may use them; the wall screen says who tapped with ``X-Sunroom-Member``
(who made a countdown), and a phone is always its own person. The wall screen never lists a
surprise: a countdown with ``show_on_display`` off.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Query

from sunroom.auth.deps import ActorDep
from sunroom.core.errors import AppError
from sunroom.plugins.context import PluginContext
from sunroom.plugins.countdowns import service
from sunroom.plugins.countdowns.schemas import (
    CountdownIn,
    CountdownOut,
    CountdownPatch,
    RemovedCountdownOut,
    UpcomingListOut,
)

if TYPE_CHECKING:
    from sunroom.plugins.countdowns.plugin import Countdowns


def build(router: APIRouter, plugin: Countdowns) -> None:
    def ctx() -> PluginContext:
        if plugin.ctx is None:
            raise AppError(503, "starting", "api.countdowns.starting")
        return plugin.ctx

    # ---- static paths before /{countdown_id} ------------------------------------------------

    @router.get("/upcoming")
    async def get_upcoming(  # pyright: ignore[reportUnusedFunction]
        actor: ActorDep,
        limit: Annotated[int | None, Query(ge=1, le=50)] = None,
        include_birthdays: bool = True,
        coming_up: bool = False,
        day: Annotated[date | None, Query(alias="date")] = None,
    ) -> UpcomingListOut:
        return await service.upcoming(
            ctx(),
            actor,
            day=day,
            limit=limit,
            include_birthdays=include_birthdays,
            coming_up=coming_up,
        )

    @router.get("/removed")
    async def get_removed(actor: ActorDep) -> list[RemovedCountdownOut]:  # pyright: ignore[reportUnusedFunction]
        return await service.removed(ctx(), actor)

    @router.get("")
    async def get_countdowns(actor: ActorDep) -> list[CountdownOut]:  # pyright: ignore[reportUnusedFunction]
        return await service.all_countdowns(ctx(), actor)

    @router.post("", status_code=201)
    async def post_countdown(body: CountdownIn, actor: ActorDep) -> CountdownOut:  # pyright: ignore[reportUnusedFunction]
        return await service.add_countdown(ctx(), actor, body)

    # ---- one countdown ----------------------------------------------------------------------

    @router.patch("/{countdown_id}")
    async def patch_countdown(  # pyright: ignore[reportUnusedFunction]
        countdown_id: str, body: CountdownPatch, actor: ActorDep
    ) -> CountdownOut:
        return await service.change_countdown(ctx(), countdown_id, body)

    @router.delete("/{countdown_id}", status_code=204)
    async def delete_countdown(countdown_id: str, actor: ActorDep) -> None:  # pyright: ignore[reportUnusedFunction]
        await service.remove_countdown(ctx(), countdown_id)

    @router.post("/{countdown_id}/restore")
    async def restore_countdown(countdown_id: str, actor: ActorDep) -> CountdownOut:  # pyright: ignore[reportUnusedFunction]
        return await service.restore_countdown(ctx(), countdown_id)
