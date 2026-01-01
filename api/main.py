"""iHIM API Server"""
from fastapi import FastAPI, Request, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, conlist, field_validator, ValidationError
from pathlib import Path
from typing import Optional, List
from datetime import datetime
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
    from team.feedback.metrics import get_metrics, get_metrics_summary, update_metrics
    from team.feedback.processor import process_session_results, save_feedback_entry
    from team.feedback.optimizer import generate_optimizations, get_optimizations_for_agent
    from team.blackboard import (
        get_blackboard_summary, get_messages, get_blockers, get_done_agents,
        post_message, update_status, add_deliverable, agent_done, agent_blocked,
        init_blackboard, load_blackboard, clear_blackboard
    )
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

# Import C2PA module (Content Provenance)
try:
    from api.c2pa.routes import router as c2pa_router
    C2PA_AVAILABLE = True
except ImportError as e:
    print(f"Warning: C2PA module not available: {e}")
    C2PA_AVAILABLE = False

app = FastAPI(title="iHIM", description="Your Command Center - with Blackboard API")

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

    # Only apply no-cache to API endpoints (not static files or root)
    if request.url.path.startswith("/api/"):
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

# Include the C2PA router (Content Provenance)
if C2PA_AVAILABLE:
    app.include_router(c2pa_router)


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


# =============================================================================
# BLACKBOARD REQUEST MODELS
# =============================================================================

class BlackboardMessageRequest(BaseModel):
    """Request model for posting a message to the blackboard."""
    agent: str = Field(..., min_length=1, max_length=50, pattern=r'^[a-zA-Z0-9_-]+$', description="Agent ID posting the message (e.g., 'frontend-dev')")
    message: str = Field(..., min_length=1, max_length=5000, description="The message content")
    msg_type: Optional[str] = Field(None, min_length=1, max_length=50, pattern=r'^[A-Z_]+$', description="Message type: DONE, QUESTION, DELIVERABLE, BLOCKER, etc.")
    to: Optional[str] = Field(None, min_length=1, max_length=50, pattern=r'^[a-zA-Z0-9_-]+$', description="Target agent for directed messages")


class BlackboardStatusRequest(BaseModel):
    """Request model for updating agent status."""
    agent: str = Field(..., min_length=1, max_length=50, pattern=r'^[a-zA-Z0-9_-]+$', description="Agent ID to update")
    status: str = Field(..., min_length=1, max_length=50, description="New status (e.g., 'working', 'blocked', 'complete')")


class BlackboardDeliverableRequest(BaseModel):
    """Request model for recording a deliverable."""
    agent: str = Field(..., min_length=1, max_length=50, pattern=r'^[a-zA-Z0-9_-]+$', description="Agent ID that created the deliverable")
    deliverable: str = Field(..., min_length=1, max_length=500, description="Description of what was created (file path, endpoint, etc.)")


class BlackboardDoneRequest(BaseModel):
    """Request model for marking an agent as done."""
    agent: str = Field(..., min_length=1, max_length=50, pattern=r'^[a-zA-Z0-9_-]+$', description="Agent ID that is done")
    summary: str = Field(..., min_length=1, max_length=2000, description="Summary of work completed")


class BlackboardBlockedRequest(BaseModel):
    """Request model for reporting a blocker."""
    agent: str = Field(..., min_length=1, max_length=50, pattern=r'^[a-zA-Z0-9_-]+$', description="Agent ID that is blocked")
    blocker: str = Field(..., min_length=1, max_length=1000, description="Description of what is blocking progress")


class BlackboardInitRequest(BaseModel):
    """Request model for initializing a new blackboard."""
    feature: str = Field(..., min_length=1, max_length=500, description="Description of the feature being built")
    agents: List[str] = Field(..., min_items=1, max_items=20, description="List of agent IDs participating")

    @field_validator('agents')
    @classmethod
    def validate_agent_names(cls, v):
        """Validate agent names to prevent injection attacks."""
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
    """Serve the dashboard"""
    return FileResponse(UI_DIR / "index.html")


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


