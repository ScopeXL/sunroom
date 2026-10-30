"""The chores plugin's routes, under /api/chores (PLAN §11.3). Every route answers 404
plugin_disabled while the plugin is off (the framework gates them).

Static addresses come before the ``/{chore_id}`` ones. A is any signed-in device (``ActorDep``),
P a parent (``ParentDep``); who gets the credit for a tap is ``common.credited`` (ADR 0025).
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Query

from sunroom.auth.deps import ActorDep, ParentDep
from sunroom.core.errors import AppError
from sunroom.plugins.chores import rewards, routines, service
from sunroom.plugins.chores.schemas import (
    AdjustIn,
    CheckIn,
    ChoreIn,
    ChoreOut,
    ChorePatch,
    CompleteIn,
    CompleteOut,
    CompletionOut,
    DayIn,
    DayOut,
    FinishIn,
    FinishOut,
    PointsOut,
    RedeemIn,
    RedemptionOut,
    RemovedChoreOut,
    RewardIn,
    RewardOut,
    RewardPatch,
    RewardsOut,
    RoutineIn,
    RoutineOut,
    RoutinePatch,
    RoutineRunOut,
    RoutinesOut,
    StepsIn,
    WeekOut,
)
from sunroom.plugins.context import PluginContext

if TYPE_CHECKING:
    from sunroom.plugins.chores.plugin import Chores

# Settings lists switched-off chores, rewards and routines too, so they can be switched back on.
IncludeInactive = Annotated[bool, Query()]


def build(router: APIRouter, plugin: Chores) -> None:
    def ctx() -> PluginContext:
        if plugin.ctx is None:
            raise AppError(503, "starting", "api.tasks.starting")
        return plugin.ctx

    # ---- chores ------------------------------------------------------------------------------

    @router.get("")
    async def list_chores(  # pyright: ignore[reportUnusedFunction]
        actor: ActorDep, include_inactive: IncludeInactive = False
    ) -> list[ChoreOut]:
        return await service.list_chores(ctx(), include_inactive=include_inactive)

    @router.post("", status_code=201)
    async def add_chore(body: ChoreIn, actor: ActorDep) -> ChoreOut:  # pyright: ignore[reportUnusedFunction]
        return await service.add_chore(ctx(), actor, body)

    @router.get("/today")
    async def today(  # pyright: ignore[reportUnusedFunction]
        actor: ActorDep, day: Annotated[date | None, Query(alias="date")] = None
    ) -> DayOut:
        return await service.day_view(ctx(), day)

    @router.get("/week")
    async def week(actor: ActorDep, start: date | None = None) -> WeekOut:  # pyright: ignore[reportUnusedFunction]
        return await service.week_view(ctx(), start)

    @router.get("/removed")
    async def removed(actor: ActorDep) -> list[RemovedChoreOut]:  # pyright: ignore[reportUnusedFunction]
        return await service.removed(ctx())

    @router.post("/completions/{completion_id}/approve")
    async def approve_completion(completion_id: str, actor: ParentDep) -> CompletionOut:  # pyright: ignore[reportUnusedFunction]
        return await service.decide(ctx(), actor, completion_id, approve=True)

    @router.post("/completions/{completion_id}/reject")
    async def reject_completion(completion_id: str, actor: ParentDep) -> CompletionOut:  # pyright: ignore[reportUnusedFunction]
        return await service.decide(ctx(), actor, completion_id, approve=False)

    # ---- stars -------------------------------------------------------------------------------

    @router.get("/points")
    async def stars(actor: ActorDep) -> PointsOut:  # pyright: ignore[reportUnusedFunction]
        return await service.stars_view(ctx())

    @router.post("/points/adjust")
    async def adjust(body: AdjustIn, actor: ParentDep) -> PointsOut:  # pyright: ignore[reportUnusedFunction]
        return await service.adjust(ctx(), actor, body)

    # ---- rewards -----------------------------------------------------------------------------

    @router.get("/rewards")
    async def list_rewards(  # pyright: ignore[reportUnusedFunction]
        actor: ActorDep, include_inactive: IncludeInactive = False
    ) -> RewardsOut:
        return await rewards.rewards_view(ctx(), include_inactive=include_inactive)

    @router.post("/rewards", status_code=201)
    async def add_reward(body: RewardIn, actor: ParentDep) -> RewardOut:  # pyright: ignore[reportUnusedFunction]
        return await rewards.add_reward(ctx(), body)

    @router.patch("/rewards/{reward_id}")
    async def change_reward(  # pyright: ignore[reportUnusedFunction]
        reward_id: str, body: RewardPatch, actor: ParentDep
    ) -> RewardOut:
        return await rewards.change_reward(ctx(), reward_id, body)

    @router.delete("/rewards/{reward_id}", status_code=204)
    async def remove_reward(reward_id: str, actor: ParentDep) -> None:  # pyright: ignore[reportUnusedFunction]
        await rewards.remove_reward(ctx(), reward_id)

    @router.post("/rewards/{reward_id}/redeem", status_code=201)
    async def redeem(  # pyright: ignore[reportUnusedFunction]
        reward_id: str, body: RedeemIn, actor: ActorDep
    ) -> RedemptionOut:
        return await rewards.redeem(ctx(), actor, reward_id, body)

    @router.post("/redemptions/{redemption_id}/cancel")
    async def cancel_redemption(redemption_id: str, actor: ActorDep) -> RedemptionOut:  # pyright: ignore[reportUnusedFunction]
        return await rewards.cancel(ctx(), actor, redemption_id)

    @router.post("/redemptions/{redemption_id}/approve")
    async def approve_redemption(redemption_id: str, actor: ParentDep) -> RedemptionOut:  # pyright: ignore[reportUnusedFunction]
        return await rewards.decide(ctx(), actor, redemption_id, approve=True)

    @router.post("/redemptions/{redemption_id}/deny")
    async def deny_redemption(redemption_id: str, actor: ParentDep) -> RedemptionOut:  # pyright: ignore[reportUnusedFunction]
        return await rewards.decide(ctx(), actor, redemption_id, approve=False)

    # ---- routines ----------------------------------------------------------------------------

    @router.get("/routines")
    async def list_routines(  # pyright: ignore[reportUnusedFunction]
        actor: ActorDep,
        member_id: str | None = None,
        day: Annotated[date | None, Query(alias="date")] = None,
        include_inactive: IncludeInactive = False,
    ) -> RoutinesOut:
        return await routines.routines_view(
            ctx(), member_id, day, include_inactive=include_inactive
        )

    @router.post("/routines", status_code=201)
    async def add_routine(body: RoutineIn, actor: ParentDep) -> RoutineOut:  # pyright: ignore[reportUnusedFunction]
        return await routines.add_routine(ctx(), body)

    @router.patch("/routines/{routine_id}")
    async def change_routine(  # pyright: ignore[reportUnusedFunction]
        routine_id: str, body: RoutinePatch, actor: ParentDep
    ) -> RoutineOut:
        return await routines.change_routine(ctx(), routine_id, body)

    @router.delete("/routines/{routine_id}", status_code=204)
    async def remove_routine(routine_id: str, actor: ParentDep) -> None:  # pyright: ignore[reportUnusedFunction]
        await routines.remove_routine(ctx(), routine_id)

    @router.put("/routines/{routine_id}/steps")
    async def replace_steps(  # pyright: ignore[reportUnusedFunction]
        routine_id: str, body: StepsIn, actor: ParentDep
    ) -> RoutineOut:
        return await routines.replace_steps(ctx(), routine_id, body)

    @router.post("/routines/{routine_id}/steps/{step_id}/check")
    async def check_step(  # pyright: ignore[reportUnusedFunction]
        routine_id: str, step_id: str, body: CheckIn, actor: ActorDep
    ) -> RoutineRunOut:
        return await routines.check(ctx(), actor, routine_id, step_id, body)

    @router.post("/routines/{routine_id}/finish")
    async def finish_routine(  # pyright: ignore[reportUnusedFunction]
        routine_id: str, body: FinishIn, actor: ActorDep
    ) -> FinishOut:
        return await routines.finish(ctx(), actor, routine_id, body)

    # ---- one chore ---------------------------------------------------------------------------

    @router.patch("/{chore_id}")
    async def change_chore(chore_id: str, body: ChorePatch, actor: ParentDep) -> ChoreOut:  # pyright: ignore[reportUnusedFunction]
        return await service.change_chore(ctx(), chore_id, body)

    @router.delete("/{chore_id}", status_code=204)
    async def remove_chore(chore_id: str, actor: ParentDep) -> None:  # pyright: ignore[reportUnusedFunction]
        await service.remove_chore(ctx(), chore_id)

    @router.post("/{chore_id}/restore")
    async def restore_chore(chore_id: str, actor: ParentDep) -> ChoreOut:  # pyright: ignore[reportUnusedFunction]
        return await service.restore_chore(ctx(), chore_id)

    @router.post("/{chore_id}/skip")
    async def skip_day(chore_id: str, body: DayIn, actor: ParentDep) -> ChoreOut:  # pyright: ignore[reportUnusedFunction]
        return await service.skip(ctx(), chore_id, body.date, skipped=True)

    @router.post("/{chore_id}/unskip")
    async def unskip_day(chore_id: str, body: DayIn, actor: ParentDep) -> ChoreOut:  # pyright: ignore[reportUnusedFunction]
        return await service.skip(ctx(), chore_id, body.date, skipped=False)

    @router.post("/{chore_id}/complete")
    async def complete(  # pyright: ignore[reportUnusedFunction]
        chore_id: str, body: CompleteIn, actor: ActorDep
    ) -> CompleteOut:
        return await service.complete(ctx(), actor, chore_id, body)

    @router.post("/{chore_id}/undo", status_code=204)
    async def undo(chore_id: str, body: CompleteIn, actor: ActorDep) -> None:  # pyright: ignore[reportUnusedFunction]
        await service.undo(ctx(), actor, chore_id, body)
