"""Test-only endpoints (PLAN §11.1): mounted only with SUNROOM_TEST_MODE=1, which is refused
inside the container, and answering only requests from this machine (end-to-end runs and
``just seed``). Synthetic data only.
"""

from __future__ import annotations

import asyncio
import ipaddress
import shutil
from datetime import date, datetime, time, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import delete, select, update

from sunroom.auth.deps import Actor
from sunroom.auth.password import hash_password, hash_pin
from sunroom.auth.sessions import pin_epoch_of
from sunroom.calendar import service as calendar_service
from sunroom.calendar.models import Event, EventRevision
from sunroom.calendar.schemas import CalendarCreate, EventCreate
from sunroom.core.clock import ShiftableClock
from sunroom.core.errors import AppError
from sunroom.domain.timeparts import to_local
from sunroom.household import service as household_service
from sunroom.household.models import AppMeta, Member
from sunroom.meta import erase
from sunroom.state import AppState, StateDep

E2E_PASSWORD = "e2e-household-passphrase"  # noqa: S105 - synthetic, also in .gitleaks.toml


def _local_only(request: Request) -> None:
    host = request.client.host if request.client else ""
    try:
        loopback = ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = host in {"testclient", "localhost"}
    if not loopback:
        raise AppError(404, "not_found", "That couldn't be found.")


router = APIRouter(
    prefix="/api/_test", include_in_schema=False, dependencies=[Depends(_local_only)]
)


@router.post("/reset", status_code=204)
async def reset(state: StateDep) -> None:
    """Back to a server that has never been set up."""
    # The plugins keep their switches and settings: end-to-end tests set them once.
    epoch = await erase.empty_tables(state, plugin_state=False)
    if isinstance(state.clock, ShiftableClock):
        state.clock.reset()
    await asyncio.to_thread(shutil.rmtree, state.photos.root, True)
    state.photos.ensure_folders()
    # Nor any copies on the server, which Settings → Backup lists (ADR 0034).
    await asyncio.to_thread(_remove_copies, state)
    state.backups.last_success_at = state.backups.last_error = None
    state.hello_version.stand_in = None
    state.feedback.clear()
    erase.forget(state, epoch)


def _remove_copies(state: AppState) -> None:
    shutil.rmtree(state.backups.backup_dir, ignore_errors=True)
    for aside in state.settings.data_dir.glob("sunroom.pre-restore.*"):
        aside.unlink(missing_ok=True)


@router.get("/feedback")
async def kept_feedback(state: StateDep) -> list[dict[str, object]]:
    """What Send Feedback would have posted, oldest first (meta/feedback.py keeps it here)."""
    return list(state.feedback.kept)


@router.post("/drop-streams", status_code=204)
async def drop_streams(state: StateDep) -> None:
    state.hub.drop_all()


class VersionIn(BaseModel):
    version: Annotated[str, Field(min_length=1, max_length=40)]
    once: bool = False


@router.post("/version", status_code=204)
async def stand_in_version(body: VersionIn, state: StateDep) -> None:
    """The stream's next hello (or, without ``once``, every hello until a reset) names this
    version, as if the container had been updated: every screen then says so and reloads."""
    state.hello_version.stand_in = body.version
    state.hello_version.once = body.once


@router.post("/revoke-sessions", status_code=204)
async def revoke_sessions(state: StateDep) -> None:
    async with state.db.write() as tx:
        await tx.session.execute(update(AppMeta).values(auth_epoch=AppMeta.auth_epoch + 1))
        meta = await tx.session.get(AppMeta, 1)
        epoch = meta.auth_epoch if meta else state.auth.epoch + 1
    state.auth.epoch = epoch


class ClockIn(BaseModel):
    set: datetime | None = None  # timezone-aware
    advance_minutes: float | None = None
    reset: bool = False


@router.post("/clock", status_code=204)
async def move_clock(body: ClockIn, state: StateDep) -> None:
    clock = state.clock
    if not isinstance(clock, ShiftableClock):
        raise AppError(409, "clock_fixed", "This server's clock can't be moved.")
    if body.reset:
        clock.reset()
    if body.set is not None:
        clock.set(body.set)
    if body.advance_minutes is not None:
        clock.advance(minutes=body.advance_minutes)


class SeedIn(BaseModel):
    profile: Literal["sample-family"] = "sample-family"
    password: Annotated[str, Field(min_length=8, max_length=256)] = E2E_PASSWORD
    pin: Annotated[str, Field(pattern=r"^\d{4,6}$")] | None = None
    timezone: str = "America/New_York"
    events: bool = True  # a week of sample events around today; False for an empty board
    plugins: bool = True  # each enabled plugin's sample data (lists, chores…); False for none


SAMPLE_FAMILY: tuple[tuple[str, str, str, date | None], ...] = (
    ("Ana", "parent", "sea", date(1988, 4, 12)),
    ("Sam", "parent", "sky", None),
    ("Mia", "kid", "rose", date(2017, 10, 9)),  # in the seeded week, so the board shows it
    ("Leo", "kid", "moss", date(2020, 2, 3)),
)


@router.post("/seed", status_code=204)
async def seed(body: SeedIn, state: StateDep) -> None:
    """The synthetic "Sample Family" (`just seed`, screenshots, end-to-end runs): set up, four
    people, an optional PIN, a place (Sample Town), a second calendar and a week of events
    around today, and each enabled plugin's own (lists and chores since M3; meals, countdowns,
    photos and the weather since M4)."""
    await _seed(state, body)