@app.get("/api/feedback/metrics")
async def get_feedback_metrics():
    """
    Get metrics summary showing improvement over time.

    Returns session count, success rates, trends, and top learnings.
    """
    if not FEEDBACK_AVAILABLE:
        return {"error": "Feedback system not available"}

    return get_metrics_summary()


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
# BLACKBOARD ENDPOINTS (Agent Coordination)
# =============================================================================

@app.get("/api/blackboard")
async def get_blackboard():
    """
    Get current blackboard status.

    Shows feature being built, current phase, agent statuses,
    and coordination metrics.
    """
    if not FEEDBACK_AVAILABLE:
        return error_response("Blackboard system not available", status_code=503, error_type="ServiceUnavailable")

    return get_blackboard_summary()


@app.get("/api/blackboard/messages")
async def get_blackboard_messages(
    message_type: Optional[str] = None,
    for_agent: Optional[str] = None
):
    """
    Get messages from the blackboard.

    Optional filters:
    - message_type: Filter by type (BLOCKED, DONE, QUESTION, etc.)
    - for_agent: Get messages targeted at specific agent
    """
    if not FEEDBACK_AVAILABLE:
        return error_response("Blackboard system not available", status_code=503, error_type="ServiceUnavailable")

    try:
        messages = get_messages(message_type=message_type, for_agent=for_agent)
        return {
            "count": len(messages),
            "messages": [m.to_dict() for m in messages]
        }
    except Exception as e:
        return error_response(str(e), status_code=500, error_type="InternalError")


@app.get("/api/blackboard/blockers")
async def get_current_blockers():
    """
    Get currently unresolved blockers.

    Useful for monitoring agent coordination issues.
    """
    if not FEEDBACK_AVAILABLE:
        return error_response("Blackboard system not available", status_code=503, error_type="ServiceUnavailable")

    try:
        blockers = get_blockers()
        done_agents = get_done_agents()
        return {
            "blockers": [b.to_dict() for b in blockers],
            "blocker_count": len(blockers),
            "done_agents": done_agents
        }
    except Exception as e:
        return error_response(str(e), status_code=500, error_type="InternalError")


# -----------------------------------------------------------------------------
# BLACKBOARD POST ENDPOINTS (Agent Write Operations)
# -----------------------------------------------------------------------------

@app.post("/api/blackboard")
async def post_blackboard_message(request: BlackboardMessageRequest):
    """
    Post a message to the blackboard.

    This is the primary endpoint for agents to communicate.
    Agents can post status updates, questions, deliverables, etc.

    Example request:
    ```json
    {
        "agent": "frontend-dev",
        "message": "Modal component complete with search functionality",
        "msg_type": "DONE"
    }
    ```

    Message types:
    - DONE: Agent has completed their work
    - QUESTION: Asking another agent something (use 'to' field)
    - DELIVERABLE: Recording a file/endpoint created
    - BLOCKER: Reporting being blocked
    - (none): General status update

    Returns:
        success: Whether the message was posted
        message: Confirmation or error message
    """
    if not FEEDBACK_AVAILABLE:
        return error_response("Blackboard system not available", status_code=503, error_type="ServiceUnavailable")

    try:
        result = post_message(
            agent=request.agent,
            message=request.message,
            msg_type=request.msg_type,
            to=request.to
        )
        if result:
            return {
                "success": True,
                "message": f"Message posted by {request.agent}",
                "msg_type": request.msg_type or "status"
            }
        else:
            return error_response("Failed to post message - blackboard may not be initialized", status_code=400, error_type="BlackboardNotInitialized")
    except Exception as e:
        return error_response(str(e), status_code=500, error_type="InternalError")


@app.post("/api/blackboard/status")
async def update_agent_status(request: BlackboardStatusRequest):
    """
    Update an agent's status on the blackboard.

    Example request:
    ```json
    {
        "agent": "backend-dev",
        "status": "working"
    }
    ```

    Common statuses: starting, working, blocked, complete

    Returns:
        success: Whether status was updated
    """
    if not FEEDBACK_AVAILABLE:
        return error_response("Blackboard system not available", status_code=503, error_type="ServiceUnavailable")

    try:
        result = update_status(request.agent, request.status)
        if result:
            return {
                "success": True,
                "agent": request.agent,
                "status": request.status
            }
        else:
            return error_response("Failed to update status - blackboard may not be initialized", status_code=400, error_type="BlackboardNotInitialized")
    except Exception as e:
        return error_response(str(e), status_code=500, error_type="InternalError")


