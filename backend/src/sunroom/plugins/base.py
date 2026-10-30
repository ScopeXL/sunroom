"""The plugin contract (PLAN §6.2, ADR 0002).

A plugin is one package under ``plugins/<id>/`` plus a folder under ``frontend/src/features/``,
each listed in an explicit registry. It sees the world only through ``PluginContext``
(plugins/context.py): never the engine, never another plugin's tables. Two rules every plugin
keeps (CLAUDE.md): it works with every other plugin disabled, and it never reads another
plugin's tables.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from fastapi import APIRouter

from sunroom.core.lang import Value, t_en
from sunroom.plugins.spec import ParamField

if TYPE_CHECKING:
    from sunroom.plugins.context import PluginContext

PLUGIN_ID = re.compile(r"^[a-z][a-z0-9_]{1,30}$")


class PluginStatus(StrEnum):
    DISABLED = "disabled"
    STARTING = "starting"
    RUNNING = "running"
    ERRORED = "errored"
    STOPPING = "stopping"


@dataclass(frozen=True, slots=True)
class DisplayPanel:
    """A block in the display's Today panel (or a board tile)."""

    key: str
    title: str
    sizes: tuple[str, ...] = ("m",)
    default_size: str = "m"
    requires_member: bool = False


@dataclass(frozen=True, slots=True)
class DisplayRoom:
    """A full-screen room on the display's rail."""

    key: str
    title: str
    icon: str
    order: int = 50


@dataclass(frozen=True, slots=True)
class PhoneTab:
    key: str
    title: str
    icon: str
    path: str
    order: int = 50


@dataclass(frozen=True, slots=True)
class SettingsSection:
    key: str
    title: str
    parent_only: bool = True


@dataclass(frozen=True, slots=True)
class Contributions:
    display_panels: tuple[DisplayPanel, ...] = ()
    display_rooms: tuple[DisplayRoom, ...] = ()
    phone_tabs: tuple[PhoneTab, ...] = ()
    settings_sections: tuple[SettingsSection, ...] = ()
    display_overlay: bool = False  # the screensaver


@dataclass(frozen=True, slots=True)
class PluginManifest:
    id: str  # ^[a-z][a-z0-9_]{1,30}$ ; its URL prefix is the id with '-' for '_'
    version: str  # semver of the plugin's API and settings shape
    name: str  # what the user sees under Settings → Features
    description: str  # one line: what it adds
    settings_spec: tuple[ParamField, ...] = ()
    tables: tuple[str, ...] = ()  # every table this plugin owns
    export_tables: tuple[str, ...] = ()  # the ones that go into Export everything
    # Columns of exported tables that never leave: {"sync_accounts": {"credentials_enc"}}
    export_column_excluded: dict[str, frozenset[str]] = field(
        default_factory=dict[str, frozenset[str]]
    )
    contributes: Contributions = Contributions()
    default_enabled: bool = False
    subscribes: tuple[str, ...] = ()  # hub event prefixes delivered to on_event

    @property
    def url_prefix(self) -> str:
        return self.id.replace("_", "-")


@dataclass(frozen=True, slots=True)
class Problem:
    """Something that needs a parent, for Needs Attention (ADR 0034): an account that stopped
    syncing, a photo source that fails. ``id`` is stable per cause ("sync:<account id>");
    ``key`` its one sentence in the family's words, with no ids or secrets, in ``lang/en.json``
    (``api.<area>.*``), and ``params`` its values: the page says it in the family's language,
    and ``title`` is its English (ADR 0043); ``detail`` a quiet second line, for parents only;
    ``since`` when it started; ``page`` the Settings page that fixes it."""

    id: str
    key: str
    params: Mapping[str, Value] = field(default_factory=dict[str, Value])
    detail: str | None = None
    since: datetime | None = None
    page: str | None = None

    @property
    def title(self) -> str:
        return t_en(self.key, **self.params)


@dataclass(frozen=True, slots=True)
class HubEvent:
    """A live-update event as a plugin receives it (``area.verb`` plus its payload)."""

    type: str
    payload: dict[str, Any]


@runtime_checkable
class Plugin(Protocol):
    manifest: PluginManifest

    def register_routes(self, router: APIRouter) -> None:
        """Add the plugin's routes. The router is already prefixed (/api/<url_prefix>) and gated:
        every route answers 404 plugin_disabled while the plugin is off."""
        ...

    async def on_enable(self, ctx: PluginContext) -> None:
        """Start: register jobs with ``ctx.every`` / ``ctx.spawn``. Runs in the plugin's task."""
        ...

    async def on_disable(self, ctx: PluginContext) -> None:
        """Stop within 10 s. Must not raise. Data stays (PLAN §6.4)."""
        ...

    async def on_event(self, ctx: PluginContext, event: HubEvent) -> None:
        """A hub event matching ``manifest.subscribes`` (never overlaps other callbacks)."""
        ...

    async def validate_settings(self, ctx: PluginContext, values: dict[str, Any]) -> list[str]:
        """Extra checks after coercion; return plain-English problems (empty when fine)."""
        ...

    def upgrade_settings(self, raw: dict[str, Any], from_version: str) -> dict[str, Any]:
        """Stored settings written by an older ``manifest.version``, as this version reads them.
        Called once at boot when the stored version is behind, on the raw JSON, before unknown
        keys are dropped: the place to carry a renamed or reshaped setting over, so nothing the
        family set disappears. Return ``raw`` unchanged when there's nothing to carry."""
        ...

    async def seed_sample(self, ctx: PluginContext, people: dict[str, str]) -> None:
        """Test mode only (``just seed``, screenshots, end-to-end runs): the synthetic Sample
        Family's data in this plugin's tables. ``people`` maps names (Ana, Sam, Mia, Leo) to
        member ids."""
        ...

    async def problems(self, ctx: PluginContext) -> list[Problem]:
        """What needs a parent right now (Needs Attention, ADR 0034); empty when all is well.
        Read on request, while the plugin is on, never for one that's off; a failure here is
        logged and shows nothing."""
        ...


class PluginBase:
    """Optional defaults for the hooks most plugins don't need."""

    manifest: PluginManifest

    def register_routes(self, router: APIRouter) -> None:
        return None

    async def on_enable(self, ctx: PluginContext) -> None:
        return None

    async def on_disable(self, ctx: PluginContext) -> None:
        return None

    async def on_event(self, ctx: PluginContext, event: HubEvent) -> None:
        return None

    async def validate_settings(self, ctx: PluginContext, values: dict[str, Any]) -> list[str]:
        return []

    def upgrade_settings(self, raw: dict[str, Any], from_version: str) -> dict[str, Any]:
        return raw

    async def seed_sample(self, ctx: PluginContext, people: dict[str, str]) -> None:
        return None

    async def problems(self, ctx: PluginContext) -> list[Problem]:
        return []
