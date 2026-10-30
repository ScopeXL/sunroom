"""Test-only routes, with ``--fake`` (the e2e runs and ``just kiosk-dev``): put the pretend
screen back as it started before each test, or change what it pretends to be. Never mounted on a
real screen."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel

from sunroom_kiosk.state import Agent

router = APIRouter(prefix="/api/screen/_test", include_in_schema=False)


class FakeIn(BaseModel):
    kind: Literal["pi", "desktop"] | None = None
    wired: bool | None = None
    offline: bool | None = None  # no Wi-Fi joined (and no cable): the Wi-Fi step shows
    sunroom: str | None = None  # an address saved without checking it (Can't Reach)
    run: Literal["ok", "hold", "fail"] | None = None  # how Run Sunroom Here goes
    # This Screen's Software row: a newer version found, or a helper too old to finish one.
    update: Literal["available", "terminal"] | None = None


def _agent(request: Request) -> Agent:
    agent: Agent = request.app.state.agent
    return agent


@router.post("/reset", status_code=204)
async def reset(request: Request) -> None:
    await _agent(request).reset_fake()


@router.post("/fake", status_code=204)
async def fake(body: FakeIn, request: Request) -> None:
    await _agent(request).change_fake(
        kind=body.kind,
        wired=body.wired,
        offline=body.offline,
        sunroom=body.sunroom,
        run=body.run,
        update=body.update,
    )
