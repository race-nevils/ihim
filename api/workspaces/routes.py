"""Workspaces API — live git branch/branch monitor.

Auto-discovers branches and branches from git; the optional manifest file
adds enrichment (purpose, display names). Response shape is the contract the
Workspaces widget renders: status, ahead/behind, staged/modified/untracked/
conflicted breakdown, last activity (newest of commit date and branch
mtime, which catches uncommitted churn).

The repo root is derived from this file's location (IHIM/ lives inside the
repo) and can be overridden with IHIM_WORKSPACE_ROOT. `git branch list` reports
all branches from any of them, so this works identically whether the server
runs from the main repo or a branch.
"""

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter

router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])

REPO_DIR = os.environ.get("IHIM_WORKSPACE_ROOT") or str(Path(__file__).resolve().parents[3])
MANIFEST_PATH = Path(os.environ.get(
    "IHIM_WORKSPACES_MANIFEST",
    str(Path.home() / "harness dir" / "projects" / "C--Users-<user>-workspace" / "memory" / "workspaces.json"),
))
EXCLUDE_BRANCHES = {"main", "master"}
STALE_DAYS = 14


def _load_manifest() -> Dict[str, Dict[str, Any]]:
    if not MANIFEST_PATH.exists():
        return {}
    try:
        data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        entries = data.get("workspaces", []) if isinstance(data, dict) else []
        return {e["branch"]: e for e in entries if "branch" in e}
    except Exception:
        return {}


def _run_git(*args: str, cwd: Optional[str] = None) -> Optional[str]:
    """Run git with fixed arguments (never user input); None on failure."""
    try:
        result = subprocess.run(
            ["git", *args], capture_output=True, timeout=5, cwd=cwd or REPO_DIR,
        )
        if result.returncode == 0:
            return result.stdout.decode("utf-8", errors="replace")
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def _discover_worktrees() -> Dict[str, str]:
    """{branch: worktree_path} from `git branch list --porcelain`."""
    branches: Dict[str, str] = {}
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
    """One for-each-ref call: {branch: {date, message, upstream}}."""
    fmt = "%(refname:short)%09%(committerdate:iso-strict)%09%(subject)%09%(upstream:short)"
    output = _run_git("for-each-ref", "--sort=-committerdate", f"--format={fmt}", "refs/heads/")
    if not output:
        return {}
    metadata = {}
    for line in output.splitlines():
        parts = line.split("\t")
        if len(parts) >= 3:
            metadata[parts[0].strip()] = {
                "date": parts[1].strip() or None,
                "message": parts[2].strip() or None,
                "upstream": parts[3].strip() if len(parts) > 3 and parts[3].strip() else None,
            }
    return metadata


def _merged_branches() -> set:
    output = _run_git("branch", "--merged", "main", "--format=%(refname:short)")
    if not output:
        return set()
    return {b.strip() for b in output.splitlines() if b.strip()}


def _ahead_behind(branch: str) -> Tuple[int, int]:
    """(ahead_of_main, behind_main) via rev-list --left-right --count."""
    output = _run_git("rev-list", "--left-right", "--count", f"main...{branch}")
    if not output:
        return (0, 0)
    parts = output.strip().split()
    if len(parts) == 2:
        try:
            return (int(parts[1]), int(parts[0]))
        except ValueError:
            pass
    return (0, 0)


def _empty_status_counts() -> Dict[str, int]:
    return {"total": 0, "staged": 0, "modified": 0, "untracked": 0, "conflicted": 0}


def _parse_porcelain_status(output: str) -> Dict[str, int]:
    """Bucket porcelain v1 codes. Buckets overlap by design: 'MM' counts as
    both staged and modified. total == line count == legacy dirty count."""
    counts = _empty_status_counts()
    if not output:
        return counts
    for line in output.splitlines():
        if len(line) < 2:
            continue
        x, y = line[0], line[1]
        xy = line[:2]
        counts["total"] += 1
        if xy == "??":
            counts["untracked"] += 1
        elif x == "U" or y == "U" or xy in ("AA", "DD"):
            counts["conflicted"] += 1
        else:
            if x in "MADRCT":
                counts["staged"] += 1
            if y in "MDT":
                counts["modified"] += 1
    return counts


