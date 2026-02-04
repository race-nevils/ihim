"""
Health check system - monitors status of all workspace components.
workspace is the root. iHIM is one system within workspace.
"""

import json
import importlib
import os
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List

from .models import ComponentHealth, HealthStatus, SystemHealth
from .topology import get_system_topology, IHIM_ROOT, WORKSPACE_ROOT


def get_file_age_seconds(file_path: Path) -> Optional[float]:
    """Get seconds since file was last modified."""
    try:
        if file_path.exists():
            mtime = file_path.stat().st_mtime
            return (datetime.now().timestamp() - mtime)
        return None
    except Exception:
        return None


def check_json_file(file_path: Path) -> tuple[HealthStatus, str, dict]:
    """
    Check a JSON file for validity.

    Returns: (status, message, metrics)
    """
    metrics = {}

    if not file_path.exists():
        return HealthStatus.INACTIVE, "File not created yet", metrics

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # Get file stats
        age = get_file_age_seconds(file_path)
        metrics["file_size"] = file_path.stat().st_size
        metrics["last_modified"] = datetime.fromtimestamp(
            file_path.stat().st_mtime
        ).isoformat()

        # Count items if it's a list or dict
        if isinstance(data, list):
            metrics["item_count"] = len(data)
        elif isinstance(data, dict):
            metrics["key_count"] = len(data)

        # Stale if not modified in 30 minutes (for actively used files)
        if age and age > 1800:
            return HealthStatus.DEGRADED, "File is stale (>30min old)", metrics

        return HealthStatus.HEALTHY, "Valid JSON", metrics

    except json.JSONDecodeError as e:
        return HealthStatus.ERROR, f"Invalid JSON: {str(e)[:50]}", metrics
    except Exception as e:
        return HealthStatus.ERROR, f"Read error: {str(e)[:50]}", metrics


def check_python_module(module_path: str) -> tuple[HealthStatus, str, dict]:
    """
    Check if a Python module can be imported.

    Returns: (status, message, metrics)
    """
    metrics = {}

    try:
        module = importlib.import_module(module_path)
        metrics["module_loaded"] = True

        # Check for expected attributes
        if hasattr(module, '__all__'):
            metrics["exports"] = len(module.__all__)

        return HealthStatus.HEALTHY, "Module loaded", metrics

    except ImportError as e:
        return HealthStatus.ERROR, f"Import failed: {str(e)[:50]}", metrics
    except Exception as e:
        return HealthStatus.ERROR, f"Error: {str(e)[:50]}", metrics


def check_directory(dir_path: Path) -> tuple[HealthStatus, str, dict]:
    """
    Check if a directory exists and count its contents.

    Returns: (status, message, metrics)
    """
    metrics = {}

    if not dir_path.exists():
        return HealthStatus.ERROR, "Directory missing", metrics

    if not dir_path.is_dir():
        return HealthStatus.ERROR, "Not a directory", metrics

    try:
        files = list(dir_path.glob("*"))
        metrics["file_count"] = len([f for f in files if f.is_file()])
        metrics["dir_count"] = len([f for f in files if f.is_dir()])

        return HealthStatus.HEALTHY, f"{metrics['file_count']} files", metrics

    except Exception as e:
        return HealthStatus.ERROR, f"Error: {str(e)[:50]}", metrics


def check_file_exists(file_path: Path) -> tuple[HealthStatus, str, dict]:
    """
    Simple check if a file exists.

    Returns: (status, message, metrics)
    """
    metrics = {}

    if not file_path.exists():
        return HealthStatus.ERROR, "File missing", metrics

    try:
        metrics["file_size"] = file_path.stat().st_size
        metrics["last_modified"] = datetime.fromtimestamp(
            file_path.stat().st_mtime
        ).isoformat()

        return HealthStatus.HEALTHY, "File exists", metrics

    except Exception as e:
        return HealthStatus.ERROR, f"Error: {str(e)[:50]}", metrics


