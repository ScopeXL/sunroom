"""Plugin runners (PLAN §6.3, §6.4): one asyncio task and queue per enabled plugin.

``on_enable`` runs in the plugin's task; job tickers and subscribed hub events are queued, so a
plugin's callbacks never overlap and its code needs no locks. Plugins run alongside each other.
Any exception marks that plugin ``errored`` with a scrubbed message, stops its background work
and publishes ``plugins.changed``; its routes keep working, because its data is intact. A parent
sees a quiet line ("Weather stopped working. Retry") that calls ``restart``. A plugin that fails
to start never stops the server.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Coroutine, Mapping
from dataclasses import dataclass, field
from typing import Any, cast

from sqlalchemy import select

from sunroom.core.clock import Clock
from sunroom.core.lang import t_en
from sunroom.core.logging import get_logger
from sunroom.db.engine import Database
from sunroom.plugins.base import HubEvent, Plugin, PluginStatus, Problem
from sunroom.plugins.context import Job, PluginContext
from sunroom.plugins.models import PluginState
from sunroom.plugins.spec import coerce_params, defaults

log = get_logger(__name__)

QUEUE_MAX = 1024
STOP_BUDGET_S = 10.0

ContextFactory = Callable[[str, "PluginRunner"], PluginContext]


@dataclass(frozen=True, slots=True)
class _Tick:
    job: str


@dataclass(frozen=True, slots=True)
class _Deliver:
    event: HubEvent


_STOP = object()


class PluginRunner:
    """One enabled plugin: its task, its queue, its job tickers and anything it spawned."""

    def __init__(
        self,
        plugin: Plugin,
        context_factory: ContextFactory,
        *,
        on_running: Callable[[str], None],
        on_error: Callable[[str, BaseException], None],
    ) -> None:
        self.plugin = plugin
        self.id = plugin.manifest.id
        self.queue: asyncio.Queue[object] = asyncio.Queue(maxsize=QUEUE_MAX)
        self.jobs: dict[str, Job] = {}
        self._tickers: list[asyncio.Task[None]] = []
        self._spawned: set[asyncio.Task[None]] = set()
        self._task: asyncio.Task[None] | None = None
        self._stopping: asyncio.Future[None] | None = None
        self._on_running = on_running
        self._on_error = on_error
        self.failed = False
        self.ctx = context_factory(self.id, self)

    # ---- PluginContext's Runner protocol -------------------------------------------------

    def every(self, name: str, interval_s: float, job: Job) -> None:
        self.jobs[name] = job

        async def ticker() -> None:
            while True:
                self._enqueue(_Tick(name))
                await asyncio.sleep(interval_s)

        self._tickers.append(asyncio.create_task(ticker(), name=f"plugin:{self.id}:{name}"))

    def spawn(self, name: str, coro: Coroutine[Any, Any, None]) -> None:
        task = asyncio.create_task(coro, name=f"plugin:{self.id}:{name}")
        self._spawned.add(task)
        task.add_done_callback(self._spawned_done)

    # ---- lifecycle -----------------------------------------------------------------------

    def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name=f"plugin:{self.id}")

    def deliver(self, event: HubEvent) -> None:
        self._enqueue(_Deliver(event))

    async def _run(self) -> None:
        try:
            await self.plugin.on_enable(self.ctx)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._fail(exc)
            return
        self._on_running(self.id)
        while True:
            item = await self.queue.get()
            if item is _STOP:
                return
            try:
                if isinstance(item, _Tick):
                    await self.jobs[item.job]()
                elif isinstance(item, _Deliver):
                    await self.plugin.on_event(self.ctx, item.event)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._fail(exc)
                return

    def _enqueue(self, item: object) -> None:
        if self.failed:
            return
        try:
            self.queue.put_nowait(item)
        except asyncio.QueueFull:
            self._fail(RuntimeError("it fell too far behind (its queue overflowed)"))

    def _spawned_done(self, task: asyncio.Task[None]) -> None:
        self._spawned.discard(task)
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            self._fail(exc)

    def _fail(self, exc: BaseException) -> None:
        if self.failed:
            return
        self.failed = True
        self._cancel_background()
        self._on_error(self.id, exc)

    def _cancel_background(self) -> None:
        for task in [*self._tickers, *self._spawned]:
            task.cancel()
        self._tickers.clear()

    async def stop(self) -> None:
        """Stop within the budget; never raises (PLAN §6.4). Calling it again waits for the
        same stop, so on_disable runs once."""
        if self._stopping is None:
            self._stopping = asyncio.ensure_future(self._stop())
        await asyncio.shield(self._stopping)

    async def _stop(self) -> None:
        self._cancel_background()
        task = self._task
        if task is not None and not task.done():
            try:
                self.queue.put_nowait(_STOP)
            except asyncio.QueueFull:
                task.cancel()
            done, _ = await asyncio.wait({task}, timeout=STOP_BUDGET_S / 2)
            if not done:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        try:
            await asyncio.wait_for(self.plugin.on_disable(self.ctx), timeout=STOP_BUDGET_S / 2)
        except Exception:
            log.warning("plugin.disable_failed", plugin=self.id)
        spawned = list(self._spawned)
        if spawned:
            await asyncio.gather(*spawned, return_exceptions=True)


@dataclass
class _Live:
    status: PluginStatus = PluginStatus.DISABLED
    enabled: bool = False
    error: str | None = None
    settings: dict[str, Any] = field(default_factory=dict[str, Any])
    settings_version: int = 1
    runner: PluginRunner | None = None


class PluginError(Exception):
    """A plugin action refused: ``key`` names the sentence in ``lang/en.json`` and ``message``
    is its English; ``problems`` are a settings change's plain-English problems."""

    def __init__(self, code: str, key: str, problems: list[str] | None = None) -> None:
        self.code = code
        self.key = key
        self.message = t_en(key)
        super().__init__(self.message)
        self.problems = problems or []