@app.post("/api/blackboard/deliverable")
async def record_deliverable(request: BlackboardDeliverableRequest):
    """
    Record a deliverable (file, endpoint, component) created by an agent.

    Example request:
    ```json
    {
        "agent": "frontend-dev",
        "deliverable": "IHIM/ui/components/Modal.js"
    }
    ```

    Returns:
        success: Whether deliverable was recorded
    """
    if not FEEDBACK_AVAILABLE:
        return error_response("Blackboard system not available", status_code=503, error_type="ServiceUnavailable")

    try:
        result = add_deliverable(request.agent, request.deliverable)
        if result:
            return {
                "success": True,
                "agent": request.agent,
                "deliverable": request.deliverable
            }
        else:
            return error_response("Failed to record deliverable - blackboard may not be initialized", status_code=400, error_type="BlackboardNotInitialized")
    except Exception as e:
        return error_response(str(e), status_code=500, error_type="InternalError")


@app.post("/api/blackboard/done")
async def mark_agent_done(request: BlackboardDoneRequest):
    """
    Mark an agent as done with a summary of their work.

    This is a convenience endpoint that:
    1. Updates agent status to 'complete'
    2. Posts a DONE message with the summary

    Example request:
    ```json
    {
        "agent": "qa-tester",
        "summary": "All 47 tests passing. Added edge case coverage for modal."
    }
    ```

    Returns:
        success: Whether agent was marked done
    """
    if not FEEDBACK_AVAILABLE:
        return error_response("Blackboard system not available", status_code=503, error_type="ServiceUnavailable")

    try:
        result = agent_done(request.agent, request.summary)
        if result:
            return {
                "success": True,
                "agent": request.agent,
                "summary": request.summary,
                "status": "complete"
            }
        else:
            return error_response("Failed to mark done - blackboard may not be initialized", status_code=400, error_type="BlackboardNotInitialized")
    except Exception as e:
        return error_response(str(e), status_code=500, error_type="InternalError")


@app.post("/api/blackboard/blocked")
async def report_blocker(request: BlackboardBlockedRequest):
    """
    Report that an agent is blocked.

    This is a convenience endpoint that:
    1. Updates agent status to 'blocked'
    2. Posts a BLOCKER message describing the issue

    Example request:
    ```json
    {
        "agent": "frontend-dev",
        "blocker": "Waiting for backend API endpoint /api/users to be implemented"
    }
    ```

    Returns:
        success: Whether blocker was recorded
    """
    if not FEEDBACK_AVAILABLE:
        return error_response("Blackboard system not available", status_code=503, error_type="ServiceUnavailable")

    try:
        result = agent_blocked(request.agent, request.blocker)
        if result:
            return {
                "success": True,
                "agent": request.agent,
                "blocker": request.blocker,
                "status": "blocked"
            }
        else:
            return error_response("Failed to report blocker - blackboard may not be initialized", status_code=400, error_type="BlackboardNotInitialized")
    except Exception as e:
        return error_response(str(e), status_code=500, error_type="InternalError")


@app.post("/api/blackboard/init")
async def initialize_blackboard(request: BlackboardInitRequest):
    """
    Initialize a new blackboard for a feature build.

    This creates a fresh blackboard, replacing any existing one.
    Should be called at the start of a spawn session.

    Example request:
    ```json
    {
        "feature": "Slash Command Modal with search and categories",
        "agents": ["frontend-dev", "backend-dev", "qa-tester", "devops", "security-reviewer"]
    }
    ```

    Returns:
        success: Whether blackboard was initialized
        feature: The feature description
        agents: List of participating agents
    """
    if not FEEDBACK_AVAILABLE:
        return error_response("Blackboard system not available", status_code=503, error_type="ServiceUnavailable")

    try:
        board = init_blackboard(request.feature, request.agents)
        return {
            "success": True,
            "feature": board.feature,
            "agents": list(board.agent_status.keys()),
            "phase": board.phase.value if hasattr(board.phase, 'value') else board.phase,
            "started_at": board.started_at
        }
    except Exception as e:
        return error_response(str(e), status_code=500, error_type="InternalError")


