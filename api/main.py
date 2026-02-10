"""iHIM API Server"""
# Load environment variables before any other imports
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent.parent / ".env")

from fastapi import FastAPI, Request, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, conlist, field_validator, ValidationError
from pathlib import Path
from typing import Optional, List
from datetime import datetime, timezone
import sys
import json
import uuid
import psutil
import re

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from actions.registry import ACTIONS, run_action
from team import route_prompt, spawn_agent_team, collapse_team
from team.state import get_team_state, reset_team_state
from team.spawner import get_team_status, collect_results
from api.flightpath.scanner import scan_project, get_directory_graph

# Import feedback system components
try:
    from team.feedback.aggregator import aggregate_session, get_session_feedback, save_session_feedback
    from team.feedback.metrics import get_metrics, update_metrics
    from team.feedback.processor import process_session_results, save_feedback_entry
    from team.feedback.optimizer import generate_optimizations, get_optimizations_for_agent

    FEEDBACK_AVAILABLE = True
except ImportError as e:
    print(f"Warning: Feedback system not available: {e}")
    FEEDBACK_AVAILABLE = False

# Import sanity check system
try:
    from sanity.check import run_sanity_check, SanityReport
    SANITY_AVAILABLE = True
except ImportError as e:
    print(f"Warning: Sanity check system not available: {e}")
    SANITY_AVAILABLE = False

# Import system topology and health
try:
    from api.system import (
        get_system_topology,
        get_node_by_id,
        check_all_health,
        check_component_health,
    )
    SYSTEM_HEALTH_AVAILABLE = True
except ImportError as e:
    print(f"Warning: System health module not available: {e}")
    SYSTEM_HEALTH_AVAILABLE = False

# Import cleanup module
try:
    from data.cleanup import (
        run_integrity_report,
        run_cleanup,
        cleanup_orphaned_entries,
        cleanup_stale_processed,
        cleanup_test_artifacts
    )
    CLEANUP_AVAILABLE = True
except ImportError as e:
    print(f"Warning: Cleanup module not available: {e}")
    CLEANUP_AVAILABLE = False

# Import commands module
try:
    from api.commands.routes import router as slash_commands_router
    SLASH_COMMANDS_AVAILABLE = True
except ImportError as e:
    print(f"Warning: Slash commands module not available: {e}")
    SLASH_COMMANDS_AVAILABLE = False

# Import team builder module
try:
    from api.team_builder.routes import router as team_builder_router
    TEAM_BUILDER_AVAILABLE = True
except ImportError as e:
    print(f"Warning: Team builder module not available: {e}")
    TEAM_BUILDER_AVAILABLE = False

# Import terminal module (Mission Control)
try:
    from api.terminal.routes import router as terminal_router
    TERMINAL_AVAILABLE = True
except ImportError as e:
    print(f"Warning: Terminal module not available: {e}")
    TERMINAL_AVAILABLE = False

# Import agents module (Agent Workshop)
try:
    from api.agents.routes import router as agents_router
    AGENTS_AVAILABLE = True
except ImportError as e:
    print(f"Warning: Agents module not available: {e}")
    AGENTS_AVAILABLE = False


# Import calendar module (Google Calendar)
try:
    from api.calendar.routes import router as calendar_router
    CALENDAR_AVAILABLE = True
except ImportError as e:
    print(f"Warning: Calendar module not available: {e}")
    CALENDAR_AVAILABLE = False

# Import brain module (Second Brain Search & Stats)
try:
    from api.brain.routes import router as brain_router
    BRAIN_AVAILABLE = True
except ImportError as e:
    print(f"Warning: Brain module not available: {e}")
    BRAIN_AVAILABLE = False

# Import chat module (Brain Chat with RAG)
try:
    from api.chat.routes import router as chat_router
    CHAT_AVAILABLE = True
except ImportError as e:
    print(f"Warning: Chat module not available: {e}")
    CHAT_AVAILABLE = False

# Import health module (Health Dashboard)
try:
    from api.health.routes import router as health_router
    HEALTH_AVAILABLE = True
except ImportError as e:
    print(f"Warning: Health module not available: {e}")
    HEALTH_AVAILABLE = False

# Import dashboard module (Vault Dashboard)
try:
    from api.dashboard.routes import router as dashboard_router
    DASHBOARD_AVAILABLE = True
except ImportError as e:
    print(f"Warning: Dashboard module not available: {e}")
    DASHBOARD_AVAILABLE = False

app = FastAPI(title="iHIM", description="Your Command Center")

# CORS middleware for Chrome extension access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins (including Chrome extensions)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =============================================================================
# STANDARDIZED ERROR RESPONSE HELPER
# =============================================================================
def error_response(message: str, status_code: int = 400, error_type: str = "ValidationError") -> JSONResponse:
    """
    Create a standardized error response.

    Args:
        message: Human-readable error message
        status_code: HTTP status code (default 400)
        error_type: Error type identifier (default ValidationError)

    Returns:
        JSONResponse with consistent error structure
    """
    return JSONResponse(
        status_code=status_code,
        content={
            "success": False,
            "error": {
                "type": error_type,
                "message": message
            }
        }
    )


# =============================================================================
# GLOBAL EXCEPTION HANDLER FOR VALIDATION ERRORS
# =============================================================================
@app.exception_handler(ValidationError)
async def validation_exception_handler(request: Request, exc: ValidationError):
    """
    Handle Pydantic validation errors with standardized response.

    Prevents leaking internal structure and provides clear error messages.
    """
    errors = exc.errors()
    # Format the first error for clarity
    if errors:
        first_error = errors[0]
        field = " -> ".join(str(loc) for loc in first_error["loc"])
        message = f"{field}: {first_error['msg']}"
    else:
        message = "Invalid request data"

    return error_response(message, status_code=422, error_type="ValidationError")


# =============================================================================
# CACHE-CONTROL MIDDLEWARE
# =============================================================================
@app.middleware("http")
async def add_cache_control_headers(request: Request, call_next):
    """
    Add cache-control headers to prevent stale data.

    Dynamic API endpoints get no-cache headers to ensure fresh data.
    Static assets can still be cached by the browser.
    """
    response = await call_next(request)

    # No-cache for API endpoints and root HTML (prevents stale page after restart)
    if request.url.path.startswith("/api/") or request.url.path == "/":
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"

    return response


# Include the commands router (enhanced module)
if SLASH_COMMANDS_AVAILABLE:
    app.include_router(slash_commands_router)

# Include the team builder router
if TEAM_BUILDER_AVAILABLE:
    app.include_router(team_builder_router)

# Include the terminal router (Mission Control)
if TERMINAL_AVAILABLE:
    app.include_router(terminal_router)

# Include the agents router (Agent Workshop)
if AGENTS_AVAILABLE:
    app.include_router(agents_router)


# Include the calendar router (Google Calendar)
if CALENDAR_AVAILABLE:
    app.include_router(calendar_router)

# Include the brain router (Second Brain Search)
if BRAIN_AVAILABLE:
    app.include_router(brain_router)

# Include the chat router (Brain Chat with RAG)
if CHAT_AVAILABLE:
    app.include_router(chat_router)

# Include the health router (Health Dashboard)
if HEALTH_AVAILABLE:
    app.include_router(health_router)

# Include the dashboard router (Vault Dashboard)
if DASHBOARD_AVAILABLE:
    app.include_router(dashboard_router)


# Request models
class SpawnRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=5000, description="Task description")
    project: str = Field(default="workspace", min_length=1, max_length=100)
    agents: Optional[List[str]] = Field(None, min_items=1, max_items=20, description="Custom agent list (None = default 5 dev agents)")
    team_name: Optional[str] = Field(None, min_length=1, max_length=100, description="Name for custom teams")

    @field_validator('agents')
    @classmethod
    def validate_agent_names(cls, v):
        """Validate agent names to prevent injection attacks."""
        if v is None:
            return v
        pattern = re.compile(r'^[a-zA-Z0-9_-]+$')
        for agent in v:
            if not pattern.match(agent):
                raise ValueError(f"Invalid agent name '{agent}'. Only alphanumeric, dash, and underscore allowed.")
            if len(agent) > 50:
                raise ValueError(f"Agent name '{agent}' exceeds max length of 50 characters.")
        return v



