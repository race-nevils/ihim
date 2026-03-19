"""iHIM API Server — lean orchestrator.

App setup, middleware, exception handlers, router includes, and a handful
of endpoints that don't warrant their own module (actions, health, system
monitor, cleanup, sanity, server control, VPT).
"""

# Load environment variables before any other imports
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent.parent / ".env")

from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import Response, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, Field, ValidationError
from datetime import datetime, timezone
from typing import Optional
import asyncio
import os
import sys
import json
import uuid
import psutil

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from actions.registry import ACTIONS, run_action
from api.errors import (
    problem,
    http_exception_handler,
    validation_exception_handler,
    pydantic_exception_handler,
    unhandled_exception_handler,
)


# =============================================================================
# FEATURE MODULE IMPORTS (graceful degradation)
# =============================================================================

def _try_import(label, import_fn):
    """Import a feature module; return (result, True) or (None, False)."""
    try:
        return import_fn(), True
    except ImportError as e:
        print(f"Warning: {label} not available: {e}")
        return None, False


slash_commands_router, SLASH_COMMANDS_AVAILABLE = _try_import(
    "Slash commands", lambda: __import__("api.commands.routes", fromlist=["router"]).router)
team_builder_router, TEAM_BUILDER_AVAILABLE = _try_import(
    "Team builder", lambda: __import__("api.team_builder.routes", fromlist=["router"]).router)
team_router, _TEAM_ROUTER_OK = _try_import(
    "Team router", lambda: __import__("api.team_builder.routes", fromlist=["team_router"]).team_router)
calendar_router, CALENDAR_AVAILABLE = _try_import(
    "Calendar", lambda: __import__("api.calendar.routes", fromlist=["router"]).router)
brain_router, BRAIN_AVAILABLE = _try_import(
    "Brain", lambda: __import__("api.brain.routes", fromlist=["router"]).router)
chat_router, CHAT_AVAILABLE = _try_import(
    "Chat", lambda: __import__("api.chat.routes", fromlist=["router"]).router)
health_router, HEALTH_AVAILABLE = _try_import(
    "Health", lambda: __import__("api.health.routes", fromlist=["router"]).router)
dashboard_router, DASHBOARD_AVAILABLE = _try_import(
    "Dashboard", lambda: __import__("api.dashboard.routes", fromlist=["router"]).router)
workspaces_router, WORKSPACES_AVAILABLE = _try_import(
    "Workspaces", lambda: __import__("api.workspaces.routes", fromlist=["router"]).router)
stopwatch_router, STOPWATCH_AVAILABLE = _try_import(
    "Stopwatch", lambda: __import__("api.stopwatch.routes", fromlist=["router"]).router)
feedback_router, FEEDBACK_AVAILABLE = _try_import(
    "Feedback", lambda: __import__("api.feedback.routes", fromlist=["router"]).router)
flightpath_router, FLIGHTPATH_AVAILABLE = _try_import(
    "Flight Path", lambda: __import__("api.flightpath.routes", fromlist=["router"]).router)
compliance_router, COMPLIANCE_AVAILABLE = _try_import(
    "Compliance", lambda: __import__("api.compliance.routes", fromlist=["router"]).router)
privilege_router, PRIVILEGE_AVAILABLE = _try_import(
    "Privilege", lambda: __import__("api.privilege.routes", fromlist=["router"]).router)
recorder_router, RECORDER_AVAILABLE = _try_import(
    "Recorder", lambda: __import__("api.recorder.routes", fromlist=["router"]).router)
capture_router, CAPTURE_AVAILABLE = _try_import(
    "Capture", lambda: __import__("api.capture.routes", fromlist=["router"]).router)
preferences_router, PREFERENCES_AVAILABLE = _try_import(
    "Preferences", lambda: __import__("api.preferences", fromlist=["router"]).router)
stt_router, STT_AVAILABLE = _try_import(
    "STT", lambda: __import__("api.stt.routes", fromlist=["router"]).router)
graph_router, GRAPH_AVAILABLE = _try_import(
    "Knowledge Graph", lambda: __import__("api.graph.routes", fromlist=["router"]).router)
pipeline_router, PIPELINE_AVAILABLE = _try_import(
    "Pipeline", lambda: __import__("api.pipeline.routes", fromlist=["router"]).router)
agentnode_router, AGENTNODE_AVAILABLE = _try_import(
    "agent node", lambda: __import__("api.agentnode.routes", fromlist=["router"]).router)

# System topology & health (not yet a router — functions used inline below)
try:
    from api.system import (
        get_system_topology, get_node_by_id,
        check_all_health, check_component_health,
    )
    SYSTEM_HEALTH_AVAILABLE = True
except ImportError:
    SYSTEM_HEALTH_AVAILABLE = False

# Cleanup module
try:
    from data.cleanup import (
        run_integrity_report, run_cleanup,
        cleanup_orphaned_entries, cleanup_stale_processed, cleanup_test_artifacts,
    )
    CLEANUP_AVAILABLE = True
except ImportError:
    CLEANUP_AVAILABLE = False

# Sanity check
try:
    from sanity.check import run_sanity_check, SanityReport
    SANITY_AVAILABLE = True
except ImportError:
    SANITY_AVAILABLE = False


# =============================================================================
# BOOT ID — regenerates on every server restart, used for cache busting
# =============================================================================

BOOT_ID = uuid.uuid4().hex[:8]


# =============================================================================
# APP SETUP
# =============================================================================

import logging as _logging
_logger = _logging.getLogger(__name__)

# Server start time for uptime tracking
_server_started_at = None