@app.delete("/api/blackboard")
async def clear_blackboard_endpoint():
    """
    Clear/reset the blackboard.

    Removes all messages, statuses, and deliverables.
    Use when starting fresh or after a session is complete.

    Returns:
        success: Whether blackboard was cleared
    """
    if not FEEDBACK_AVAILABLE:
        return error_response("Blackboard system not available", status_code=503, error_type="ServiceUnavailable")

    try:
        result = clear_blackboard()
        if result:
            return {"success": True, "message": "Blackboard cleared"}
        else:
            return error_response("Failed to clear blackboard", status_code=500, error_type="InternalError")
    except Exception as e:
        return error_response(str(e), status_code=500, error_type="InternalError")


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
        except Exception:
            pass
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
# TASK LIST ENDPOINTS
# =============================================================================

TASKS_FILE = Path(__file__).parent.parent / "data" / "tasks.json"


class TaskCreate(BaseModel):
    text: str = Field(..., min_length=1, max_length=500)
    priority: str = Field(default="medium", min_length=1, max_length=20, pattern=r'^[a-z]+$')
    description: Optional[str] = Field(None, max_length=2000)


class TaskUpdate(BaseModel):
    text: Optional[str] = Field(None, min_length=1, max_length=500)
    priority: Optional[str] = Field(None, min_length=1, max_length=20, pattern=r'^[a-z]+$')
    completed: Optional[bool] = None
    description: Optional[str] = Field(None, max_length=2000)


def load_tasks() -> list:
    """Load tasks from JSON file."""
    if TASKS_FILE.exists():
        try:
            data = json.loads(TASKS_FILE.read_text(encoding="utf-8"))
            tasks = data.get("tasks", [])
            # Ensure all tasks have a description field (backward compatibility)
            for task in tasks:
                if "description" not in task:
                    task["description"] = ""
            return tasks
        except Exception:
            pass
    return []


def save_tasks(tasks: list):
    """Save tasks to JSON file."""
    TASKS_FILE.parent.mkdir(parents=True, exist_ok=True)
    TASKS_FILE.write_text(
        json.dumps({"tasks": tasks}, indent=2),
        encoding="utf-8"
    )


@app.get("/api/tasks")
async def get_tasks():
    """Get all tasks."""
    return {"tasks": load_tasks()}


@app.post("/api/tasks")
async def create_task(task: TaskCreate):
    """Create a new task."""
    tasks = load_tasks()
    new_task = {
        "id": str(uuid.uuid4())[:8],
        "text": task.text,
        "priority": task.priority,
        "completed": False,
        "description": task.description or ""
    }
    tasks.append(new_task)
    save_tasks(tasks)
    return {"success": True, "task": new_task}


@app.put("/api/tasks/{task_id}")
async def update_task(task_id: str, update: TaskUpdate):
    """Update a task."""
    tasks = load_tasks()
    for task in tasks:
        if task["id"] == task_id:
            if update.text is not None:
                task["text"] = update.text
            if update.priority is not None:
                task["priority"] = update.priority
            if update.completed is not None:
                task["completed"] = update.completed
            if update.description is not None:
                task["description"] = update.description
            save_tasks(tasks)
            return {"success": True, "task": task}
    return {"success": False, "message": "Task not found"}


@app.delete("/api/tasks/{task_id}")
async def delete_task(task_id: str):
    """Delete a task."""
    tasks = load_tasks()
    tasks = [t for t in tasks if t["id"] != task_id]
    save_tasks(tasks)
    return {"success": True}


@app.post("/api/tasks/clear-completed")
async def clear_completed():
    """Delete all completed tasks."""
    tasks = load_tasks()
    tasks = [t for t in tasks if not t.get("completed", False)]
    save_tasks(tasks)
    return {"success": True, "remaining": len(tasks)}


# =============================================================================
# QUICK NOTES ENDPOINTS (Scratchpad/Note-taking)
# =============================================================================

NOTES_FILE = Path(__file__).parent.parent / "data" / "notes.json"


class NoteCreate(BaseModel):
    """Request model for creating a new note."""
    content: str = Field(..., min_length=1, max_length=10000)
    title: Optional[str] = Field(None, max_length=200)


