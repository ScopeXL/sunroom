"""The agent's API, ``/api/screen/…`` (docs/M7.md, "The agent's API"), and the screen's own
pages (``frontend/src/screen``, built into ``static/``).

Who may call it:

* **Only by a loopback name.** It listens on 127.0.0.1, and a request's Host must be
  ``127.0.0.1``, ``localhost`` or ``[::1]`` with its port: a web page that points its own name
  at 127.0.0.1 still sends that name, and is refused.
* **From two kinds of page.** CORS answers the Sunroom this screen shows and the agent's own
  pages, never credentials; a preflight that asks about the private network is told yes
  (Chrome's Private Network Access).
* **Changes carry ``X-Sunroom-Screen: 1``**, which no form can send and no other page may (it
  makes the request need a preflight), and a page's ``Origin`` must be one of those two.
"""

from __future__ import annotations

import secrets
import socket
from collections.abc import AsyncGenerator, Awaitable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

import uvicorn
from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from sunroom_kiosk import logs
from sunroom_kiosk.discovery import CheckFailedError, found_out
from sunroom_kiosk.events import EventHub, frame
from sunroom_kiosk.platform.base import PlatformError, WifiNetwork
from sunroom_kiosk.schemas import (
    ScreenAboutOut,
    ScreenAcceptedOut,
    ScreenCapability,
    ScreenCheckIn,
    ScreenCheckOut,
    ScreenErrorOut,
    ScreenFoundOut,
    ScreenOpenIn,
    ScreenRotationIn,
    ScreenSaveIn,
    ScreenScanOut,
    ScreenStateOut,
    ScreenUpdateOut,
    ScreenUpdatePolicyIn,
    ScreenWifiJoinIn,
    ScreenWifiListOut,
    ScreenWifiOut,
)
from sunroom_kiosk.state import Agent

log = logs.get("api")

PREFIX = "/api/screen"
CHANGES = frozenset({"POST", "PUT", "PATCH", "DELETE"})
NONCE_PLACEHOLDER = "__SUNROOM_CSP_NONCE__"
STATIC = Path(__file__).parent / "static"

ERRORS: dict[int | str, dict[str, Any]] = {
    403: {"model": ScreenErrorOut},
    409: {"model": ScreenErrorOut},
    422: {"model": ScreenErrorOut},
}


class AppError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def envelope(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)


def csp(nonce: str) -> str:
    return (
        "default-src 'self'; script-src 'self'; "
        f"style-src 'self' 'nonce-{nonce}'; img-src 'self' data:; font-src 'self'; "
        "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'; "
        "object-src 'none'"
    )


async def _respond(send: Send, response: Response) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": response.status_code,
            "headers": response.raw_headers,
        }
    )
    await send({"type": "http.response.body", "body": response.body})


class Guard:
    """The rules above, as a pure ASGI middleware (the event stream passes untouched)."""

    def __init__(self, app: ASGIApp, *, agent: Agent) -> None:
        self.app = app
        self.agent = agent

    def _hosts(self) -> set[str]:
        port = self.agent.port
        return {f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}"}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        if headers.get("host", "").lower() not in self._hosts():
            await _respond(
                send, envelope(421, "unknown_host", "Sunroom Screen answers only on this screen.")
            )
            return
        method: str = scope["method"]
        origin = headers.get("origin")
        allowed = origin is not None and origin in self.agent.origins()
        if method == "OPTIONS" and origin and headers.get("access-control-request-method"):
            if not allowed:
                await _respond(send, envelope(403, "origin", "That page can't use this screen."))
                return
            preflight = Response(status_code=204)
            preflight.headers["Access-Control-Allow-Origin"] = origin
            preflight.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE"
            preflight.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Sunroom-Screen"
            preflight.headers["Access-Control-Max-Age"] = "600"
            preflight.headers["Vary"] = "Origin"
            if headers.get("access-control-request-private-network") == "true":
                preflight.headers["Access-Control-Allow-Private-Network"] = "true"
            await _respond(send, preflight)
            return
        if method in CHANGES:
            if origin is not None and not allowed:
                await _respond(send, envelope(403, "origin", "That page can't change this screen."))
                return
            if headers.get("x-sunroom-screen") != "1":
                await _respond(
                    send, envelope(403, "header", "A change needs the X-Sunroom-Screen header.")
                )
                return

        async def with_cors(message: Message) -> None:
            if message["type"] == "http.response.start" and allowed and origin is not None:
                out = MutableHeaders(scope=message)
                out["Access-Control-Allow-Origin"] = origin
                out.append("Vary", "Origin")
            await send(message)

        await self.app(scope, receive, with_cors)