@asynccontextmanager
async def lifespan(app):
    """Startup/shutdown lifecycle for iHIM."""
    global _server_started_at
    import time
    _server_started_at = time.monotonic()

    # --- Startup ---
    if CALENDAR_AVAILABLE:
        try:
            from api.calendar.google_auth import get_credentials
            creds = get_credentials()
            print(f"Google Calendar: {'token valid' if creds else 'no valid token (re-auth needed)'}")
        except Exception as e:
            print(f"Google Calendar: startup token check failed: {e}")

    if STT_AVAILABLE:
        try:
            from tools.stt.engine import get_engine
            get_engine().start_listening()
            print("STT: hotkey listener auto-started")
        except Exception as e:
            print(f"STT: auto-start failed (non-fatal): {e}")

    yield

    # --- Shutdown (comprehensive cleanup) ---
    _logger.info("Server shutdown initiated — cleaning up resources...")

    # 1. Close Ollama adapter (httpx.AsyncClient)
    if CHAT_AVAILABLE:
        try:
            from api.chat.routes import ollama_adapter
            await ollama_adapter.close()
            _logger.info("Shutdown: AsyncOllamaAdapter closed")
        except Exception as e:
            _logger.warning("Shutdown: AsyncOllamaAdapter close failed: %s", e)

    # 2. Stop stt hotkey listener
    if STT_AVAILABLE:
        try:
            from tools.stt.engine import get_engine
            get_engine().stop_listening()
            _logger.info("Shutdown: STT hotkey listener stopped")
        except Exception as e:
            _logger.warning("Shutdown: STT stop failed: %s", e)

    # 4. Kill active transcription worker subprocesses
    try:
        from api.recorder.routes import _active_workers
        for rec_id, proc in list(_active_workers.items()):
            try:
                proc.kill()
                _logger.info("Shutdown: killed transcription worker for %s", rec_id)
            except Exception:
                pass
        _active_workers.clear()
    except Exception as e:
        _logger.warning("Shutdown: transcription worker cleanup failed: %s", e)

    _logger.info("Server shutdown complete")


app = FastAPI(title="iHIM", description="Your Command Center", lifespan=lifespan)


# CORS — env-configured origins (falls back to permissive for local dev)
_allowed_origins = os.environ.get("IHIM_CORS_ORIGINS", "").strip()
if _allowed_origins:
    _origins_list = [o.strip() for o in _allowed_origins.split(",") if o.strip()]
else:
    # Default: permissive for local dev
    _origins_list = [
        "http://localhost:7777",
        "http://127.0.0.1:7777",
    ]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# RFC 9457 exception handlers
app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(ValidationError, pydantic_exception_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)


# =============================================================================
# SECURITY + CACHE-CONTROL MIDDLEWARE
# =============================================================================

# CSP directives — report-only to start (won't block anything, just logs violations)
_IHIM_PORT = os.environ.get("IHIM_PORT", "7777")
_CSP_POLICY = "; ".join([
    "default-src 'self'",
    "script-src 'self' 'unsafe-inline'",       # inline scripts in index.html
    "style-src 'self' 'unsafe-inline'",         # inline styles + glassmorphism
    "img-src 'self' data: blob:",               # data URIs for icons
    "font-src 'self'",
    f"connect-src 'self' ws://localhost:{_IHIM_PORT} ws://127.0.0.1:{_IHIM_PORT}",  # WebSocket
    "frame-ancestors 'none'",
])


@app.middleware("http")
async def security_and_cache_headers(request: Request, call_next):
    """Add security headers and cache-control to all responses."""
    response = await call_next(request)

    # --- Security headers (all responses) ---
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Content-Security-Policy-Report-Only"] = _CSP_POLICY
    response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), geolocation=()"

    # --- Cache-control (API + root + static assets during dev) ---
    if request.url.path.startswith(("/api/", "/static/")) or request.url.path == "/":
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"

    return response


# =============================================================================
# REQUEST TIMEOUT SAFETY NET
# =============================================================================

_REQUEST_TIMEOUT = 30.0  # seconds — catches any remaining event loop blocks


@app.middleware("http")
async def request_timeout_middleware(request: Request, call_next):
    """30-second timeout on all HTTP requests.

    If a handler blocks the event loop beyond this, return 504 instead of
    hanging forever. WebSocket upgrades and health checks are excluded.
    """
    # Skip timeout for WebSocket upgrade requests
    if request.headers.get("upgrade", "").lower() == "websocket":
        return await call_next(request)

    try:
        return await asyncio.wait_for(call_next(request), timeout=_REQUEST_TIMEOUT)
    except asyncio.TimeoutError:
        _logger.error("Request timed out after %.0fs: %s %s", _REQUEST_TIMEOUT, request.method, request.url.path)
        return JSONResponse(
            status_code=504,
            content={
                "type": "about:blank",
                "title": "Gateway Timeout",
                "status": 504,
                "detail": f"Request timed out after {_REQUEST_TIMEOUT:.0f} seconds",
                "instance": str(request.url.path),
            },
            media_type="application/problem+json",
        )


# =============================================================================
# ROUTER INCLUDES
# =============================================================================

_routers = [
    (slash_commands_router, SLASH_COMMANDS_AVAILABLE),
    (team_builder_router, TEAM_BUILDER_AVAILABLE),
    (team_router, _TEAM_ROUTER_OK),
(calendar_router, CALENDAR_AVAILABLE),
    (brain_router, BRAIN_AVAILABLE),
    (chat_router, CHAT_AVAILABLE),
    (health_router, HEALTH_AVAILABLE),
    (dashboard_router, DASHBOARD_AVAILABLE),
    (workspaces_router, WORKSPACES_AVAILABLE),
    (stopwatch_router, STOPWATCH_AVAILABLE),
    (feedback_router, FEEDBACK_AVAILABLE),
    (flightpath_router, FLIGHTPATH_AVAILABLE),
    (compliance_router, COMPLIANCE_AVAILABLE),
    (privilege_router, PRIVILEGE_AVAILABLE),
    (recorder_router, RECORDER_AVAILABLE),
    (capture_router, CAPTURE_AVAILABLE),
    (preferences_router, PREFERENCES_AVAILABLE),
    (stt_router, STT_AVAILABLE),
    (graph_router, GRAPH_AVAILABLE),
    (pipeline_router, PIPELINE_AVAILABLE),
    (agentnode_router, AGENTNODE_AVAILABLE),
]

