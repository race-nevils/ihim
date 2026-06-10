"""Standardized success-response helpers.

    {"success": true, ...}                          # single resource / action
    {"success": true, "count": N, "items": [...]}   # collection

Errors are RFC 9457 Problem Details — see api.errors.
"""

from typing import Any

from fastapi.responses import JSONResponse


def ok(data: Any = None, *, message: str | None = None, **extra) -> dict:
    """Success envelope. A dict payload merges at top level."""
    body: dict[str, Any] = {"success": True}
    if message is not None:
        body["message"] = message
    if isinstance(data, dict):
        body.update(data)
    elif data is not None:
        body["data"] = data
    if extra:
        body.update(extra)
    return body


def created(data: Any = None, *, message: str | None = None, **extra) -> JSONResponse:
    """201 Created with success envelope."""
    return JSONResponse(status_code=201, content=ok(data, message=message, **extra))


def collection(items: list, *, key: str = "items", **extra) -> dict:
    """Success envelope for a list of resources."""
    body: dict[str, Any] = {"success": True, "count": len(items), key: items}
    if extra:
        body.update(extra)
    return body
