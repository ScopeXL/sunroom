"""Rewards (UX §4 "Stars & rewards", §6 "Redeem a reward"): a kid asks for one with their stars
and a parent says yes or "Not now". An ask nobody has answered holds its stars, so they can't be
asked with twice; a yes spends them. Turned off in Settings, every change here is refused.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sunroom.auth.deps import Actor, parent_refusal
from sunroom.core.errors import AppError
from sunroom.plugins.chores.common import (
    KID,
    Now,
    credited,
    gone,
    ledger,
    names,
    now_of,
    stars_of,
    streak_book,
    switches,
)
from sunroom.plugins.chores.models import Redemption, RedemptionStatus, Reward
from sunroom.plugins.chores.schemas import (
    RedeemIn,
    RedemptionOut,
    RewardIn,
    RewardOut,
    RewardPatch,
    RewardsOut,
)
from sunroom.plugins.context import PluginContext

RECENT = timedelta(days=14)


def rewards_off() -> AppError:
    return AppError(409, "rewards_off", "api.tasks.rewards_off")


def _rewards_on(ctx: PluginContext) -> None:
    if not switches(ctx).rewards:
        raise rewards_off()


def not_enough(name: str | None, have: int, cost: int) -> AppError:
    """Not enough stars; ``name`` None for someone no longer in the family."""
    if name is None:
        return AppError(
            409, "not_enough", "api.tasks.not_enough_them", params={"have": have, "cost": cost}
        )
    return AppError(
        409, "not_enough", "api.tasks.not_enough", params={"name": name, "have": have, "cost": cost}
    )


def reward_out(reward: Reward) -> RewardOut:
    return RewardOut(
        id=reward.id,
        title=reward.title,
        cost_points=reward.cost_points,
        icon=reward.icon,
        active=reward.active,
    )


def redemption_out(redemption: Redemption, title: str) -> RedemptionOut:
    return RedemptionOut.model_validate(
        {
            "id": redemption.id,
            "reward_id": redemption.reward_id,
            "reward_title": title,
            "member_id": redemption.member_id,
            "cost_points": redemption.cost_points,
            "status": redemption.status,
            "requested_at": redemption.requested_at,
            "decided_at": redemption.decided_at,
            "decided_by_member_id": redemption.decided_by_member_id,
        }
    )


async def asked(session: AsyncSession) -> list[RedemptionOut]:
    """Rewards asked for and waiting for a parent, oldest first."""
    rows = await session.execute(
        select(Redemption, Reward.title)
        .join(Reward, Reward.id == Redemption.reward_id)
        .where(Redemption.status == RedemptionStatus.REQUESTED)
        .order_by(Redemption.requested_at, Redemption.id)
    )
    return [redemption_out(redemption, title) for redemption, title in rows]


async def _recent(session: AsyncSession, now: Now) -> list[RedemptionOut]:
    """Answered (yes or not now) in the last two weeks, newest first."""
    rows = await session.execute(
        select(Redemption, Reward.title)
        .join(Reward, Reward.id == Redemption.reward_id)
        .where(
            Redemption.status.in_([RedemptionStatus.APPROVED, RedemptionStatus.DENIED]),
            Redemption.decided_at >= now.utc - RECENT,
        )
        .order_by(Redemption.decided_at.desc(), Redemption.id.desc())
    )
    return [redemption_out(redemption, title) for redemption, title in rows]


async def rewards_view(ctx: PluginContext, *, include_inactive: bool) -> RewardsOut:
    now = await now_of(ctx)
    members = await ctx.members.active()
    kids = [member.id for member in members if member.role == KID]
    query = select(Reward).where(Reward.deleted_at.is_(None))
    if not include_inactive:
        query = query.where(Reward.active.is_(True))
    async with ctx.read() as session:
        rewards = await session.scalars(query.order_by(Reward.cost_points, Reward.title, Reward.id))
        listed = [reward_out(reward) for reward in rewards]
        book = await streak_book(session, now, {member.id for member in members})
        stars = await stars_of(session, now, kids, book)
        return RewardsOut(
            rewards=listed,
            stars=stars,
            asked=await asked(session),
            recent=await _recent(session, now),
        )


# ---- making and changing (parents) -------------------------------------------------------------


async def _reward(session: AsyncSession, reward_id: str) -> Reward:
    reward = await session.get(Reward, reward_id)
    if reward is None or reward.deleted_at is not None:
        raise gone("api.tasks.reward_gone")
    return reward


async def add_reward(ctx: PluginContext, body: RewardIn) -> RewardOut:
    _rewards_on(ctx)
    async with ctx.write() as tx:
        reward = Reward(
            title=body.title, cost_points=body.cost_points, icon=body.icon, created_at=ctx.now()
        )
        tx.session.add(reward)
        await tx.session.flush()
        tx.publish("chores.changed", {"reward_id": reward.id})
        return reward_out(reward)


async def change_reward(ctx: PluginContext, reward_id: str, body: RewardPatch) -> RewardOut:
    """Only what's sent changes; an icon sent empty (null) is taken off."""
    _rewards_on(ctx)
    async with ctx.write() as tx:
        reward = await _reward(tx.session, reward_id)
        if body.title is not None:
            reward.title = body.title
        if body.cost_points is not None:
            reward.cost_points = body.cost_points
        if "icon" in body.model_fields_set:
            reward.icon = body.icon
        if body.active is not None:
            reward.active = body.active
        tx.publish("chores.changed", {"reward_id": reward.id})
        return reward_out(reward)


