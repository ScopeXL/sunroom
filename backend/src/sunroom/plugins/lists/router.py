"""The lists plugin's routes, under /api/lists (PLAN §11.3). Every route answers 404
plugin_disabled while the plugin is off (the framework gates them).

Any signed-in device may use them; the wall screen says who tapped with ``X-Sunroom-Member``,
and a phone is always its own person. Removing or putting back a whole list needs a parent (or
a kid's phone, for its person's own list); see ``service`` for who may remove an item.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Query

from sunroom.auth.deps import ActorDep
from sunroom.core.errors import AppError
from sunroom.plugins.context import PluginContext
from sunroom.plugins.lists import service
from sunroom.plugins.lists.schemas import (
    ClearedOut,
    IdsIn,
    ItemOut,
    ItemPatch,
    ItemsAdded,
    ItemsIn,
    ListDetailOut,
    ListIn,
    ListOut,
    ListPatch,
    OrderIn,
    RemovedOut,
    TodoOut,
)

if TYPE_CHECKING:
    from sunroom.plugins.lists.plugin import Lists


def build(router: APIRouter, plugin: Lists) -> None:
    def ctx() -> PluginContext:
        if plugin.ctx is None:
            raise AppError(503, "starting", "api.lists.starting")
        return plugin.ctx

    # ---- every list (static paths before /{list_id}) ------------------------------------------

    @router.get("")
    async def get_lists(actor: ActorDep) -> list[ListOut]:  # pyright: ignore[reportUnusedFunction]
        return await service.all_lists(ctx())

    @router.post("", status_code=201)
    async def post_list(body: ListIn, actor: ActorDep) -> ListOut:  # pyright: ignore[reportUnusedFunction]
        return await service.create_list(ctx(), actor, body)

    @router.put("/order", status_code=204)
    async def put_order(body: OrderIn, actor: ActorDep) -> None:  # pyright: ignore[reportUnusedFunction]
        await service.order_lists(ctx(), body.ids)

    @router.get("/todo")
    async def get_todo(  # pyright: ignore[reportUnusedFunction]
        actor: ActorDep, day: Annotated[date | None, Query(alias="date")] = None
    ) -> TodoOut:
        return await service.todo(ctx(), day)

    @router.get("/removed")
    async def get_removed(actor: ActorDep) -> RemovedOut:  # pyright: ignore[reportUnusedFunction]
        return await service.removed(ctx())

    # ---- one list ---------------------------------------------------------------------------

    @router.patch("/{list_id}")
    async def patch_list(list_id: str, body: ListPatch, actor: ActorDep) -> ListOut:  # pyright: ignore[reportUnusedFunction]
        return await service.update_list(ctx(), list_id, body)

    @router.delete("/{list_id}", status_code=204)
    async def delete_list(list_id: str, actor: ActorDep) -> None:  # pyright: ignore[reportUnusedFunction]
        await service.remove_list(ctx(), actor, list_id)

    @router.post("/{list_id}/restore")
    async def restore_list(list_id: str, actor: ActorDep) -> ListOut:  # pyright: ignore[reportUnusedFunction]
        return await service.restore_list(ctx(), actor, list_id)

    # ---- its items --------------------------------------------------------------------------

    @router.get("/{list_id}/items")
    async def get_items(list_id: str, actor: ActorDep) -> ListDetailOut:  # pyright: ignore[reportUnusedFunction]
        return await service.list_detail(ctx(), list_id)

    @router.post("/{list_id}/items", status_code=201)
    async def post_items(list_id: str, body: ItemsIn, actor: ActorDep) -> ItemsAdded:  # pyright: ignore[reportUnusedFunction]
        return await service.add_items(ctx(), actor, list_id, body)

    @router.patch("/{list_id}/items/{item_id}")
    async def patch_item(  # pyright: ignore[reportUnusedFunction]
        list_id: str, item_id: str, body: ItemPatch, actor: ActorDep
    ) -> ItemOut:
        return await service.update_item(ctx(), actor, list_id, item_id, body)

    @router.delete("/{list_id}/items/{item_id}", status_code=204)
    async def delete_item(list_id: str, item_id: str, actor: ActorDep) -> None:  # pyright: ignore[reportUnusedFunction]
        await service.remove_item(ctx(), actor, list_id, item_id)

    @router.post("/{list_id}/restore-items")
    async def restore_items(list_id: str, body: IdsIn, actor: ActorDep) -> list[ItemOut]:  # pyright: ignore[reportUnusedFunction]
        return await service.restore_items(ctx(), actor, list_id, body.ids)

    @router.post("/{list_id}/clear-checked")
    async def clear_checked(list_id: str, actor: ActorDep) -> ClearedOut:  # pyright: ignore[reportUnusedFunction]
        return await service.clear_checked(ctx(), list_id)