class NoteUpdate(BaseModel):
    """Request model for updating an existing note."""
    content: Optional[str] = Field(None, min_length=1, max_length=10000)
    title: Optional[str] = Field(None, max_length=200)


def load_notes() -> list:
    """Load notes from JSON file."""
    if NOTES_FILE.exists():
        try:
            data = json.loads(NOTES_FILE.read_text(encoding="utf-8"))
            return data.get("notes", [])
        except Exception:
            pass
    return []


def save_notes(notes: list):
    """Save notes to JSON file."""
    NOTES_FILE.parent.mkdir(parents=True, exist_ok=True)
    NOTES_FILE.write_text(
        json.dumps({"notes": notes}, indent=2),
        encoding="utf-8"
    )


@app.get("/api/notes")
async def get_notes():
    """
    Get all notes.

    Returns notes sorted by updated_at (newest first).
    """
    notes = load_notes()
    # Sort by updated_at descending (newest first)
    notes.sort(key=lambda n: n.get("updated_at", n.get("created_at", "")), reverse=True)
    return {"notes": notes}


@app.get("/api/notes/{note_id}")
async def get_note(note_id: str):
    """Get a single note by ID."""
    notes = load_notes()
    for note in notes:
        if note["id"] == note_id:
            return {"success": True, "note": note}
    return {"success": False, "message": "Note not found"}


@app.post("/api/notes", status_code=201)
async def create_note(note: NoteCreate):
    """
    Create a new note.

    Timestamps are generated server-side in ISO 8601 format.
    """
    notes = load_notes()
    now = datetime.utcnow().isoformat() + "Z"

    new_note = {
        "id": str(uuid.uuid4())[:8],
        "title": note.title or "",
        "content": note.content,
        "created_at": now,
        "updated_at": now
    }
    notes.append(new_note)
    save_notes(notes)
    return {"success": True, "note": new_note}


@app.put("/api/notes/{note_id}")
async def update_note(note_id: str, update: NoteUpdate):
    """
    Update an existing note.

    Updates the updated_at timestamp automatically.
    """
    notes = load_notes()
    for note in notes:
        if note["id"] == note_id:
            if update.content is not None:
                note["content"] = update.content
            if update.title is not None:
                note["title"] = update.title
            note["updated_at"] = datetime.utcnow().isoformat() + "Z"
            save_notes(notes)
            return {"success": True, "note": note}
    return {"success": False, "message": "Note not found"}


@app.delete("/api/notes/{note_id}")
async def delete_note(note_id: str):
    """Delete a note."""
    notes = load_notes()
    original_count = len(notes)
    notes = [n for n in notes if n["id"] != note_id]

    if len(notes) == original_count:
        return {"success": False, "message": "Note not found"}

    save_notes(notes)
    return {"success": True}


@app.delete("/api/notes")
async def delete_all_notes():
    """Delete all notes (with confirmation required in frontend)."""
    save_notes([])
    return {"success": True, "message": "All notes deleted"}


# =============================================================================
# PERIODIC TABLE ENDPOINTS (Team Mode Elements)
# =============================================================================

@app.get("/api/periodic-elements")
async def get_periodic_elements():
    """Return periodic table elements and layout for the UI."""
    import os
    import json

    base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    # Load elements
    elements_path = os.path.join(base_path, "data", "periodic_elements.json")
    layout_path = os.path.join(base_path, "data", "periodic_layout.json")

    elements = []
    layout = []

    try:
        if os.path.exists(elements_path):
            with open(elements_path, 'r') as f:
                data = json.load(f)
                # Handle wrapper object: {"meta": {...}, "elements": [...]}
                elements = data.get("elements", data) if isinstance(data, dict) else data
    except Exception as e:
        print(f"Error loading elements: {e}")

    try:
        if os.path.exists(layout_path):
            with open(layout_path, 'r') as f:
                layout_data = json.load(f)
                layout = layout_data.get('layout', [])
    except Exception as e:
        print(f"Error loading layout: {e}")

    # Fallback if no files exist
    if not elements:
        elements = [
            {"symbol": "O", "name": "the agent", "category": "tiers", "description": "Architect tier - full permissions"},
            {"symbol": "S", "name": "the agent", "category": "tiers", "description": "Operator tier - read/write"},
            {"symbol": "H", "name": "the agent", "category": "tiers", "description": "Scout tier - read-only"},
            {"symbol": "Ye", "name": "Yellow Mode", "category": "modes", "description": "Fast build: 2S + 4W + 4O"},
            {"symbol": "Re", "name": "Red Mode", "category": "modes", "description": "Discovery: 8S + 2H monitors"},
            {"symbol": "Gr", "name": "Green Mode", "category": "modes", "description": "Verify gate: 10H"},
            {"symbol": "Bl", "name": "Blue Mode", "category": "modes", "description": "Recon swarm: 10H READ-ONLY"}
        ]

    if not layout:
        layout = [
            {"symbol": "O", "row": 1, "col": 1},
            {"symbol": "S", "row": 1, "col": 2},
            {"symbol": "H", "row": 1, "col": 3},
            {"symbol": "Ye", "row": 1, "col": 15},
            {"symbol": "Re", "row": 1, "col": 16},
            {"symbol": "Gr", "row": 1, "col": 17},
            {"symbol": "Bl", "row": 1, "col": 18}
        ]

    return {"elements": elements, "layout": layout}


