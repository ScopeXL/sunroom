"""Features: the plugin list, switches and settings (PLAN §6.4, §6.5), and the gate that makes
a disabled plugin's routes answer 404 ``plugin_disabled``."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any, Literal

from fastapi import APIRouter, Depends, FastAPI
from pydantic import BaseModel

from sunroom.auth.deps import ActorDep, ParentDep
from sunroom.core.errors import AppError
from sunroom.plugins.base import Plugin
from sunroom.plugins.manager import PluginError
from sunroom.plugins.spec import masked
from sunroom.state import AppState, StateDep

router = APIRouter(prefix="/api/plugins", tags=["plugins"])


class PanelOut(BaseModel):
    key: str
    title: str
    sizes: list[str]
    default_size: str
    requires_member: bool


class RoomOut(BaseModel):
    key: str
    title: str
    icon: str
    order: int


class TabOut(BaseModel):
    key: str
    title: str
    icon: str
    path: str
    order: int


class SectionOut(BaseModel):
    key: str
    title: str
    parent_only: bool


class ContributesOut(BaseModel):
    display_panels: list[PanelOut]
    display_rooms: list[RoomOut]
    phone_tabs: list[TabOut]
    settings_sections: list[SectionOut]
    display_overlay: bool


class FieldOut(BaseModel):
    key: str
    label: str
    type: str
    help: str
    default: Any
    required: bool
    min: float | None
    max: float | None
    step: float | None
    unit: str | None
    group: str
    choices: list[str] | None
    choice_labels: list[str] | None
    max_length: int | None


class PluginOut(BaseModel):
    id: str
    url_prefix: str
    version: str
    name: str
    description: str
    enabled: bool
    status: Literal["disabled", "starting", "running", "errored", "stopping"]
    error: str | None
    settings_spec: list[FieldOut]
    settings: dict[str, Any]
    contributes: ContributesOut
    requires_parent_to_manage: bool


class SettingsIn(BaseModel):
    values: dict[str, Any]


def plugin_out(state: AppState, plugin: Plugin) -> PluginOut:
    manifest = plugin.manifest
    contributes = manifest.contributes
    return PluginOut.model_validate(
        {
            "id": manifest.id,
            "url_prefix": manifest.url_prefix,
            "version": manifest.version,
            "name": manifest.name,
            "description": manifest.description,
            "enabled": state.plugins.is_enabled(manifest.id),
            "status": state.plugins.status(manifest.id).value,
            "error": state.plugins.error(manifest.id),
            "settings_spec": [field.describe() for field in manifest.settings_spec],
            "settings": masked(manifest.settings_spec, state.plugins.settings(manifest.id)),
            "contributes": {
                "display_panels": [
                    {
                        "key": panel.key,
                        "title": panel.title,
                        "sizes": list(panel.sizes),
                        "default_size": panel.default_size,
                        "requires_member": panel.requires_member,
                    }
                    for panel in contributes.display_panels
                ],
                "display_rooms": [
                    {"key": r.key, "title": r.title, "icon": r.icon, "order": r.order}
                    for r in contributes.display_rooms
                ],
                "phone_tabs": [
                    {
                        "key": t.key,
                        "title": t.title,
                        "icon": t.icon,
                        "path": t.path,
                        "order": t.order,
                    }
                    for t in contributes.phone_tabs
                ],
                "settings_sections": [
                    {"key": s.key, "title": s.title, "parent_only": s.parent_only}
                    for s in contributes.settings_sections
                ],
                "display_overlay": contributes.display_overlay,
            },
            "requires_parent_to_manage": True,
        }
    )


def _plugin(state: AppState, plugin_id: str) -> Plugin:
    plugin = state.plugins.registry.get(plugin_id)
    if plugin is None:
        raise AppError(404, "not_found", "api.plugins.not_found")
    return plugin


def _as_app_error(exc: PluginError) -> AppError:
    status = 404 if exc.code == "not_found" else 409 if exc.code == "plugin_disabled" else 422
    extra = {"problems": exc.problems} if exc.problems else None
    return AppError(status, exc.code, exc.key, extra=extra)


@router.get("")
async def list_plugins(state: StateDep, actor: ActorDep) -> list[PluginOut]:
    return [plugin_out(state, plugin) for plugin in state.plugins.registry.values()]


@router.post("/{plugin_id}/enable")
async def enable(plugin_id: str, state: StateDep, actor: ParentDep) -> PluginOut:
    plugin = _plugin(state, plugin_id)
    try:
        await state.plugins.enable(plugin_id)
    except PluginError as exc:
        raise _as_app_error(exc) from None
    return plugin_out(state, plugin)


@router.post("/{plugin_id}/disable")
async def disable(plugin_id: str, state: StateDep, actor: ParentDep) -> PluginOut:
    plugin = _plugin(state, plugin_id)
    try:
        await state.plugins.disable(plugin_id)
    except PluginError as exc:
        raise _as_app_error(exc) from None
    return plugin_out(state, plugin)


@router.post("/{plugin_id}/restart")
async def restart(plugin_id: str, state: StateDep, actor: ParentDep) -> PluginOut:
    plugin = _plugin(state, plugin_id)
    try:
        await state.plugins.restart(plugin_id)
    except PluginError as exc:
        raise _as_app_error(exc) from None
    return plugin_out(state, plugin)


@router.get("/{plugin_id}/settings")
async def get_settings(plugin_id: str, state: StateDep, actor: ActorDep) -> dict[str, Any]:
    plugin = _plugin(state, plugin_id)
    return masked(plugin.manifest.settings_spec, state.plugins.settings(plugin_id))


@router.put("/{plugin_id}/settings")
async def put_settings(
    plugin_id: str, body: SettingsIn, state: StateDep, actor: ParentDep
) -> dict[str, Any]:
    plugin = _plugin(state, plugin_id)
    try:
        values = await state.plugins.update_settings(plugin_id, body.values)
    except PluginError as exc:
        raise _as_app_error(exc) from None
    return masked(plugin.manifest.settings_spec, values)


def gate(plugin_id: str, name: str) -> Callable[[StateDep], Coroutine[Any, Any, None]]:
    """A dependency every route of a plugin carries: off means 404 plugin_disabled."""

    async def check(state: StateDep) -> None:
        if not state.plugins.is_enabled(plugin_id):
            raise AppError(404, "plugin_disabled", "api.plugins.turned_off", params={"name": name})

    return check


def mount_plugin_routes(app: FastAPI, registry: dict[str, Plugin]) -> None:
    for plugin in registry.values():
        manifest = plugin.manifest
        plugin_router = APIRouter(
            prefix=f"/api/{manifest.url_prefix}",
            tags=[manifest.id],
            dependencies=[Depends(gate(manifest.id, manifest.name))],
        )
        plugin.register_routes(plugin_router)
        app.include_router(plugin_router)