def check_markdown_file(file_path: Path, stale_days: int = 7) -> tuple[HealthStatus, str, dict]:
    """
    Check a markdown file for existence and freshness.

    Returns: (status, message, metrics)
    """
    metrics = {}

    if not file_path.exists():
        return HealthStatus.ERROR, "File missing", metrics

    try:
        stat = file_path.stat()
        metrics["file_size"] = stat.st_size
        metrics["last_modified"] = datetime.fromtimestamp(stat.st_mtime).isoformat()

        # Calculate age in days
        age_seconds = datetime.now().timestamp() - stat.st_mtime
        age_days = age_seconds / 86400
        metrics["age_days"] = round(age_days, 1)

        # Read first line to get "Updated:" date if present
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.startswith("Updated:"):
                        metrics["updated_line"] = line.strip()
                        break
        except Exception:
            pass

        if age_days > stale_days:
            return HealthStatus.DEGRADED, f"Stale ({int(age_days)}d old)", metrics

        return HealthStatus.HEALTHY, f"Fresh ({int(age_days)}d)", metrics

    except Exception as e:
        return HealthStatus.ERROR, f"Error: {str(e)[:50]}", metrics


def check_skills_directory(dir_path: Path) -> tuple[HealthStatus, str, dict]:
    """
    Check skills directory - count valid skill folders.

    Returns: (status, message, metrics)
    """
    metrics = {}

    if not dir_path.exists():
        return HealthStatus.ERROR, "Skills directory missing", metrics

    try:
        # Count skill folders (those with skill.md inside)
        skill_count = 0
        skill_names = []
        for item in dir_path.iterdir():
            if item.is_dir() and (item / "skill.md").exists():
                skill_count += 1
                skill_names.append(item.name)

        metrics["skill_count"] = skill_count
        metrics["skills"] = skill_names

        if skill_count == 0:
            return HealthStatus.DEGRADED, "No skills found", metrics

        return HealthStatus.HEALTHY, f"{skill_count} skills", metrics

    except Exception as e:
        return HealthStatus.ERROR, f"Error: {str(e)[:50]}", metrics


def check_commands_directory(dir_path: Path) -> tuple[HealthStatus, str, dict]:
    """
    Check commands directory - count .md command files.

    Returns: (status, message, metrics)
    """
    metrics = {}

    if not dir_path.exists():
        return HealthStatus.INACTIVE, "No commands yet", metrics

    try:
        # Count .md files (commands)
        commands = [f.stem for f in dir_path.glob("*.md")]
        metrics["command_count"] = len(commands)
        metrics["commands"] = commands

        if len(commands) == 0:
            return HealthStatus.INACTIVE, "No commands yet", metrics

        return HealthStatus.HEALTHY, f"{len(commands)} commands", metrics

    except Exception as e:
        return HealthStatus.ERROR, f"Error: {str(e)[:50]}", metrics


def check_jsonl_file(file_path: Path) -> tuple[HealthStatus, str, dict]:
    """
    Check a JSONL (JSON Lines) file for validity.

    Returns: (status, message, metrics)
    """
    metrics = {}

    if not file_path.exists():
        return HealthStatus.INACTIVE, "No entries yet", metrics

    try:
        line_count = 0
        valid_lines = 0
        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    line_count += 1
                    try:
                        json.loads(line)
                        valid_lines += 1
                    except json.JSONDecodeError:
                        pass

        metrics["total_lines"] = line_count
        metrics["valid_entries"] = valid_lines
        metrics["file_size"] = file_path.stat().st_size

        if line_count == 0:
            return HealthStatus.INACTIVE, "Empty file", metrics

        if valid_lines < line_count:
            return HealthStatus.DEGRADED, f"{valid_lines}/{line_count} valid", metrics

        return HealthStatus.HEALTHY, f"{valid_lines} entries", metrics

    except Exception as e:
        return HealthStatus.ERROR, f"Error: {str(e)[:50]}", metrics


# =========================================================================
# COMPONENT-SPECIFIC HEALTH CHECKS
# =========================================================================

def check_api_server() -> ComponentHealth:
    """Check API server health."""
    # Since we're running inside the API, it's healthy if we reach here
    return ComponentHealth(
        id="api-server",
        status=HealthStatus.HEALTHY,
        message="Running",
        last_check=datetime.now().isoformat(),
        metrics={"port": 7777}
    )


