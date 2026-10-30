"""The weather plugin's routes, under /api/weather (PLAN §11.3). Every route answers 404
plugin_disabled while the plugin is off (the framework gates them).

Any signed-in device reads the forecast. Checking again and the town search are a parent's
(Settings → Household → Location), each with its limit: Check now once a minute, ten searches a
minute for each device (PLAN §12.7).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Query

from sunroom.auth.deps import ActorDep, ParentDep
from sunroom.core.errors import AppError
from sunroom.plugins.context import PluginContext
from sunroom.plugins.weather import service
from sunroom.plugins.weather.schemas import PlaceOut, WeatherOut

if TYPE_CHECKING:
    from sunroom.plugins.weather.plugin import Weather


def build(router: APIRouter, plugin: Weather) -> None:
    searches = service.SearchLimit()

    def ctx() -> PluginContext:
        if plugin.ctx is None:
            raise AppError(503, "starting", "api.weather.starting")
        return plugin.ctx

    @router.get("")
    async def get_weather(actor: ActorDep) -> WeatherOut:  # pyright: ignore[reportUnusedFunction]
        return await service.weather(ctx())

    @router.post("/refresh")
    async def post_refresh(actor: ParentDep) -> WeatherOut:  # pyright: ignore[reportUnusedFunction]
        return await service.check_now(ctx())

    @router.get("/geocode")
    async def get_geocode(  # pyright: ignore[reportUnusedFunction]
        actor: ParentDep, q: Annotated[str, Query(min_length=2, max_length=80)]
    ) -> list[PlaceOut]:
        context = ctx()
        searches.check(actor.device_id, context.now())
        return await service.search(context, q)
