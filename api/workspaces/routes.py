"""
Workspaces API routes.

Serves workspace data from the agent's memory manifest.
"""

import json
from pathlib import Path
from typing import Dict, List, Any
from fastapi import APIRouter, HTTPException
from datetime import datetime

router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])

# Absolute path to manifest (outside git, in the agent's memory)
MANIFEST_PATH = Path(r"C:\Users\<user>\harness dir\projects\C--Users-<user>-workspace\memory\workspaces.json")


def _load_manifest() -> Dict[str, List[Dict[str, Any]]]:
    """Load workspaces manifest from the agent's memory directory."""
    if not MANIFEST_PATH.exists():
        return {"workspaces": []}

    try:
        with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {"workspaces": []}
    except json.JSONDecodeError:
        # Corrupted manifest - return empty, log warning
        print(f"WARNING: Corrupted workspace manifest at {MANIFEST_PATH}")
        return {"workspaces": []}
    except Exception as e:
        print(f"ERROR loading workspace manifest: {e}")
        return {"workspaces": []}


@router.get("")
async def list_workspaces():
    """
    Get list of all workspaces.

    Returns workspace manifest with name, branch, purpose, status, timestamps.
    """
    manifest = _load_manifest()
    workspaces = manifest.get("workspaces", [])

    # Enrich with computed fields if needed
    for workspace in workspaces:
        # Add relative time since last activity (future enhancement)
        if "last_activity" in workspace:
            try:
                last_active = datetime.fromisoformat(workspace["last_activity"].replace("Z", "+00:00"))
                workspace["last_activity_relative"] = _relative_time(last_active)
            except:
                workspace["last_activity_relative"] = "unknown"

    return {
        "success": True,
        "workspaces": workspaces,
        "count": len(workspaces)
    }


@router.get("/status")
async def workspace_status():
    """
    Quick summary of workspace state.

    Returns count of active workspaces and basic health info.
    """
    manifest = _load_manifest()
    workspaces = manifest.get("workspaces", [])

    active_count = sum(1 for w in workspaces if w.get("status") == "active")
    merged_count = sum(1 for w in workspaces if w.get("status") == "merged")
    stale_count = sum(1 for w in workspaces if w.get("status") == "stale")

    return {
        "success": True,
        "total": len(workspaces),
        "active": active_count,
        "merged": merged_count,
        "stale": stale_count
    }


def _relative_time(dt: datetime) -> str:
    """Convert datetime to relative time string (e.g., '2 hours ago')."""
    now = datetime.now(dt.tzinfo)
    delta = now - dt

    if delta.days > 0:
        return f"{delta.days}d ago"
    elif delta.seconds >= 3600:
        return f"{delta.seconds // 3600}h ago"
    elif delta.seconds >= 60:
        return f"{delta.seconds // 60}m ago"
    else:
        return "just now"
