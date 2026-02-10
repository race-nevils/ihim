"""Vault Dashboard API routes.

Endpoints for the Tasks/Projects/Documents dashboard window.
Task completion state lives in task_status table (UI-only, not in JSON-LD SSOT).
"""

from fastapi import APIRouter

from data.database import (
    get_tasks_with_status,
    get_projects_with_status,
    toggle_task_completion,
    get_entries_paginated,
    get_entry_by_id,
    count_by_category,
)

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/tasks")
async def dashboard_tasks():
    """Get dated tasks with completion status, ordered chronologically."""
    tasks = get_tasks_with_status()
    return {
        "success": True,
        "count": len(tasks),
        "tasks": tasks,
    }


@router.get("/projects")
async def dashboard_projects():
    """Get undated projects with completion status, newest first."""
    projects = get_projects_with_status()
    return {
        "success": True,
        "count": len(projects),
        "projects": projects,
    }


@router.patch("/tasks/{entry_id}/toggle")
async def dashboard_toggle(entry_id: str):
    """Toggle completion status for a task or project."""
    entry = get_entry_by_id(entry_id)
    if not entry:
        return {"success": False, "error": f"Entry not found: {entry_id}"}

    new_state = toggle_task_completion(entry_id)
    return {
        "success": True,
        **new_state,
    }


@router.get("/categories")
async def dashboard_categories():
    """Get category list with counts."""
    counts = count_by_category()
    return {
        "success": True,
        "categories": counts,
    }


@router.get("/entries")
async def dashboard_entries(
    category: str = None,
    limit: int = 50,
    offset: int = 0,
    sort: str = "created_at",
):
    """Paginated document browser for any category."""
    result = get_entries_paginated(
        category=category,
        limit=min(limit, 100),
        offset=max(offset, 0),
        sort=sort,
    )
    return {
        "success": True,
        **result,
    }
