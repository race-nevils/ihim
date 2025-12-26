"""
Health check system - monitors status of all iHIM components.
"""

import json
import importlib
import os
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List

from .models import ComponentHealth, HealthStatus, SystemHealth
from .topology import get_system_topology, IHIM_ROOT


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


def check_blackboard() -> ComponentHealth:
    """Check blackboard file."""
    file_path = IHIM_ROOT / "team" / "blackboard.json"

    if not file_path.exists():
        return ComponentHealth(
            id="blackboard",
            status=HealthStatus.INACTIVE,
            message="No active session",
            last_check=datetime.now().isoformat(),
        )

    status, msg, metrics = check_json_file(file_path)

    # Get additional blackboard info
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            metrics["phase"] = data.get("phase", "unknown")
            metrics["message_count"] = len(data.get("messages", []))
    except Exception:
        pass

    return ComponentHealth(
        id="blackboard",
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


def check_data_tasks() -> ComponentHealth:
    """Check tasks.json file."""
    file_path = IHIM_ROOT / "data" / "tasks.json"
    status, msg, metrics = check_json_file(file_path)

    # For tasks, staleness is expected - override to healthy if valid
    if status == HealthStatus.DEGRADED and "Valid" in msg or "stale" in msg:
        status = HealthStatus.HEALTHY
        msg = f"{metrics.get('item_count', 0)} tasks"

    return ComponentHealth(
        id="data-tasks",
        status=status,
        message=msg,
        last_check=datetime.now().isoformat(),
        metrics=metrics
    )


def check_data_notes() -> ComponentHealth:
    """Check notes.json file."""
    file_path = IHIM_ROOT / "data" / "notes.json"
    status, msg, metrics = check_json_file(file_path)

    # For notes, staleness is expected - override to healthy if valid
    if status == HealthStatus.DEGRADED and "Valid" in msg or "stale" in msg:
        status = HealthStatus.HEALTHY
        msg = f"{metrics.get('item_count', 0)} notes"

    return ComponentHealth(
        id="data-notes",
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
# MAIN CHECK FUNCTIONS
# =========================================================================

# Map of component IDs to their check functions
HEALTH_CHECKS: Dict[str, callable] = {
    "ihim-root": check_ihim_root,
    "api-server": check_api_server,
    "actions-registry": check_actions_registry,
    "team-system": check_team_system,
    "team-spawner": check_team_spawner,
    "team-router": check_team_router,
    "team-state": check_team_state,
    "blackboard": check_blackboard,
    "feedback-system": check_feedback_system,
    "feedback-processor": check_feedback_processor,
    "feedback-aggregator": check_feedback_aggregator,
    "feedback-optimizer": check_feedback_optimizer,
    "feedback-metrics": check_feedback_metrics,
    "data-stores": check_data_stores,
    "data-tasks": check_data_tasks,
    "data-notes": check_data_notes,
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
