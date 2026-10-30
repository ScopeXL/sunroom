"""Serving the built single-page app (PLAN §5.1, ADR 0007).

* ``/assets/*``: hashed build files, cached forever by the security-headers middleware; a
  missing asset is a 404, never index.html.
* other top-level files (``sw.js``, ``manifest.webmanifest``, icons): ``no-cache``.
* every other GET outside /api and the photo files under /photos/ (``/photos`` itself is the
  Photos room), and ``/index.html`` itself: index.html with ``no-cache``, stamped with a fresh
  CSP nonce. The same nonce goes into the page's ``<meta name="csp-nonce">`` and into that
  response's ``style-src``, so the app can hand it to the animation library and nothing else
  can add styles. A service worker's cached copy keeps its own matching header and meta, so it
  stays consistent offline.
* a wall screen run by Sunroom Screen opens ``/display?screen=<port>``: that one document's
  ``connect-src`` also allows ``http://127.0.0.1:<port>``, so Settings → This Screen can call the
  agent (ADR 0035). Any other path or port (1024 to 65535 only) gets the plain policy.

The app is ``SUNROOM_STATIC_DIR`` (the image's /app/static, the e2e server's frontend/dist), or,
when that isn't set, the copy inside the installed package that Sunroom run as a program brings
with it (``sunroom/static``, ADR 0038). A checkout has no such copy: `just server-build` makes it
only in the wheel it builds.
"""

from __future__ import annotations

import mimetypes
import secrets
from pathlib import Path
from urllib.parse import parse_qs

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles

from sunroom.core.errors import AppError
from sunroom.core.logging import get_logger
from sunroom.web.headers import csp

mimetypes.add_type("application/manifest+json", ".webmanifest")
NO_CACHE = {"Cache-Control": "no-cache"}
NONCE_PLACEHOLDER = "__SUNROOM_CSP_NONCE__"
log = get_logger(__name__)


def _not_found() -> AppError:
    return AppError(404, "not_found", "api.http.404")


def _reserved(path: str) -> bool:
    """Paths the app never answers: the API, the build's assets, and the photo files. The bare
    ``/photos`` is the Photos room's address (the wall's code opens it on a phone that may never
    have loaded the app), so only what's under it is reserved."""
    if path.startswith("photos/"):
        return True
    return any(path == top or path.startswith(f"{top}/") for top in ("api", "assets"))


def new_nonce() -> str:
    return secrets.token_urlsafe(18)


def screen_port(path: str, query: str) -> int | None:
    """The port of this screen's own agent, for a ``/display`` document that names it once."""
    if path != "display":
        return None
    values = parse_qs(query).get("screen", [])
    if len(values) != 1 or not values[0].isdigit():
        return None
    port = int(values[0])
    return port if 1024 <= port <= 65535 else None


def render_index(template: str, agent_port: int | None = None) -> HTMLResponse:
    nonce = new_nonce()
    return HTMLResponse(
        template.replace(NONCE_PLACEHOLDER, nonce),
        headers={**NO_CACHE, "Content-Security-Policy": csp(nonce, agent_port)},
    )


def packaged_static(package: Path | None = None) -> Path | None:
    """The built app inside the installed package, when this package carries one."""
    packaged = (package or Path(__file__).resolve().parent.parent) / "static"
    return packaged if (packaged / "index.html").is_file() else None


def mount_spa(app: FastAPI, static_dir: Path | None) -> None:
    if static_dir is None or not (static_dir / "index.html").is_file():

        @app.api_route("/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
        async def no_frontend(path: str) -> Response:  # pyright: ignore[reportUnusedFunction]
            if _reserved(path):
                raise _not_found()
            return PlainTextResponse(
                "The Sunroom API is running, but the frontend isn't built here. "
                "In development, open the Vite dev server instead.",
                status_code=404,
            )

        return

    root = static_dir.resolve()
    template = (root / "index.html").read_text(encoding="utf-8")
    if NONCE_PLACEHOLDER not in template:
        log.warning("spa.no_nonce_placeholder", effect="animations that add styles will be blocked")
    if (root / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=root / "assets"), name="assets")

    @app.api_route("/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    async def spa(path: str, request: Request) -> Response:  # pyright: ignore[reportUnusedFunction]
        if _reserved(path):
            raise _not_found()
        if path and path != "index.html":
            candidate = (root / path).resolve()
            if candidate.is_file() and candidate.is_relative_to(root):
                return FileResponse(candidate, headers=NO_CACHE)
        return render_index(template, screen_port(path, request.url.query))
