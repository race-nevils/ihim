"""
Workspaces API routes.

Auto-discovers branches and branches from git.
Manifest provides optional enrichment (purpose, custom names).
"""

import json
import subprocess
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from fastapi import APIRouter, HTTPException
from datetime import datetime

router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])

REPO_DIR = r"C:\Users\<user>\workspace"
MANIFEST_PATH = Path(r"C:\Users\<user>\harness dir\projects\C--Users-<user>-workspace\memory\workspaces.json")
EXCLUDE_BRANCHES = {"main", "master"}


def _load_manifest() -> Dict[str, Dict[str, Any]]:
    """Load manifest as a branch-keyed lookup for enrichment."""
    if not MANIFEST_PATH.exists():
        return {}
    try:
        with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            entries = data.get("workspaces", []) if isinstance(data, dict) else []
            return {e["branch"]: e for e in entries if "branch" in e}
    except Exception:
        return {}


def _git_discover() -> Tuple[Dict[str, str], List[str]]:
    """Discover branches and branches from git.

    Returns:
        branches: {branch: worktree_path}
        branches: [all branch names]
    """
    branches = {}
    branches = []

    # Get branches
    try:
        result = subprocess.run(
            ["git", "branch", "list", "--porcelain"],
            capture_output=True, text=True, timeout=5, cwd=REPO_DIR
        )
        if result.returncode == 0:
            current_path = None
            for line in result.stdout.splitlines():
                if line.startswith("branch "):
                    current_path = line[len("branch "):].strip()
                elif line.startswith("branch ") and current_path:
                    branch = line[len("branch "):].strip().replace("refs/heads/", "")
                    branches[branch] = current_path
    except Exception:
        pass

    # Get all branches
    try:
        result = subprocess.run(
            ["git", "branch", "--format=%(refname:short)"],
            capture_output=True, text=True, timeout=5, cwd=REPO_DIR
        )
        if result.returncode == 0:
            branches = [b.strip() for b in result.stdout.splitlines() if b.strip()]
    except Exception:
        pass

    return branches, branches


def _branch_last_commit(branch: str) -> Optional[str]:
    """Get ISO timestamp of last commit on branch."""
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%aI", branch],
            capture_output=True, text=True, timeout=5, cwd=REPO_DIR
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        pass
    return None


def _branch_to_name(branch: str) -> str:
    """Convert branch name to display name. feature/foo-bar -> foo-bar"""
    # Strip common prefixes
    for prefix in ("feature/", "fix/", "hotfix/", "chore/", "refactor/"):
        if branch.startswith(prefix):
            return branch[len(prefix):]
    return branch


def _build_workspaces() -> List[Dict[str, Any]]:
    """Build workspace list from git state + manifest enrichment."""
    branches, branches = _git_discover()
    manifest = _load_manifest()

    # Deduplicate: use branches as the master list (branches are a subset)
    seen = set()
    workspaces = []

    for branch in branches:
        if branch in EXCLUDE_BRANCHES:
            continue
        if branch in seen:
            continue
        seen.add(branch)

        has_worktree = branch in branches
        enrichment = manifest.get(branch, {})

        ws = {
            "name": enrichment.get("name", _branch_to_name(branch)),
            "branch": branch,
            "status": "active" if has_worktree else "branch-only",
            "has_worktree": has_worktree,
        }

        if has_worktree:
            ws["path"] = branches[branch]

        # Manifest enrichment (purpose, custom dates)
        if enrichment.get("purpose"):
            ws["purpose"] = enrichment["purpose"]

        # Last activity from git commit timestamp
        commit_time = _branch_last_commit(branch)
        if commit_time:
            ws["last_activity"] = commit_time

        workspaces.append(ws)

    return workspaces


@router.get("")
async def list_workspaces():
    """
    Auto-discover workspaces from git branches and branches.
    Manifest enriches with purpose/custom names. Main branch excluded.
    """
    workspaces = _build_workspaces()

    # Add relative time
    for ws in workspaces:
        if "last_activity" in ws:
            try:
                last_active = datetime.fromisoformat(ws["last_activity"])
                ws["last_activity_relative"] = _relative_time(last_active)
            except Exception:
                ws["last_activity_relative"] = "unknown"

    return {
        "success": True,
        "workspaces": workspaces,
        "count": len(workspaces)
    }


@router.get("/status")
async def workspace_status():
    """Quick summary of workspace state."""
    workspaces = _build_workspaces()

    active_count = sum(1 for w in workspaces if w.get("status") == "active")
    branch_only = sum(1 for w in workspaces if w.get("status") == "branch-only")

    return {
        "success": True,
        "total": len(workspaces),
        "active": active_count,
        "branch_only": branch_only
    }


def _relative_time(dt: datetime) -> str:
    """Convert datetime to relative time string."""
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
