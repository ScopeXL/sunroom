"""Household settings, people, the display's panels and commands, and the network allowlist
(PLAN §11.1)."""

from __future__ import annotations

from fastapi import APIRouter, Request
from sqlalchemy import delete, select

from sunroom.auth.deps import ActorDep, ParentDep
from sunroom.calendar.service import rematch_people
from sunroom.core.errors import AppError
from sunroom.household import service
from sunroom.household.models import KioskPanel, Member, NetworkAllowEntry
from sunroom.household.schemas import (
    AllowEntryIn,
    AllowEntryOut,
    KioskCommandIn,
    KioskLayoutIn,
    KioskPanelOut,
    MemberCreate,
    MemberOut,
    MemberUpdate,
    SettingsOut,
    SettingsUpdate,
)
from sunroom.photos.models import PhotoKind
from sunroom.photos.router import read_upload
from sunroom.state import AppState, StateDep

router = APIRouter(prefix="/api", tags=["household"])


async def refresh_members(state: AppState) -> None:
    async with state.db.read() as db:
        state.household.members = {member.id for member in await service.active_members(db)}


@router.get("/settings")
async def get_settings(state: StateDep, actor: ActorDep) -> SettingsOut:
    async with state.db.read() as db:
        return service.settings_out(await service.household(db), state.settings)


@router.patch("/settings")
async def update_settings(body: SettingsUpdate, state: StateDep, actor: ParentDep) -> SettingsOut:
    changes = body.model_dump(exclude_unset=True)
    if "timezone" in changes and service.valid_zone(changes["timezone"]) is None:
        raise AppError(422, "invalid", "api.settings.unknown_zone", extra={"fields": ["timezone"]})
    if ("sleep_from" in changes) != ("sleep_to" in changes):
        raise AppError(
            422,
            "invalid",
            "api.settings.sleep_together",
            extra={"fields": ["sleep_from", "sleep_to"]},
        )
    async with state.db.write() as tx:
        home = await service.household(tx.session)
        for key, value in changes.items():
            if key == "household_name":
                home.name = value
            elif key in {
                "latitude",
                "longitude",
                "location_label",
                "sleep_from",
                "sleep_to",
                "dim_from",
                "default_reminder_minutes",
            }:
                setattr(home, key, value)
            elif value is not None:
                setattr(home, key, value)
        home.updated_at = state.clock.now()
        state.household.zone = service.effective_zone(home, state.settings)
        # Fewer copies to keep takes effect with the next backup, never at the tap (ADR 0034).
        state.household.backups = service.backup_policy(home)
        tx.publish("settings.changed")
        return service.settings_out(home, state.settings)


@router.get("/members")
async def list_members(state: StateDep, actor: ActorDep, archived: bool = False) -> list[MemberOut]:
    async with state.db.read() as db:
        if archived:
            rows = await db.scalars(select(Member).order_by(Member.sort, Member.created_at))
            return [service.member_out(m) for m in rows]
        return [service.member_out(m) for m in await service.active_members(db)]


@router.post("/members", status_code=201)
async def create_member(body: MemberCreate, state: StateDep, actor: ParentDep) -> MemberOut:
    async with state.db.write() as tx:
        member = await service.create_member(
            tx.session,
            name=body.name,
            role=body.role,
            color=body.color,
            birthday=body.birthday,
            now=state.clock.now(),
        )
        tx.publish("members.changed", {"id": member.id})
        # A new name may be in titles already (ADR 0034).
        await rematch_people(tx)
        out = service.member_out(member)
    await refresh_members(state)
    return out


@router.patch("/members/{member_id}")
async def update_member(
    member_id: str, body: MemberUpdate, state: StateDep, actor: ParentDep
) -> MemberOut:
    changes = body.model_dump(exclude_unset=True)
    async with state.db.write() as tx:
        member = await service.get_member(tx.session, member_id)
        if changes.get("name") and changes["name"].casefold() != member.name.casefold():
            others = await service.active_members(tx.session)
            if any(m.name.casefold() == changes["name"].casefold() for m in others):
                raise AppError(409, "name_taken", "api.members.name_taken")
        renamed = bool(changes.get("name")) and changes["name"] != member.name
        for key in ("name", "role", "color"):
            if changes.get(key) is not None:
                setattr(member, key, changes[key])
        if "birthday" in changes:
            member.birthday = changes["birthday"]
        tx.publish("members.changed", {"id": member.id})
        if renamed:
            await tx.session.flush()
            await rematch_people(tx)
        return service.member_out(member)


@router.post("/members/{member_id}/archive")
async def archive_member(member_id: str, state: StateDep, actor: ParentDep) -> MemberOut:
    async with state.db.write() as tx:
        member = await service.archive_member(tx.session, member_id, state.clock.now())
        tx.publish("members.changed", {"id": member.id})
        await tx.session.flush()
        await rematch_people(tx)
        out = service.member_out(member)
    await refresh_members(state)
    return out