async def remove_reward(ctx: PluginContext, reward_id: str) -> None:
    """Off the list; asks already made for it stay for a parent to answer."""
    _rewards_on(ctx)
    async with ctx.write() as tx:
        reward = await _reward(tx.session, reward_id)
        reward.deleted_at = ctx.now()
        tx.publish("chores.changed", {"reward_id": reward.id})


# ---- asking, taking back, answering ------------------------------------------------------------


async def redeem(ctx: PluginContext, actor: Actor, reward_id: str, body: RedeemIn) -> RedemptionOut:
    """Ask for a reward: the stars not already held must cover it."""
    _rewards_on(ctx)
    now = await now_of(ctx)
    member = credited(actor, body.member_id, await ctx.members.active())
    async with ctx.write() as tx:
        reward = await _reward(tx.session, reward_id)
        if not reward.active:
            raise gone("api.tasks.reward_gone")
        stars = await ledger(tx.session, now, [member.id])
        free = stars.balance(member.id) - stars.held(member.id)
        if free < reward.cost_points:
            raise not_enough(member.name, max(free, 0), reward.cost_points)
        redemption = Redemption(
            reward_id=reward.id,
            member_id=member.id,
            cost_points=reward.cost_points,
            status=RedemptionStatus.REQUESTED,
            requested_at=now.utc,
        )
        tx.session.add(redemption)
        await tx.session.flush()
        tx.publish("chores.changed", {"redemption_id": redemption.id})
        tx.publish("points.changed", {"member_id": member.id})
        return redemption_out(redemption, reward.title)


async def _redemption(session: AsyncSession, redemption_id: str) -> tuple[Redemption, str]:
    found = (
        await session.execute(
            select(Redemption, Reward.title)
            .join(Reward, Reward.id == Redemption.reward_id)
            .where(Redemption.id == redemption_id)
        )
    ).first()
    if found is None:
        raise AppError(404, "not_found", "api.tasks.ask_gone")
    redemption, title = found
    return redemption, title


def _answered(redemption: Redemption, who: str | None) -> AppError:
    if redemption.status == RedemptionStatus.CANCELLED:
        if who is None:
            return AppError(409, "already_answered", "api.tasks.taken_back_them")
        return AppError(409, "already_answered", "api.tasks.taken_back", params={"name": who})
    return AppError(409, "already_answered", "api.tasks.already_answered")


async def cancel(ctx: PluginContext, actor: Actor, redemption_id: str) -> RedemptionOut:
    """Take it back: the one who asked, or a parent."""
    _rewards_on(ctx)
    members = await ctx.members.active()
    async with ctx.write() as tx:
        redemption, title = await _redemption(tx.session, redemption_id)
        if not actor.is_parent and credited(actor, None, members).id != redemption.member_id:
            raise parent_refusal(actor)
        if redemption.status == RedemptionStatus.CANCELLED:
            return redemption_out(redemption, title)
        if redemption.status != RedemptionStatus.REQUESTED:
            raise AppError(409, "already_answered", "api.tasks.already_answered")
        redemption.status = RedemptionStatus.CANCELLED
        redemption.decided_by_member_id = actor.member_id
        redemption.decided_at = ctx.now()
        tx.publish("chores.changed", {"redemption_id": redemption.id})
        tx.publish("points.changed", {"member_id": redemption.member_id})
        return redemption_out(redemption, title)


async def decide(
    ctx: PluginContext, actor: Actor, redemption_id: str, *, approve: bool
) -> RedemptionOut:
    """A parent's yes (the stars are spent) or "Not now"."""
    _rewards_on(ctx)
    now = await now_of(ctx)
    who = names(await ctx.members.active())
    target = RedemptionStatus.APPROVED if approve else RedemptionStatus.DENIED
    async with ctx.write() as tx:
        redemption, title = await _redemption(tx.session, redemption_id)
        name = who.get(redemption.member_id)
        if redemption.status == target:
            return redemption_out(redemption, title)
        if redemption.status != RedemptionStatus.REQUESTED:
            raise _answered(redemption, name)
        if approve:
            have = (await ledger(tx.session, now, [redemption.member_id])).balance(
                redemption.member_id
            )
            if have < redemption.cost_points:
                raise not_enough(name, max(have, 0), redemption.cost_points)
        redemption.status = target
        redemption.decided_by_member_id = actor.member_id
        redemption.decided_at = now.utc
        tx.publish("chores.changed", {"redemption_id": redemption.id})
        tx.publish("points.changed", {"member_id": redemption.member_id})
        return redemption_out(redemption, title)