# Serve static files
UI_DIR = Path(__file__).parent.parent / "ui"
app.mount("/static", StaticFiles(directory=UI_DIR / "static"), name="static")


@app.get("/")
async def root():
    """Serve the dashboard (no-cache to prevent stale page after restart)"""
    html_path = UI_DIR / "index.html"
    content = html_path.read_bytes()
    return Response(
        content=content,
        media_type="text/html",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        }
    )


@app.get("/api/actions")
async def get_actions():
    """Get all available actions (filters out hidden ones)"""
    visible_actions = {k: v for k, v in ACTIONS.items() if not v.get("hidden", False)}
    return {"actions": visible_actions}


@app.post("/api/actions/{action_id}")
async def execute_action(action_id: str):
    """Execute an action"""
    result = run_action(action_id)
    return result


@app.get("/api/health")
async def health():
    """Health check"""
    return {"status": "ok", "name": "iHIM"}


# =============================================================================
# SYSTEM MONITOR ENDPOINTS
# =============================================================================

@app.get("/api/system/stats")
async def system_stats():
    """
    Get current system stats (CPU, RAM).

    Returns lightweight metrics for the system monitor widget.
    """
    cpu_percent = psutil.cpu_percent(interval=None)
    memory = psutil.virtual_memory()

    return {
        "cpu": {
            "percent": cpu_percent,
            "cores": psutil.cpu_count(logical=False),
            "threads": psutil.cpu_count(logical=True)
        },
        "memory": {
            "percent": memory.percent,
            "used_gb": round(memory.used / (1024**3), 1),
            "total_gb": round(memory.total / (1024**3), 1),
            "available_gb": round(memory.available / (1024**3), 1)
        }
    }


WATCHER_HEARTBEAT_PATH = Path(__file__).parent.parent / "data" / "watcher_heartbeat.json"


@app.get("/api/system/watcher")
async def watcher_status():
    """
    Get inbox watcher status from its heartbeat file.

    Health is computed from heartbeat freshness:
    - <6s: healthy (watcher polls every 2s)
    - 6-10s: degraded (heartbeat is slow)
    - >10s: error (watcher likely crashed)
    - File missing: inactive (never started)
    """
    if not WATCHER_HEARTBEAT_PATH.exists():
        return {
            "status": "inactive",
            "message": "Watcher has not started",
            "tracked_count": 0,
            "settling_count": 0,
        }

    try:
        data = json.loads(WATCHER_HEARTBEAT_PATH.read_text(encoding="utf-8"))
        ts = datetime.fromisoformat(data["timestamp"].replace("Z", "+00:00"))
        age = (datetime.now(timezone.utc) - ts).total_seconds()

        if age < 6:
            health = "healthy"
        elif age < 10:
            health = "degraded"
        else:
            health = "error"

        return {
            "status": health,
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
        return {
            "status": "error",
            "message": f"Failed to read heartbeat: {str(e)}",
            "tracked_count": 0,
            "settling_count": 0,
        }


# =============================================================================
# SYSTEM TOPOLOGY & HEALTH ENDPOINTS
# =============================================================================

@app.get("/api/system/topology")
async def system_topology(refresh: bool = False):
    """
    Get the complete workspace system topology.

    Returns all components (nodes) and their connections (edges)
    for the Flight Path visualization.

    Query params:
        refresh: If true, rebuild the topology from scratch (bypass cache)
    """
    if not SYSTEM_HEALTH_AVAILABLE:
        return {"error": "System health module not available"}

    topology = get_system_topology(refresh=refresh)
    return {
        "success": True,
        **topology.to_dict()
    }


@app.get("/api/system/health")
async def system_health():
    """
    Get health status of all iHIM components.

    Returns current status (healthy/degraded/error/inactive) for each
    component, with metrics and error messages.
    """
    if not SYSTEM_HEALTH_AVAILABLE:
        return {"error": "System health module not available"}

    health = check_all_health()
    return {
        "success": True,
        **health.to_dict()
    }


@app.get("/api/system/node/{node_id}")
async def system_node_details(node_id: str):
    """
    Get detailed info for a specific node.

    Combines topology info with current health status.
    """
    if not SYSTEM_HEALTH_AVAILABLE:
        return {"error": "System health module not available"}

    node = get_node_by_id(node_id)
    if not node:
        return {"error": f"Node '{node_id}' not found"}

    health = check_component_health(node_id)

    return {
        "success": True,
        "node": {
            "id": node.id,
            "name": node.name,
            "type": node.type.value,
            "description": node.description,
            "file_path": node.file_path,
            "parent": node.parent,
            "children": node.children,
        },
        "health": {
            "status": health.status.value if health else "unknown",
            "message": health.message if health else "",
            "last_check": health.last_check if health else "",
            "last_activity": health.last_activity if health else None,
            "metrics": health.metrics if health else {},
        }
    }


# =============================================================================
# CLEANUP ENDPOINTS (Database Maintenance)
# =============================================================================

@app.get("/api/cleanup/report")
async def cleanup_report():
    """
    Get integrity report for the brain database.

    Returns counts of entries, issues found (orphans, duplicates, stale files).
    """
    if not CLEANUP_AVAILABLE:
        return {"error": "Cleanup module not available"}

    report = run_integrity_report()
    return {"success": True, **report}


@app.post("/api/cleanup/run")
async def cleanup_run(dry_run: bool = True):
    """
    Run cleanup cycle on the brain database.

    Args:
        dry_run: If true (default), only report what would be done.
                 Set to false to actually delete.
    """
    if not CLEANUP_AVAILABLE:
        return {"error": "Cleanup module not available"}

    result = run_cleanup(dry_run=dry_run)
    return {"success": True, **result}


@app.post("/api/cleanup/orphans")
async def cleanup_orphans(dry_run: bool = True):
    """Clean orphaned database entries (no matching file)."""
    if not CLEANUP_AVAILABLE:
        return {"error": "Cleanup module not available"}

    result = cleanup_orphaned_entries(dry_run=dry_run)
    return {"success": True, **result}


@app.post("/api/cleanup/stale")
async def cleanup_stale(max_age_days: int = 7, dry_run: bool = True):
    """Clean stale files from processed folder."""
    if not CLEANUP_AVAILABLE:
        return {"error": "Cleanup module not available"}

    result = cleanup_stale_processed(max_age_days=max_age_days, dry_run=dry_run)
    return {"success": True, **result}


@app.post("/api/cleanup/artifacts")
async def cleanup_artifacts(dry_run: bool = True):
    """Clean test artifacts from brain folders."""
    if not CLEANUP_AVAILABLE:
        return {"error": "Cleanup module not available"}

    result = cleanup_test_artifacts(dry_run=dry_run)
    return {"success": True, **result}


# =============================================================================
# TEAM ENDPOINTS (Agent Team System)
# =============================================================================

@app.post("/api/team/spawn")
async def spawn_team(request: SpawnRequest):
    """
    Spawn an agent team.

    Takes one prompt, morphs it into tailored prompts per agent,
    opens CLI tabs in one Windows Terminal window.

    Args:
        prompt: The task description
        project: Project name (default: workspace)
        agents: Custom agent list (default: 5 software dev agents)
        team_name: Name for the team (for custom teams)

    Uses your the agent harness Max subscription - no extra API costs.
    """
    # Route the prompt to agents (custom list or default 5)
    routed_prompts = route_prompt(
        prompt=request.prompt,
        project=request.project,
        agents=request.agents  # None = default 5 dev agents
    )

    # Spawn the agents
    feature_desc = request.team_name or request.prompt[:50]
    result = spawn_agent_team(routed_prompts, feature_description=feature_desc)

    # Update state
    if result["success"]:
        state = get_team_state()
        state.spawn(
            prompt=request.prompt,
            project=request.project,
            agents=list(routed_prompts.keys())
        )

    return result


# Request model for custom team spawn
class CustomSpawnRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=5000, description="Task description")
    team_type: str = Field(default="auto", min_length=1, max_length=50, pattern=r'^[a-zA-Z0-9_-]+$', description="auto, project, research, custom")
    team_size: int = Field(default=3, ge=1, le=20, description="Number of agents (1-20)")
    project: str = Field(default="workspace", min_length=1, max_length=100)
    options: Optional[dict] = None


