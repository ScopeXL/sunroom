"""The meals plugin's routes, under /api/meals (PLAN §11.3). Every route answers 404
plugin_disabled while the plugin is off (the framework gates them).

Any signed-in device may use them; the wall screen says who tapped with ``X-Sunroom-Member``
(who added a meal), and a phone is always its own person. Nothing here needs a parent: Undo and
Recently removed cover mistakes.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Query

from sunroom.auth.deps import ActorDep
from sunroom.core.errors import AppError
from sunroom.plugins.context import PluginContext
from sunroom.plugins.meals import service
from sunroom.plugins.meals.schemas import (
    CopyWeekIn,
    CopyWeekOut,
    EntryIn,
    EntryOut,
    EntrySaved,
    MealMoveIn,
    MealMoveOut,
    MealsRemovedOut,
    MealWeekOut,
    SavedMealIn,
    SavedMealOut,
    SavedMealPatch,
)

if TYPE_CHECKING:
    from sunroom.plugins.meals.plugin import Meals

# A week for the Meals room, one day for Tonight; two weeks at most.
Days = Annotated[int, Query(ge=1, le=14)]
Search = Annotated[str | None, Query(max_length=120)]


def build(router: APIRouter, plugin: Meals) -> None:
    def ctx() -> PluginContext:
        if plugin.ctx is None:
            raise AppError(503, "starting", "api.meals.starting")
        return plugin.ctx

    # ---- the week (static paths before /{id} ones) ---------------------------------------------

    @router.get("/week")
    async def get_week(  # pyright: ignore[reportUnusedFunction]
        actor: ActorDep, start: date | None = None, days: Days = 7
    ) -> MealWeekOut:
        return await service.week(ctx(), start, days)

    @router.put("/entries")
    async def put_entry(body: EntryIn, actor: ActorDep) -> EntrySaved:  # pyright: ignore[reportUnusedFunction]
        return await service.save_entry(ctx(), actor, body)

    @router.post("/copy-week")
    async def copy_week(body: CopyWeekIn, actor: ActorDep) -> CopyWeekOut:  # pyright: ignore[reportUnusedFunction]
        return await service.copy_week(ctx(), actor, body)

    @router.get("/removed")
    async def get_removed(actor: ActorDep) -> MealsRemovedOut:  # pyright: ignore[reportUnusedFunction]
        return await service.removed(ctx())

    # ---- one entry ----------------------------------------------------------------------------

    @router.delete("/entries/{entry_id}", status_code=204)
    async def delete_entry(entry_id: str, actor: ActorDep) -> None:  # pyright: ignore[reportUnusedFunction]
        await service.remove_entry(ctx(), entry_id)

    @router.post("/entries/{entry_id}/restore")
    async def restore_entry(entry_id: str, actor: ActorDep) -> EntryOut:  # pyright: ignore[reportUnusedFunction]
        return await service.restore_entry(ctx(), entry_id)

    @router.post("/entries/{entry_id}/move")
    async def move_entry(entry_id: str, body: MealMoveIn, actor: ActorDep) -> MealMoveOut:  # pyright: ignore[reportUnusedFunction]
        return await service.move_entry(ctx(), entry_id, body)

    # ---- saved meals --------------------------------------------------------------------------

    @router.get("/saved")
    async def get_saved(actor: ActorDep, q: Search = None) -> list[SavedMealOut]:  # pyright: ignore[reportUnusedFunction]
        return await service.saved_meals(ctx(), q)

    @router.post("/saved", status_code=201)
    async def post_saved(body: SavedMealIn, actor: ActorDep) -> SavedMealOut:  # pyright: ignore[reportUnusedFunction]
        return await service.add_saved(ctx(), actor, body)

    @router.patch("/saved/{saved_id}")
    async def patch_saved(  # pyright: ignore[reportUnusedFunction]
        saved_id: str, body: SavedMealPatch, actor: ActorDep
    ) -> SavedMealOut:
        return await service.change_saved(ctx(), saved_id, body)

    @router.delete("/saved/{saved_id}", status_code=204)
    async def delete_saved(saved_id: str, actor: ActorDep) -> None:  # pyright: ignore[reportUnusedFunction]
        await service.archive_saved(ctx(), saved_id)

    @router.post("/saved/{saved_id}/restore")
    async def restore_saved(saved_id: str, actor: ActorDep) -> SavedMealOut:  # pyright: ignore[reportUnusedFunction]
        return await service.restore_saved(ctx(), saved_id)