@router.post("/members/{member_id}/restore")
async def restore_member(member_id: str, state: StateDep, actor: ParentDep) -> MemberOut:
    async with state.db.write() as tx:
        member = await service.restore_member(tx.session, member_id)
        tx.publish("members.changed", {"id": member.id})
        await tx.session.flush()
        await rematch_people(tx)
        out = service.member_out(member)
    await refresh_members(state)
    return out


@router.put("/members/{member_id}/avatar")
async def set_avatar(
    member_id: str, request: Request, state: StateDep, actor: ParentDep
) -> MemberOut:
    """The picture is the request body (JPEG, PNG, WebP, HEIC), up to 15 MB."""
    data = await read_upload(request)
    # Encoded before the write lock is taken: it's the slow part.
    encoded = await state.photos.encode(data, kind=PhotoKind.AVATAR, zone=state.zone())
    async with state.db.write() as tx:
        member = await service.get_member(tx.session, member_id)
        photo = await state.photos.ingest(
            tx.session,
            data,
            kind=PhotoKind.AVATAR,
            zone=state.zone(),
            now=state.clock.now(),
            encoded=encoded,
        )
        member.avatar_photo_id = photo.id
        tx.publish("members.changed", {"id": member.id})
        return service.member_out(member)


@router.delete("/members/{member_id}/avatar")
async def remove_avatar(member_id: str, state: StateDep, actor: ParentDep) -> MemberOut:
    async with state.db.write() as tx:
        member = await service.get_member(tx.session, member_id)
        member.avatar_photo_id = None
        tx.publish("members.changed", {"id": member.id})
        return service.member_out(member)


@router.get("/kiosk/layout")
async def get_layout(state: StateDep, actor: ActorDep) -> list[KioskPanelOut]:
    async with state.db.read() as db:
        return await service.kiosk_panels(db)


@router.put("/kiosk/layout")
async def set_layout(body: KioskLayoutIn, state: StateDep, actor: ParentDep) -> list[KioskPanelOut]:
    keys = [panel.key for panel in body.panels]
    if len(set(keys)) != len(keys):
        raise AppError(422, "invalid", "api.settings.panel_twice")
    async with state.db.write() as tx:
        # Panels left out keep their rows (a disabled plugin's panel comes back where it was),
        # after the ones listed.
        existing = {row.panel_key: row for row in await tx.session.scalars(select(KioskPanel))}
        for position, panel in enumerate(body.panels):
            row = existing.pop(panel.key, None) or KioskPanel(panel_key=panel.key)
            row.position, row.visible, row.size = position, panel.visible, panel.size
            tx.session.add(row)
        for offset, row in enumerate(sorted(existing.values(), key=lambda r: r.position)):
            row.position = len(body.panels) + offset
        await tx.session.flush()
        tx.publish("settings.changed", {"area": "kiosk_layout"})
        return await service.kiosk_panels(tx.session)


@router.post("/kiosk/command", status_code=204)
async def kiosk_command(body: KioskCommandIn, state: StateDep, actor: ParentDep) -> None:
    """Tell every wall screen to do something now (wall screens act; phones ignore it)."""
    state.hub.publish("kiosk.command", body.model_dump(exclude_none=True))


@router.get("/network-allowlist")
async def list_allowlist(state: StateDep, actor: ParentDep) -> list[AllowEntryOut]:
    async with state.db.read() as db:
        rows = await db.scalars(select(NetworkAllowEntry).order_by(NetworkAllowEntry.created_at))
        return [AllowEntryOut.model_validate(row, from_attributes=True) for row in rows]


@router.post("/network-allowlist", status_code=201)
async def add_allowlist(body: AllowEntryIn, state: StateDep, actor: ParentDep) -> AllowEntryOut:
    async with state.db.write() as tx:
        entry = NetworkAllowEntry(
            target=service.allow_target(body.target),
            label=body.label,
            created_by_member_id=actor.member_id,
            created_at=state.clock.now(),
        )
        tx.session.add(entry)
        await tx.session.flush()
        tx.publish("settings.changed", {"area": "network"})
        return AllowEntryOut.model_validate(entry, from_attributes=True)


@router.delete("/network-allowlist/{entry_id}", status_code=204)
async def remove_allowlist(entry_id: str, state: StateDep, actor: ParentDep) -> None:
    async with state.db.write() as tx:
        result = await tx.session.execute(
            delete(NetworkAllowEntry).where(NetworkAllowEntry.id == entry_id)
        )
        if not getattr(result, "rowcount", 0):
            raise AppError(404, "not_found", "api.network.allow_not_found")
        tx.publish("settings.changed", {"area": "network"})