# =============================================================================
# HEURISTICS ENDPOINTS (Tricks & Debugging Patterns)
# =============================================================================

HEURISTICS_FILE = Path(__file__).parent.parent / "data" / "heuristics.json"


class HeuristicCreate(BaseModel):
    """Request model for creating a new heuristic."""
    trigger_conditions: List[str] = Field(..., min_items=1, max_items=10, description="When to apply this trick")
    action: str = Field(..., min_length=1, max_length=1000, description="What to do")
    anti_action: Optional[str] = Field(None, max_length=1000, description="What NOT to do")
    rationale: Optional[str] = Field(None, max_length=1000, description="Why this works")
    pattern: Optional[str] = Field(None, max_length=50, description="Pattern category")


class HeuristicUpdate(BaseModel):
    """Request model for updating a heuristic."""
    trigger_conditions: Optional[List[str]] = Field(None, min_items=1, max_items=10)
    action: Optional[str] = Field(None, min_length=1, max_length=1000)
    anti_action: Optional[str] = Field(None, max_length=1000)
    rationale: Optional[str] = Field(None, max_length=1000)
    pattern: Optional[str] = Field(None, max_length=50)


def load_heuristics() -> dict:
    """Load heuristics from JSON file."""
    if HEURISTICS_FILE.exists():
        try:
            return json.loads(HEURISTICS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"heuristics": [], "meta": {"last_updated": "", "total_heuristics": 0}}


def save_heuristics(data: dict):
    """Save heuristics to JSON file."""
    HEURISTICS_FILE.parent.mkdir(parents=True, exist_ok=True)
    data["meta"]["last_updated"] = datetime.utcnow().isoformat() + "Z"
    data["meta"]["total_heuristics"] = len(data.get("heuristics", []))
    HEURISTICS_FILE.write_text(
        json.dumps(data, indent=2),
        encoding="utf-8"
    )


@app.get("/api/heuristics")
async def get_heuristics():
    """
    Get all heuristics (tricks & patterns).

    Returns all stored debugging tricks with their usage stats.
    """
    data = load_heuristics()
    return {
        "success": True,
        "heuristics": data.get("heuristics", []),
        "meta": data.get("meta", {})
    }


@app.get("/api/heuristics/{heuristic_id}")
async def get_heuristic(heuristic_id: str):
    """Get a single heuristic by ID."""
    data = load_heuristics()
    for h in data.get("heuristics", []):
        if h["id"] == heuristic_id:
            return {"success": True, "heuristic": h}
    return {"success": False, "message": "Heuristic not found"}