@app.post("/api/team/spawn-custom")
async def spawn_custom_team(request: CustomSpawnRequest):
    """
    Spawn a custom agent team based on team type and size.

    This is the bridge endpoint for the Team Builder UI.
    Maps team_type to appropriate template and spawns agents.

    Args:
        prompt: Task description
        team_type: auto, project, research, or custom
        team_size: Number of agents (2-10)
        project: Project name
        options: Additional config (blackboard, feedback, parallel)

    Returns:
        Spawn status with session info.
    """
    # Map team types to templates
    template_map = {
        "auto": "software-dev",  # Default to software dev for now
        "project": "project-management",
        "research": "research",
        "custom": "software-dev"  # Custom also defaults to software-dev
    }

    template_id = template_map.get(request.team_type, "software-dev")

    # If team_builder is available, use it
    if TEAM_BUILDER_AVAILABLE:
        try:
            from api.team_builder.routes import spawn_team, SpawnTeamRequest

            spawn_request = SpawnTeamRequest(
                template_id=template_id,
                task_description=request.prompt,
                project=request.project
            )

            result = await spawn_team(spawn_request)
            return result
        except Exception as e:
            # Fall back to basic spawn
            pass

    # Fallback: use basic route_prompt with software-dev team
    routed_prompts = route_prompt(
        prompt=request.prompt,
        project=request.project
    )

    # Limit to requested team size
    if len(routed_prompts) > request.team_size:
        agents_to_keep = list(routed_prompts.keys())[:request.team_size]
        routed_prompts = {k: v for k, v in routed_prompts.items() if k in agents_to_keep}

    result = spawn_agent_team(routed_prompts, feature_description=request.prompt[:50])

    if result["success"]:
        state = get_team_state()
        state.spawn(
            prompt=request.prompt,
            project=request.project,
            agents=list(routed_prompts.keys())
        )

    return result


@app.get("/api/team/status")
async def team_status():
    """Get current team status."""
    return get_team_status()


@app.post("/api/team/collapse")
async def collapse_team_endpoint():
    """Collapse the team - close all agent tabs."""
    result = collapse_team()
    if result["success"]:
        state = get_team_state()
        state.collapse()
    return result


@app.get("/api/team/results")
async def team_results():
    """Get all agent results."""
    return collect_results()


@app.post("/api/team/reset")
async def reset_team():
    """Reset team state and clear all files."""
    reset_team_state()
    return {"success": True, "message": "Team state reset"}


# =============================================================================
# FEEDBACK SYSTEM ENDPOINTS (Self-Improvement Loop)
# =============================================================================

class ProcessFeedbackRequest(BaseModel):
    """Request model for processing session feedback."""
    session_id: str = Field(..., min_length=1, max_length=100, pattern=r'^[a-zA-Z0-9_-]+$')
    prompt: str = Field(default="", max_length=5000)


@app.get("/api/feedback/status")
async def feedback_status():
    """Check if feedback system is available."""
    return {
        "available": FEEDBACK_AVAILABLE,
        "message": "Feedback system active" if FEEDBACK_AVAILABLE else "Feedback system not loaded"
    }


@app.get("/api/feedback/session/{session_id}")
async def get_session_feedback_endpoint(session_id: str):
    """
    Get aggregated feedback for a specific spawn session.

    Returns what worked, what failed, coordination gaps, and learnings.
    """
    if not FEEDBACK_AVAILABLE:
        return {"error": "Feedback system not available"}

    feedback = get_session_feedback(session_id)
    if feedback:
        return {"success": True, "feedback": feedback.model_dump(mode="json")}
    return {"success": False, "message": f"No feedback found for session {session_id}"}