for rtr, available in _routers:
    if available:
        app.include_router(rtr)


# =============================================================================
# STATIC FILES & ROOT
# =============================================================================

UI_DIR = Path(__file__).parent.parent / "ui"
_static_dir = UI_DIR / "static"
if _static_dir.exists():
    app.mount("/static", StaticFiles(directory=_static_dir), name="static")
else:
    import logging as _log
    _log.getLogger(__name__).warning(f"Static directory not found: {_static_dir}")


_index_html_path = UI_DIR / "index.html"


def _build_import_map(boot_id: str) -> str:
    """Generate an importmap that cache-busts ALL JS module imports.

    Without this, only main.js gets ``?v=BOOT_ID``.  Sub-imports like
    ``./stt.js`` use bare relative paths and Chrome aggressively caches
    ES modules, ignoring no-cache headers on the module responses.
    The importmap remaps every resolved URL to a versioned one.
    """
    js_dir = _static_dir / "js"
    if not js_dir.exists():
        return ""

    imports = {}
    for js_file in sorted(js_dir.rglob("*.js")):
        rel_path = js_file.relative_to(_static_dir)
        url_path = f"/static/{rel_path.as_posix()}"
        imports[url_path] = f"{url_path}?v={boot_id}"

    if not imports:
        return ""

    map_json = json.dumps({"imports": imports}, indent=2)
    return f'<script type="importmap">\n{map_json}\n</script>'


def _inject_boot_id(html_bytes: bytes) -> bytes:
    """Replace __BOOT_ID__ and __IMPORT_MAP__ placeholders with current values."""
    text = html_bytes.decode("utf-8")
    text = text.replace("__IMPORT_MAP__", _build_import_map(BOOT_ID))
    text = text.replace("__BOOT_ID__", BOOT_ID)
    return text.encode("utf-8")


def _static_fingerprint() -> str:
    """Max mtime of all UI files — changes when any file is edited on disk.

    Scans both ``ui/static/`` (JS, CSS) and ``ui/index.html`` so the
    auto-reload polling catches HTML-only changes too.
    """
    max_mtime = 0.0
    # Static assets (JS, CSS, images)
    if _static_dir.exists():
        for root, _dirs, files in os.walk(_static_dir):
            for f in files:
                try:
                    mt = os.path.getmtime(os.path.join(root, f))
                    if mt > max_mtime:
                        max_mtime = mt
                except OSError:
                    pass
    # HTML template
    if _index_html_path.exists():
        try:
            mt = os.path.getmtime(_index_html_path)
            if mt > max_mtime:
                max_mtime = mt
        except OSError:
            pass
    return str(int(max_mtime))


@app.get("/api/boot-id")
async def get_boot_id():
    """Return boot ID + static fingerprint. Clients poll to detect any change."""
    return {"boot_id": BOOT_ID, "static_fp": _static_fingerprint()}


@app.get("/")
async def root():
    """Serve the dashboard with cache-busted static file references.

    Always reads from disk so HTML template changes are picked up instantly
    without a server restart (same as static JS/CSS files).
    """
    content = _inject_boot_id(_index_html_path.read_bytes())
    return Response(
        content=content,
        media_type="text/html",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        }
    )


# ── PWA: manifest + service worker at root scope ──

_manifest_path = UI_DIR / "manifest.json"
_sw_path = UI_DIR / "sw.js"


@app.get("/manifest.json")
async def serve_manifest():
    """W3C Web App Manifest — makes iHIM installable as PWA."""
    if not _manifest_path.exists():
        return problem(404, "manifest.json not found")
    return Response(
        content=_manifest_path.read_bytes(),
        media_type="application/manifest+json",
    )


@app.get("/sw.js")
async def serve_sw():
    """Service Worker — must be served from root scope for full control."""
    if not _sw_path.exists():
        return problem(404, "sw.js not found")
    return Response(
        content=_sw_path.read_bytes(),
        media_type="application/javascript",
        headers={"Service-Worker-Allowed": "/"},
    )


# =============================================================================
# ACTIONS
# =============================================================================

@app.get("/api/actions")
async def get_actions():
    """Get all available actions (filters out hidden ones)."""
    visible_actions = {k: v for k, v in ACTIONS.items() if not v.get("hidden", False)}
    return {"actions": visible_actions}


@app.post("/api/actions/{action_id}")
async def execute_action(action_id: str):
    """Execute an action."""
    return run_action(action_id)


@app.get("/api/health")
async def health():
    """Health check with server vitals.

    Returns uptime, memory usage, active workers, and connection counts.
    This endpoint must stay fast — it's used by the supervisor health check.
    """
    import time

    result = {"status": "ok", "name": "iHIM", "pid": os.getpid()}

    # Uptime
    if _server_started_at is not None:
        result["uptime_seconds"] = round(time.monotonic() - _server_started_at, 1)

    # Memory usage (server process)
    try:
        proc = psutil.Process(os.getpid())
        mem = proc.memory_info()
        result["memory_mb"] = round(mem.rss / (1024 * 1024), 1)
    except Exception:
        pass

    # Active transcription workers
    try:
        from api.recorder.routes import _active_workers
        result["active_transcription_workers"] = len(_active_workers)
    except Exception:
        pass

    return result


# =============================================================================
# SYSTEM MONITOR
# =============================================================================

@app.get("/api/system/stats")
async def system_stats():
    """Get current system stats (CPU, RAM)."""
    cpu_percent = psutil.cpu_percent(interval=None)
    memory = psutil.virtual_memory()
    return {
        "cpu": {
            "percent": cpu_percent,
            "cores": psutil.cpu_count(logical=False),
            "threads": psutil.cpu_count(logical=True),
        },
        "memory": {
            "percent": memory.percent,
            "used_gb": round(memory.used / (1024**3), 1),
            "total_gb": round(memory.total / (1024**3), 1),
            "available_gb": round(memory.available / (1024**3), 1),
        },
    }


