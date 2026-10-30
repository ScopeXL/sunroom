"""GET /api/events: the household-wide live-update stream (PLAN §11.5). Its hello names the
server's version, so every open screen notices an updated container and reloads (ADR 0028)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from sunroom.auth.deps import read_token
from sunroom.core.errors import AppError
from sunroom.core.version import build_info
from sunroom.events.hub import STOP, render
from sunroom.state import StateDep

router = APIRouter(tags=["events"])

STREAM_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "X-Accel-Buffering": "no",
}


def _later_position(a: str | None, b: str | None) -> str | None:
    """The client passes ?since=; a browser-native reconnect sends Last-Event-ID instead."""
    candidates = [value for value in (a, b) if value]
    if not candidates:
        return None

    def seq(value: str) -> int:
        try:
            return int(value.rpartition(":")[2])
        except ValueError:
            return -1

    return max(candidates, key=seq)


@router.get("/api/events", include_in_schema=False)
async def events(request: Request, state: StateDep, since: str | None = None) -> StreamingResponse:
    token = read_token(request, state)
    if token is None:
        raise AppError(401, "signed_out", "api.auth.signed_out")
    hub = state.hub
    conn = hub.register(token.device_id, token.epoch)
    mode, backlog, start_seq = hub.catch_up(
        _later_position(since, request.headers.get("last-event-id"))
    )

    async def stream() -> AsyncIterator[str]:
        last_sent = start_seq
        try:
            yield "retry: 3000\n\n"
            yield render(
                {
                    "type": "hello",
                    "mode": mode,
                    "epoch": hub.epoch,
                    "seq": hub.seq if mode != "replay" else start_seq,
                    "server_time": int(state.clock.now().timestamp() * 1000),
                    "version": state.hello_version.named(build_info().version),
                }
            )
            for frame in backlog:
                yield frame.text
                last_sent = frame.seq
            while True:
                if conn.stopped or hub.closing:
                    return
                if conn.overflowed:
                    while not conn.queue.empty():
                        conn.queue.get_nowait()
                    conn.overflowed = False
                    last_sent = hub.seq
                    yield render(
                        {
                            "type": "hello",
                            "mode": "resync",
                            "epoch": hub.epoch,
                            "seq": hub.seq,
                            "server_time": int(state.clock.now().timestamp() * 1000),
                            "version": state.hello_version.named(build_info().version),
                        }
                    )
                    continue
                try:
                    frame = await asyncio.wait_for(conn.queue.get(), timeout=hub.ping_interval_s)
                except TimeoutError:
                    current = read_token(request, state)
                    if current is None or current.epoch != conn.epoch:
                        yield render({"type": "session.expired"})
                        return
                    yield render({"type": "ping", "t": int(state.clock.now().timestamp() * 1000)})
                    continue
                if frame is STOP:
                    if token.device_id in state.auth.revoked_devices:
                        yield render({"type": "session.expired"})
                    return
                if frame.seq <= last_sent:
                    continue
                last_sent = frame.seq
                yield frame.text
        finally:
            hub.unregister(conn)

    return StreamingResponse(
        stream(), media_type="text/event-stream; charset=utf-8", headers=STREAM_HEADERS
    )
