"""One error envelope for the whole API (ADR 0043):
``{"error": {"code": "...", "message": "...", "key": "...", "params": {...}}}``.

``message`` is plain English a household member can act on (docs/UX.md §2), read from
``lang/en.json`` under ``key``; ``params`` are its ``{name}`` values (``{}`` when it has none).
The page says the key in the family's language, and shows ``message`` for a key it doesn't know.
``code`` is for the code that reads the answer, and never changes with the words.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from sunroom.core.lang import Words, plain, t_en
from sunroom.core.logging import get_logger

log = get_logger(__name__)

_STATUS_CODES: dict[int, tuple[str, str]] = {
    400: ("bad_request", "api.http.400"),
    401: ("signed_out", "api.http.401"),
    403: ("forbidden", "api.http.403"),
    404: ("not_found", "api.http.404"),
    405: ("method_not_allowed", "api.http.405"),
    409: ("conflict", "api.http.409"),
    413: ("too_large", "api.http.413"),
    429: ("rate_limited", "api.http.429"),
}


class AppError(Exception):
    """A refusal the family reads: its English is ``lang/en.json``'s ``key`` with ``params``."""

    def __init__(
        self,
        status: int,
        code: str,
        key: str,
        *,
        params: Mapping[str, object] | None = None,
        headers: dict[str, str] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        self.params = plain(params)
        self.message = t_en(key, **self.params)
        super().__init__(self.message)
        self.status = status
        self.code = code
        self.key = key
        self.headers = headers
        self.extra = extra or {}

    @classmethod
    def said(
        cls,
        status: int,
        code: str,
        words: Words,
        *,
        headers: dict[str, str] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> AppError:
        """A refusal whose sentence came from elsewhere (a check, a library, a provider)."""
        return cls(status, code, words.key, params=words.params, headers=headers, extra=extra)


def envelope(
    code: str, key: str, params: Mapping[str, object] | None = None, **extra: Any
) -> dict[str, Any]:
    values = plain(params)
    return {
        "error": {
            "code": code,
            "message": t_en(key, **values),
            "key": key,
            "params": values,
            **extra,
        }
    }


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return JSONResponse(
            envelope(exc.code, exc.key, exc.params, **exc.extra),
            status_code=exc.status,
            headers=exc.headers,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        code, key = _STATUS_CODES.get(exc.status_code, ("error", "api.error"))
        return JSONResponse(
            envelope(code, key),
            status_code=exc.status_code,
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        fields = sorted(
            {".".join(str(part) for part in error.get("loc", ())[1:]) for error in exc.errors()}
            - {""}
        )
        return JSONResponse(envelope("invalid", "api.invalid", fields=fields), status_code=422)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        log.exception("request.unhandled_error", path=request.url.path)
        return JSONResponse(envelope("server_error", "api.server_error"), status_code=500)