@app.post("/api/feedback/process")
async def process_feedback(request: ProcessFeedbackRequest):
    """
    Process agent results for a session and generate feedback.

    Call this after agents complete to:
    1. Parse all result files
    2. Aggregate into session feedback
    3. Update metrics
    4. Generate prompt optimizations

    Returns the aggregated feedback.
    """
    if not FEEDBACK_AVAILABLE:
        return {"error": "Feedback system not available"}

    try:
        # Process all results
        entries = process_session_results(request.session_id)

        # Save individual feedback entries
        for entry in entries:
            save_feedback_entry(entry)

        # Aggregate session feedback
        session_feedback = aggregate_session(request.session_id, request.prompt)
        save_session_feedback(session_feedback)

        # Update metrics
        metrics = update_metrics(session_feedback)

        # Generate new optimizations based on feedback
        optimizations = generate_optimizations(session_feedback)

        return {
            "success": True,
            "session_id": request.session_id,
            "feedback": session_feedback.model_dump(mode="json"),
            "metrics": metrics.model_dump(mode="json"),
            "new_optimizations": len(optimizations)
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/api/feedback/optimizations")
async def get_optimizations():
    """
    Get all current prompt optimizations.

    These are learnings that will be injected into future agent prompts.
    """
    if not FEEDBACK_AVAILABLE:
        return {"error": "Feedback system not available"}

    try:
        from team.feedback.optimizer import load_optimizations
        optimizations = load_optimizations()
        return {
            "count": len(optimizations),
            "optimizations": [opt.model_dump(mode="json") for opt in optimizations]
        }
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/feedback/optimizations/{agent}")
async def get_agent_optimizations(agent: str):
    """
    Get optimizations that apply to a specific agent.

    Returns both agent-specific and universal optimizations.
    """
    if not FEEDBACK_AVAILABLE:
        return {"error": "Feedback system not available"}

    try:
        optimizations = get_optimizations_for_agent(agent)
        return {
            "agent": agent,
            "count": len(optimizations),
            "optimizations": [opt.model_dump(mode="json") for opt in optimizations]
        }
    except Exception as e:
        return {"error": str(e)}




# =============================================================================
# STOPWATCH ENDPOINTS (Multiple Independent Stopwatches)
# =============================================================================

STOPWATCHES_FILE = Path(__file__).parent.parent / "data" / "stopwatches.json"


class StopwatchCreate(BaseModel):
    """Request model for creating a new stopwatch."""
    label: Optional[str] = Field(None, max_length=100, description="Optional name for the stopwatch")


class StopwatchUpdate(BaseModel):
    """Request model for updating a stopwatch."""
    label: Optional[str] = Field(None, max_length=100)


def load_stopwatches() -> list:
    """Load stopwatches from JSON file."""
    if STOPWATCHES_FILE.exists():
        try:
            data = json.loads(STOPWATCHES_FILE.read_text(encoding="utf-8"))
            return data.get("stopwatches", [])
        except Exception as e:
            print(f"Warning: Failed to load stopwatches: {e}")
    return []


def save_stopwatches(stopwatches: list):
    """Save stopwatches to JSON file."""
    STOPWATCHES_FILE.parent.mkdir(parents=True, exist_ok=True)
    STOPWATCHES_FILE.write_text(
        json.dumps({"stopwatches": stopwatches}, indent=2),
        encoding="utf-8"
    )


@app.get("/api/stopwatches")
async def get_stopwatches():
    """
    Get all stopwatches.

    Returns all stopwatches with their current state.
    The frontend should calculate current elapsed time for running stopwatches
    using: elapsed_ms + (now - started_at) if is_running is true.
    """
    return {"stopwatches": load_stopwatches()}


@app.post("/api/stopwatches", status_code=201)
async def create_stopwatch(stopwatch: StopwatchCreate = None):
    """
    Create a new stopwatch (spawn one).

    Creates a stopwatch in stopped state with 0 elapsed time.
    Frontend can immediately start it if desired.
    """
    stopwatches = load_stopwatches()
    now = datetime.utcnow().isoformat() + "Z"

    new_stopwatch = {
        "id": str(uuid.uuid4())[:8],
        "label": (stopwatch.label if stopwatch else None) or "",
        "elapsed_ms": 0,
        "is_running": False,
        "started_at": None,
        "created_at": now
    }
    stopwatches.append(new_stopwatch)
    save_stopwatches(stopwatches)
    return {"success": True, "stopwatch": new_stopwatch}


@app.get("/api/stopwatches/{stopwatch_id}")
async def get_stopwatch(stopwatch_id: str):
    """Get a single stopwatch by ID."""
    stopwatches = load_stopwatches()
    for sw in stopwatches:
        if sw["id"] == stopwatch_id:
            return {"success": True, "stopwatch": sw}
    return {"success": False, "message": "Stopwatch not found"}


@app.put("/api/stopwatches/{stopwatch_id}")
async def update_stopwatch(stopwatch_id: str, update: StopwatchUpdate):
    """Update a stopwatch's label."""
    stopwatches = load_stopwatches()
    for sw in stopwatches:
        if sw["id"] == stopwatch_id:
            if update.label is not None:
                sw["label"] = update.label
            save_stopwatches(stopwatches)
            return {"success": True, "stopwatch": sw}
    return {"success": False, "message": "Stopwatch not found"}


@app.post("/api/stopwatches/{stopwatch_id}/start")
async def start_stopwatch(stopwatch_id: str):
    """
    Start a stopwatch.

    Sets is_running=true and records started_at timestamp.
    If already running, returns current state without error.
    """
    stopwatches = load_stopwatches()
    for sw in stopwatches:
        if sw["id"] == stopwatch_id:
            if not sw["is_running"]:
                sw["is_running"] = True
                sw["started_at"] = datetime.utcnow().isoformat() + "Z"
                save_stopwatches(stopwatches)
            return {"success": True, "stopwatch": sw}
    return {"success": False, "message": "Stopwatch not found"}


@app.post("/api/stopwatches/{stopwatch_id}/stop")
async def stop_stopwatch(stopwatch_id: str):
    """
    Stop a stopwatch.

    Calculates elapsed time since started_at, adds to elapsed_ms,
    sets is_running=false and clears started_at.
    If already stopped, returns current state without error.
    """
    stopwatches = load_stopwatches()
    for sw in stopwatches:
        if sw["id"] == stopwatch_id:
            if sw["is_running"] and sw["started_at"]:
                # Calculate elapsed since started
                started = datetime.fromisoformat(sw["started_at"].rstrip("Z"))
                now = datetime.utcnow()
                additional_ms = int((now - started).total_seconds() * 1000)
                sw["elapsed_ms"] = sw.get("elapsed_ms", 0) + additional_ms
                sw["is_running"] = False
                sw["started_at"] = None
                save_stopwatches(stopwatches)
            return {"success": True, "stopwatch": sw}
    return {"success": False, "message": "Stopwatch not found"}


@app.post("/api/stopwatches/{stopwatch_id}/reset")
async def reset_stopwatch(stopwatch_id: str):
    """
    Reset a stopwatch to zero.

    Stops the stopwatch if running and resets elapsed_ms to 0.
    """
    stopwatches = load_stopwatches()
    for sw in stopwatches:
        if sw["id"] == stopwatch_id:
            sw["elapsed_ms"] = 0
            sw["is_running"] = False
            sw["started_at"] = None
            save_stopwatches(stopwatches)
            return {"success": True, "stopwatch": sw}
    return {"success": False, "message": "Stopwatch not found"}


@app.post("/api/stopwatches/{stopwatch_id}/lap")
async def lap_stopwatch(stopwatch_id: str):
    """
    Record a lap time without stopping.

    Returns the current elapsed time as a lap record.
    The stopwatch continues running.
    """
    stopwatches = load_stopwatches()
    for sw in stopwatches:
        if sw["id"] == stopwatch_id:
            current_elapsed = sw.get("elapsed_ms", 0)
            if sw["is_running"] and sw["started_at"]:
                started = datetime.fromisoformat(sw["started_at"].rstrip("Z"))
                now = datetime.utcnow()
                current_elapsed += int((now - started).total_seconds() * 1000)
            return {
                "success": True,
                "lap_ms": current_elapsed,
                "timestamp": datetime.utcnow().isoformat() + "Z"
            }
    return {"success": False, "message": "Stopwatch not found"}


@app.delete("/api/stopwatches/{stopwatch_id}")
async def delete_stopwatch(stopwatch_id: str):
    """Delete a stopwatch."""
    stopwatches = load_stopwatches()
    original_count = len(stopwatches)
    stopwatches = [sw for sw in stopwatches if sw["id"] != stopwatch_id]

    if len(stopwatches) == original_count:
        return {"success": False, "message": "Stopwatch not found"}

    save_stopwatches(stopwatches)
    return {"success": True}


@app.delete("/api/stopwatches")
async def delete_all_stopwatches():
    """Delete all stopwatches."""
    save_stopwatches([])
    return {"success": True, "message": "All stopwatches deleted"}








# =============================================================================
# FLIGHT PATH ENDPOINTS (Project Dependency Visualizer)
# =============================================================================

# Known project paths for quick access
KNOWN_PROJECTS = {
    "workspace": Path(__file__).parent.parent.parent,  # C:\Users\<user>\workspace
    "iHIM": Path(__file__).parent.parent,  # C:\Users\<user>\workspace\IHIM
    "<business>": Path(__file__).parent.parent.parent / "<business>",
}


class FlightPathRequest(BaseModel):
    """Request model for Flight Path scan."""
    project_path: Optional[str] = Field(None, description="Full path to project root")
    project_name: Optional[str] = Field(None, description="Known project name (workspace, iHIM, <business>)")
    max_depth: int = Field(default=3, ge=1, le=6, description="Max directory depth to scan")


@app.get("/api/flightpath/projects")
async def list_known_projects():
    """
    List known projects available for scanning.

    Returns project names and their paths.
    """
    return {
        "projects": [
            {"name": name, "path": str(path), "exists": path.exists()}
            for name, path in KNOWN_PROJECTS.items()
        ]
    }


@app.post("/api/flightpath/scan")
async def scan_project_endpoint(request: FlightPathRequest):
    """
    Scan a project and return the full dependency graph.

    Use this for detailed analysis. For the high-level visualization,
    use /api/flightpath/graph instead.

    Args:
        project_path: Full path to project root
        project_name: OR use a known project name
        max_depth: How deep to scan (1-6, default 3)

    Returns:
        Complete project graph with files, directories, and edges.
    """
    # Resolve project path
    if request.project_name and request.project_name in KNOWN_PROJECTS:
        project_path = KNOWN_PROJECTS[request.project_name]
    elif request.project_path:
        project_path = Path(request.project_path)
    else:
        return {
            "success": False,
            "error": "Must provide either project_path or project_name",
            "known_projects": list(KNOWN_PROJECTS.keys())
        }

    # Validate path exists
    if not project_path.exists():
        return {
            "success": False,
            "error": f"Project path does not exist: {project_path}"
        }

    if not project_path.is_dir():
        return {
            "success": False,
            "error": f"Project path is not a directory: {project_path}"
        }

    try:
        graph = scan_project(str(project_path), request.max_depth)
        return {
            "success": True,
            "graph": graph.to_dict()
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Scan failed: {str(e)}"
        }


@app.post("/api/flightpath/graph")
async def get_project_graph(request: FlightPathRequest):
    """
    Get a high-level directory graph for visualization.

    This is the main "Flight Path" view - shows directories as nodes
    and their import relationships as edges. Perfect for getting a
    bird's-eye view of a project without getting lost in file details.

    Args:
        project_path: Full path to project root
        project_name: OR use a known project name
        max_depth: How deep to scan (1-6, default 3)

    Returns:
        Simplified graph with nodes (directories) and edges (relationships).
    """
    # Resolve project path
    if request.project_name and request.project_name in KNOWN_PROJECTS:
        project_path = KNOWN_PROJECTS[request.project_name]
    elif request.project_path:
        project_path = Path(request.project_path)
    else:
        return {
            "success": False,
            "error": "Must provide either project_path or project_name",
            "known_projects": list(KNOWN_PROJECTS.keys())
        }

    # Validate path exists
    if not project_path.exists():
        return {
            "success": False,
            "error": f"Project path does not exist: {project_path}"
        }

    if not project_path.is_dir():
        return {
            "success": False,
            "error": f"Project path is not a directory: {project_path}"
        }

    try:
        graph = get_directory_graph(str(project_path), request.max_depth)
        return {
            "success": True,
            "graph": graph
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Graph generation failed: {str(e)}"
        }


@app.get("/api/flightpath/graph/{project_name}")
async def get_known_project_graph(project_name: str, max_depth: int = 3):
    """
    Quick access to graph for known projects.

    GET /api/flightpath/graph/iHIM
    GET /api/flightpath/graph/workspace?max_depth=2

    Returns the high-level directory graph.
    """
    if project_name not in KNOWN_PROJECTS:
        return {
            "success": False,
            "error": f"Unknown project: {project_name}",
            "known_projects": list(KNOWN_PROJECTS.keys())
        }

    project_path = KNOWN_PROJECTS[project_name]

    if not project_path.exists():
        return {
            "success": False,
            "error": f"Project path does not exist: {project_path}"
        }

    try:
        # Clamp max_depth to valid range
        max_depth = max(1, min(6, max_depth))
        graph = get_directory_graph(str(project_path), max_depth)
        return {
            "success": True,
            "graph": graph
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Graph generation failed: {str(e)}"
        }


# =============================================================================
# SANITY CHECK ENDPOINTS (System Health Verification)
# =============================================================================

@app.get("/api/sanity")
async def sanity_check_status():
    """Check if sanity system is available."""
    return {
        "available": SANITY_AVAILABLE,
        "message": "Sanity check system active" if SANITY_AVAILABLE else "Sanity check not loaded"
    }


@app.post("/api/sanity/run")
async def run_sanity_check_endpoint():
    """
    Run full system sanity check.

    Validates:
    - Required Python modules installed
    - Directory structure intact
    - All iHIM modules importable
    - Action registry consistency
    - Template formatting works
    - Data files are valid JSON
    - Naming conventions followed
    - API server can start

    Returns detailed report with pass/fail status and fix hints.
    """
    if not SANITY_AVAILABLE:
        return {"error": "Sanity check system not available"}

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
                    "name": c.name,
                    "passed": c.passed,
                    "message": c.message,
                    "severity": c.severity,
                    "fix_hint": c.fix_hint
                }
                for c in report.checks
            ],
            "summary": report.summary()
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


