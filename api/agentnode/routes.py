"""agent node Agent Node — Remote management via private link.

Proxies status, agent tasks, model info, and power management from
the agent node mini PC (192.168.20.2) through iHIM's API. The frontend
never talks directly to the agent node — this module handles all
communication.

Architecture:
  Desktop (iHIM :7777) --HTTP--> agent node (OpenClaw :18789)
                                   └── llama.cpp :8080 (localhost)

Power management goes through OpenClaw system skills (HTTP),
except Wake-on-LAN which is a desktop-side PowerShell UDP packet.
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from datetime import datetime, timezone
from typing import Optional
import asyncio
import os

from api.errors import problem

router = APIRouter(prefix="/api/agentnode", tags=["agentnode"])

# ---------------------------------------------------------------------------
# Configuration (from .env or defaults)
# ---------------------------------------------------------------------------

AGENTNODE_HOST = os.getenv("AGENTNODE_HOST", "192.168.20.2")
AGENTNODE_OPENCLAW_PORT = int(os.getenv("AGENTNODE_OPENCLAW_PORT", "18789"))
AGENTNODE_MAC = os.getenv("AGENTNODE_MAC", "")  # MAC address for Wake-on-LAN
CONNECT_TIMEOUT = 2.0  # Fast timeout — agent node is on local link

OPENCLAW_BASE = f"http://{AGENTNODE_HOST}:{AGENTNODE_OPENCLAW_PORT}"


# ---------------------------------------------------------------------------
# Internal HTTP client (async, fast timeout)
# ---------------------------------------------------------------------------

async def _fetch(path: str, method: str = "GET", json_body: dict = None) -> dict:
    """Fetch from agent node with fast timeout. Returns dict or raises."""
    import httpx
    url = f"{OPENCLAW_BASE}{path}"
    try:
        async with httpx.AsyncClient(timeout=CONNECT_TIMEOUT) as client:
            if method == "POST":
                resp = await client.post(url, json=json_body)
            else:
                resp = await client.get(url)
            return {"status_code": resp.status_code, "data": resp.json()}
    except httpx.TimeoutException:
        return {"status_code": 0, "error": "timeout", "data": None}
    except httpx.HTTPError as e:
        return {"status_code": 0, "error": str(e), "data": None}
    except Exception as e:
        return {"status_code": 0, "error": str(e), "data": None}


async def _is_reachable() -> bool:
    """Fast reachability check — TCP connect to OpenClaw port."""
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


# ---------------------------------------------------------------------------
# Status endpoint — single call for dashboard widget
# ---------------------------------------------------------------------------

@router.get("/status")
async def get_status(request: Request):
    """Combined status: reachability + system metrics + agent + model.

    Returns a flat object the frontend can render without multiple calls.
    Gracefully degrades — unreachable agent node returns offline status.
    """
    reachable = await _is_reachable()
    now = datetime.now(timezone.utc).isoformat()

    if not reachable:
        return {
            "status": "offline",
            "timestamp": now,
            "host": AGENTNODE_HOST,
            "system": None,
            "agent": None,
            "model": None,
        }

    # Parallel fetch: system metrics, agent status, model info
    system_task = _fetch("/api/system/stats")
    agent_task = _fetch("/api/agent/status")
    model_task = _fetch("/api/model/status")

    system_res, agent_res, model_res = await asyncio.gather(
        system_task, agent_task, model_task, return_exceptions=True
    )

    def _extract(res):
        if isinstance(res, Exception):
            return None
        if isinstance(res, dict) and res.get("status_code") == 200:
            return res.get("data")
        return None

    system_data = _extract(system_res)
    agent_data = _extract(agent_res)
    model_data = _extract(model_res)

    # Determine overall status
    overall = "online"
    if agent_data and agent_data.get("status") == "error":
        overall = "degraded"
    if not system_data and not agent_data:
        overall = "degraded"

    return {
        "status": overall,
        "timestamp": now,
        "host": AGENTNODE_HOST,
        "system": system_data,
        "agent": agent_data,
        "model": model_data,
    }


# ---------------------------------------------------------------------------
# Agent endpoints (proxy to OpenClaw)
# ---------------------------------------------------------------------------

@router.get("/agent/tasks")
async def get_agent_tasks(request: Request):
    """List agent task queue from OpenClaw."""
    reachable = await _is_reachable()
    if not reachable:
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
    """Submit a task to OpenClaw agent."""
    reachable = await _is_reachable()
    if not reachable:
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


# ---------------------------------------------------------------------------
# Power management
# ---------------------------------------------------------------------------

@router.post("/power/shutdown")
async def shutdown_agentnode(request: Request):
    """Request agent node shutdown via OpenClaw system skill."""
    reachable = await _is_reachable()
    if not reachable:
        return problem(503, "agent node unreachable", instance=request.url.path)

    res = await _fetch("/api/system/shutdown", method="POST", json_body={})
    if res.get("error"):
        return problem(502, f"Shutdown failed: {res['error']}", instance=request.url.path)
    return {"result": "shutdown_initiated", "timestamp": datetime.now(timezone.utc).isoformat()}


@router.post("/power/reboot")
async def reboot_agentnode(request: Request):
    """Request agent node reboot via OpenClaw system skill."""
    reachable = await _is_reachable()
    if not reachable:
        return problem(503, "agent node unreachable", instance=request.url.path)

    res = await _fetch("/api/system/reboot", method="POST", json_body={})
    if res.get("error"):
        return problem(502, f"Reboot failed: {res['error']}", instance=request.url.path)
    return {"result": "reboot_initiated", "timestamp": datetime.now(timezone.utc).isoformat()}


@router.post("/power/wol")
async def wake_on_lan(request: Request):
    """Send Wake-on-LAN magic packet to agent node via desktop PowerShell.

    WoL is the only power action that runs locally — the agent node is off,
    so there's no API to call. We send a UDP magic packet from the desktop.
    """
    if not AGENTNODE_MAC:
        return problem(
            400,
            "AGENTNODE_MAC not configured in .env",
            instance=request.url.path,
        )

    # Build magic packet: 6x FF + 16x MAC address
    mac_bytes = bytes.fromhex(AGENTNODE_MAC.replace(":", "").replace("-", ""))
    magic = b"\xff" * 6 + mac_bytes * 16

    import socket
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.sendto(magic, ("255.255.255.255", 9))
        sock.close()
    except OSError as e:
        return problem(500, f"WoL send failed: {e}", instance=request.url.path)

    return {
        "result": "wol_sent",
        "mac": AGENTNODE_MAC,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Health check (for flight path integration)
# ---------------------------------------------------------------------------

@router.get("/health")
async def health_check(request: Request):
    """Health check for flight path system integration.

    Returns draft-inadarei-api-health-check format.
    """
    reachable = await _is_reachable()
    status = "pass" if reachable else "fail"

    return JSONResponse(
        content={
            "status": status,
            "description": "agent node Agent Node",
            "checks": {
                "agentnode:reachable": [{
                    "componentType": "system",
                    "observedValue": reachable,
                    "status": status,
                    "time": datetime.now(timezone.utc).isoformat(),
                }],
            },
        },
        media_type="application/health+json",
    )