def check_actions_registry() -> ComponentHealth:
    """Check actions registry."""
    try:
        from actions.registry import ACTIONS
        count = len(ACTIONS)
        return ComponentHealth(
            id="actions-registry",
            status=HealthStatus.HEALTHY,
            message=f"{count} actions registered",
            last_check=datetime.now().isoformat(),
            metrics={"action_count": count, "actions": list(ACTIONS.keys())}
        )
    except Exception as e:
        return ComponentHealth(
            id="actions-registry",
            status=HealthStatus.ERROR,
            message=str(e)[:100],
            last_check=datetime.now().isoformat(),
        )


def check_team_system() -> ComponentHealth:
    """Check team system overall."""
    dir_path = IHIM_ROOT / "team"
    status, msg, metrics = check_directory(dir_path)
    return ComponentHealth(
        id="team-system",
        status=status,
        message=msg,
        last_check=datetime.now().isoformat(),
        metrics=metrics
    )


def check_team_spawner() -> ComponentHealth:
    """Check spawner module."""
    status, msg, metrics = check_python_module("team.spawner")
    return ComponentHealth(
        id="team-spawner",
        status=status,
        message=msg,
        last_check=datetime.now().isoformat(),
        metrics=metrics
    )


def check_team_router() -> ComponentHealth:
    """Check router module."""
    status, msg, metrics = check_python_module("team.router")
    return ComponentHealth(
        id="team-router",
        status=status,
        message=msg,
        last_check=datetime.now().isoformat(),
        metrics=metrics
    )


def check_team_state() -> ComponentHealth:
    """Check state manager module."""
    status, msg, metrics = check_python_module("team.state")
    return ComponentHealth(
        id="team-state",
        status=status,
        message=msg,
        last_check=datetime.now().isoformat(),
        metrics=metrics
    )




def check_feedback_system() -> ComponentHealth:
    """Check feedback system directory."""
    dir_path = IHIM_ROOT / "team" / "feedback"
    status, msg, metrics = check_directory(dir_path)
    return ComponentHealth(
        id="feedback-system",
        status=status,
        message=msg,
        last_check=datetime.now().isoformat(),
        metrics=metrics
    )


def check_feedback_processor() -> ComponentHealth:
    """Check feedback processor module."""
    status, msg, metrics = check_python_module("team.feedback.processor")
    return ComponentHealth(
        id="feedback-processor",
        status=status,
        message=msg,
        last_check=datetime.now().isoformat(),
        metrics=metrics
    )


def check_feedback_aggregator() -> ComponentHealth:
    """Check feedback aggregator module."""
    status, msg, metrics = check_python_module("team.feedback.aggregator")
    return ComponentHealth(
        id="feedback-aggregator",
        status=status,
        message=msg,
        last_check=datetime.now().isoformat(),
        metrics=metrics
    )


def check_feedback_optimizer() -> ComponentHealth:
    """Check feedback optimizer module."""
    status, msg, metrics = check_python_module("team.feedback.optimizer")
    return ComponentHealth(
        id="feedback-optimizer",
        status=status,
        message=msg,
        last_check=datetime.now().isoformat(),
        metrics=metrics
    )


def check_feedback_metrics() -> ComponentHealth:
    """Check feedback metrics module."""
    status, msg, metrics = check_python_module("team.feedback.metrics")
    return ComponentHealth(
        id="feedback-metrics",
        status=status,
        message=msg,
        last_check=datetime.now().isoformat(),
        metrics=metrics
    )


def check_data_stores() -> ComponentHealth:
    """Check data directory."""
    dir_path = IHIM_ROOT / "data"
    status, msg, metrics = check_directory(dir_path)
    return ComponentHealth(
        id="data-stores",
        status=status,
        message=msg,
        last_check=datetime.now().isoformat(),
        metrics=metrics
    )


def check_data_team_state() -> ComponentHealth:
    """Check team_state.json file."""
    file_path = IHIM_ROOT / "team" / "team_state.json"
    status, msg, metrics = check_json_file(file_path)

    # Get team active status
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            metrics["active"] = data.get("active", False)
    except Exception:
        pass

    return ComponentHealth(
        id="data-team-state",
        status=status,
        message=msg,
        last_check=datetime.now().isoformat(),
        metrics=metrics
    )