WATCHER_HEARTBEAT_PATH = Path(__file__).parent.parent / "data" / "watcher_heartbeat.json"


@app.get("/api/system/watcher")
async def watcher_status():
    """Get inbox watcher status from its heartbeat file."""
    if not WATCHER_HEARTBEAT_PATH.exists():
        return {"status": "inactive", "message": "Watcher has not started", "tracked_count": 0, "settling_count": 0}

    try:
        data = json.loads(WATCHER_HEARTBEAT_PATH.read_text(encoding="utf-8"))
        ts = datetime.fromisoformat(data["timestamp"].replace("Z", "+00:00"))
        age = (datetime.now(timezone.utc) - ts).total_seconds()

        if age < 6:
            status = "healthy"
        elif age < 10:
            status = "degraded"
        else:
            status = "error"

        return {
            "status": status,
            "age_seconds": round(age, 1),
            "pid": data.get("pid"),
            "uptime_seconds": data.get("uptime_seconds", 0),
            "poll_count": data.get("poll_count", 0),
            "tracked_count": data.get("tracked_count", 0),
            "settling_count": data.get("settling_count", 0),
            "tracked_files": data.get("tracked_files", []),
            "recent_activity": data.get("recent_activity", []),
            "last_heartbeat": data.get("timestamp"),
        }
    except Exception as e:
        return {"status": "error", "message": f"Failed to read heartbeat: {str(e)}", "tracked_count": 0, "settling_count": 0}


# =============================================================================
# SYSTEM TOPOLOGY & HEALTH
# =============================================================================

@app.get("/api/system/topology")
async def system_topology(request: Request, refresh: bool = False):
    """Get the complete workspace system topology."""
    if not SYSTEM_HEALTH_AVAILABLE:
        return problem(503, "System health module not available", instance=request.url.path)
    topology = get_system_topology(refresh=refresh)
    return {"success": True, **topology.to_dict()}


@app.get("/api/system/health")
async def system_health(request: Request):
    """Get health status of all iHIM components."""
    if not SYSTEM_HEALTH_AVAILABLE:
        return problem(503, "System health module not available", instance=request.url.path)
    h = check_all_health()
    return {"success": True, **h.to_dict()}


@app.get("/api/system/node/{node_id}")
async def system_node_details(node_id: str, request: Request):
    """Get detailed info for a specific node."""
    if not SYSTEM_HEALTH_AVAILABLE:
        return problem(503, "System health module not available", instance=request.url.path)
    node = get_node_by_id(node_id)
    if not node:
        return problem(404, f"Node '{node_id}' not found", instance=request.url.path)
    h = check_component_health(node_id)
    return {
        "success": True,
        "node": {
            "id": node.id, "name": node.name, "type": node.type.value,
            "description": node.description, "file_path": node.file_path,
            "parent": node.parent, "children": node.children,
        },
        "health": {
            "status": h.status.value if h else "unknown",
            "message": h.message if h else "",
            "last_check": h.last_check if h else "",
            "last_activity": h.last_activity if h else None,
            "metrics": h.metrics if h else {},
        },
    }


# =============================================================================
# CLEANUP
# =============================================================================

@app.get("/api/cleanup/report")
async def cleanup_report(request: Request):
    """Get integrity report for the brain database."""
    if not CLEANUP_AVAILABLE:
        return problem(503, "Cleanup module not available", instance=request.url.path)
    report = run_integrity_report()
    return {"success": True, **report}


@app.post("/api/cleanup/run")
async def cleanup_run(request: Request, dry_run: bool = True):
    """Run cleanup cycle on the brain database."""
    if not CLEANUP_AVAILABLE:
        return problem(503, "Cleanup module not available", instance=request.url.path)
    result = run_cleanup(dry_run=dry_run)
    return {"success": True, **result}


@app.post("/api/cleanup/orphans")
async def cleanup_orphans(request: Request, dry_run: bool = True):
    """Clean orphaned database entries (no matching file)."""
    if not CLEANUP_AVAILABLE:
        return problem(503, "Cleanup module not available", instance=request.url.path)
    result = cleanup_orphaned_entries(dry_run=dry_run)
    return {"success": True, **result}


@app.post("/api/cleanup/stale")
async def cleanup_stale(request: Request, max_age_days: int = 7, dry_run: bool = True):
    """Clean stale files from processed folder."""
    if not CLEANUP_AVAILABLE:
        return problem(503, "Cleanup module not available", instance=request.url.path)
    result = cleanup_stale_processed(max_age_days=max_age_days, dry_run=dry_run)
    return {"success": True, **result}


@app.post("/api/cleanup/artifacts")
async def cleanup_artifacts(request: Request, dry_run: bool = True):
    """Clean test artifacts from brain folders."""
    if not CLEANUP_AVAILABLE:
        return problem(503, "Cleanup module not available", instance=request.url.path)
    result = cleanup_test_artifacts(dry_run=dry_run)
    return {"success": True, **result}


# =============================================================================
# SANITY CHECK
# =============================================================================

@app.get("/api/sanity")
async def sanity_check_status():
    """Check if sanity system is available."""
    return {
        "available": SANITY_AVAILABLE,
        "message": "Sanity check system active" if SANITY_AVAILABLE else "Sanity check not loaded",
    }


@app.post("/api/sanity/run")
async def run_sanity_check_endpoint(request: Request):
    """Run full system sanity check."""
    if not SANITY_AVAILABLE:
        return problem(503, "Sanity check system not available", instance=request.url.path)
    try:
        report = run_sanity_check(verbose=False)
        return {
            "success": True,
            "passed": report.passed,
            "errors": report.errors,
            "warnings": report.warnings,
            "timestamp": report.timestamp,
            "checks": [
                {
                    "name": c.name, "passed": c.passed, "message": c.message,
                    "severity": c.severity, "fix_hint": c.fix_hint,
                }
                for c in report.checks
            ],
            "summary": report.summary(),
        }
    except Exception as e:
        return problem(500, str(e), instance=request.url.path)