# =============================================================================
# SLASH COMMAND CENTER ENDPOINTS
# =============================================================================
# NOTE: Slash command endpoints have been moved to the api/commands/ module
# and are included via the slash_commands_router above.
# See: IHIM/api/commands/routes.py for the full implementation.
#
# Available endpoints:
#   GET  /api/slash-commands              - List all commands with filtering
#   GET  /api/slash-commands/summary      - Quick summary for command palette
#   GET  /api/slash-commands/{id}         - Get command details
#   GET  /api/slash-commands/{id}/content - Get raw markdown content
#   PUT  /api/slash-commands/{id}/auto-invoke - Configure auto-invoke
#   GET  /api/slash-commands/auto-invoke/active - Get auto-invoke enabled commands
#   GET  /api/slash-commands/ideas/all    - List all brainstorm ideas
#   POST /api/slash-commands/ideas        - Create new idea
#   PUT  /api/slash-commands/ideas/{id}   - Update idea
#   POST /api/slash-commands/ideas/{id}/vote - Vote on idea
#   POST /api/slash-commands/ideas/{id}/note - Add discussion note
#   POST /api/slash-commands/ideas/{id}/promote - Promote idea to command
#   DELETE /api/slash-commands/ideas/{id} - Delete idea
#   GET  /api/slash-commands/categories/all - List categories
#   POST /api/slash-commands/categories   - Create category
#   POST /api/slash-commands/sync         - Sync with file system
#   GET  /api/slash-commands/sync/status  - Check sync status
#   GET  /api/slash-commands/search       - Search commands and ideas
# =============================================================================


# =============================================================================
# SERVER CONTROL ENDPOINTS
# =============================================================================