def check_sanity() -> ComponentHealth:
    """Check sanity check system."""
    status, msg, metrics = check_python_module("sanity.check")
    return ComponentHealth(
        id="sanity-check",
        status=status,
        message=msg,
        last_check=datetime.now().isoformat(),
        metrics=metrics
    )


def check_ui_assets() -> ComponentHealth:
    """Check UI assets directory."""
    dir_path = IHIM_ROOT / "ui"
    status, msg, metrics = check_directory(dir_path)
    return ComponentHealth(
        id="ui-assets",
        status=status,
        message=msg,
        last_check=datetime.now().isoformat(),
        metrics=metrics
    )


def check_ui_dashboard() -> ComponentHealth:
    """Check dashboard HTML file."""
    file_path = IHIM_ROOT / "ui" / "index.html"
    status, msg, metrics = check_file_exists(file_path)
    return ComponentHealth(
        id="ui-dashboard",
        status=status,
        message=msg,
        last_check=datetime.now().isoformat(),
        metrics=metrics
    )


def check_ui_styles() -> ComponentHealth:
    """Check CSS file."""
    file_path = IHIM_ROOT / "ui" / "static" / "style.css"
    status, msg, metrics = check_file_exists(file_path)
    return ComponentHealth(
        id="ui-styles",
        status=status,
        message=msg,
        last_check=datetime.now().isoformat(),
        metrics=metrics
    )


def check_ihim_root() -> ComponentHealth:
    """Check iHIM root (always healthy if API is running)."""
    return ComponentHealth(
        id="ihim-root",
        status=HealthStatus.HEALTHY,
        message="Command Center Online",
        last_check=datetime.now().isoformat(),
        metrics={}
    )


# =========================================================================
# workspace-LEVEL HEALTH CHECKS (Parent systems above iHIM)
# =========================================================================

def check_workspace_root() -> ComponentHealth:
    """Check workspace root (always healthy if we can read the directory)."""
    status, msg, metrics = check_directory(WORKSPACE_ROOT)
    return ComponentHealth(
        id="workspace-root",
        status=status if status != HealthStatus.ERROR else HealthStatus.ERROR,
        message="Virtual Workstation Online" if status == HealthStatus.HEALTHY else msg,
        last_check=datetime.now().isoformat(),
        metrics=metrics
    )


def check_memory_system() -> ComponentHealth:
    """Check overall memory system health."""
    # Check that all three memory files exist
    memory_md = WORKSPACE_ROOT / "MEMORY.md"
    owner_md = WORKSPACE_ROOT / "NOTES.md"
    archive_md = WORKSPACE_ROOT / "MEMORY_ARCHIVE.md"

    metrics = {
        "memory_exists": memory_md.exists(),
        "owner_exists": owner_md.exists(),
        "archive_exists": archive_md.exists(),
    }

    missing = []
    if not memory_md.exists():
        missing.append("MEMORY.md")
    if not owner_md.exists():
        missing.append("NOTES.md")
    if not archive_md.exists():
        missing.append("MEMORY_ARCHIVE.md")

    if missing:
        return ComponentHealth(
            id="memory-system",
            status=HealthStatus.ERROR,
            message=f"Missing: {', '.join(missing)}",
            last_check=datetime.now().isoformat(),
            metrics=metrics
        )

    return ComponentHealth(
        id="memory-system",
        status=HealthStatus.HEALTHY,
        message="Dual memory active",
        last_check=datetime.now().isoformat(),
        metrics=metrics
    )


def check_memory_claude() -> ComponentHealth:
    """Check the agent's memory file (MEMORY.md)."""
    file_path = WORKSPACE_ROOT / "MEMORY.md"
    status, msg, metrics = check_markdown_file(file_path, stale_days=7)
    return ComponentHealth(
        id="memory-claude",
        status=status,
        message=msg,
        last_check=datetime.now().isoformat(),
        metrics=metrics
    )


def check_memory_owner() -> ComponentHealth:
    """Check the operator's memory file (NOTES.md)."""
    file_path = WORKSPACE_ROOT / "NOTES.md"
    status, msg, metrics = check_markdown_file(file_path, stale_days=7)
    return ComponentHealth(
        id="memory-owner",
        status=status,
        message=msg,
        last_check=datetime.now().isoformat(),
        metrics=metrics
    )


