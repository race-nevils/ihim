"""Standardized API response helpers.

Success responses use a consistent envelope:

    {"success": true, "data": {...}}           # single resource
    {"success": true, "items": [...], "count": N}  # collection

Error responses use RFC 9457 Problem Details (see ``api.errors``).

Usage in route handlers::

    from api.responses import ok, created, collection

    @router.get("/widgets/{id}")
    async def get_widget(id: str):
        widget = find_widget(id)
        return ok(widget)

    @router.post("/widgets", status_code=201)
    async def create_widget(req: WidgetCreate):
        widget = save_widget(req)
        return created(widget, message="Widget created")

    @router.get("/widgets")
    async def list_widgets():
        widgets = get_all_widgets()
        return collection(widgets)
"""

from fastapi.responses import JSONResponse
from typing import Any


def ok(data: Any = None, *, message: str | None = None, **extra) -> dict:
    """Standard success envelope for a single resource or action result.

    Args:
        data: The payload (dict, list, or scalar). Merged at top level if dict.
        message: Optional human-readable message.
        **extra: Additional top-level keys.
    """
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
    body = ok(data, message=message, **extra)
    return JSONResponse(status_code=201, content=body)


def collection(items: list, *, key: str = "items", **extra) -> dict:
    """Standard success envelope for a list of resources.

    Args:
        items: The list of resources.
        key: Top-level key name for the list (default "items").
        **extra: Additional top-level keys (e.g., pagination).
    """
    body: dict[str, Any] = {"success": True, "count": len(items), key: items}
    if extra:
        body.update(extra)
    return body