# =============================================================================
# SERVER CONTROL
# =============================================================================

@app.post("/api/server/restart")
async def restart_server():
    """Restart the iHIM server."""
    import subprocess
    import os
    import tempfile

    if sys.platform != "win32":
        return problem(501, "Only supported on Windows currently")

    ihim_dir = Path(__file__).parent.parent
    run_script = ihim_dir / "run.py"

    if not run_script.exists():
        return problem(404, f"run.py not found at {run_script}")

    python_path = str(Path(sys.executable))

    restart_log = ihim_dir / "data" / "restart.log"
    log_path = str(restart_log).replace("\\", "/")
    ps_script = f"""
$log = "{log_path}"
"[$(Get-Date)] Restart script started" | Out-File $log

Start-Sleep -Seconds 1

# Step 1: Find ALL PIDs on port 7777
$connections = Get-NetTCPConnection -LocalPort 7777 -ErrorAction SilentlyContinue
$portPids = @($connections | Where-Object {{ $_.OwningProcess -gt 0 }} | Select-Object -ExpandProperty OwningProcess -Unique)

"[$(Get-Date)] Found PIDs on port 7777: $($portPids -join ', ')" | Out-File $log -Append

# Step 2: Collect all PIDs to kill (port holders + their parents)
$killPids = @()
foreach ($pid in $portPids) {{
    $killPids += $pid
    # Walk up to find uvicorn reload watcher parent
    $parent = (Get-CimInstance Win32_Process -Filter "ProcessId = $pid" -ErrorAction SilentlyContinue).ParentProcessId
    if ($parent -and $parent -gt 4) {{
        $parentName = (Get-CimInstance Win32_Process -Filter "ProcessId = $parent" -ErrorAction SilentlyContinue).Name
        if ($parentName -match 'python') {{
            $killPids += $parent
            "[$(Get-Date)] Including parent PID $parent ($parentName)" | Out-File $log -Append
        }}
    }}
}}
$killPids = @($killPids | Sort-Object -Unique)

# Step 3: Kill process trees with taskkill (no real/zombie distinction)
if ($killPids.Count -gt 0) {{
    "[$(Get-Date)] Killing $($killPids.Count) PIDs with taskkill /T /F" | Out-File $log -Append
    foreach ($pid in $killPids) {{
        "[$(Get-Date)] taskkill /T /F /PID $pid" | Out-File $log -Append
        & taskkill /T /F /PID $pid 2>&1 | Out-File $log -Append
    }}
}} else {{
    "[$(Get-Date)] No PIDs found on port 7777" | Out-File $log -Append
}}

# Step 4: Verify port is clear (retry up to 3 times)
$maxAttempts = 3
for ($attempt = 1; $attempt -le $maxAttempts; $attempt++) {{
    Start-Sleep -Seconds 2
    $remaining = Get-NetTCPConnection -LocalPort 7777 -ErrorAction SilentlyContinue
    $remainingPids = @($remaining | Where-Object {{ $_.OwningProcess -gt 0 }} | Select-Object -ExpandProperty OwningProcess -Unique)

    if ($remainingPids.Count -eq 0) {{
        "[$(Get-Date)] Port 7777 is clear (attempt $attempt)" | Out-File $log -Append
        break
    }}

    "[$(Get-Date)] Port still held by PIDs: $($remainingPids -join ', ') (attempt $attempt/$maxAttempts)" | Out-File $log -Append
    foreach ($pid in $remainingPids) {{
        & taskkill /T /F /PID $pid 2>&1 | Out-File $log -Append
    }}
}}

# Final check
$finalCheck = Get-NetTCPConnection -LocalPort 7777 -ErrorAction SilentlyContinue
if ($finalCheck) {{
    "[$(Get-Date)] WARNING: Port 7777 still not clear after $maxAttempts attempts" | Out-File $log -Append
}}

# Step 5: Start new server
"[$(Get-Date)] Starting new server" | Out-File $log -Append
$env:IHIM_SUPERVISED = "1"
Start-Process -FilePath '{python_path}' -ArgumentList 'run.py' -WorkingDirectory '{ihim_dir}' -WindowStyle Hidden
"[$(Get-Date)] Server started successfully" | Out-File $log -Append

Start-Sleep -Seconds 2
Remove-Item -Path $MyInvocation.MyCommand.Path -Force -ErrorAction SilentlyContinue
"""

    try:
        fd, ps_path = tempfile.mkstemp(suffix=".ps1", prefix="ihim_restart_")
        with os.fdopen(fd, "w") as f:
            f.write(ps_script)

        wmi_cmd = f'powershell.exe -ExecutionPolicy Bypass -WindowStyle Hidden -File "{ps_path}"'
        subprocess.Popen(
            ["wmic", "process", "call", "create", wmi_cmd],
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return {"success": True, "message": "Server restart initiated", "pid": os.getpid()}
    except Exception as e:
        return problem(500, f"Failed to spawn restart process: {e}")


@app.get("/api/server/status")
async def server_status():
    """Get server status and uptime info."""
    import time
    result = {
        "status": "running",
        "pid": os.getpid(),
        "reload_enabled": True,
        "port": int(os.environ.get("IHIM_PORT", 7777)),
    }
    if _server_started_at is not None:
        result["uptime_seconds"] = round(time.monotonic() - _server_started_at, 1)
    return result


# =============================================================================
# VPT (VALUE PER TOKEN)
# =============================================================================

class VPTCalculateRequest(BaseModel):
    """Request model for VPT calculation."""
    success: bool = Field(..., description="Did the task succeed?")
    outcome_quality: int = Field(..., ge=1, le=5)
    efficiency_ratio: float = Field(..., ge=0.0, le=1.0)
    dead_ends: int = Field(default=0, ge=0)
    pivots: int = Field(default=0, ge=0)
    total_tokens: int = Field(..., ge=1)
    reusability: int = Field(default=3, ge=1, le=5)
    learning_value: int = Field(default=3, ge=1, le=5)


_VPT_INTERPRETATIONS = {
    "★★★★★": "Exceptional efficiency",
    "★★★★": "High value",
    "★★★": "Good, room for improvement",
    "★★": "Acceptable, review for optimization",
    "★": "Low efficiency, investigate",
}


@app.get("/api/vpt/calculate")
async def calculate_vpt_endpoint(
    request: Request,
    success: bool,
    outcome_quality: int,
    efficiency_ratio: float,
    dead_ends: int = 0,
    pivots: int = 0,
    total_tokens: int = 1,
    reusability: int = 3,
    learning_value: int = 3,
):
    """Calculate VPT (Value Per Token) score via query params."""
    from api.vpt.calculator import calculate_vpt_full

    for name, val, lo, hi in [
        ("outcome_quality", outcome_quality, 1, 5),
        ("reusability", reusability, 1, 5),
        ("learning_value", learning_value, 1, 5),
    ]:
        if val < lo or val > hi:
            return problem(400, f"{name} must be {lo}-{hi}", instance=request.url.path)
    if efficiency_ratio < 0.0 or efficiency_ratio > 1.0:
        return problem(400, "efficiency_ratio must be 0-1", instance=request.url.path)
    if total_tokens < 1:
        return problem(400, "total_tokens must be at least 1", instance=request.url.path)

    try:
        composite, vpt, rating = calculate_vpt_full(
            success=success, outcome_quality=outcome_quality,
            efficiency_ratio=efficiency_ratio, dead_ends=dead_ends,
            pivots=pivots, total_tokens=total_tokens,
            reusability=reusability, learning_value=learning_value,
        )
        return {
            "success": True,
            "composite_score": round(composite, 2),
            "vpt_score": round(vpt, 2),
            "rating": rating,
            "interpretation": _VPT_INTERPRETATIONS.get(rating, "Unknown"),
            "details": {
                "success": success, "outcome_quality": outcome_quality,
                "efficiency_ratio": efficiency_ratio, "dead_ends": dead_ends,
                "pivots": pivots, "total_tokens": total_tokens,
                "reusability": reusability, "learning_value": learning_value,
            },
        }
    except Exception as e:
        return problem(500, f"Calculation failed: {str(e)}", instance=request.url.path)


@app.post("/api/vpt/calculate")
async def calculate_vpt_post(req: VPTCalculateRequest, request: Request):
    """Calculate VPT (Value Per Token) score via POST body."""
    from api.vpt.calculator import calculate_vpt_full

    try:
        composite, vpt, rating = calculate_vpt_full(
            success=req.success, outcome_quality=req.outcome_quality,
            efficiency_ratio=req.efficiency_ratio, dead_ends=req.dead_ends,
            pivots=req.pivots, total_tokens=req.total_tokens,
            reusability=req.reusability, learning_value=req.learning_value,
        )
        return {
            "success": True,
            "composite_score": round(composite, 2),
            "vpt_score": round(vpt, 2),
            "rating": rating,
            "interpretation": _VPT_INTERPRETATIONS.get(rating, "Unknown"),
            "details": {
                "success": req.success, "outcome_quality": req.outcome_quality,
                "efficiency_ratio": req.efficiency_ratio, "dead_ends": req.dead_ends,
                "pivots": req.pivots, "total_tokens": req.total_tokens,
                "reusability": req.reusability, "learning_value": req.learning_value,
            },
        }
    except Exception as e:
        return problem(500, f"Calculation failed: {str(e)}", instance=request.url.path)


# =============================================================================
# VPT: DEBRIEF RECORD & SUMMARY
# =============================================================================

_DEBRIEFS_PATH = Path(__file__).parent.parent / "data" / "debriefs.jsonl"


class VPTRecordRequest(BaseModel):
    """Request model for recording a debrief with auto-VPT calculation."""
    task: str = Field(..., min_length=1, description="Task description")
    outcome: str = Field(..., pattern="^(success|partial|failed)$")
    total_commands: int = Field(..., ge=1)
    effective_commands: int = Field(..., ge=0)
    dead_ends: int = Field(default=0, ge=0)
    pivots: int = Field(default=0, ge=0)
    reusability: int = Field(default=3, ge=1, le=5)
    learning_value: int = Field(default=3, ge=1, le=5)
    root_cause: Optional[str] = None
    learning: Optional[str] = None
    pattern: Optional[str] = None
    scores: Optional[dict] = None
    dead_ends_detail: Optional[list] = None
    missed_signals: Optional[list] = None


@app.post("/api/vpt/record")
async def record_debrief(req: VPTRecordRequest, request: Request):
    """Record a debrief with auto-computed VPT, appended to debriefs.jsonl."""
    from api.vpt.calculator import calculate_vpt_full, estimate_tokens_from_commands

    try:
        eff_commands = min(req.effective_commands, req.total_commands)
        efficiency_ratio = eff_commands / req.total_commands
        total_tokens = estimate_tokens_from_commands(req.total_commands)
        outcome_quality = min(5, max(1, (req.scores or {}).get("overall", 3)))
        is_success = req.outcome == "success"

        composite, vpt, rating = calculate_vpt_full(
            success=is_success,
            outcome_quality=outcome_quality,
            efficiency_ratio=efficiency_ratio,
            dead_ends=req.dead_ends,
            pivots=req.pivots,
            total_tokens=total_tokens,
            reusability=req.reusability,
            learning_value=req.learning_value,
        )

        ts = datetime.now(timezone.utc).isoformat()
        entry = {
            "timestamp": ts,
            "task": req.task,
            "outcome": req.outcome,
            "metrics": {
                "total_commands": req.total_commands,
                "effective_commands": eff_commands,
                "efficiency_ratio": round(efficiency_ratio, 3),
            },
            "scores": req.scores or {},
            "vpt": {
                "composite_score": round(composite, 2),
                "score": round(vpt, 2),
                "rating": rating,
            },
            "root_cause": req.root_cause,
            "learning": req.learning,
            "pattern": req.pattern,
            "dead_ends_detail": req.dead_ends_detail,
            "missed_signals": req.missed_signals,
        }

        _DEBRIEFS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_DEBRIEFS_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + "\n")

        return {
            "success": True,
            "recorded": True,
            "timestamp": ts,
            "vpt": {
                "composite_score": round(composite, 2),
                "score": round(vpt, 2),
                "rating": rating,
            },
        }
    except Exception as e:
        return problem(500, f"Record failed: {str(e)}", instance=request.url.path)


