"""RFC 9457 Problem Details for HTTP APIs.

Every error response from iHIM — HTTPException, validation failure, or
unhandled exception — is serialized as application/problem+json:

    {
        "type": "about:blank",
        "title": "Not Found",
        "status": 404,
        "detail": "Entry xyz not found",
        "instance": "/api/brain/entries/xyz"
    }
"""

from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

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
    """Build an RFC 9457 Problem Details response."""
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
    return JSONResponse(status_code=status, content=body, media_type="application/problem+json")


def _first_error_detail(errors: list) -> str:
    if not errors:
        return "Invalid request data"
    first = errors[0]
    field = " -> ".join(str(loc) for loc in first.get("loc", ()))
    return f"{field}: {first.get('msg', 'invalid')}"


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    return problem(exc.status_code, str(exc.detail), instance=request.url.path)


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    errors = exc.errors()
    return problem(422, _first_error_detail(errors), instance=request.url.path, errors=errors)


async def pydantic_exception_handler(request: Request, exc: ValidationError) -> JSONResponse:
    return problem(422, _first_error_detail(exc.errors()), instance=request.url.path)


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    # Never leak stack traces to the client; uvicorn logs the traceback.
    return problem(500, "An unexpected error occurred", instance=request.url.path)


def register_exception_handlers(app) -> None:
    # Register on the STARLETTE base class: the router raises it directly for
    # unmatched routes/methods, and fastapi.HTTPException subclasses it — a
    # handler bound to the subclass would miss router-level 404/405s.
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(ValidationError, pydantic_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