def check_memory_archive() -> ComponentHealth:
    """Check memory archive file."""
    file_path = WORKSPACE_ROOT / "MEMORY_ARCHIVE.md"
    # Archive doesn't need freshness check - it's append-only
    status, msg, metrics = check_file_exists(file_path)
    return ComponentHealth(
        id="memory-archive",
        status=status,
        message=msg,
        last_check=datetime.now().isoformat(),
        metrics=metrics
    )


def check_skills_system() -> ComponentHealth:
    """Check the agent harness skills system."""
    dir_path = WORKSPACE_ROOT / "harness dir" / "skills"
    status, msg, metrics = check_skills_directory(dir_path)
    return ComponentHealth(
        id="skills-system",
        status=status,
        message=msg,
        last_check=datetime.now().isoformat(),
        metrics=metrics
    )


def check_commands_system() -> ComponentHealth:
    """Check the agent harness commands system."""
    dir_path = WORKSPACE_ROOT / "harness dir" / "commands"
    status, msg, metrics = check_commands_directory(dir_path)
    return ComponentHealth(
        id="commands-system",
        status=status,
        message=msg,
        last_check=datetime.now().isoformat(),
        metrics=metrics
    )


def check_guardrails_system() -> ComponentHealth:
    """Check guardrails file."""
    file_path = WORKSPACE_ROOT / "GUARDRAILS.md"
    status, msg, metrics = check_file_exists(file_path)
    return ComponentHealth(
        id="guardrails-system",
        status=status,
        message="Boundaries active" if status == HealthStatus.HEALTHY else msg,
        last_check=datetime.now().isoformat(),
        metrics=metrics
    )


def check_projects_system() -> ComponentHealth:
    """Check projects system - count active project directories."""
    metrics = {}
    project_dirs = ["<business>", "Legal"]
    existing = []

    for proj in project_dirs:
        if (WORKSPACE_ROOT / proj).exists():
            existing.append(proj)

    metrics["project_count"] = len(existing)
    metrics["projects"] = existing

    return ComponentHealth(
        id="projects-system",
        status=HealthStatus.HEALTHY,
        message=f"{len(existing)} active projects",
        last_check=datetime.now().isoformat(),
        metrics=metrics
    )


def check_project_edgeflow() -> ComponentHealth:
    """Check EdgeFlowAI LP project."""
    dir_path = WORKSPACE_ROOT / "<business>"
    status, msg, metrics = check_directory(dir_path)
    return ComponentHealth(
        id="project-edgeflow",
        status=status,
        message=msg,
        last_check=datetime.now().isoformat(),
        metrics=metrics
    )


def check_project_legal() -> ComponentHealth:
    """Check Legal project."""
    dir_path = WORKSPACE_ROOT / "Legal"
    status, msg, metrics = check_directory(dir_path)
    return ComponentHealth(
        id="project-legal",
        status=status,
        message=msg,
        last_check=datetime.now().isoformat(),
        metrics=metrics
    )


def check_learning_system() -> ComponentHealth:
    """Check self-improvement system."""
    debrief_cmd = WORKSPACE_ROOT / "harness dir" / "commands" / "debrief.md"

    metrics = {
        "debrief_exists": debrief_cmd.exists(),
    }

    if not debrief_cmd.exists():
        return ComponentHealth(
            id="learning-system",
            status=HealthStatus.DEGRADED,
            message="Debrief command missing",
            last_check=datetime.now().isoformat(),
            metrics=metrics
        )

    return ComponentHealth(
        id="learning-system",
        status=HealthStatus.HEALTHY,
        message="Self-improvement active",
        last_check=datetime.now().isoformat(),
        metrics=metrics
    )


def check_debrief_engine() -> ComponentHealth:
    """Check debrief command file."""
    file_path = WORKSPACE_ROOT / "harness dir" / "commands" / "debrief.md"
    status, msg, metrics = check_file_exists(file_path)
    return ComponentHealth(
        id="debrief-engine",
        status=status,
        message=msg,
        last_check=datetime.now().isoformat(),
        metrics=metrics
    )