@app.get("/api/vpt/summary")
async def vpt_summary(request: Request, limit: int = 20):
    """Read debrief trends from debriefs.jsonl."""
    if not _DEBRIEFS_PATH.exists():
        return {
            "count": 0, "shown": 0, "debriefs": [],
            "trend": "insufficient_data",
            "stats": {},
        }

    try:
        entries = []
        for line in _DEBRIEFS_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

        total = len(entries)
        shown = min(limit, total)
        recent = list(reversed(entries[-shown:])) if entries else []

        # Compute stats from entries with VPT data
        vpt_scores = [
            e.get("vpt", {}).get("score")
            for e in entries
            if e.get("vpt", {}).get("score") is not None
        ]
        success_count = sum(1 for e in entries if e.get("outcome") == "success")

        stats = {}
        if vpt_scores:
            stats = {
                "avg_vpt": round(sum(vpt_scores) / len(vpt_scores), 2),
                "min_vpt": round(min(vpt_scores), 2),
                "max_vpt": round(max(vpt_scores), 2),
                "success_rate": round(success_count / total, 3) if total else 0,
                "total_debriefs": total,
            }

        # Trend: compare first-half avg to second-half avg (5% threshold)
        trend = "insufficient_data"
        if len(vpt_scores) >= 4:
            mid = len(vpt_scores) // 2
            first_avg = sum(vpt_scores[:mid]) / mid
            second_avg = sum(vpt_scores[mid:]) / (len(vpt_scores) - mid)
            if first_avg > 0:
                change = (second_avg - first_avg) / first_avg
                if change > 0.05:
                    trend = "improving"
                elif change < -0.05:
                    trend = "declining"
                else:
                    trend = "stable"

        return {
            "count": total,
            "shown": shown,
            "debriefs": recent,
            "trend": trend,
            "stats": stats,
        }
    except Exception as e:
        return problem(500, f"Summary failed: {str(e)}", instance=request.url.path)


