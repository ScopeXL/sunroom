"""``GET /api/discover``: how a Sunroom screen finds this server (ADR 0035, docs/M7.md T1).

Public, read-only and never cached. A screen setting itself up sweeps its network for this route
(and older servers by ``/api/setup/status``), and keeps the ``id`` of the one it was told to use,
so it finds it again when the router hands the server a new address.

The household's name goes only to a local address: an IP literal, ``localhost``, this
container's own name, a single-label name or one with a LAN suffix (``web/hosts.is_local_name``).
A page on the internet rebound to a home address still sends its own public name as the Host,
and gets ``null``. ``url`` is SUNROOM_ADVERTISED_URL when it is set, else ``null``: the screen
then keeps the address it found.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel

from sunroom.core.version import build_info
from sunroom.household import service as household_service
from sunroom.household.models import AppMeta
from sunroom.state import StateDep
from sunroom.web.hosts import host_name, is_local_name, own_hostname

router = APIRouter(prefix="/api", tags=["meta"])


class DiscoverOut(BaseModel):
    sunroom: Literal[True] = True
    id: str  # this Sunroom's own id, kept across restarts, backups and restores
    version: str
    setup_complete: bool
    name: str | None  # the household's name, only to a local address
    url: str | None  # SUNROOM_ADVERTISED_URL, when it is set
    # The household's language once it's set up: the screen's own pages speak it (ADR 0043).
    language: str | None


@router.get("/discover")
async def discover(request: Request, response: Response, state: StateDep) -> DiscoverOut:
    response.headers["Cache-Control"] = "no-store"
    async with state.db.read() as session:
        meta = await session.get(AppMeta, 1)
        home = await household_service.household(session)
    local = is_local_name(host_name(request.headers.get("host", "")), own_hostname())
    complete = state.household.setup_complete
    return DiscoverOut(
        id=meta.instance_id if meta is not None and meta.instance_id else "",
        version=build_info().version,
        setup_complete=complete,
        name=home.name if local and complete and home.name else None,
        url=state.settings.sunroom_advertised_url,
        language=home.language if complete else None,
    )
