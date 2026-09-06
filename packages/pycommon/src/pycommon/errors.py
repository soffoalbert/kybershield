"""A single error envelope for every service.

The ingestion service answers `{"error": "...", "issues": [{path, message}]}`,
while FastAPI's default is `{"detail": ...}`. A client talking to all three
would have to parse two shapes and branch on which host it called, so the
FastAPI services are brought onto ingestion's shape here rather than the other
way round: `error` is a stable machine-readable slug, and `issues` names the
offending fields without echoing their values, because payloads carry secrets.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

__all__ = ["ValidationFailed", "install_error_handlers"]

logger = logging.getLogger(__name__)

#: Status code to the slug reported as `error`. Anything unlisted falls back to
#: a generic slug, so a new status cannot leak a stack trace or a bare string.
_SLUGS = {
    400: "validation_failed",
    401: "unauthorized",
    404: "not_found",
    413: "payload_too_large",
    503: "storage_unavailable",
}


class ValidationFailed(HTTPException):
    """A 400 carrying per-field issues, matching ingestion's shape.

    An `HTTPException` subclass so FastAPI's own machinery still handles it and
    it documents itself as a 400 in the OpenAPI schema.
    """

    def __init__(self, issues: list[dict[str, str]]) -> None:
        super().__init__(status_code=400, detail=issues)

    @classmethod
    def at(cls, path: str, message: str) -> ValidationFailed:
        """Build a single-issue failure for the named field."""
        return cls([{"path": path, "message": message}])


def _body(status_code: int, issues: list[dict[str, str]] | None) -> dict[str, Any]:
    body: dict[str, Any] = {"error": _SLUGS.get(status_code, "request_failed")}
    if issues:
        body["issues"] = issues
    return body


def install_error_handlers(app: FastAPI) -> None:
    """Render every error on this app as the shared envelope.

    Covers the three ways a FastAPI app produces one: a raised
    `HTTPException`, a request that fails signature validation before the
    handler runs, and anything unhandled.
    """

    @app.exception_handler(HTTPException)
    async def _http_exception(_: Request, exc: HTTPException) -> JSONResponse:
        # `ValidationFailed` puts a list of issues in `detail`; a plain
        # `HTTPException` puts a string there.
        issues = (
            exc.detail
            if isinstance(exc.detail, list)
            else [{"path": "", "message": str(exc.detail)}]
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=_body(exc.status_code, issues),
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def _request_validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        # 400 rather than FastAPI's default 422: a bad query parameter is the
        # same class of client mistake as a bad body, and ingestion already
        # answers 400 for that.
        issues = [
            {
                # `loc` starts with the source ("query", "path", "body"), which
                # is noise to a caller who knows what they sent.
                "path": ".".join(str(part) for part in error["loc"][1:]),
                "message": error["msg"],
            }
            for error in exc.errors()
        ]
        return JSONResponse(status_code=400, content=_body(400, issues))

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        # Logged, never returned: the message can name the schema or the
        # connection string.
        logger.exception("unhandled error")
        return JSONResponse(status_code=500, content={"error": "internal_server_error"})