def agent_of(request: Request) -> Agent:
    agent: Agent = request.app.state.agent
    return agent


AgentDep = Annotated[Agent, Depends(agent_of)]


def need(agent: Agent, capability: ScreenCapability, what: str) -> None:
    if capability not in agent.capabilities():
        raise AppError(409, "not_here", f"{what} isn't something this screen can do.")


async def attempt(work: Awaitable[Any]) -> Any:
    """A device action, its failure said plainly (PlatformError's words are the family's)."""
    try:
        return await work
    except PlatformError as error:
        raise AppError(409, "device", str(error)) from None


router = APIRouter(prefix=PREFIX, tags=["screen"], responses=ERRORS)


@router.get("")
async def read_state(agent: AgentDep) -> ScreenStateOut:
    return agent.snapshot()


@router.get("/events", include_in_schema=False)
async def events(agent: AgentDep) -> StreamingResponse:
    return StreamingResponse(
        agent.hub.stream(first=frame("state", agent.snapshot())),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@router.post("/restart", status_code=202)
async def restart(agent: AgentDep) -> ScreenAcceptedOut:
    need(agent, "restart", "Restarting")
    await agent.later(agent.platform.restart)
    return ScreenAcceptedOut()


@router.post("/shutdown", status_code=202)
async def shutdown(agent: AgentDep) -> ScreenAcceptedOut:
    need(agent, "shutdown", "Shutting down")
    await agent.later(agent.platform.shutdown)
    return ScreenAcceptedOut()


@router.post("/quit", status_code=202)
async def quit_screen(agent: AgentDep) -> ScreenAcceptedOut:
    need(agent, "quit", "Quitting")
    await agent.later(agent.quit)
    return ScreenAcceptedOut()


@router.post("/keep-pairing", status_code=202)
async def keep_pairing(agent: AgentDep) -> ScreenAcceptedOut:
    """The wall's page has just been paired (or set Sunroom up): the browser writes its cookies
    to disk now, so a restart straight after keeps the pairing (ADR 0040)."""
    agent.spawn(agent.browser.save_cookies())
    return ScreenAcceptedOut()


@router.get("/update")
async def check_update(agent: AgentDep) -> ScreenUpdateOut:
    """Check now: the newest version on GitHub, against this one."""
    await agent.updater.check_now()
    agent.publish_state()
    return ScreenUpdateOut.model_validate(agent.updater.status(agent.update_check()))


@router.post("/update", status_code=202)
async def install_update(agent: AgentDep) -> ScreenAcceptedOut:
    need(agent, "update", "Updating")
    agent.spawn(agent.updater.install(agent))
    return ScreenAcceptedOut()


@router.post("/update-sunroom", status_code=202)
async def update_sunroom(agent: AgentDep) -> ScreenAcceptedOut:
    """An all-in-one Pi: the Sunroom on this screen too (it runs /opt/sunroom/update.sh)."""
    need(agent, "update_sunroom", "Updating Sunroom from here")
    agent.spawn(agent.update_sunroom())
    return ScreenAcceptedOut()


@router.put("/update-policy")
async def update_policy(body: ScreenUpdatePolicyIn, agent: AgentDep) -> ScreenUpdateOut:
    agent.set_update_check(body.check)
    return ScreenUpdateOut.model_validate(agent.updater.status(agent.update_check()))


def wifi_out(networks: list[WifiNetwork]) -> ScreenWifiListOut:
    return ScreenWifiListOut(
        networks=[
            ScreenWifiOut(
                id=n.id,
                ssid=n.ssid,
                strength=n.strength,
                secured=n.secured,
                connected=n.connected,
                saved=n.saved,
            )
            for n in sorted(networks, key=lambda n: (not n.connected, -n.strength))
        ]
    )


@router.get("/wifi")
async def wifi_list(agent: AgentDep) -> ScreenWifiListOut:
    need(agent, "wifi", "Wi-Fi")
    return wifi_out(await attempt(agent.platform.wifi_networks()))


@router.post("/wifi")
async def wifi_join(body: ScreenWifiJoinIn, agent: AgentDep) -> ScreenWifiListOut:
    need(agent, "wifi", "Wi-Fi")
    await attempt(agent.platform.wifi_join(body.ssid, body.password))
    log.info("Joined the Wi-Fi network %s.", body.ssid)
    await agent.refresh_network()
    return wifi_out(await attempt(agent.platform.wifi_networks()))


@router.delete("/wifi/{network_id}")
async def wifi_forget(network_id: str, agent: AgentDep) -> ScreenWifiListOut:
    need(agent, "wifi", "Wi-Fi")
    await attempt(agent.platform.wifi_forget(network_id))
    await agent.refresh_network()
    return wifi_out(await attempt(agent.platform.wifi_networks()))


@router.get("/sunrooms")
async def sunrooms(agent: AgentDep) -> ScreenScanOut:
    return ScreenScanOut(
        scanning=agent.discovery.scanning,
        found=[ScreenFoundOut.model_validate(found) for found in agent.scan_results()],
    )


@router.post("/sunrooms/scan", status_code=202)
async def scan(agent: AgentDep) -> ScreenScanOut:
    if not agent.discovery.scanning:
        agent.spawn(agent.scan())
    return ScreenScanOut(scanning=True, found=[])


@router.post("/sunroom/check")
async def check_address(body: ScreenCheckIn, agent: AgentDep) -> ScreenCheckOut:
    try:
        found = await agent.check(body.url)
    except CheckFailedError as error:
        return ScreenCheckOut(ok=False, sunroom=None, message=str(error))
    return ScreenCheckOut(
        ok=True, sunroom=ScreenFoundOut.model_validate(found_out(found)), message=None
    )


@router.put("/sunroom")
async def save_sunroom(body: ScreenSaveIn, agent: AgentDep) -> ScreenStateOut:
    """Use this Sunroom from now on: checked again here, so only a Sunroom is ever saved."""
    try:
        found = await agent.check(body.url)
    except CheckFailedError as error:
        raise AppError(422, "not_a_sunroom", str(error)) from None
    await agent.use(found, body.found)
    return agent.snapshot()


@router.delete("/sunroom")
async def forget_sunroom(agent: AgentDep) -> ScreenStateOut:
    await agent.forget()
    return agent.snapshot()


@router.post("/run-sunroom", status_code=202)
async def run_sunroom(agent: AgentDep) -> ScreenAcceptedOut:
    need(agent, "run_sunroom", "Running Sunroom here")
    agent.start_run()
    return ScreenAcceptedOut()


@router.put("/display")
async def display(body: ScreenRotationIn, agent: AgentDep) -> ScreenStateOut:
    need(agent, "rotate", "Turning the picture")
    await attempt(agent.rotate(body.rotation))
    return agent.snapshot()


@router.post("/open", status_code=202)
async def open_page(body: ScreenOpenIn, agent: AgentDep) -> ScreenAcceptedOut:
    url = agent.agent_url("/settings") if body.page == "settings" else agent.start_page()
    await agent.browser.navigate(url)
    return ScreenAcceptedOut()


@router.get("/about")
async def about(agent: AgentDep) -> ScreenAboutOut:
    return agent.about()


def mount_pages(app: FastAPI, static: Path) -> None:
    """The screen's own pages: the built shell, its assets, and its index for every other path
    (with a fresh CSP nonce, as Sunroom's own index.html; ``motion`` gets the nonce)."""
    index = next((p for p in (static / "screen.html", static / "index.html") if p.is_file()), None)
    if index is None:

        @app.get("/{path:path}", include_in_schema=False)
        async def no_pages(path: str) -> Response:  # pyright: ignore[reportUnusedFunction]
            if path.startswith("api/"):
                return envelope(404, "not_found", "That couldn't be found.")
            return HTMLResponse(
                "Sunroom Screen is running, but its pages aren't built here "
                "(just kiosk-build, or just kiosk-dev for development).",
                status_code=404,
            )

        return
    template = index.read_text(encoding="utf-8")
    root = static.resolve()
    if (root / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=root / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def pages(path: str) -> Response:  # pyright: ignore[reportUnusedFunction]
        if path.startswith("api/") or path.startswith("assets/"):
            return envelope(404, "not_found", "That couldn't be found.")
        if path and "/" not in path:
            candidate = (root / path).resolve()
            if candidate.is_file() and candidate.is_relative_to(root) and candidate != index:
                return FileResponse(candidate, headers={"Cache-Control": "no-cache"})
        nonce = secrets.token_urlsafe(18)
        return HTMLResponse(
            template.replace(NONCE_PLACEHOLDER, nonce),
            headers={"Cache-Control": "no-cache", "Content-Security-Policy": csp(nonce)},
        )


def create_app(
    agent: Agent,
    *,
    static: Path | None = STATIC,
    test_routes: bool = False,
    run_agent: bool = True,
) -> FastAPI:
    """``run_agent``: start the agent (browser, health checks, the screen's sleep) with the
    server and stop it with the server; tests that drive it by hand pass False."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        if run_agent:
            await agent.start()
        try:
            yield
        finally:
            if run_agent:
                await agent.stop()

    app = FastAPI(
        title="Sunroom Screen",
        version="0",
        lifespan=lifespan,
        openapi_url=None,
        docs_url=None,
        redoc_url=None,
    )
    app.state.agent = agent

    @app.exception_handler(AppError)
    async def app_error(request: Request, error: AppError) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return envelope(error.status, error.code, error.message)

    @app.exception_handler(PlatformError)
    async def platform_error(request: Request, error: PlatformError) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return envelope(409, "device", str(error))

    app.include_router(router)
    if test_routes:
        from sunroom_kiosk.testing import router as testing_router

        app.include_router(testing_router)
    if static is not None:
        mount_pages(app, static)
    app.add_middleware(Guard, agent=agent)
    return app


# What uvicorn may still wait for once the event streams are ended (another request in flight).
SHUTDOWN_GRACE_S = 3  # seconds (uvicorn takes whole ones)


class AgentServer(uvicorn.Server):
    """uvicorn on 127.0.0.1, ending the screen pages' event streams the moment it's asked to
    stop (SIGTERM from launchd or systemd, an update's restart). It waits for every open
    connection before the app's own shutdown, and a page's stream never ends by itself: the
    agent never got to close its browser, which the system then killed before it wrote a fresh
    pairing's cookie (ADR 0040). Whatever is still open after ``SHUTDOWN_GRACE_S`` is cut."""

    def __init__(self, app: FastAPI, *, hub: EventHub, port: int) -> None:
        super().__init__(
            uvicorn.Config(
                app,
                host="127.0.0.1",
                port=port,
                log_level="warning",
                access_log=False,
                timeout_graceful_shutdown=SHUTDOWN_GRACE_S,
            )
        )
        self.hub = hub

    async def shutdown(self, sockets: list[socket.socket] | None = None) -> None:
        self.hub.close()
        await super().shutdown(sockets)
