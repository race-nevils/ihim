"""Server health, system stats, and process control.

/api/server/restart delegates to scripts/server.ps1 — the single canonical
lifecycle tool — spawned detached so it survives this process being stopped.
No temp scripts, no WMIC, no process-tree guessing: the script resolves the
listener by port, verifies it is an iHIM python process, and kills the tree
exactly once (there is no reload watcher to respawn it anymore).
"""

import logging
import os
import subprocess
import sys

import psutil
from fastapi import APIRouter, Request

from api.errors import problem
from api.responses import ok
from api.runtime import IHIM_DIR, uptime_seconds

logger = logging.getLogger(__name__)
router = APIRouter(tags=["server"])

_SERVER_PS1 = IHIM_DIR / "scripts" / "server.ps1"


@router.get("/api/health")
async def health():
    """Liveness + vitals. Must stay fast — restart tooling polls it."""
    result = {"status": "ok", "name": "iHIM", "pid": os.getpid()}
    up = uptime_seconds()
    if up is not None:
        result["uptime_seconds"] = up
    try:
        mem = psutil.Process(os.getpid()).memory_info()
        result["memory_mb"] = round(mem.rss / (1024 * 1024), 1)
    except Exception:
        pass
    try:
        from api.recorder.routes import _active_workers
        result["active_transcription_workers"] = len(_active_workers)
    except Exception:
        pass
    return result


@router.get("/api/system/stats")
async def system_stats():
    """CPU + RAM for the bottom-bar monitor (polled every 2s)."""
    memory = psutil.virtual_memory()
    return {
        "cpu": {
            "percent": psutil.cpu_percent(interval=None),
            "cores": psutil.cpu_count(logical=False),
            "threads": psutil.cpu_count(logical=True),
        },
        "memory": {
            "percent": memory.percent,
            "used_gb": round(memory.used / (1024 ** 3), 1),
            "total_gb": round(memory.total / (1024 ** 3), 1),
            "available_gb": round(memory.available / (1024 ** 3), 1),
        },
    }


@router.get("/api/server/status")
async def server_status(request: Request):
    """Process status; port read from the actual request, never guessed."""
    return {
        "status": "running",
        "pid": os.getpid(),
        "port": request.url.port,
        "uptime_seconds": uptime_seconds(),
    }


@router.post("/api/server/restart")
async def restart_server(request: Request):
    """Restart this instance via the canonical lifecycle script, detached."""
    if sys.platform != "win32":
        return problem(501, "Restart is only supported on Windows", instance=request.url.path)
    if not _SERVER_PS1.exists():
        return problem(404, f"Lifecycle script not found: {_SERVER_PS1}", instance=request.url.path)

    port = request.url.port or 7777
    try:
        flags = (
            subprocess.DETACHED_PROCESS
            | subprocess.CREATE_NEW_PROCESS_GROUP
            | subprocess.CREATE_NO_WINDOW
        )
        subprocess.Popen(
            [
                "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                "-File", str(_SERVER_PS1), "restart", "-Port", str(port), "-DelaySeconds", "1",
            ],
            creationflags=flags,
            close_fds=True,
            cwd=str(IHIM_DIR),
        )
    except Exception as e:
        logger.error("Failed to spawn restart script: %s", e)
        return problem(500, f"Failed to spawn restart script: {e}", instance=request.url.path)

    return ok(message="Restart initiated", pid=os.getpid(), port=port)
