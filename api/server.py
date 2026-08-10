"""Server health, system stats, and process control.

/api/server/restart fires the 'iHIM Restart' scheduled task, which runs
scripts/server.ps1 restart — the single canonical lifecycle tool — under the
Task Scheduler service, outside this process's kill tree. A spawned child
helper cannot do this job: server.ps1's taskkill /T reaps its own helper
(tree-kill-self), and DETACHED_PROCESS powershell exits without executing
(bug note 2026-07-27_detached-process-restart-spawn-dead-on-arrival-
sleep-defenses.md — this endpoint returned 200 and did nothing for 11 days).
"""

import asyncio
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

def _git(*args):
    try:
        out = subprocess.run(["git", "-C", str(IHIM_DIR), *args],
                             capture_output=True, text=True, timeout=5)
        return out.stdout.strip() if out.returncode == 0 else ""
    except Exception:
        return ""


# Source identity: WHOSE checkout answers on :7777. Computed once at import
# (health must stay fast); additive fields on /api/health — existing consumers
# (watchdog, lifecycle script, restart tooling) read only the original keys.
# (bug note 2026-07-09_port-serves-wrong-branch-not-stale-cache.md)
SOURCE = {
    "tree": _git("rev-parse", "--show-toplevel") or str(IHIM_DIR),
    "branch": _git("branch", "--show-current") or "unknown",
    "sha": _git("rev-parse", "--short", "HEAD") or "unknown",
    "dirty": bool(_git("status", "--porcelain", "--", ".")),  # IHIM subtree only
}


@router.get("/api/health")
async def health():
    """Liveness + vitals. Must stay fast — restart tooling polls it."""
    result = {"status": "ok", "name": "iHIM", "pid": os.getpid(), **SOURCE}
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


# CPU sampling runs on OUR cadence, never the request's. psutil.cpu_percent(
# interval=None) reports the average since the last call *anywhere in this
# process*, so measuring it inside the handler makes the window equal to the
# gap between polls: the first call after boot reads 0.0, a second client
# (Electron shell + a browser tab) halves everyone's window, and a refresh
# burst collapses it to milliseconds — under one scheduler tick the ratio is
# noise (measured 2026-08-10: 6.8/22.2/10.8/50.0 against a true 22-28%).
# RAM never had the bug: virtual_memory() is a stateless instantaneous read.
# Nothing else in the process may call psutil.cpu_percent() — it would steal
# this sampler's window and reintroduce the same skew.
_CPU_SAMPLE_SECONDS = 1.0
_cpu_percent: float | None = None
_cpu_task: asyncio.Task | None = None


async def _sample_cpu() -> None:
    global _cpu_percent
    psutil.cpu_percent(interval=None)  # prime the counter; this read is always 0.0
    while True:
        await asyncio.sleep(_CPU_SAMPLE_SECONDS)
        try:
            _cpu_percent = psutil.cpu_percent(interval=None)
        except Exception as e:
            logger.warning("CPU sampler read failed: %s", e)


def start_cpu_sampler() -> None:
    """Start the fixed-cadence CPU sampler (called from the app lifespan)."""
    global _cpu_task
    if _cpu_task is None or _cpu_task.done():
        _cpu_task = asyncio.create_task(_sample_cpu())


async def stop_cpu_sampler() -> None:
    global _cpu_task
    if _cpu_task is not None:
        _cpu_task.cancel()
        try:
            await _cpu_task
        except asyncio.CancelledError:
            pass
        _cpu_task = None


@router.get("/api/system/stats")
async def system_stats():
    """CPU + RAM for the bottom-bar monitor (polled every 2s).

    ``cpu.percent`` is the sampler's last reading, and is null until the first
    sample lands a second after boot — the monitor renders that as ``--``.
    """
    memory = psutil.virtual_memory()
    return {
        "cpu": {
            "percent": _cpu_percent,
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


def _launch_operator_script(request: Request, filename: str, label: str):
    """Launch an operator script (scripts/<filename> in the parent workspace)
    in its own console window — the Sneakernet window's buttons are shortcuts,
    nothing more. The scripts are interactive (progress output + a final
    pause), so they MUST get a visible console and their output must never be
    captured; CREATE_NEW_CONSOLE gives the child a fresh console even though
    this server runs windowless. Fire-and-forget: the operator watches the
    console, not the API response."""
    if sys.platform != "win32":
        return problem(501, f"{label} is only supported on Windows",
                       instance=request.url.path)

    script = IHIM_DIR.parent / "scripts" / filename
    if not script.is_file():
        # Deployments carved away from the parent workspace don't ship the
        # operator scripts — the button exists, the action honestly says so.
        return problem(501, f"{filename} not present in this deployment",
                       instance=request.url.path)

    try:
        proc = subprocess.Popen(
            ["cmd.exe", "/c", str(script)],
            cwd=str(script.parent),
            creationflags=subprocess.CREATE_NEW_CONSOLE,
        )
    except Exception as e:
        logger.error("%s launch failed: %s", label, e)
        return problem(500, f"{label} launch failed: {e}", instance=request.url.path)

    logger.info("%s launched (pid %d): %s", label, proc.pid, script)
    return ok(message=f"{label} launched", pid=proc.pid)


@router.post("/api/system/travel")
async def launch_travel(request: Request):
    """The LEAVING leg: refresh the drive mirror before ejecting."""
    return _launch_operator_script(request, "travel.cmd", "Leaving")


@router.post("/api/system/travel/return")
async def launch_travel_return(request: Request):
    """The RETURNING leg: pull Mac work + transcripts back off the drive."""
    return _launch_operator_script(request, "travel-return.cmd", "Returning")


@router.post("/api/server/restart")
async def restart_server(request: Request):
    """Restart the live instance via the out-of-tree scheduled task."""
    if sys.platform != "win32":
        return problem(501, "Restart is only supported on Windows", instance=request.url.path)

    port = request.url.port or 7777
    if port != 7777:
        # The task is pinned to the live server. Test instances (7778+) are
        # started by their own scripts and restarted by hand — a task per
        # throwaway port is machine state nobody maintains.
        return problem(
            501,
            f"Self-restart serves only the live :7777 instance; restart port "
            f"{port} via scripts/server.ps1 directly",
            instance=request.url.path,
        )

    from tools.stt.engine import RESTART_TASK_NAME
    try:
        result = subprocess.run(
            ["schtasks", "/run", "/tn", RESTART_TASK_NAME],
            capture_output=True, text=True, timeout=30,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except Exception as e:
        logger.error("Restart task trigger failed: %s", e)
        return problem(500, f"Restart task trigger failed: {e}", instance=request.url.path)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        logger.critical(
            "Restart task '%s' trigger FAILED rc=%d: %s — run "
            "IHIM/scripts/install-resume-watchdog.ps1 to register it",
            RESTART_TASK_NAME, result.returncode, detail,
        )
        return problem(
            500,
            f"Restart task '{RESTART_TASK_NAME}' not runnable ({detail}); "
            f"run IHIM/scripts/install-resume-watchdog.ps1",
            instance=request.url.path,
        )

    return ok(message="Restart initiated", pid=os.getpid(), port=port)