# =============================================================================
# HEURISTIC BANK
# =============================================================================

_HEURISTICS_PATH = Path(__file__).parent.parent / "data" / "heuristics.json"


def _load_heuristics() -> dict:
    """Load heuristics bank from JSON file."""
    if not _HEURISTICS_PATH.exists():
        return {"meta": {"last_updated": None, "total": 0, "version": "1.1.0"}, "heuristics": []}
    return json.loads(_HEURISTICS_PATH.read_text(encoding="utf-8"))


def _save_heuristics(data: dict):
    """Atomic write heuristics bank (tmp + replace)."""
    tmp_path = _HEURISTICS_PATH.with_suffix(".tmp")
    data["meta"]["last_updated"] = datetime.now(timezone.utc).isoformat()
    data["meta"]["total"] = len(data.get("heuristics", []))
    tmp_path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    tmp_path.replace(_HEURISTICS_PATH)


class HeuristicCreateRequest(BaseModel):
    """Request model for creating a new heuristic."""
    id: str = Field(..., min_length=1, pattern="^h\\d+$")
    trigger: str = Field(..., min_length=1)
    action: str = Field(..., min_length=1)
    pattern: str = Field(default="uncategorized")
    status: str = Field(default="banked", pattern="^(active|banked)$")
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)


class HeuristicFireRequest(BaseModel):
    """Optional body for firing a heuristic with a confidence score."""
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)


@app.get("/api/vpt/heuristics")
async def list_heuristics(status: Optional[str] = None):
    """List all heuristics, optionally filtered by status."""
    data = _load_heuristics()
    heuristics = data.get("heuristics", [])

    if status:
        heuristics = [h for h in heuristics if h.get("status") == status]

    return {
        "count": len(heuristics),
        "total": data["meta"]["total"],
        "heuristics": heuristics,
    }


@app.post("/api/vpt/heuristics")
async def create_heuristic(req: HeuristicCreateRequest, request: Request):
    """Add a new heuristic to the bank."""
    data = _load_heuristics()
    existing_ids = {h["id"] for h in data.get("heuristics", [])}

    if req.id in existing_ids:
        return problem(409, f"Heuristic '{req.id}' already exists", instance=request.url.path)

    new_h = {
        "id": req.id,
        "trigger": req.trigger,
        "action": req.action,
        "fire_count": 0,
        "last_fired": None,
        "status": req.status,
        "pattern": req.pattern,
        "confidence": req.confidence,
        "miss_count": 0,
    }
    data["heuristics"].append(new_h)
    _save_heuristics(data)

    return {"success": True, "created": new_h}