def _worktree_dirty(path: str) -> Tuple[bool, Dict[str, int]]:
    output = _run_git("-C", path, "status", "--porcelain")
    if output is None:
        return (False, _empty_status_counts())
    counts = _parse_porcelain_status(output)
    return (counts["total"] > 0, counts)


def _compute_status(has_worktree: bool, is_merged: bool, ahead: int, behind: int,
                    last_commit_date: Optional[str]) -> str:
    """active branch > diverged > merged (no branch) > stale > branch-only."""
    if has_worktree:
        return "active"
    if ahead > 0 and behind > 0:
        return "diverged"
    if is_merged:
        return "merged"
    if last_commit_date:
        try:
            commit_dt = datetime.fromisoformat(last_commit_date)
            if commit_dt.tzinfo is None:
                commit_dt = commit_dt.replace(tzinfo=timezone.utc)
            if (datetime.now(commit_dt.tzinfo) - commit_dt).days > STALE_DAYS:
                return "stale"
        except ValueError:
            pass
    return "branch-only"


def _branch_to_name(branch: str) -> str:
    for prefix in ("feature/", "fix/", "hotfix/", "chore/", "refactor/"):
        if branch.startswith(prefix):
            return branch[len(prefix):]
    return branch


def _relative_time(dt: datetime) -> str:
    delta = datetime.now(dt.tzinfo) - dt
    if delta.days > 0:
        return f"{delta.days}d ago"
    if delta.seconds >= 3600:
        return f"{delta.seconds // 3600}h ago"
    if delta.seconds >= 60:
        return f"{delta.seconds // 60}m ago"
    return "just now"


def _build_workspaces() -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    branches = _discover_worktrees()
    branch_meta = _batch_branch_metadata()
    merged = _merged_branches()
    manifest = _load_manifest()

    all_branches = [b for b in branch_meta if b not in EXCLUDE_BRANCHES]
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

        is_dirty = False
        status_counts = _empty_status_counts()
        if has_worktree:
            is_dirty, status_counts = _worktree_dirty(branches[branch])

        status = _compute_status(has_worktree, is_merged, ahead, behind, meta.get("date"))
        enrichment = manifest.get(branch, {})

        ws: Dict[str, Any] = {
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
            "dirty_files_count": status_counts["total"],
            "staged_count": status_counts["staged"],
            "modified_count": status_counts["modified"],
            "untracked_count": status_counts["untracked"],
            "conflicted_count": status_counts["conflicted"],
        }
        if has_worktree:
            ws["path"] = branches[branch]
        if enrichment.get("purpose"):
            ws["purpose"] = enrichment["purpose"]

        # Last activity = max(commit date, branch mtime): mtime catches
        # branch switches and uncommitted file churn.
        activity_ts = 0.0
        activity_iso = None
        if meta.get("date"):
            try:
                dt = datetime.fromisoformat(meta["date"])
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                activity_ts, activity_iso = dt.timestamp(), dt.isoformat()
            except ValueError:
                pass
        if has_worktree:
            try:
                mtime = os.path.getmtime(branches[branch])
                if mtime > activity_ts:
                    activity_ts = mtime
                    activity_iso = datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
            except OSError:
                pass
        if activity_iso:
            ws["last_activity"] = activity_iso
        ws["_activity_ts"] = activity_ts

        workspaces.append(ws)
        summary["total"] += 1
        if status == "active":
            summary["active"] += 1
        if status == "merged":
            summary["merged"] += 1
        if is_dirty:
            summary["dirty"] += 1
        if has_worktree:
            summary["branches"] += 1

    workspaces.sort(key=lambda w: w.pop("_activity_ts", 0.0), reverse=True)
    return workspaces, summary


@router.get("")
async def list_workspaces():
    """All branches/branches with rich git state, newest activity first."""
    workspaces, summary = _build_workspaces()
    for ws in workspaces:
        if "last_activity" in ws:
            try:
                ws["last_activity_relative"] = _relative_time(datetime.fromisoformat(ws["last_activity"]))
            except ValueError:
                ws["last_activity_relative"] = "unknown"
    return {"success": True, "workspaces": workspaces, "count": len(workspaces), "summary": summary}


@router.get("/status")
async def workspace_status():
    """Quick summary counts."""
    _, summary = _build_workspaces()
    return {"success": True, **summary}
