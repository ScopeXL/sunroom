"""The screensaver plugin's routes, under /api/screensaver (PLAN §11.3). Every route answers 404
plugin_disabled while the plugin is off (the framework gates them).

Any signed-in device reads the manifest (the wall shows it; a phone's More → Photos starts it with
core's ``POST /api/kiosk/command``). Where photos come from is a parent's business: the inbox and
the photo libraries (ADR 0036) live behind the PIN in Settings → Photos & Screensaver. Static
addresses come before ``/{source_id}`` ones.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel

from sunroom.auth.deps import ActorDep, ParentDep
from sunroom.core.errors import AppError
from sunroom.plugins.context import PluginContext
from sunroom.plugins.screensaver import libraries, service
from sunroom.plugins.screensaver.schemas import (
    LibraryChoicesOut,
    LibraryIn,
    LibraryKindOut,
    LibraryOut,
    LibraryPatch,
    LibraryReconnectIn,
    ManifestOut,
    ScanOut,
    SourceOut,
    SourcePatch,
)

if TYPE_CHECKING:
    from sunroom.plugins.screensaver.plugin import Screensaver


class LibraryTestIn(BaseModel):
    """The test server's pretend library: ``wipe`` leaves it needing its key again."""

    wipe: bool = False


def build(router: APIRouter, plugin: Screensaver) -> None:
    def ctx() -> PluginContext:
        if plugin.ctx is None:
            raise AppError(503, "starting", "api.photos.starting")
        return plugin.ctx

    @router.get("/manifest")
    async def get_manifest(actor: ActorDep) -> ManifestOut:  # pyright: ignore[reportUnusedFunction]
        return await service.manifest(ctx())

    @router.get("/sources")
    async def get_sources(actor: ParentDep) -> list[SourceOut]:  # pyright: ignore[reportUnusedFunction]
        return await service.sources(ctx())

    @router.patch("/sources/{source_id}")
    async def patch_source(  # pyright: ignore[reportUnusedFunction]
        source_id: str, body: SourcePatch, actor: ParentDep
    ) -> SourceOut:
        return await service.update_source(ctx(), source_id, body)

    @router.post("/sources/{source_id}/scan")
    async def scan_source(source_id: str, actor: ParentDep) -> ScanOut:  # pyright: ignore[reportUnusedFunction]
        return await service.scan_source(ctx(), source_id)

    # ---- photo libraries (ADR 0036) -------------------------------------------------------

    @router.get("/library-kinds")
    async def get_library_kinds(actor: ParentDep) -> list[LibraryKindOut]:  # pyright: ignore[reportUnusedFunction]
        ctx()
        return libraries.library_kinds()

    @router.get("/libraries")
    async def get_libraries(actor: ParentDep) -> list[LibraryOut]:  # pyright: ignore[reportUnusedFunction]
        return await libraries.libraries(ctx())

    @router.post("/libraries", status_code=201)
    async def add_library(body: LibraryIn, actor: ParentDep) -> LibraryOut:  # pyright: ignore[reportUnusedFunction]
        return await libraries.add_library(ctx(), body)

    @router.get("/libraries/{source_id}")
    async def get_library(source_id: str, actor: ParentDep) -> LibraryOut:  # pyright: ignore[reportUnusedFunction]
        return await libraries.get_library(ctx(), source_id)

    @router.patch("/libraries/{source_id}")
    async def patch_library(  # pyright: ignore[reportUnusedFunction]
        source_id: str, body: LibraryPatch, actor: ParentDep
    ) -> LibraryOut:
        return await libraries.update_library(ctx(), source_id, body)

    @router.post("/libraries/{source_id}/reconnect")
    async def reconnect_library(  # pyright: ignore[reportUnusedFunction]
        source_id: str, body: LibraryReconnectIn, actor: ParentDep
    ) -> LibraryOut:
        return await libraries.reconnect_library(ctx(), source_id, body)

    @router.delete("/libraries/{source_id}", status_code=204)
    async def remove_library(source_id: str, actor: ParentDep) -> None:  # pyright: ignore[reportUnusedFunction]
        await libraries.remove_library(ctx(), source_id)

    @router.get("/libraries/{source_id}/choices")
    async def get_choices(  # pyright: ignore[reportUnusedFunction]
        source_id: str, actor: ParentDep, refresh: bool = False
    ) -> LibraryChoicesOut:
        return await libraries.library_choices(ctx(), source_id, refresh=refresh)

    @router.get(
        "/libraries/{source_id}/thumb",
        response_class=Response,
        responses={200: {"content": {"image/jpeg": {}}, "description": "A face or a picture"}},
    )
    async def get_thumb(  # pyright: ignore[reportUnusedFunction]
        source_id: str,
        actor: ParentDep,
        person: Annotated[str | None, Query(max_length=100)] = None,
        asset: Annotated[str | None, Query(max_length=100)] = None,
    ) -> Response:
        data, media = await libraries.library_thumb(ctx(), source_id, person=person, asset=asset)
        return Response(data, media_type=media, headers={"Cache-Control": "private, max-age=3600"})

    @router.post("/libraries/{source_id}/scan")
    async def scan_library(source_id: str, actor: ParentDep) -> LibraryOut:  # pyright: ignore[reportUnusedFunction]
        context = ctx()
        library = await libraries.get_library(context, source_id)
        if not library.enabled:
            raise AppError(409, "source_off", "api.photos.turn_on_first")
        if not libraries.start_pass(context, source_id):
            raise AppError(409, "already_checking", "api.photos.checking_library")
        return await libraries.get_library(context, source_id)

    # Like the core's /api/_test routes: open on the test server, absent everywhere else.
    @router.post("/_test/library")
    async def test_library(body: LibraryTestIn) -> LibraryOut:  # pyright: ignore[reportUnusedFunction]
        context = ctx()
        if not context.test_mode:
            raise AppError(404, "not_found", "api.testing.not_found")
        return await libraries.pretend_library(context, wipe=body.wipe)