@app.patch("/api/vpt/heuristics/{heuristic_id}/fire")
async def fire_heuristic(heuristic_id: str, request: Request):
    """Increment fire_count for a heuristic with optional confidence score.

    Accepts optional JSON body: {"confidence": 0.85}
    - If confidence provided: updates running average
    - If not provided: increments fire_count only (backward compat)
    - Promotion: fire_count >= 3 AND (confidence is None OR >= 0.6)
    - Demotion: active + confidence < 0.4 after 3+ fires → demoted to banked
    """
    data = _load_heuristics()
    target = None
    for h in data.get("heuristics", []):
        if h["id"] == heuristic_id:
            target = h
            break

    if target is None:
        return problem(404, f"Heuristic '{heuristic_id}' not found", instance=request.url.path)

    # Parse optional confidence from body
    fire_confidence = None
    try:
        body = await request.json()
        req = HeuristicFireRequest(**body)
        fire_confidence = req.confidence
    except Exception:
        pass  # No body or invalid — backward compat, just increment

    target["fire_count"] = target.get("fire_count", 0) + 1
    target["last_fired"] = datetime.now(timezone.utc).isoformat()

    # Update confidence running average if score provided
    if fire_confidence is not None:
        old_confidence = target.get("confidence")
        old_count = target["fire_count"] - 1  # count before this fire
        if old_confidence is None or old_count == 0:
            target["confidence"] = fire_confidence
        else:
            target["confidence"] = round(
                ((old_confidence * old_count) + fire_confidence) / target["fire_count"], 4
            )

    confidence = target.get("confidence")

    # Promotion: banked → active when fire_count >= 3 AND confidence qualifies
    promoted = False
    if target.get("status") == "banked" and target["fire_count"] >= 3:
        if confidence is None or confidence >= 0.6:
            target["status"] = "active"
            promoted = True

    # Demotion: active → banked when confidence drops below 0.4 after 3+ fires
    demoted = False
    if (target.get("status") == "active"
            and confidence is not None
            and confidence < 0.4
            and target["fire_count"] >= 3):
        target["status"] = "banked"
        demoted = True

    _save_heuristics(data)

    return {
        "success": True,
        "id": heuristic_id,
        "fire_count": target["fire_count"],
        "last_fired": target["last_fired"],
        "confidence": target.get("confidence"),
        "miss_count": target.get("miss_count", 0),
        "status": target["status"],
        "promoted": promoted,
        "demoted": demoted,
    }


@app.patch("/api/vpt/heuristics/{heuristic_id}/miss")
async def miss_heuristic(heuristic_id: str, request: Request):
    """Record a miss for a heuristic (was applicable but led to wrong outcome).

    Increments miss_count and recalculates confidence downward.
    Formula: confidence = fire_count / (fire_count + miss_count)
    """
    data = _load_heuristics()
    target = None
    for h in data.get("heuristics", []):
        if h["id"] == heuristic_id:
            target = h
            break

    if target is None:
        return problem(404, f"Heuristic '{heuristic_id}' not found", instance=request.url.path)

    target["miss_count"] = target.get("miss_count", 0) + 1

    # Recalculate confidence based on hit/miss ratio
    fire_count = target.get("fire_count", 0)
    miss_count = target["miss_count"]
    if fire_count + miss_count > 0:
        target["confidence"] = round(fire_count / (fire_count + miss_count), 4)

    # Demotion check: active → banked when confidence < 0.4 after 3+ fires
    demoted = False
    confidence = target.get("confidence")
    total_events = fire_count + miss_count
    if (target.get("status") == "active"
            and confidence is not None
            and confidence < 0.4
            and total_events >= 3):
        target["status"] = "banked"
        demoted = True

    _save_heuristics(data)

    return {
        "success": True,
        "id": heuristic_id,
        "fire_count": fire_count,
        "miss_count": target["miss_count"],
        "confidence": target.get("confidence"),
        "status": target["status"],
        "demoted": demoted,
    }


# =============================================================================
# BRAIN PROCESSING METRICS
# =============================================================================

_BRAIN_METRICS_PATH = Path(__file__).parent.parent / "data" / "brain_metrics.jsonl"


@app.get("/api/brain/metrics")
async def brain_metrics(request: Request):
    """Read brain processing health from brain_metrics.jsonl."""
    if not _BRAIN_METRICS_PATH.exists():
        return {"total_entries": 0, "recent": [], "stats": {}}

    try:
        entries = []
        for line in _BRAIN_METRICS_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

        total = len(entries)
        recent = entries[-10:] if entries else []

        if not entries:
            return {"total_entries": 0, "recent": [], "stats": {}}

        # Aggregate timing stats
        def _avg(vals):
            return round(sum(vals) / len(vals)) if vals else 0

        def _p95(vals):
            if not vals:
                return 0
            s = sorted(vals)
            idx = int(len(s) * 0.95)
            return s[min(idx, len(s) - 1)]

        dedup_ms = [e["timing_ms"]["dedup"] for e in entries if "timing_ms" in e and "dedup" in e.get("timing_ms", {})]
        classify_ms = [e["timing_ms"]["classify"] for e in entries if "timing_ms" in e and "classify" in e.get("timing_ms", {})]
        store_ms = [e["timing_ms"]["store"] for e in entries if "timing_ms" in e and "store" in e.get("timing_ms", {})]
        calendar_ms = [e["timing_ms"]["calendar"] for e in entries if "timing_ms" in e and "calendar" in e.get("timing_ms", {})]
        total_ms = [e["timing_ms"]["total"] for e in entries if "timing_ms" in e and "total" in e.get("timing_ms", {})]

        # Error rate
        error_count = sum(1 for e in entries if e.get("action") == "error" or e.get("error"))
        error_rate = round(error_count / total, 3) if total else 0

        # Category distribution
        categories = {}
        for e in entries:
            cat = e.get("category")
            if cat:
                categories[cat] = categories.get(cat, 0) + 1

        # Action breakdown
        actions = {}
        for e in entries:
            act = e.get("action")
            if act:
                actions[act] = actions.get(act, 0) + 1

        stats = {
            "avg_dedup_ms": _avg(dedup_ms),
            "avg_classify_ms": _avg(classify_ms),
            "avg_store_ms": _avg(store_ms),
            "avg_calendar_ms": _avg(calendar_ms),
            "avg_total_ms": _avg(total_ms),
            "p95_classify_ms": _p95(classify_ms),
            "error_rate": error_rate,
            "category_distribution": categories,
            "actions": actions,
        }

        return {"total_entries": total, "recent": recent, "stats": stats}

    except Exception as e:
        return problem(500, f"Metrics read failed: {str(e)}", instance=request.url.path)