def check_debriefs_log() -> ComponentHealth:
    """Check debriefs.jsonl file."""
    file_path = IHIM_ROOT / "data" / "debriefs.jsonl"
    status, msg, metrics = check_jsonl_file(file_path)
    return ComponentHealth(
        id="debriefs-log",
        status=status,
        message=msg,
        last_check=datetime.now().isoformat(),
        metrics=metrics
    )


def check_slash_commands() -> ComponentHealth:
    """Check commands API component."""
    dir_path = IHIM_ROOT / "api" / "commands"
    status, msg, metrics = check_directory(dir_path)
    return ComponentHealth(
        id="slash-commands",
        status=status,
        message=msg,
        last_check=datetime.now().isoformat(),
        metrics=metrics
    )


def check_data_slash_commands() -> ComponentHealth:
    """Check slash_commands.json data file."""
    file_path = IHIM_ROOT / "data" / "slash_commands.json"
    status, msg, metrics = check_json_file(file_path)

    # Override stale check for this file
    if status == HealthStatus.DEGRADED and "stale" in msg.lower():
        status = HealthStatus.HEALTHY
        msg = f"{metrics.get('key_count', 0)} commands defined"

    return ComponentHealth(
        id="data-slash-commands",
        status=status,
        message=msg,
        last_check=datetime.now().isoformat(),
        metrics=metrics
    )


# =========================================================================
# MAIN CHECK FUNCTIONS
# =========================================================================

# Map of component IDs to their check functions
HEALTH_CHECKS: Dict[str, callable] = {
    # workspace-level systems (top of hierarchy)
    "workspace-root": check_workspace_root,
    "memory-system": check_memory_system,
    "memory-claude": check_memory_claude,
    "memory-owner": check_memory_owner,
    "memory-archive": check_memory_archive,
    "skills-system": check_skills_system,
    "commands-system": check_commands_system,
    "guardrails-system": check_guardrails_system,
    "projects-system": check_projects_system,
    "project-edgeflow": check_project_edgeflow,
    "project-legal": check_project_legal,
    "learning-system": check_learning_system,
    "debrief-engine": check_debrief_engine,
    "debriefs-log": check_debriefs_log,

    # iHIM systems (child of workspace)
    "ihim-root": check_ihim_root,
    "api-server": check_api_server,
    "actions-registry": check_actions_registry,
    "slash-commands": check_slash_commands,
    "team-system": check_team_system,
    "team-spawner": check_team_spawner,
    "team-router": check_team_router,
    "team-state": check_team_state,
    "feedback-system": check_feedback_system,
    "feedback-processor": check_feedback_processor,
    "feedback-aggregator": check_feedback_aggregator,
    "feedback-optimizer": check_feedback_optimizer,
    "feedback-metrics": check_feedback_metrics,
    "data-stores": check_data_stores,
    "data-slash-commands": check_data_slash_commands,
    "data-team-state": check_data_team_state,
    "sanity-check": check_sanity,
    "ui-assets": check_ui_assets,
    "ui-dashboard": check_ui_dashboard,
    "ui-styles": check_ui_styles,
}


def check_component_health(component_id: str) -> Optional[ComponentHealth]:
    """
    Check health of a specific component.

    Returns None if component ID is unknown.
    """
    check_fn = HEALTH_CHECKS.get(component_id)
    if check_fn:
        try:
            return check_fn()
        except Exception as e:
            return ComponentHealth(
                id=component_id,
                status=HealthStatus.ERROR,
                message=f"Check failed: {str(e)[:50]}",
                last_check=datetime.now().isoformat(),
            )
    return None


def check_all_health() -> SystemHealth:
    """
    Check health of all components.

    Returns complete system health status.
    """
    components = []
    error_count = 0
    degraded_count = 0

    for component_id in HEALTH_CHECKS:
        health = check_component_health(component_id)
        if health:
            components.append(health)
            if health.status == HealthStatus.ERROR:
                error_count += 1
            elif health.status == HealthStatus.DEGRADED:
                degraded_count += 1

    # Determine overall status
    if error_count > 0:
        overall = HealthStatus.ERROR
    elif degraded_count > 0:
        overall = HealthStatus.DEGRADED
    else:
        overall = HealthStatus.HEALTHY

    return SystemHealth(
        components=components,
        overall_status=overall,
    )
