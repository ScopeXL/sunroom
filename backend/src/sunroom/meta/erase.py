"""Erase everything (ADR 0029): back to a server that has never been set up, on purpose.

Settings → Backup → Start Over, from a phone or computer, with the household password. First a
verified copy of the database goes to ``backups/pre-erase/``, a folder the nightly rotation never
looks in; if that copy can't be made, nothing is erased. Then every table is emptied and the rows
a new install starts with are put back, every plugin returns to its default switch and settings,
the photo files are deleted (not ``photos/inbox``, which the family fills by hand), and every
device and screen is signed out.

The test server's reset uses the two halves that must not drift apart: which tables go
(``empty_tables``), and what the process forgets (``forget``).
"""

from __future__ import annotations

import asyncio
import shutil
from collections.abc import Collection
from pathlib import Path

from sqlalchemy import select, update

from sunroom.auth.models import Device
from sunroom.calendar.models import Calendar, Event
from sunroom.core.logging import get_logger
from sunroom.db import backup
from sunroom.db.models import Base
from sunroom.household import service as household_service
from sunroom.household.models import AppMeta, Household, KioskPanel, Member
from sunroom.photos.store import PhotoStore
from sunroom.state import AppState

log = get_logger(__name__)

# The one table that stays: the auth epoch, and what the secret key is checked against at boot.
KEPT = frozenset({"app_meta"})
PLUGIN_STATE = "plugin_state"


async def empty_tables(state: AppState, *, plugin_state: bool) -> int:
    """In one transaction: every table emptied, children before parents, then a new install's
    rows put back (the Home calendar, the household, the wall's Today panel), the household
    password forgotten and the auth epoch moved on, so every session made before is refused.
    ``plugin_state=False`` leaves the plugins' switches and settings (the test server's reset).
    Returns the new epoch."""
    now = state.clock.now()
    async with state.db.write() as tx:
        # The two columns that point back up the order.
        await tx.session.execute(update(Event).values(parent_event_id=None))
        await tx.session.execute(update(Member).values(avatar_photo_id=None))
        for table in reversed(Base.metadata.sorted_tables):
            if table.name in KEPT or (table.name == PLUGIN_STATE and not plugin_state):
                continue
            await tx.session.execute(table.delete())
        home = Calendar(name="Home", color="sky", created_at=now)
        tx.session.add(home)
        await tx.session.flush()
        tx.session.add(
            Household(id=1, name="Our home", default_calendar_id=home.id, updated_at=now)
        )
        tx.session.add(KioskPanel(panel_key="calendar.today", position=0, visible=True, size="m"))
        await tx.session.execute(
            update(AppMeta).values(password_hash=None, auth_epoch=AppMeta.auth_epoch + 1)
        )
        meta = await tx.session.get(AppMeta, 1)
        return meta.auth_epoch if meta else state.auth.epoch + 1


def forget(state: AppState, epoch: int, signed_out: Collection[str] = ()) -> None:
    """What the process knew about the household that's gone: sessions, the PIN, the limiters,
    caches, who lives here. Every open stream is dropped; the ones of ``signed_out`` devices are
    told their session ended first, so their screens go to sign-in or the welcome screen at
    once rather than at their next request."""
    state.auth.epoch = epoch
    state.auth.devices.clear()
    state.auth.revoked_devices.clear()
    state.auth.revoked_devices.update(signed_out)
    state.auth.last_seen_written.clear()
    state.auth.has_pin = False
    state.auth.pin_epoch = 0
    state.login_limiter.reset()
    state.pin_limiter.reset()
    state.uploads.clear()
    state.calendar.cache.clear()
    # What lives only in memory: the update check's last answer, and a wall screen's wake.
    state.updates.latest = state.updates.checked_at = state.updates.problem = None
    state.screen.awake_until = None
    state.screen.notify()
    state.household.setup_complete = False
    state.household.password_set = state.settings.app_password is not None
    state.household.members.clear()
    state.household.backups = backup.BackupPolicy()
    state.household.zone = household_service.effective_zone(
        Household(timezone=None), state.settings
    )
    state.hub.drop_all()


def _delete_photo_files(store: PhotoStore) -> None:
    """Every stored picture, thumbnail and avatar, and what was set aside. Not the inbox: those
    are the family's own files, dropped in by hand."""
    for folder in ("library", "thumbs", "avatars", ".orphans"):
        shutil.rmtree(store.root / folder, ignore_errors=True)
    store.ensure_folders()


async def erase_everything(state: AppState) -> Path:
    """Erase the household and start over. Returns the copy made first. Raises
    ``backup.BackupError`` with nothing erased when that copy can't be made."""
    copy = (
        state.backups.backup_dir / backup.PRE_ERASE_DIR / backup.pre_erase_name(state.clock.now())
    )
    await asyncio.to_thread(backup.take_backup, state.backups.db_path, copy)
    async with state.db.read() as db:
        devices = set(await db.scalars(select(Device.id)))
    epoch = state.auth.epoch

    async def empty() -> None:
        nonlocal epoch
        epoch = await empty_tables(state, plugin_state=True)

    # The plugins stop first (a job must not write into a table being emptied), and start again
    # as on a new install.
    await state.plugins.reset(empty)
    await asyncio.to_thread(_delete_photo_files, state.photos)
    forget(state, epoch, signed_out=devices)
    log.warning("erase.completed", copy=copy.name, devices=len(devices))
    return copy