class PluginManager:
    def __init__(
        self,
        registry: Mapping[str, Plugin],
        *,
        db: Database,
        clock: Clock,
        context_factory: Callable[[str, PluginRunner, Callable[[], dict[str, Any]]], PluginContext],
        publish: Callable[[str, dict[str, Any]], None],
        scrub: Callable[[str], str] = lambda text: text,
    ) -> None:
        self.registry = dict(registry)
        self._db = db
        self._clock = clock
        self._context_factory = context_factory
        self._publish = publish
        self._scrub = scrub
        self._live: dict[str, _Live] = {plugin_id: _Live() for plugin_id in self.registry}
        self._lock = asyncio.Lock()

    # ---- queries -------------------------------------------------------------------------

    def is_enabled(self, plugin_id: str) -> bool:
        live = self._live.get(plugin_id)
        return live is not None and live.enabled

    def status(self, plugin_id: str) -> PluginStatus:
        return self._live[plugin_id].status

    def error(self, plugin_id: str) -> str | None:
        return self._live[plugin_id].error

    def settings(self, plugin_id: str) -> dict[str, Any]:
        return dict(self._live[plugin_id].settings)

    # ---- boot and shutdown ---------------------------------------------------------------

    async def boot(self) -> None:
        """A row per registered plugin (inserted with its default), then start the enabled ones."""
        now = self._clock.now()
        async with self._db.write() as tx:
            rows = {row.plugin_id: row for row in await tx.session.scalars(select(PluginState))}
            for plugin_id, plugin in self.registry.items():
                row = rows.get(plugin_id)
                if row is None:
                    row = PluginState(
                        plugin_id=plugin_id,
                        enabled=plugin.manifest.default_enabled,
                        settings_json=json.dumps(defaults(plugin.manifest.settings_spec)),
                        plugin_version=plugin.manifest.version,
                        enabled_at=now if plugin.manifest.default_enabled else None,
                        updated_at=now,
                    )
                    tx.session.add(row)
                elif row.plugin_version != plugin.manifest.version:
                    # A setting whose shape changed is carried over before the spec drops it.
                    row.settings_json = json.dumps(
                        plugin.upgrade_settings(self._stored(row.settings_json), row.plugin_version)
                    )
                    row.plugin_version = plugin.manifest.version
                live = self._live[plugin_id]
                live.enabled = row.enabled
                live.settings = self._coerce_stored(plugin, row.settings_json)
                live.settings_version = row.settings_version
        for plugin_id, live in self._live.items():
            if live.enabled:
                self._start(plugin_id)

    async def stop_all(self) -> None:
        await asyncio.gather(
            *(self._stop_runner(plugin_id) for plugin_id in self._live), return_exceptions=True
        )

    async def reset(self, erase: Callable[[], Awaitable[None]]) -> None:
        """Erase everything (meta/erase.py): stop every plugin, let ``erase`` empty the tables
        (``plugin_state`` with them), then start as a new install does: each plugin's default
        switch and settings. If ``erase`` fails, the plugins start again from the rows still
        there."""
        async with self._lock:
            await self.stop_all()
            for live in self._live.values():
                live.status, live.enabled, live.error = PluginStatus.DISABLED, False, None
            try:
                await erase()
            finally:
                await self.boot()

    # ---- changes (parent-only routes) ----------------------------------------------------

    async def enable(self, plugin_id: str) -> None:
        async with self._lock:
            self._known(plugin_id)
            live = self._live[plugin_id]
            if live.enabled and live.status is not PluginStatus.ERRORED:
                return
            await self._save(plugin_id, enabled=True)
            live.enabled = True
            await self._stop_runner(plugin_id)
            self._start(plugin_id)
        self._changed(plugin_id)

    async def disable(self, plugin_id: str) -> None:
        async with self._lock:
            self._known(plugin_id)
            live = self._live[plugin_id]
            if not live.enabled:
                return
            live.status = PluginStatus.STOPPING
            await self._stop_runner(plugin_id)
            await self._save(plugin_id, enabled=False)
            live.enabled = False
            live.status = PluginStatus.DISABLED
            live.error = None
        self._changed(plugin_id)

    async def restart(self, plugin_id: str) -> None:
        async with self._lock:
            self._known(plugin_id)
            if not self._live[plugin_id].enabled:
                raise PluginError("plugin_disabled", "api.plugins.turn_on_first")
            await self._stop_runner(plugin_id)
            self._start(plugin_id)
        self._changed(plugin_id)

    async def update_settings(self, plugin_id: str, raw: dict[str, Any]) -> dict[str, Any]:
        self._known(plugin_id)
        plugin = self.registry[plugin_id]
        live = self._live[plugin_id]
        values, problems = coerce_params(plugin.manifest.settings_spec, raw, previous=live.settings)
        if not problems:
            ctx = live.runner.ctx if live.runner else self._idle_context(plugin_id)
            problems = await plugin.validate_settings(ctx, values)
        if problems:
            raise PluginError("invalid_settings", "api.plugins.invalid_settings", problems)
        async with self._db.write() as tx:
            row = await tx.session.get(PluginState, plugin_id)
            assert row is not None  # boot() inserts every registered plugin
            row.settings_json = json.dumps(values)
            row.settings_version += 1
            row.updated_at = self._clock.now()
            live.settings_version = row.settings_version
            live.settings = values
            tx.publish("plugins.changed", {"id": plugin_id, "status": live.status.value})
        return dict(values)

    async def problems(self) -> list[tuple[str, Problem]]:
        """Each enabled plugin's problems (Needs Attention, ADR 0034), with its id, in registry
        order. A stopped plugin is core's to report (its hook may be what broke); one whose hook
        fails is logged and adds nothing."""
        found: list[tuple[str, Problem]] = []
        for plugin_id, plugin in self.registry.items():
            live = self._live[plugin_id]
            if not live.enabled or live.status is PluginStatus.ERRORED:
                continue
            ctx = live.runner.ctx if live.runner else self._idle_context(plugin_id)
            try:
                found.extend((plugin_id, problem) for problem in await plugin.problems(ctx))
            except Exception:  # a plugin's bug never breaks the list
                log.warning("plugin.problems_failed", plugin=plugin_id, exc_info=True)
        return found

    async def seed_sample(self, people: dict[str, str]) -> None:
        """Test mode's Sample Family: each enabled plugin adds its own synthetic data."""
        for plugin_id, plugin in self.registry.items():
            if not self.is_enabled(plugin_id):
                continue
            live = self._live[plugin_id]
            ctx = live.runner.ctx if live.runner else self._idle_context(plugin_id)
            await plugin.seed_sample(ctx, people)

    # ---- hub events ----------------------------------------------------------------------

    def deliver(self, event_type: str, payload: dict[str, Any]) -> None:
        """Called for every published event; queued to the plugins that subscribe to it."""
        for plugin_id, live in self._live.items():
            runner = live.runner
            if runner is None or live.status is not PluginStatus.RUNNING:
                continue
            prefixes = self.registry[plugin_id].manifest.subscribes
            if any(event_type.startswith(prefix) for prefix in prefixes):
                runner.deliver(HubEvent(event_type, dict(payload)))

    # ---- internals -----------------------------------------------------------------------

    def _known(self, plugin_id: str) -> None:
        if plugin_id not in self.registry:
            raise PluginError("not_found", "api.plugins.not_found")

    @staticmethod
    def _stored(settings_json: str) -> dict[str, Any]:
        """The settings as stored: whatever keys an older version wrote included."""
        try:
            loaded: object = json.loads(settings_json)
        except json.JSONDecodeError:
            loaded = {}
        return cast("dict[str, Any]", loaded) if isinstance(loaded, dict) else {}

    def _coerce_stored(self, plugin: Plugin, settings_json: str) -> dict[str, Any]:
        stored = self._stored(settings_json)
        spec = plugin.manifest.settings_spec
        known = {field.key for field in spec}
        raw = {key: value for key, value in stored.items() if key in known}
        values, problems = coerce_params(spec, raw, previous=raw)
        if problems:
            # A setting the current spec can't read (shape changed): fall back to its default.
            fallback = defaults(spec)
            log.warning("plugin.settings_reset", plugin=plugin.manifest.id, problems=len(problems))
            values = {key: values.get(key, fallback.get(key)) for key in known}
        return values

    def _start(self, plugin_id: str) -> None:
        live = self._live[plugin_id]
        live.status = PluginStatus.STARTING
        live.error = None
        runner = PluginRunner(
            self.registry[plugin_id],
            lambda pid, run: self._context_factory(pid, run, lambda: self._live[pid].settings),
            on_running=self._running,
            on_error=self._errored,
        )
        live.runner = runner
        runner.start()

    def _idle_context(self, plugin_id: str) -> PluginContext:
        """A context for validate_settings while the plugin isn't running."""
        runner = PluginRunner(
            self.registry[plugin_id],
            lambda pid, run: self._context_factory(pid, run, lambda: self._live[pid].settings),
            on_running=lambda _pid: None,
            on_error=lambda _pid, _exc: None,
        )
        return runner.ctx

    async def _stop_runner(self, plugin_id: str) -> None:
        live = self._live[plugin_id]
        runner, live.runner = live.runner, None
        if runner is not None:
            await runner.stop()

    def _running(self, plugin_id: str) -> None:
        live = self._live[plugin_id]
        if live.status is PluginStatus.STARTING:
            live.status = PluginStatus.RUNNING
            self._changed(plugin_id)
            log.info("plugin.running", plugin=plugin_id)

    def _errored(self, plugin_id: str, exc: BaseException) -> None:
        live = self._live[plugin_id]
        live.status = PluginStatus.ERRORED
        live.error = self._scrub(f"{type(exc).__name__}: {exc}")[:300]
        log.error("plugin.errored", plugin=plugin_id, error=live.error)
        runner = live.runner
        if runner is not None:
            # Its task stops itself after a callback fails; a spawned task's failure needs the
            # main task told too. Either way nothing of this plugin keeps running.
            asyncio.get_running_loop().create_task(runner.stop())
        self._changed(plugin_id)

    def _changed(self, plugin_id: str) -> None:
        self._publish("plugins.changed", {"id": plugin_id, "status": self.status(plugin_id).value})

    async def _save(self, plugin_id: str, *, enabled: bool) -> None:
        now = self._clock.now()
        async with self._db.write() as tx:
            row = await tx.session.get(PluginState, plugin_id)
            assert row is not None
            row.enabled = enabled
            if enabled:
                row.enabled_at = now
            else:
                row.disabled_at = now
            row.updated_at = now