@app.post("/api/heuristics", status_code=201)
async def create_heuristic(heuristic: HeuristicCreate):
    """
    Create a new heuristic (trick).

    Capture a debugging pattern that worked for future reference.
    """
    data = load_heuristics()
    heuristics = data.get("heuristics", [])

    # Generate next ID
    existing_ids = [h.get("id", "") for h in heuristics]
    max_num = 0
    for hid in existing_ids:
        if hid.startswith("h"):
            try:
                num = int(hid[1:])
                max_num = max(max_num, num)
            except ValueError:
                pass
    new_id = f"h{max_num + 1:03d}"

    now = datetime.utcnow().strftime("%Y-%m-%d")
    new_heuristic = {
        "id": new_id,
        "trigger_conditions": heuristic.trigger_conditions,
        "action": heuristic.action,
        "anti_action": heuristic.anti_action or "",
        "rationale": heuristic.rationale or "",
        "source_debrief": now,
        "pattern": heuristic.pattern or "general",
        "confidence": 0.80,
        "times_seen": 1,
        "times_applied": 0,
        "tokens_saved_estimate": 200
    }

    heuristics.append(new_heuristic)
    data["heuristics"] = heuristics
    save_heuristics(data)

    return {"success": True, "heuristic": new_heuristic}


@app.put("/api/heuristics/{heuristic_id}")
async def update_heuristic(heuristic_id: str, update: HeuristicUpdate):
    """Update an existing heuristic."""
    data = load_heuristics()
    heuristics = data.get("heuristics", [])

    for h in heuristics:
        if h["id"] == heuristic_id:
            if update.trigger_conditions is not None:
                h["trigger_conditions"] = update.trigger_conditions
            if update.action is not None:
                h["action"] = update.action
            if update.anti_action is not None:
                h["anti_action"] = update.anti_action
            if update.rationale is not None:
                h["rationale"] = update.rationale
            if update.pattern is not None:
                h["pattern"] = update.pattern

            data["heuristics"] = heuristics
            save_heuristics(data)
            return {"success": True, "heuristic": h}

    return {"success": False, "message": "Heuristic not found"}


@app.post("/api/heuristics/{heuristic_id}/apply")
async def apply_heuristic(heuristic_id: str):
    """
    Mark a heuristic as applied.

    Increments times_applied counter and updates confidence.
    """
    data = load_heuristics()
    heuristics = data.get("heuristics", [])

    for h in heuristics:
        if h["id"] == heuristic_id:
            h["times_applied"] = h.get("times_applied", 0) + 1
            h["times_seen"] = h.get("times_seen", 0) + 1
            # Increase confidence slightly with each successful application
            h["confidence"] = min(0.99, h.get("confidence", 0.8) + 0.02)

            data["heuristics"] = heuristics
            save_heuristics(data)
            return {
                "success": True,
                "heuristic": h,
                "message": f"Applied! Now used {h['times_applied']} times."
            }

    return {"success": False, "message": "Heuristic not found"}


@app.delete("/api/heuristics/{heuristic_id}")
async def delete_heuristic(heuristic_id: str):
    """Delete a heuristic."""
    data = load_heuristics()
    heuristics = data.get("heuristics", [])
    original_count = len(heuristics)

    heuristics = [h for h in heuristics if h["id"] != heuristic_id]

    if len(heuristics) == original_count:
        return {"success": False, "message": "Heuristic not found"}

    data["heuristics"] = heuristics
    save_heuristics(data)
    return {"success": True}


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
    Restart the iHIM server by killing and restarting the process.

    Spawns a detached process that:
    1. Waits 1 second for this response to complete
    2. Kills all Python processes
    3. Starts a new server via run.py

    The frontend should poll /api/health until the server is back.
    """
    import subprocess
    import os
    from pathlib import Path

    if sys.platform != "win32":
        return {"success": False, "message": "Only supported on Windows currently"}

    # Get paths
    ihim_dir = Path(__file__).parent.parent
    run_script = ihim_dir / "run.py"

    if not run_script.exists():
        return {"success": False, "message": f"run.py not found at {run_script}"}

    # PowerShell script to kill and restart
    # Escape single quotes in path for PowerShell by doubling them
    ihim_dir_escaped = str(ihim_dir).replace("'", "''")
    ps_script = f"""
    Start-Sleep -Seconds 1
    Stop-Process -Name python -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1
    Set-Location '{ihim_dir_escaped}'
    Start-Process python -ArgumentList 'run.py' -WindowStyle Hidden
    """

    # Spawn detached PowerShell process
    try:
        subprocess.Popen(
            ["powershell.exe", "-Command", ps_script],
            creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
            close_fds=True,
        )
        return {
            "success": True,
            "message": "Server restart initiated - wait 3 seconds and refresh",
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
    except ImportError:
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
