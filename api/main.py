"""iHIM API Server"""
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from pathlib import Path
from typing import Optional
from datetime import datetime
import sys
import json
import uuid
import psutil

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
    from team.blackboard import get_blackboard_summary, get_messages, get_blockers, get_done_agents
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

app = FastAPI(title="iHIM", description="Your Command Center")

# CORS middleware for Chrome extension access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins (including Chrome extensions)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include the commands router (enhanced module)
if SLASH_COMMANDS_AVAILABLE:
    app.include_router(slash_commands_router)


# Request models
class SpawnRequest(BaseModel):
    prompt: str
    project: str = "workspace"

# Serve static files
UI_DIR = Path(__file__).parent.parent / "ui"
app.mount("/static", StaticFiles(directory=UI_DIR / "static"), name="static")


@app.get("/")
async def root():
    """Serve the dashboard"""
    return FileResponse(UI_DIR / "index.html")


@app.get("/api/actions")
async def get_actions():
    """Get all available actions"""
    return {"actions": ACTIONS}


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
async def system_topology():
    """
    Get the complete iHIM system topology.

    Returns all components (nodes) and their connections (edges)
    for the Flight Path vitals visualization.
    """
    if not SYSTEM_HEALTH_AVAILABLE:
        return {"error": "System health module not available"}

    topology = get_system_topology()
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
    Spawn the software dev team.

    Takes one prompt, morphs it into 5 tailored prompts,
    opens 5 CLI tabs in one Windows Terminal window.

    Uses your the agent harness Max subscription - no extra API costs.
    """
    # Route the prompt to all agents
    routed_prompts = route_prompt(
        prompt=request.prompt,
        project=request.project
    )

    # Spawn the agents (5 tabs in one window)
    result = spawn_agent_team(routed_prompts)

    # Update state
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
    session_id: str
    prompt: str = ""


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
        return {"error": "Blackboard system not available"}

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
        return {"error": "Blackboard system not available"}

    try:
        messages = get_messages(message_type=message_type, for_agent=for_agent)
        return {
            "count": len(messages),
            "messages": [m.to_dict() for m in messages]
        }
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/blackboard/blockers")
async def get_current_blockers():
    """
    Get currently unresolved blockers.

    Useful for monitoring agent coordination issues.
    """
    if not FEEDBACK_AVAILABLE:
        return {"error": "Blackboard system not available"}

    try:
        blockers = get_blockers()
        done_agents = get_done_agents()
        return {
            "blockers": [b.to_dict() for b in blockers],
            "blocker_count": len(blockers),
            "done_agents": done_agents
        }
    except Exception as e:
        return {"error": str(e)}


# =============================================================================
# TASK LIST ENDPOINTS
# =============================================================================

TASKS_FILE = Path(__file__).parent.parent / "data" / "tasks.json"


class TaskCreate(BaseModel):
    text: str
    priority: str = "medium"


class TaskUpdate(BaseModel):
    text: Optional[str] = None
    priority: Optional[str] = None
    completed: Optional[bool] = None


def load_tasks() -> list:
    """Load tasks from JSON file."""
    if TASKS_FILE.exists():
        try:
            data = json.loads(TASKS_FILE.read_text(encoding="utf-8"))
            return data.get("tasks", [])
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
        "completed": False
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
    Trigger a server restart.

    With --reload flag, touching a .py file triggers uvicorn to restart.
    This is the cleanest way to reload code changes.

    Usage: curl -X POST http://localhost:7777/api/server/restart
    """
    from pathlib import Path

    # Touch main.py to trigger uvicorn reload
    main_file = Path(__file__)
    main_file.touch()

    return {
        "success": True,
        "message": "Server restart triggered (uvicorn will reload)",
        "touched": str(main_file)
    }


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
