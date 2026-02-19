"""Capture routes — trigger the Second Brain capture widget via iHIM API."""

import asyncio
import socket

from fastapi import APIRouter, Request

from api.errors import problem

router = APIRouter(prefix="/api/capture", tags=["capture"])

WIDGET_PORT = 47778


@router.post("/trigger")
async def trigger_capture(request: Request):
    """Signal the capture widget to show its input bar.

    The widget listens on an internal port (47778) for TCP connections.
    This endpoint bridges AHK hotkeys → iHIM API → widget, so the trigger
    only works when production iHIM is running.
    """
    def _connect():
        try:
            conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            conn.settimeout(1)
            conn.connect(("127.0.0.1", WIDGET_PORT))
            conn.close()
            return True
        except (ConnectionRefusedError, TimeoutError, OSError):
            return False

    connected = await asyncio.get_event_loop().run_in_executor(None, _connect)

    if connected:
        return {"success": True, "message": "Capture widget triggered"}

    return problem(
        status=503,
        title="Capture widget unavailable",
        detail="Could not connect to capture widget. Is it running?",
        instance=request.url.path,
    )
