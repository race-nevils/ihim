"""Vault API — Tasks / Projects / Documents browser over the brain index.

Renamed from api/dashboard in the 2026-06 refactor (only the Vault widget
consumes it). Task completion lives in the task_status table — UI-only
state, deliberately NOT part of the JSON-LD source of truth.
"""

from typing import Optional

from fastapi import APIRouter, Query, Request

from api.errors import problem
from data.database import (
    count_by_category,
    get_entries_paginated,
    get_entry_by_id,
    get_projects_with_status,
    get_tasks_with_status,
    toggle_task_completion,
)

router = APIRouter(prefix="/api/vault", tags=["vault"])


@router.get("/tasks")
async def vault_tasks():
    """Dated tasks with completion status, chronological."""
    tasks = get_tasks_with_status()
    return {"success": True, "count": len(tasks), "tasks": tasks}


@router.get("/projects")
async def vault_projects():
    """Undated projects with completion status, newest first."""
    projects = get_projects_with_status()
    return {"success": True, "count": len(projects), "projects": projects}


@router.patch("/tasks/{entry_id}/toggle")
async def vault_toggle(entry_id: str, request: Request):
    """Toggle completion for a task or project."""
    if not get_entry_by_id(entry_id):
        return problem(404, f"Entry not found: {entry_id}", instance=request.url.path)
    return {"success": True, **toggle_task_completion(entry_id)}


@router.get("/categories")
async def vault_categories():
    """Category list with counts."""
    return {"success": True, "categories": count_by_category()}


@router.get("/entries")
async def vault_entries(
    category: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    sort: str = Query("created_at"),
):
    """Paginated document browser."""
    result = get_entries_paginated(category=category, limit=limit, offset=offset, sort=sort)
    return {"success": True, **result}