async def _seed(state: AppState, body: SeedIn) -> None:
    zone = household_service.valid_zone(body.timezone)
    if zone is None:
        raise AppError(422, "invalid", "Unknown time zone.")
    now = state.clock.now()
    password_hash = await asyncio.to_thread(hash_password, body.password)
    pin_hash = await asyncio.to_thread(hash_pin, body.pin) if body.pin else None
    async with state.db.write() as tx:
        home = await household_service.household(tx.session)
        home.name = "Sample Family"
        home.timezone = zone.key
        # Sample Town: a made-up name on a famous public spot, for the weather and sunset.
        home.location_label = "Sample Town"
        home.latitude, home.longitude = 40.71, -74.01
        home.onboarded_at = home.onboarded_at or now
        home.parent_pin_hash = pin_hash
        home.pin_length = len(body.pin) if body.pin else None
        home.pin_updated_at = now if pin_hash else None
        meta = await tx.session.get(AppMeta, 1)
        assert meta is not None
        meta.password_hash = password_hash
        existing = {member.name for member in await household_service.active_members(tx.session)}
        for sort, (name, role, color, birthday) in enumerate(SAMPLE_FAMILY):
            if name not in existing:
                tx.session.add(
                    Member(
                        name=name,
                        role=role,
                        color=color,
                        birthday=birthday,
                        sort=sort,
                        created_at=now,
                    )
                )
        tx.publish("settings.changed", {"area": "seed"})
        tx.publish("members.changed")
    state.household.setup_complete = True
    state.household.password_set = True
    state.household.zone = zone
    state.auth.has_pin = pin_hash is not None
    state.auth.pin_epoch = pin_epoch_of(pin_hash)
    async with state.db.read() as db:
        state.household.members = {m.id for m in await household_service.active_members(db)}
        people = {m.name: m.id for m in await household_service.active_members(db)}
        has_events = await db.scalar(select(Event.id).limit(1)) is not None
    if body.events and not has_events:
        await _seed_events(state, people)
    if body.plugins:
        await state.plugins.seed_sample(people)


async def _seed_events(state: AppState, people: dict[str, str]) -> None:
    """Synthetic events from last week to next, placed relative to today."""
    now = state.clock.now()
    zone = state.zone()
    today = to_local(now, zone).date()
    monday = today - timedelta(days=today.weekday())
    actor = Actor(
        device_id="seed",
        epoch=0,
        kind="phone",
        member_id=people.get("Ana"),
        is_kid_device=False,
        is_parent=True,
        has_grant=False,
    )
    ctx = calendar_service.Context(
        actor=actor, now=now, zone_key=zone.key, members=frozenset(people.values())
    )

    def at(day: date, hour: int, minute: int = 0) -> datetime:
        return datetime.combine(day, time(hour, minute))

    async with state.db.write() as tx:
        kids = await calendar_service.create_calendar(
            tx, CalendarCreate(name="Kids' activities", color="iris"), ctx
        )
        await tx.session.flush()
        events = [
            EventCreate(
                title="School drop-off",
                start=at(monday - timedelta(days=7), 8),
                end=at(monday - timedelta(days=7), 8, 30),
                rrule="FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR",
                member_ids=[people["Ana"]],
            ),
            EventCreate(
                calendar_id=kids.id,
                title="Soccer practice",
                location="Field 3",
                start=at(monday - timedelta(days=6), 16),
                end=at(monday - timedelta(days=6), 17),
                rrule="FREQ=WEEKLY;BYDAY=TU,TH",
                member_ids=[people["Mia"]],
                reminders=[30],
            ),
            EventCreate(
                calendar_id=kids.id,
                title="Piano lesson",
                start=at(monday - timedelta(days=5), 15, 30),
                end=at(monday - timedelta(days=5), 16, 15),
                rrule="FREQ=WEEKLY;BYDAY=WE",
                member_ids=[people["Leo"]],
            ),
            EventCreate(
                title="Book club",
                start=at(monday + timedelta(days=3), 19),
                end=at(monday + timedelta(days=3), 21),
                rrule="FREQ=WEEKLY;INTERVAL=2;BYDAY=TH",
                member_ids=[people["Sam"]],
            ),
            EventCreate(
                title="Garbage night",
                start_date=monday - timedelta(days=7),
                rrule="FREQ=WEEKLY;BYDAY=MO",
            ),
            EventCreate(
                title="Pajama day",
                start_date=monday + timedelta(days=4),
                member_ids=[people["Leo"]],
            ),
            EventCreate(
                title="Vet",
                start=at(monday + timedelta(days=2), 9),
                end=at(monday + timedelta(days=2), 9, 30),
                member_ids=[people["Ana"]],
            ),
            EventCreate(
                title="Dinner at Grandma's",
                start=at(monday + timedelta(days=6), 18, 30),
                end=at(monday + timedelta(days=6), 20),
            ),
            EventCreate(
                title="Movie night",
                start=at(monday + timedelta(days=5), 19),
                end=at(monday + timedelta(days=5), 21),
                member_ids=[people["Mia"], people["Leo"]],
            ),
            EventCreate(
                title="Grandparents visiting",
                start_date=monday + timedelta(days=10),
                end_date=monday + timedelta(days=13),
            ),
        ]
        for body in events:
            await calendar_service.create_event(tx, body, ctx)
        # Seeding isn't something to undo.
        await tx.session.execute(delete(EventRevision))
