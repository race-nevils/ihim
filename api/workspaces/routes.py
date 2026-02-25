"""
Workspaces API routes.

Auto-discovers branches and branches from git.
Manifest provides optional enrichment (purpose, custom names).
Rich git state: merge status, ahead/behind, dirty branches, remote tracking.
"""

import json
import subprocess
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from fastapi import APIRouter
from datetime import datetime, timezone

router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])

REPO_DIR = r"C:\Users\<user>\workspace"
MANIFEST_PATH = Path(r"C:\Users\<user>\harness dir\projects\C--Users-<user>-workspace\memory\workspaces.json")
EXCLUDE_BRANCHES = {"main", "master"}
STALE_DAYS = 14


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


def _run_git(*args, cwd=None) -> Optional[str]:
    """Run a git command and return stdout, or None on failure."""
    try:
        result = subprocess.run(
            ["git"] + list(args),
            capture_output=True, timeout=5,
            cwd=cwd or REPO_DIR
        )
        if result.returncode == 0:
            return result.stdout.decode("utf-8", errors="replace")
    except Exception:
        pass
    return None


def _discover_worktrees() -> Dict[str, str]:
    """Discover branches from git. Returns {branch: worktree_path}."""
    branches = {}
    output = _run_git("branch", "list", "--porcelain")
    if not output:
        return branches

    current_path = None
    for line in output.splitlines():
        if line.startswith("branch "):
            current_path = line[len("branch "):].strip()
        elif line.startswith("branch ") and current_path:
            branch = line[len("branch "):].strip().replace("refs/heads/", "")
            branches[branch] = current_path

    return branches


def _batch_branch_metadata() -> Dict[str, Dict[str, Any]]:
    """Single git for-each-ref call to get all branch metadata at once.

    Returns {branch: {date, message, upstream}} for all branches.
    """
    fmt = "%(refname:short)%09%(committerdate:iso-strict)%09%(subject)%09%(upstream:short)"
    output = _run_git("for-each-ref", f"--format={fmt}", "refs/heads/")
    if not output:
        return {}

    metadata = {}
    for line in output.splitlines():
        parts = line.split("\t")
        if len(parts) >= 3:
            branch = parts[0].strip()
            metadata[branch] = {
                "date": parts[1].strip() if parts[1].strip() else None,
                "message": parts[2].strip() if parts[2].strip() else None,
                "upstream": parts[3].strip() if len(parts) > 3 and parts[3].strip() else None,
            }

    return metadata


def _merged_branches() -> set:
    """Get set of branches that are merged into main."""
    output = _run_git("branch", "--merged", "main", "--format=%(refname:short)")
    if not output:
        return set()
    return {b.strip() for b in output.splitlines() if b.strip()}


def _ahead_behind(branch: str) -> Tuple[int, int]:
    """Get ahead/behind counts relative to main. Returns (ahead, behind)."""
    output = _run_git("rev-list", "--left-right", "--count", f"main...{branch}")
    if not output:
        return (0, 0)
    parts = output.strip().split()
    if len(parts) == 2:
        try:
            # left-right: left=main ahead, right=branch ahead
            # So: behind_main = parts[0], ahead_of_main = parts[1]
            return (int(parts[1]), int(parts[0]))
        except ValueError:
            pass
    return (0, 0)


def _worktree_dirty(path: str) -> Tuple[bool, int]:
    """Check if a branch has uncommitted changes. Returns (is_dirty, file_count)."""
    output = _run_git("-C", path, "status", "--porcelain")
    if output is None:
        return (False, 0)
    lines = [l for l in output.splitlines() if l.strip()]
    return (len(lines) > 0, len(lines))


def _compute_status(
    has_worktree: bool,
    is_merged: bool,
    ahead: int,
    behind: int,
    last_commit_date: Optional[str],
) -> str:
    """Compute workspace status from git state.

    Priority: active branch > diverged > merged (no branch) > stale > branch-only.
    A branch with a branch is 'active' even if merged — merged without branch
    means it's a leftover branch that can be cleaned up.
    """
    if has_worktree:
        return "active"
    if ahead > 0 and behind > 0:
        return "diverged"
    if is_merged:
        return "merged"
    # Check staleness
    if last_commit_date:
        try:
            commit_dt = datetime.fromisoformat(last_commit_date)
            if commit_dt.tzinfo is None:
                commit_dt = commit_dt.replace(tzinfo=timezone.utc)
            now = datetime.now(commit_dt.tzinfo)
            if (now - commit_dt).days > STALE_DAYS:
                return "stale"
        except Exception:
            pass
    return "branch-only"


def _branch_to_name(branch: str) -> str:
    """Convert branch name to display name. feature/foo-bar -> foo-bar"""
    for prefix in ("feature/", "fix/", "hotfix/", "chore/", "refactor/"):
        if branch.startswith(prefix):
            return branch[len(prefix):]
    return branch


def _build_workspaces() -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """Build workspace list from git state + manifest enrichment.

    Returns (workspaces, summary).
    """
    branches = _discover_worktrees()
    branch_meta = _batch_branch_metadata()
    merged = _merged_branches()
    manifest = _load_manifest()

    all_branches = [b for b in branch_meta.keys() if b not in EXCLUDE_BRANCHES]

    # Also include any branch branches not in branch_meta (edge case)
    for branch in branches:
        if branch not in EXCLUDE_BRANCHES and branch not in branch_meta:
            all_branches.append(branch)

    summary = {"total": 0, "active": 0, "merged": 0, "dirty": 0, "branches": 0}
    workspaces = []

    for branch in all_branches:
        meta = branch_meta.get(branch, {})
        has_worktree = branch in branches
        is_merged = branch in merged
        ahead, behind = _ahead_behind(branch)

        # Dirty check only for branches
        is_dirty = False
        dirty_count = 0
        if has_worktree:
            is_dirty, dirty_count = _worktree_dirty(branches[branch])

        status = _compute_status(
            has_worktree, is_merged, ahead, behind, meta.get("date")
        )

        enrichment = manifest.get(branch, {})

        ws = {
            "name": enrichment.get("name", _branch_to_name(branch)),
            "branch": branch,
            "status": status,
            "has_worktree": has_worktree,
            "is_merged": is_merged,
            "ahead_count": ahead,
            "behind_count": behind,
            "last_commit_message": meta.get("message"),
            "has_remote": bool(meta.get("upstream")),
            "is_dirty": is_dirty,
            "dirty_files_count": dirty_count,
        }

        if has_worktree:
            ws["path"] = branches[branch]

        if enrichment.get("purpose"):
            ws["purpose"] = enrichment["purpose"]

        # Last activity from git commit timestamp
        if meta.get("date"):
            ws["last_activity"] = meta["date"]

        workspaces.append(ws)

        # Update summary
        summary["total"] += 1
        if status == "active":
            summary["active"] += 1
        if status == "merged":
            summary["merged"] += 1
        if is_dirty:
            summary["dirty"] += 1
        if has_worktree:
            summary["branches"] += 1

    return workspaces, summary


@router.get("")
async def list_workspaces():
    """
    Auto-discover workspaces from git branches and branches.
    Rich git state: merge status, ahead/behind, dirty branches, remote tracking.
    """
    workspaces, summary = _build_workspaces()

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
        "count": len(workspaces),
        "summary": summary,
    }


@router.get("/status")
async def workspace_status():
    """Quick summary of workspace state."""
    _, summary = _build_workspaces()

    return {
        "success": True,
        **summary,
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
