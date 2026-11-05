"""Collecting what needs a parent (ADR 0034).

In order: a feature that stopped; each feature's own problems (an account that stopped syncing,
a photo source that fails); a backup that failed or is a week old; a server running out of room;
a new version that's out (ADR 0046).
Everything is read on request, from what's already in memory or one quick query per feature, so
the list is never stale for long: the frontend asks again when a live event says something
changed, and every 5 minutes for the two causes no event announces (a 3:30 AM backup, the disk).
"""

from __future__ import annotations

import shutil
from datetime import datetime

from sunroom.auth.deps import Actor
from sunroom.core.lang import t_en
from sunroom.meta.updates import update_out
from sunroom.plugins.base import PluginStatus
from sunroom.problems.schemas import ProblemOut
from sunroom.state import AppState

# Under this much free space the server can't keep photos and nightly copies for long.
LOW_SPACE_BYTES = 2 * 1024**3


def _gigabytes(size: int) -> str:
    return f"{size / 1024**3:.1f} GB"


async def collect(state: AppState, actor: Actor) -> list[ProblemOut]:
    """Every problem, each with a sentence and the page that fixes it. ``detail`` is a parent's
    only: a wall screen or a child's phone sees the sentences (no secrets by construction)."""
    found: list[ProblemOut] = []
    manager = state.plugins
    for plugin_id, plugin in manager.registry.items():
        if manager.is_enabled(plugin_id) and manager.status(plugin_id) is PluginStatus.ERRORED:
            params: dict[str, str | int | float] = {"name": plugin.manifest.name}
            found.append(
                ProblemOut(
                    id=f"plugin:{plugin_id}",
                    title=t_en("api.problems.plugin_stopped", **params),
                    key="api.problems.plugin_stopped",
                    params=params,
                    detail=None,
                    since=None,
                    page="features",
                    source="core",
                )
            )
    for plugin_id, problem in await manager.problems():
        found.append(
            ProblemOut(
                id=problem.id,
                title=problem.title,
                key=problem.key,
                params=dict(problem.params),
                detail=problem.detail,
                since=problem.since,
                page=problem.page,
                source=plugin_id,
            )
        )
    backup = state.backups.status()
    if backup.get("last_error"):
        found.append(
            ProblemOut(
                id="backup:failed",
                title=t_en("api.problems.backup_failed"),
                key="api.problems.backup_failed",
                params={},
                detail=t_en("api.problems.backup_failed_detail", error=backup["last_error"]),
                since=None,
                page="backup",
                source="core",
            )
        )
    elif backup.get("stale") and backup.get("enabled", True):
        last = backup.get("last_success_at")
        found.append(
            ProblemOut(
                id="backup:stale",
                title=t_en("api.problems.backup_stale"),
                key="api.problems.backup_stale",
                params={},
                detail=None,
                since=datetime.fromisoformat(last) if isinstance(last, str) else None,
                page="backup",
                source="core",
            )
        )
    free = shutil.disk_usage(state.settings.data_dir).free
    if free < LOW_SPACE_BYTES:
        params: dict[str, str | int | float] = {"free": _gigabytes(free)}
        found.append(
            ProblemOut(
                id="storage:low",
                title=t_en("api.problems.storage_low", **params),
                key="api.problems.storage_low",
                params=params,
                detail=None,
                since=None,
                page="about",
                source="core",
            )
        )
    update = await update_out(state)
    if update.enabled and update.available and update.latest is not None:
        params = {"version": update.latest}
        found.append(
            ProblemOut(
                id="update:available",
                title=t_en("api.problems.update_available", **params),
                key="api.problems.update_available",
                params=params,
                detail=update.how,
                detail_key=update.how_key,
                since=None,
                page="about",
                source="core",
            )
        )
    if not actor.is_parent:
        found = [
            problem.model_copy(update={"detail": None, "detail_key": None}) for problem in found
        ]
    return found
