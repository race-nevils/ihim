"""RFC 9457 Problem Details for HTTP APIs.

Provides a unified error response format across all iHIM API endpoints.
Every error — whether raised via HTTPException, validation failure, or
unhandled exception — gets serialized as:

    {
        "type": "about:blank",
        "title": "Not Found",
        "status": 404,
        "detail": "Entry xyz not found",
        "instance": "/api/brain/entries/xyz"
    }

Content-Type: application/problem+json
"""

from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError

# Standard HTTP reason phrases (subset we actually use)
_STATUS_TITLES = {
    400: "Bad Request",
    401: "Unauthorized",
    403: "Forbidden",
    404: "Not Found",
    405: "Method Not Allowed",
    409: "Conflict",
    422: "Unprocessable Content",
    429: "Too Many Requests",
    500: "Internal Server Error",
    502: "Bad Gateway",
    503: "Service Unavailable",
    504: "Gateway Timeout",
}


def problem(
    status: int,
    detail: str,
    *,
    instance: str | None = None,
    type: str = "about:blank",
    title: str | None = None,
    **extra,
) -> JSONResponse:
    """Build an RFC 9457 Problem Details response.

    Args:
        status: HTTP status code.
        detail: Human-readable explanation specific to this occurrence.
        instance: URI reference identifying the specific occurrence (usually request path).
        type: URI reference identifying the problem type. Defaults to ``about:blank``.
        title: Short human-readable summary. Defaults to the HTTP reason phrase.
        **extra: Additional members merged into the response body.
    """
    body = {
        "type": type,
        "title": title or _STATUS_TITLES.get(status, "Error"),
        "status": status,
        "detail": detail,
    }
    if instance is not None:
        body["instance"] = instance
    if extra:
        body.update(extra)

    return JSONResponse(
        status_code=status,
        content=body,
        media_type="application/problem+json",
    )


# ---------------------------------------------------------------------------
# Global exception handlers — register these on the FastAPI app
# ---------------------------------------------------------------------------

async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Convert FastAPI HTTPException to Problem Details."""
    return problem(
        status=exc.status_code,
        detail=str(exc.detail),
        instance=request.url.path,
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Convert FastAPI request-validation errors to Problem Details."""
    errors = exc.errors()
    if errors:
        first = errors[0]
        field = " -> ".join(str(loc) for loc in first["loc"])
        detail = f"{field}: {first['msg']}"
    else:
        detail = "Invalid request data"

    return problem(
        status=422,
        detail=detail,
        instance=request.url.path,
        errors=errors,  # include full list as extension member
    )


async def pydantic_exception_handler(request: Request, exc: ValidationError) -> JSONResponse:
    """Convert raw Pydantic ValidationError to Problem Details."""
    errors = exc.errors()
    if errors:
        first = errors[0]
        field = " -> ".join(str(loc) for loc in first["loc"])
        detail = f"{field}: {first['msg']}"
    else:
        detail = "Invalid request data"

    return problem(
        status=422,
        detail=detail,
        instance=request.url.path,
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all for unhandled exceptions. Prevents leaking stack traces."""
    return problem(
        status=500,
        detail="An unexpected error occurred",
        instance=request.url.path,
    )
