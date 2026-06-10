"""agent node agent node — remote management proxy.

The frontend never talks to the agent node directly; this module proxies
status, agent tasks, and power management over the private link:

    Desktop (iHIM) --HTTP--> agent node (OpenClaw :18789)

Wake-on-LAN is the exception — the node is off, so the desktop sends the
UDP magic packet itself. (Ported as-is per the operator: WoL behavior untouched.)
"""

import asyncio
import os
import socket
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from api.errors import problem

router = APIRouter(prefix="/api/agentnode", tags=["agentnode"])

AGENTNODE_HOST = os.getenv("AGENTNODE_HOST", "192.168.20.2")
AGENTNODE_OPENCLAW_PORT = int(os.getenv("AGENTNODE_OPENCLAW_PORT", "18789"))
AGENTNODE_MAC = os.getenv("AGENTNODE_MAC", "")
CONNECT_TIMEOUT = 2.0  # local link — fail fast

OPENCLAW_BASE = f"http://{AGENTNODE_HOST}:{AGENTNODE_OPENCLAW_PORT}"


async def _fetch(path: str, method: str = "GET", json_body: dict | None = None) -> dict:
    """Call OpenClaw; errors come back as {'status_code': 0, 'error': ...}."""
    url = f"{OPENCLAW_BASE}{path}"
    try:
        async with httpx.AsyncClient(timeout=CONNECT_TIMEOUT) as client:
            if method == "POST":
                resp = await client.post(url, json=json_body)
            else:
                resp = await client.get(url)
            return {"status_code": resp.status_code, "data": resp.json()}
    except httpx.HTTPError as e:
        return {"status_code": 0, "error": str(e) or e.__class__.__name__, "data": None}
    except Exception as e:
        return {"status_code": 0, "error": str(e), "data": None}


async def _is_reachable() -> bool:
    """Fast TCP connect check to the OpenClaw port."""
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(AGENTNODE_HOST, AGENTNODE_OPENCLAW_PORT),
            timeout=CONNECT_TIMEOUT,
        )
        writer.close()
        await writer.wait_closed()
        return True
    except (asyncio.TimeoutError, OSError):
        return False


@router.get("/status")
async def get_status():
    """Combined status for the widget: reachability + system/agent/model."""
    reachable = await _is_reachable()
    now = datetime.now(timezone.utc).isoformat()
    if not reachable:
        return {"status": "offline", "timestamp": now, "host": AGENTNODE_HOST,
                "system": None, "agent": None, "model": None}

    results = await asyncio.gather(
        _fetch("/api/system/stats"), _fetch("/api/agent/status"), _fetch("/api/model/status"),
        return_exceptions=True,
    )

    def _extract(res):
        if isinstance(res, Exception):
            return None
        if isinstance(res, dict) and res.get("status_code") == 200:
            return res.get("data")
        return None

    system_data, agent_data, model_data = (_extract(r) for r in results)
    overall = "online"
    if agent_data and agent_data.get("status") == "error":
        overall = "degraded"
    if not system_data and not agent_data:
        overall = "degraded"

    return {"status": overall, "timestamp": now, "host": AGENTNODE_HOST,
            "system": system_data, "agent": agent_data, "model": model_data}


@router.get("/agent/tasks")
async def get_agent_tasks(request: Request):
    """List the OpenClaw agent task queue."""
    if not await _is_reachable():
        return problem(503, "agent node unreachable", instance=request.url.path)
    res = await _fetch("/api/tasks")
    if res.get("error"):
        return problem(502, f"OpenClaw error: {res['error']}", instance=request.url.path)
    return res.get("data", [])


class TaskSubmit(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=4096)
    model: Optional[str] = None
    priority: Optional[str] = Field(None, pattern="^(low|normal|high)$")


@router.post("/agent/tasks")
async def submit_task(body: TaskSubmit, request: Request):
    """Submit a task to the OpenClaw agent."""
    if not await _is_reachable():
        return problem(503, "agent node unreachable", instance=request.url.path)
    payload = {"prompt": body.prompt}
    if body.model:
        payload["model"] = body.model
    if body.priority:
        payload["priority"] = body.priority
    res = await _fetch("/api/tasks", method="POST", json_body=payload)
    if res.get("error"):
        return problem(502, f"OpenClaw error: {res['error']}", instance=request.url.path)
    return res.get("data", {})


@router.post("/power/shutdown")
async def shutdown_agentnode(request: Request):
    """Shutdown via OpenClaw system skill."""
    if not await _is_reachable():
        return problem(503, "agent node unreachable", instance=request.url.path)
    res = await _fetch("/api/system/shutdown", method="POST", json_body={})
    if res.get("error"):
        return problem(502, f"Shutdown failed: {res['error']}", instance=request.url.path)
    return {"result": "shutdown_initiated", "timestamp": datetime.now(timezone.utc).isoformat()}


@router.post("/power/reboot")
async def reboot_agentnode(request: Request):
    """Reboot via OpenClaw system skill."""
    if not await _is_reachable():
        return problem(503, "agent node unreachable", instance=request.url.path)
    res = await _fetch("/api/system/reboot", method="POST", json_body={})
    if res.get("error"):
        return problem(502, f"Reboot failed: {res['error']}", instance=request.url.path)
    return {"result": "reboot_initiated", "timestamp": datetime.now(timezone.utc).isoformat()}


@router.post("/power/wol")
async def wake_on_lan(request: Request):
    """Send the Wake-on-LAN magic packet from the desktop (node is off)."""
    if not AGENTNODE_MAC:
        return problem(400, "AGENTNODE_MAC not configured in .env", instance=request.url.path)
    mac_bytes = bytes.fromhex(AGENTNODE_MAC.replace(":", "").replace("-", ""))
    magic = b"\xff" * 6 + mac_bytes * 16
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.sendto(magic, ("255.255.255.255", 9))
        sock.close()
    except OSError as e:
        return problem(500, f"WoL send failed: {e}", instance=request.url.path)
    return {"result": "wol_sent", "mac": AGENTNODE_MAC,
            "timestamp": datetime.now(timezone.utc).isoformat()}