@app.post("/api/server/restart")
async def restart_server():
    """
    Restart the iHIM server by killing ALL processes on port 7777, then starting fresh.

    Uses port-based PID lookup (not process name) to catch both uvicorn
    parent (reloader) and child (worker) processes. Writes a temp PS1 script
    and runs via -File to avoid variable/escaping issues with -Command.
    """
    import subprocess
    import os
    import tempfile
    from pathlib import Path

    if sys.platform != "win32":
        return {"success": False, "message": "Only supported on Windows currently"}

    ihim_dir = Path(__file__).parent.parent
    run_script = ihim_dir / "run.py"

    if not run_script.exists():
        return {"success": False, "message": f"run.py not found at {run_script}"}

    python_path = str(Path(sys.executable))

    # Write PS script to a temp file — avoids $variable escaping issues with -Command
    log_path = str(Path(tempfile.gettempdir()) / "ihim_restart.log").replace("\\", "/")
    ps_script = f"""
$log = "{log_path}"
"[$(Get-Date)] Restart script started" | Out-File $log

Start-Sleep -Seconds 1

# Collect ALL python PIDs on port 7777 — both direct listeners and their parents
$targets = @()
$procs = (Get-NetTCPConnection -LocalPort 7777 -ErrorAction SilentlyContinue).OwningProcess | Sort-Object -Unique
"[$(Get-Date)] Port 7777 PIDs: $procs" | Out-File $log -Append

foreach ($p in $procs) {{
    if ($p -and $p -gt 0) {{
        $targets += $p
        # Walk up: if parent is also python, include it (reloader pattern)
        $parent = (Get-CimInstance Win32_Process -Filter "ProcessId = $p" -ErrorAction SilentlyContinue).ParentProcessId
        if ($parent -and $parent -gt 0) {{
            $parentProc = Get-Process -Id $parent -ErrorAction SilentlyContinue
            if ($parentProc -and $parentProc.ProcessName -eq 'python') {{
                $targets += $parent
                "[$(Get-Date)] Including python parent PID $parent" | Out-File $log -Append
            }}
        }}
    }}
}}

$targets = $targets | Sort-Object -Unique
"[$(Get-Date)] Kill targets: $targets" | Out-File $log -Append

# Kill each target with /T (process tree)
foreach ($t in $targets) {{
    "[$(Get-Date)] taskkill /F /PID $t /T" | Out-File $log -Append
    taskkill /F /PID $t /T 2>&1 | Out-File $log -Append
}}
Start-Sleep -Seconds 2

# Second pass — catch anything still holding the port
$still = (Get-NetTCPConnection -LocalPort 7777 -ErrorAction SilentlyContinue).OwningProcess | Sort-Object -Unique
if ($still) {{
    "[$(Get-Date)] Second pass PIDs: $still" | Out-File $log -Append
    foreach ($p in $still) {{
        if ($p -and $p -gt 0) {{
            taskkill /F /PID $p /T 2>&1 | Out-File $log -Append
        }}
    }}
}}

# Wait for port to actually clear (up to 10 seconds)
$waited = 0
while ($waited -lt 10) {{
    $check = Get-NetTCPConnection -LocalPort 7777 -State Listen -ErrorAction SilentlyContinue
    if (-not $check) {{ break }}
    Start-Sleep -Seconds 1
    $waited++
}}
"[$(Get-Date)] Port clear after $waited seconds" | Out-File $log -Append

# Start fresh server (IHIM_SUPERVISED=1 suppresses browser popup)
$env:IHIM_SUPERVISED = "1"
Start-Process -FilePath '{python_path}' -ArgumentList 'run.py' -WorkingDirectory '{ihim_dir}' -WindowStyle Hidden
"[$(Get-Date)] Started new server" | Out-File $log -Append

# Clean up this temp script
Start-Sleep -Seconds 2
Remove-Item -Path $MyInvocation.MyCommand.Path -Force -ErrorAction SilentlyContinue
"""

    try:
        # Write to temp .ps1 file (won't be inside IHIM dir, so no reload trigger)
        fd, ps_path = tempfile.mkstemp(suffix=".ps1", prefix="ihim_restart_")
        with os.fdopen(fd, "w") as f:
            f.write(ps_script)

        # Spawn via WMI so the PS process is parented by WmiPrvSE.exe,
        # NOT by this Python process. This is critical because the PS script
        # uses taskkill /T which kills the entire process tree — if PS were
        # a child of Python, it would kill itself mid-execution.
        wmi_cmd = f'powershell.exe -ExecutionPolicy Bypass -WindowStyle Hidden -File "{ps_path}"'
        subprocess.Popen(
            ["wmic", "process", "call", "create", wmi_cmd],
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return {
            "success": True,
            "message": "Server restart initiated — killing by port PID",
            "pid": os.getpid()
        }
    except Exception as e:
        return {"success": False, "message": f"Failed to spawn restart process: {e}"}


@app.get("/api/server/status")
async def server_status():
    """Get server status and uptime info."""
    import os
    return {
        "status": "running",
        "pid": os.getpid(),
        "reload_enabled": True,
        "port": 7777
    }


# =============================================================================
# STANDARDS LIBRARY (COMPLIANCE) ENDPOINTS
# =============================================================================

# Import compliance loader at module level (single instance)
try:
    from IHIM.compliance.loader import ComplianceLoader
    compliance_loader = ComplianceLoader()
    COMPLIANCE_AVAILABLE = True
except ImportError as e:
    # Try without IHIM prefix (when running from IHIM directory)
    try:
        from compliance.loader import ComplianceLoader
        compliance_loader = ComplianceLoader()
        COMPLIANCE_AVAILABLE = True
    except ImportError as e:
        print(f"Warning: Compliance system not available: {e}")
        compliance_loader = None
        COMPLIANCE_AVAILABLE = False


@app.get("/api/compliance/modules")
async def get_compliance_modules():
    """
    Get all available compliance modules.

    Returns list of modules with their metadata (name, version, category, enabled status).
    """
    if not COMPLIANCE_AVAILABLE:
        return error_response("Compliance system not available", status_code=503, error_type="ServiceUnavailable")

    try:
        # Load all available modules
        modules = compliance_loader.load_all_modules()

        # Convert to response format
        modules_list = []
        for module_id, module in modules.items():
            modules_list.append({
                "module_id": module.module_id,
                "name": module.name,
                "version": module.version,
                "category": module.category,
                "enabled": module.enabled,
                "priority": module.priority,
                "controls_count": len(module.controls),
                "description": module.metadata.get("description", "")
            })

        return {
            "success": True,
            "count": len(modules_list),
            "modules": modules_list
        }
    except Exception as e:
        return error_response(f"Failed to load modules: {str(e)}", status_code=500, error_type="InternalError")


@app.get("/api/compliance/modules/{module_id}")
async def get_compliance_module_details(module_id: str):
    """
    Get detailed information about a specific compliance module.

    Returns full module details including controls, rules, and enforcement levels.
    """
    if not COMPLIANCE_AVAILABLE:
        return error_response("Compliance system not available", status_code=503, error_type="ServiceUnavailable")

    try:
        module = compliance_loader.load_module(module_id)
        if not module:
            return error_response(f"Module '{module_id}' not found", status_code=404, error_type="NotFound")

        # Build detailed response
        controls_list = []
        for control in module.controls:
            controls_list.append({
                "control_id": control.control_id,
                "name": control.name,
                "description": control.description,
                "enforcement_level": control.enforcement_level.value,
                "triggers": control.triggers,
                "rules_count": len(control.rules),
                "evidence_required": control.evidence_required,
                "evidence_retention_days": control.evidence_retention_days
            })

        return {
            "success": True,
            "module": {
                "module_id": module.module_id,
                "name": module.name,
                "version": module.version,
                "category": module.category,
                "enabled": module.enabled,
                "priority": module.priority,
                "controls": controls_list,
                "agent_instructions": module.agent_instructions,
                "guardrail_additions": module.guardrail_additions,
                "metadata": module.metadata
            }
        }
    except Exception as e:
        return error_response(f"Failed to load module details: {str(e)}", status_code=500, error_type="InternalError")


@app.get("/api/compliance/active")
async def get_active_compliance_modules():
    """
    Get currently active compliance modules.

    Returns modules that are enabled and will be enforced at runtime.
    """
    if not COMPLIANCE_AVAILABLE:
        return error_response("Compliance system not available", status_code=503, error_type="ServiceUnavailable")

    try:
        active_modules = compliance_loader.load_active_modules()

        modules_list = []
        for module in active_modules:
            modules_list.append({
                "module_id": module.module_id,
                "name": module.name,
                "version": module.version,
                "category": module.category,
                "priority": module.priority,
                "controls_count": len(module.controls),
                "description": module.metadata.get("description", "")
            })

        return {
            "success": True,
            "count": len(modules_list),
            "modules": modules_list
        }
    except Exception as e:
        return error_response(f"Failed to load active modules: {str(e)}", status_code=500, error_type="InternalError")


@app.post("/api/compliance/activate/{module_id}")
async def activate_compliance_module(module_id: str):
    """
    Activate a compliance module.

    Enables the module for runtime enforcement and adds it to the active modules list.
    """
    if not COMPLIANCE_AVAILABLE:
        return error_response("Compliance system not available", status_code=503, error_type="ServiceUnavailable")

    try:
        success = compliance_loader.activate_module(module_id)
        if success:
            return {
                "success": True,
                "message": f"Module '{module_id}' activated",
                "module_id": module_id
            }
        else:
            return error_response(f"Failed to activate module '{module_id}' - module not found", status_code=404, error_type="NotFound")
    except Exception as e:
        return error_response(f"Activation failed: {str(e)}", status_code=500, error_type="InternalError")


@app.post("/api/compliance/deactivate/{module_id}")
async def deactivate_compliance_module(module_id: str):
    """
    Deactivate a compliance module.

    Disables the module and removes it from runtime enforcement.
    """
    if not COMPLIANCE_AVAILABLE:
        return error_response("Compliance system not available", status_code=503, error_type="ServiceUnavailable")

    try:
        success = compliance_loader.deactivate_module(module_id)
        if success:
            return {
                "success": True,
                "message": f"Module '{module_id}' deactivated",
                "module_id": module_id
            }
        else:
            return error_response(f"Failed to deactivate module '{module_id}'", status_code=400, error_type="BadRequest")
    except Exception as e:
        return error_response(f"Deactivation failed: {str(e)}", status_code=500, error_type="InternalError")


@app.get("/api/compliance/health")
async def compliance_health_check():
    """
    Run health check on the compliance system.

    Validates module integrity, state file, and directory structure.
    Returns health status with any errors or warnings.
    """
    if not COMPLIANCE_AVAILABLE:
        return error_response("Compliance system not available", status_code=503, error_type="ServiceUnavailable")

    try:
        health = compliance_loader.health_check()
        return {
            "success": True,
            "healthy": health["healthy"],
            "active_modules": health["active_modules"],
            "available_modules": health["available_modules"],
            "errors": health.get("errors", []),
            "warnings": health.get("warnings", [])
        }
    except Exception as e:
        return error_response(f"Health check failed: {str(e)}", status_code=500, error_type="InternalError")


@app.get("/api/standards/references")
async def get_standards_references():
    """
    Get reference links for various standards and frameworks.

    Returns a curated list of standards with their official documentation,
    guides, tools, and other reference materials.
    """
    references_path = Path(__file__).parent.parent / "data" / "standards_library" / "references" / "references.json"
    try:
        if references_path.exists():
            with open(references_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return {"success": True, **data}
        else:
            return {"success": False, "error": "References file not found", "standards": []}
    except Exception as e:
        return {"success": False, "error": str(e), "standards": []}


# =============================================================================
# VPT (VALUE PER TOKEN) ENDPOINTS
# =============================================================================

class VPTCalculateRequest(BaseModel):
    """Request model for VPT calculation."""
    success: bool = Field(..., description="Did the task succeed?")
    outcome_quality: int = Field(..., ge=1, le=5, description="Quality of solution (1-5)")
    efficiency_ratio: float = Field(..., ge=0.0, le=1.0, description="Effective/total actions (0-1)")
    dead_ends: int = Field(default=0, ge=0, description="Number of dead-end paths")
    pivots: int = Field(default=0, ge=0, description="Number of strategy pivots")
    total_tokens: int = Field(..., ge=1, description="Total tokens used (input + output)")
    reusability: int = Field(default=3, ge=1, le=5, description="Future reusability value (1-5)")
    learning_value: int = Field(default=3, ge=1, le=5, description="Heuristic generation value (1-5)")


@app.get("/api/vpt/calculate")
async def calculate_vpt_endpoint(
    success: bool,
    outcome_quality: int,
    efficiency_ratio: float,
    dead_ends: int = 0,
    pivots: int = 0,
    total_tokens: int = 1,
    reusability: int = 3,
    learning_value: int = 3
):
    """
    Calculate VPT (Value Per Token) score.

    Query parameters:
        success: Did the task succeed? (true/false)
        outcome_quality: Quality of solution (1-5)
        efficiency_ratio: Effective/total actions (0-1 decimal)
        dead_ends: Number of dead-end paths (default 0)
        pivots: Number of strategy pivots (default 0)
        total_tokens: Total tokens used (default 1)
        reusability: Future reusability (1-5, default 3)
        learning_value: Heuristic generation (1-5, default 3)

    Example:
        GET /api/vpt/calculate?success=true&outcome_quality=5&efficiency_ratio=0.9&dead_ends=0&pivots=1&total_tokens=3450&reusability=5&learning_value=4

    Returns:
        composite_score: Weighted value score (0-100)
        vpt_score: VPT efficiency metric
        rating: Star rating (★ to ★★★★★)
        interpretation: What the rating means
    """
    from api.vpt.calculator import calculate_vpt_full, get_vpt_rating

    try:
        # Validate ranges
        if outcome_quality < 1 or outcome_quality > 5:
            return error_response("outcome_quality must be 1-5", status_code=400)
        if efficiency_ratio < 0.0 or efficiency_ratio > 1.0:
            return error_response("efficiency_ratio must be 0-1", status_code=400)
        if total_tokens < 1:
            return error_response("total_tokens must be at least 1", status_code=400)
        if reusability < 1 or reusability > 5:
            return error_response("reusability must be 1-5", status_code=400)
        if learning_value < 1 or learning_value > 5:
            return error_response("learning_value must be 1-5", status_code=400)

        # Calculate
        composite, vpt, rating = calculate_vpt_full(
            success=success,
            outcome_quality=outcome_quality,
            efficiency_ratio=efficiency_ratio,
            dead_ends=dead_ends,
            pivots=pivots,
            total_tokens=total_tokens,
            reusability=reusability,
            learning_value=learning_value
        )

        # Interpret rating
        interpretations = {
            "★★★★★": "Exceptional efficiency",
            "★★★★": "High value",
            "★★★": "Good, room for improvement",
            "★★": "Acceptable, review for optimization",
            "★": "Low efficiency, investigate"
        }

        return {
            "success": True,
            "composite_score": round(composite, 2),
            "vpt_score": round(vpt, 2),
            "rating": rating,
            "interpretation": interpretations.get(rating, "Unknown"),
            "details": {
                "success": success,
                "outcome_quality": outcome_quality,
                "efficiency_ratio": efficiency_ratio,
                "dead_ends": dead_ends,
                "pivots": pivots,
                "total_tokens": total_tokens,
                "reusability": reusability,
                "learning_value": learning_value
            }
        }
    except Exception as e:
        return error_response(f"Calculation failed: {str(e)}", status_code=500, error_type="CalculationError")


@app.post("/api/vpt/calculate")
async def calculate_vpt_post(request: VPTCalculateRequest):
    """
    Calculate VPT (Value Per Token) score via POST.

    Same as GET endpoint but accepts JSON body.

    Example request:
    ```json
    {
        "success": true,
        "outcome_quality": 5,
        "efficiency_ratio": 0.9,
        "dead_ends": 0,
        "pivots": 1,
        "total_tokens": 3450,
        "reusability": 5,
        "learning_value": 4
    }
    ```

    Returns the same format as GET endpoint.
    """
    from api.vpt.calculator import calculate_vpt_full

    try:
        composite, vpt, rating = calculate_vpt_full(
            success=request.success,
            outcome_quality=request.outcome_quality,
            efficiency_ratio=request.efficiency_ratio,
            dead_ends=request.dead_ends,
            pivots=request.pivots,
            total_tokens=request.total_tokens,
            reusability=request.reusability,
            learning_value=request.learning_value
        )

        interpretations = {
            "★★★★★": "Exceptional efficiency",
            "★★★★": "High value",
            "★★★": "Good, room for improvement",
            "★★": "Acceptable, review for optimization",
            "★": "Low efficiency, investigate"
        }

        return {
            "success": True,
            "composite_score": round(composite, 2),
            "vpt_score": round(vpt, 2),
            "rating": rating,
            "interpretation": interpretations.get(rating, "Unknown"),
            "details": {
                "success": request.success,
                "outcome_quality": request.outcome_quality,
                "efficiency_ratio": request.efficiency_ratio,
                "dead_ends": request.dead_ends,
                "pivots": request.pivots,
                "total_tokens": request.total_tokens,
                "reusability": request.reusability,
                "learning_value": request.learning_value
            }
        }
    except Exception as e:
        return error_response(f"Calculation failed: {str(e)}", status_code=500, error_type="CalculationError")


# =============================================================================
# PRIVILEGE SYSTEM ENDPOINTS (Governance Infrastructure)
# =============================================================================

# Import privilege system components
try:
    from privilege import (
        PrivilegeLevel,
        get_trust_state,
        update_trust,
        can_perform_operation,
        classify_operation,
        OperationType,
    )
    from privilege.escalation import (
        request_escalation,
        approve_escalation,
        deny_escalation,
        get_pending_escalations,
        get_escalation_by_id,
    )
    from privilege.monitor import (
        check_for_anomalies,
        get_recent_alerts,
        get_unacknowledged_alerts,
        acknowledge_alert,
        get_monitor_status,
    )
    from privilege.rollback import (
        create_checkpoint,
        rollback_to_checkpoint,
        list_checkpoints,
        get_rollback_status,
        CheckpointTrigger,
    )
    PRIVILEGE_AVAILABLE = True
except ImportError as e:
    print(f"Warning: Privilege system not available: {e}")
    PRIVILEGE_AVAILABLE = False


class PrivilegeCheckRequest(BaseModel):
    """Request model for privilege boundary check."""
    operation_type: str = Field(..., description="Type of operation (file_read, file_write, etc.)")
    target: Optional[str] = Field(None, description="Target path, process name, etc.")
    details: Optional[dict] = Field(None, description="Additional operation details")


class EscalationRequestModel(BaseModel):
    """Request model for privilege escalation."""
    from_level: str = Field(..., pattern=r'^L[012]$', description="Current level (L0, L1, L2)")
    to_level: str = Field(..., pattern=r'^L[012]$', description="Requested level (L0, L1, L2)")
    reason: str = Field(..., min_length=1, max_length=500, description="Why escalation is needed")
    operation: str = Field(..., min_length=1, max_length=200, description="What operation requires this")


@app.get("/api/privilege/status")
async def privilege_status():
    """
    Get current privilege status.

    Returns current trust score, privilege level, and system health.
    """
    if not PRIVILEGE_AVAILABLE:
        return error_response("Privilege system not available", status_code=503, error_type="ServiceUnavailable")

    try:
        state = get_trust_state()
        monitor = get_monitor_status()
        rollback = get_rollback_status()

        return {
            "success": True,
            "trust": {
                "score": state.current_score,
                "level": state.current_level,
                "level_display": PrivilegeLevel(state.current_level).display_name,
                "successful_ops": state.total_successful_ops,
                "failed_ops": state.total_failed_ops,
                "in_recovery": state.is_in_recovery(),
                "recovery_until": state.recovery_until,
            },
            "monitor": monitor,
            "rollback": rollback,
        }
    except Exception as e:
        return error_response(f"Failed to get privilege status: {str(e)}", status_code=500, error_type="InternalError")


@app.post("/api/privilege/check")
async def privilege_check(request: PrivilegeCheckRequest):
    """
    Check if an operation is allowed at current privilege level.

    Use this before attempting operations that might hit privilege boundaries.

    Returns whether the operation is allowed, required level, and escalation path if denied.
    """
    if not PRIVILEGE_AVAILABLE:
        return error_response("Privilege system not available", status_code=503, error_type="ServiceUnavailable")

    try:
        # Parse operation type
        try:
            op_type = OperationType(request.operation_type)
        except ValueError:
            return error_response(
                f"Unknown operation type: {request.operation_type}. "
                f"Valid types: {[ot.value for ot in OperationType]}",
                status_code=400
            )

        result = can_perform_operation(op_type, request.target, request.details)

        return {
            "success": True,
            "allowed": result.allowed,
            "required_level": result.required_level.value,
            "required_level_display": result.required_level.display_name,
            "current_level": result.current_level.value,
            "current_level_display": result.current_level.display_name,
            "reason": result.reason,
            "trust_score": result.trust_score,
            "can_escalate": result.can_escalate,
            "escalation_path": result.escalation_path,
        }
    except Exception as e:
        return error_response(f"Privilege check failed: {str(e)}", status_code=500, error_type="InternalError")


@app.post("/api/privilege/escalate")
async def privilege_escalate(request: EscalationRequestModel):
    """
    Request privilege escalation.

    L0 -> L1 may auto-approve if trust threshold is met.
    L2 requests always require human approval.
    """
    if not PRIVILEGE_AVAILABLE:
        return error_response("Privilege system not available", status_code=503, error_type="ServiceUnavailable")

    try:
        from_level = PrivilegeLevel(request.from_level)
        to_level = PrivilegeLevel(request.to_level)

        result = request_escalation(from_level, to_level, request.reason, request.operation)

        return {
            "success": True,
            "request_id": result.id,
            "status": result.status,
            "auto_approved": result.status == "auto_approved",
            "message": f"Escalation request {result.status}",
            "created_at": result.created_at,
            "resolved_at": result.resolved_at,
        }
    except Exception as e:
        return error_response(f"Escalation request failed: {str(e)}", status_code=500, error_type="InternalError")


@app.get("/api/privilege/escalations")
async def get_escalations():
    """Get all pending escalation requests."""
    if not PRIVILEGE_AVAILABLE:
        return error_response("Privilege system not available", status_code=503, error_type="ServiceUnavailable")

    try:
        pending = get_pending_escalations()
        return {
            "success": True,
            "count": len(pending),
            "requests": [r.to_dict() for r in pending],
        }
    except Exception as e:
        return error_response(f"Failed to get escalations: {str(e)}", status_code=500, error_type="InternalError")


@app.post("/api/privilege/escalations/{request_id}/approve")
async def approve_escalation_endpoint(request_id: str):
    """
    Approve a pending escalation request.

    Only used for manual L2 approvals.
    """
    if not PRIVILEGE_AVAILABLE:
        return error_response("Privilege system not available", status_code=503, error_type="ServiceUnavailable")

    try:
        result = approve_escalation(request_id, approver="human")
        if result:
            return {
                "success": True,
                "request": result.to_dict(),
                "message": "Escalation approved",
            }
        return error_response(f"Escalation request not found: {request_id}", status_code=404, error_type="NotFound")
    except Exception as e:
        return error_response(f"Approval failed: {str(e)}", status_code=500, error_type="InternalError")


@app.post("/api/privilege/escalations/{request_id}/deny")
async def deny_escalation_endpoint(request_id: str, reason: str = ""):
    """Deny a pending escalation request."""
    if not PRIVILEGE_AVAILABLE:
        return error_response("Privilege system not available", status_code=503, error_type="ServiceUnavailable")

    try:
        result = deny_escalation(request_id, reason)
        if result:
            return {
                "success": True,
                "request": result.to_dict(),
                "message": "Escalation denied",
            }
        return error_response(f"Escalation request not found: {request_id}", status_code=404, error_type="NotFound")
    except Exception as e:
        return error_response(f"Denial failed: {str(e)}", status_code=500, error_type="InternalError")


@app.get("/api/privilege/alerts")
async def get_privilege_alerts(hours: int = 24, unacknowledged_only: bool = False):
    """
    Get privilege system alerts.

    Args:
        hours: Get alerts from the last N hours (default 24)
        unacknowledged_only: Only return unacknowledged alerts
    """
    if not PRIVILEGE_AVAILABLE:
        return error_response("Privilege system not available", status_code=503, error_type="ServiceUnavailable")

    try:
        if unacknowledged_only:
            alerts = get_unacknowledged_alerts()
        else:
            alerts = get_recent_alerts(hours)

        return {
            "success": True,
            "count": len(alerts),
            "alerts": [a.to_dict() for a in alerts],
        }
    except Exception as e:
        return error_response(f"Failed to get alerts: {str(e)}", status_code=500, error_type="InternalError")


@app.post("/api/privilege/alerts/{alert_id}/acknowledge")
async def acknowledge_privilege_alert(alert_id: str):
    """Acknowledge a privilege alert."""
    if not PRIVILEGE_AVAILABLE:
        return error_response("Privilege system not available", status_code=503, error_type="ServiceUnavailable")

    try:
        result = acknowledge_alert(alert_id)
        if result:
            return {
                "success": True,
                "alert": result.to_dict(),
                "message": "Alert acknowledged",
            }
        return error_response(f"Alert not found: {alert_id}", status_code=404, error_type="NotFound")
    except Exception as e:
        return error_response(f"Acknowledgment failed: {str(e)}", status_code=500, error_type="InternalError")


@app.post("/api/privilege/anomaly-check")
async def run_anomaly_check():
    """
    Run anomaly detection on current privilege state.

    Checks for unusual patterns like trust manipulation,
    boundary probing, or escalation abuse.
    """
    if not PRIVILEGE_AVAILABLE:
        return error_response("Privilege system not available", status_code=503, error_type="ServiceUnavailable")

    try:
        new_alerts = check_for_anomalies()
        return {
            "success": True,
            "alerts_generated": len(new_alerts),
            "alerts": [a.to_dict() for a in new_alerts],
        }
    except Exception as e:
        return error_response(f"Anomaly check failed: {str(e)}", status_code=500, error_type="InternalError")


@app.get("/api/privilege/checkpoints")
async def get_checkpoints(limit: int = 20):
    """List recent privilege state checkpoints."""
    if not PRIVILEGE_AVAILABLE:
        return error_response("Privilege system not available", status_code=503, error_type="ServiceUnavailable")

    try:
        checkpoints = list_checkpoints(limit)
        return {
            "success": True,
            "count": len(checkpoints),
            "checkpoints": [c.to_dict() for c in checkpoints],
        }
    except Exception as e:
        return error_response(f"Failed to list checkpoints: {str(e)}", status_code=500, error_type="InternalError")


@app.post("/api/privilege/checkpoints")
async def create_checkpoint_endpoint(description: str = "Manual checkpoint"):
    """Create a manual privilege state checkpoint."""
    if not PRIVILEGE_AVAILABLE:
        return error_response("Privilege system not available", status_code=503, error_type="ServiceUnavailable")

    try:
        checkpoint = create_checkpoint(CheckpointTrigger.MANUAL, description)
        return {
            "success": True,
            "checkpoint": checkpoint.to_dict(),
            "message": "Checkpoint created",
        }
    except Exception as e:
        return error_response(f"Checkpoint creation failed: {str(e)}", status_code=500, error_type="InternalError")


@app.post("/api/privilege/checkpoints/{checkpoint_id}/rollback")
async def rollback_checkpoint(checkpoint_id: str):
    """
    Rollback to a specific checkpoint.

    Restores trust state to the checkpoint's state.
    """
    if not PRIVILEGE_AVAILABLE:
        return error_response("Privilege system not available", status_code=503, error_type="ServiceUnavailable")

    try:
        result = rollback_to_checkpoint(checkpoint_id)
        if result:
            return {
                "success": True,
                "restored_state": {
                    "trust_score": result.current_score,
                    "level": result.current_level,
                },
                "message": f"Rolled back to checkpoint {checkpoint_id}",
            }
        return error_response(f"Checkpoint not found: {checkpoint_id}", status_code=404, error_type="NotFound")
    except Exception as e:
        return error_response(f"Rollback failed: {str(e)}", status_code=500, error_type="InternalError")
