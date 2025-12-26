"""
FastAPI routes for the Slash Command Center.

Provides comprehensive API endpoints for:
- Listing and filtering commands
- Managing brainstorm ideas
- Configuring auto-invoke
- Syncing with file system
- Searching and discovery
"""

from fastapi import APIRouter, HTTPException, Query
from typing import Optional, List
from pathlib import Path
from datetime import datetime
import json
import uuid

from .models import (
    SlashCommand,
    SlashCommandIdea,
    CommandCategory,
    IdeaStatus,
    CreateIdeaRequest,
    UpdateIdeaRequest,
    PromoteIdeaRequest,
    UpdateAutoInvokeRequest,
    SyncResultResponse,
)
from .scanner import (
    sync_commands,
    load_command_center_data,
    save_command_center_data,
    get_command_file_content,
    COMMANDS_DIR,
    DATA_FILE,
)


router = APIRouter(prefix="/api/slash-commands", tags=["Slash Commands"])


# =============================================================================
# COMMANDS ENDPOINTS
# =============================================================================

@router.get("")
async def list_commands(
    category: Optional[str] = Query(None, description="Filter by category"),
    status: Optional[str] = Query(None, description="Filter by status"),
    auto_invoke: Optional[bool] = Query(None, description="Filter by auto-invoke enabled"),
    search: Optional[str] = Query(None, description="Search in name and description"),
):
    """
    List all commands with optional filtering.

    Returns the complete command center data including commands,
    categories, and metadata.
    """
    data = load_command_center_data()
    commands = data.get("commands", [])

    # Apply filters
    if category:
        commands = [c for c in commands if c.get("category") == category]

    if status:
        commands = [c for c in commands if c.get("status") == status]

    if auto_invoke is not None:
        commands = [
            c for c in commands
            if c.get("auto_invoke", {}).get("enabled", False) == auto_invoke
        ]

    if search:
        search_lower = search.lower()
        commands = [
            c for c in commands
            if search_lower in c.get("name", "").lower()
            or search_lower in c.get("description", "").lower()
            or search_lower in c.get("short_desc", c.get("shortDesc", "")).lower()
        ]

    return {
        "success": True,
        "count": len(commands),
        "commands": commands,
        "categories": data.get("categories", {}),
        "metadata": data.get("metadata", {}),
    }


@router.get("/summary")
async def get_commands_summary():
    """
    Get a summary of all commands for quick display.

    Returns condensed command info suitable for command palette or quick reference.
    """
    data = load_command_center_data()
    commands = data.get("commands", [])

    summary = []
    for cmd in commands:
        summary.append({
            "id": cmd.get("id"),
            "name": cmd.get("name"),
            "shortDesc": cmd.get("short_desc", cmd.get("shortDesc", "")),
            "category": cmd.get("category"),
            "autoInvoke": cmd.get("auto_invoke", {}).get("enabled", False),
        })

    # Group by category
    by_category = {}
    for cmd in summary:
        cat = cmd["category"]
        if cat not in by_category:
            by_category[cat] = []
        by_category[cat].append(cmd)

    return {
        "success": True,
        "total": len(commands),
        "byCategory": by_category,
        "categories": data.get("categories", {}),
    }


@router.get("/{command_id}")
async def get_command(command_id: str, include_content: bool = False):
    """
    Get detailed information for a specific command.

    Optionally includes the raw markdown content from the .md file.
    """
    data = load_command_center_data()
    commands = data.get("commands", [])

    for cmd in commands:
        if cmd.get("id") == command_id:
            result = {"success": True, "command": cmd}

            if include_content:
                content = get_command_file_content(command_id)
                result["content"] = content

            return result

    raise HTTPException(status_code=404, detail=f"Command '{command_id}' not found")


@router.get("/{command_id}/content")
async def get_command_content(command_id: str):
    """
    Get the raw markdown content for a command.

    Useful for editing or viewing the full command definition.
    """
    content = get_command_file_content(command_id)
    if content is None:
        raise HTTPException(
            status_code=404,
            detail=f"Command file not found: {command_id}.md"
        )

    return {
        "success": True,
        "command_id": command_id,
        "file_path": str(COMMANDS_DIR / f"{command_id}.md"),
        "content": content,
    }


# =============================================================================
# AUTO-INVOKE ENDPOINTS
# =============================================================================

@router.put("/{command_id}/auto-invoke")
async def update_auto_invoke(command_id: str, config: UpdateAutoInvokeRequest):
    """
    Update auto-invoke configuration for a command.

    Allows configuring triggers, priority, cooldown, and confirmation settings.
    """
    data = load_command_center_data()
    commands = data.get("commands", [])

    for cmd in commands:
        if cmd.get("id") == command_id:
            cmd["auto_invoke"] = {
                "enabled": config.enabled,
                "triggers": [t.model_dump() for t in config.triggers],
                "priority": config.priority,
                "cooldown_seconds": config.cooldown_seconds,
                "requires_confirmation": config.requires_confirmation,
            }
            cmd["updated_at"] = datetime.utcnow().isoformat() + "Z"

            save_command_center_data(data)

            return {
                "success": True,
                "command_id": command_id,
                "auto_invoke": cmd["auto_invoke"],
            }

    raise HTTPException(status_code=404, detail=f"Command '{command_id}' not found")


@router.get("/auto-invoke/active")
async def get_auto_invoke_commands():
    """
    Get all commands with auto-invoke enabled.

    Useful for the auto-invoke engine to know what to monitor.
    """
    data = load_command_center_data()
    commands = data.get("commands", [])

    active = [
        {
            "id": cmd.get("id"),
            "name": cmd.get("name"),
            "auto_invoke": cmd.get("auto_invoke", {}),
        }
        for cmd in commands
        if cmd.get("auto_invoke", {}).get("enabled", False)
    ]

    return {
        "success": True,
        "count": len(active),
        "commands": active,
    }


# =============================================================================
# IDEAS ENDPOINTS
# =============================================================================

@router.get("/ideas/all")
async def list_ideas(
    status: Optional[str] = Query(None, description="Filter by status"),
):
    """
    List all command ideas for brainstorming.

    Ideas can be filtered by status (brainstorm, designing, approved, etc.)
    """
    data = load_command_center_data()
    ideas = data.get("ideas", [])

    if status:
        ideas = [i for i in ideas if i.get("status") == status]

    # Sort by priority (highest first), then by votes
    ideas.sort(key=lambda x: (-x.get("priority", 50), -x.get("votes", 0)))

    return {
        "success": True,
        "count": len(ideas),
        "ideas": ideas,
    }


@router.post("/ideas")
async def create_idea(request: CreateIdeaRequest):
    """
    Create a new command idea for brainstorming.

    Ideas can later be promoted to real commands.
    """
    data = load_command_center_data()

    # Ensure name starts with /
    name = request.name if request.name.startswith("/") else f"/{request.name}"

    # Check for duplicate
    existing_ideas = data.get("ideas", [])
    for idea in existing_ideas:
        if idea.get("name", "").lower() == name.lower():
            raise HTTPException(
                status_code=400,
                detail=f"Idea with name '{name}' already exists"
            )

    new_idea = {
        "id": f"idea-{str(uuid.uuid4())[:8]}",
        "name": name,
        "description": request.description,
        "status": "brainstorm",
        "proposed_category": request.proposed_category,
        "use_cases": request.use_cases,
        "implementation_notes": "",
        "priority": request.priority,
        "auto_invoke_potential": request.auto_invoke_potential,
        "potential_triggers": request.potential_triggers,
        "created_at": datetime.utcnow().isoformat() + "Z",
        "created_by": "user",
        "votes": 0,
        "notes": [],
    }

    data.setdefault("ideas", []).append(new_idea)
    save_command_center_data(data)

    return {"success": True, "idea": new_idea}


@router.get("/ideas/{idea_id}")
async def get_idea(idea_id: str):
    """Get details for a specific idea."""
    data = load_command_center_data()

    for idea in data.get("ideas", []):
        if idea.get("id") == idea_id:
            return {"success": True, "idea": idea}

    raise HTTPException(status_code=404, detail=f"Idea '{idea_id}' not found")


@router.put("/ideas/{idea_id}")
async def update_idea(idea_id: str, request: UpdateIdeaRequest):
    """
    Update an existing idea.

    Can update status, description, notes, and other fields.
    """
    data = load_command_center_data()

    for idea in data.get("ideas", []):
        if idea.get("id") == idea_id:
            # Update provided fields
            if request.name is not None:
                idea["name"] = request.name if request.name.startswith("/") else f"/{request.name}"
            if request.description is not None:
                idea["description"] = request.description
            if request.status is not None:
                idea["status"] = request.status.value
            if request.proposed_category is not None:
                idea["proposed_category"] = request.proposed_category
            if request.use_cases is not None:
                idea["use_cases"] = request.use_cases
            if request.implementation_notes is not None:
                idea["implementation_notes"] = request.implementation_notes
            if request.priority is not None:
                idea["priority"] = request.priority
            if request.auto_invoke_potential is not None:
                idea["auto_invoke_potential"] = request.auto_invoke_potential
            if request.potential_triggers is not None:
                idea["potential_triggers"] = request.potential_triggers

            idea["updated_at"] = datetime.utcnow().isoformat() + "Z"

            save_command_center_data(data)
            return {"success": True, "idea": idea}

    raise HTTPException(status_code=404, detail=f"Idea '{idea_id}' not found")


@router.post("/ideas/{idea_id}/vote")
async def vote_idea(idea_id: str, direction: int = Query(1, ge=-1, le=1)):
    """
    Vote on an idea to help prioritize.

    direction: 1 for upvote, -1 for downvote, 0 to reset
    """
    data = load_command_center_data()

    for idea in data.get("ideas", []):
        if idea.get("id") == idea_id:
            if direction == 0:
                idea["votes"] = 0
            else:
                idea["votes"] = idea.get("votes", 0) + direction

            save_command_center_data(data)
            return {"success": True, "idea_id": idea_id, "votes": idea["votes"]}

    raise HTTPException(status_code=404, detail=f"Idea '{idea_id}' not found")


@router.post("/ideas/{idea_id}/note")
async def add_idea_note(idea_id: str, note: str = Query(..., min_length=1)):
    """
    Add a discussion note to an idea.

    Notes help capture thinking and decisions during brainstorming.
    """
    data = load_command_center_data()

    for idea in data.get("ideas", []):
        if idea.get("id") == idea_id:
            idea.setdefault("notes", []).append({
                "text": note,
                "timestamp": datetime.utcnow().isoformat() + "Z",
            })

            save_command_center_data(data)
            return {"success": True, "idea_id": idea_id, "notes": idea["notes"]}

    raise HTTPException(status_code=404, detail=f"Idea '{idea_id}' not found")


@router.post("/ideas/{idea_id}/promote")
async def promote_idea(idea_id: str, request: PromoteIdeaRequest):
    """
    Promote an idea to a real command.

    Creates a new command entry based on the idea.
    The idea is marked as 'implemented' but not deleted.
    """
    data = load_command_center_data()

    # Find the idea
    idea = None
    for i in data.get("ideas", []):
        if i.get("id") == idea_id:
            idea = i
            break

    if not idea:
        raise HTTPException(status_code=404, detail=f"Idea '{idea_id}' not found")

    # Check command doesn't already exist
    cmd_id = idea["name"].lstrip("/")
    for cmd in data.get("commands", []):
        if cmd.get("id") == cmd_id:
            raise HTTPException(
                status_code=400,
                detail=f"Command '{cmd_id}' already exists"
            )

    now = datetime.utcnow().isoformat() + "Z"

    # Create the command
    new_command = {
        "id": cmd_id,
        "name": idea["name"],
        "short_desc": request.short_desc,
        "shortDesc": request.short_desc,
        "description": idea["description"],
        "category": request.category,
        "status": "planned",  # Not active until .md file created
        "source": "promoted",
        "usage": request.usage,
        "examples": request.examples,
        "auto_invoke": {
            "enabled": idea.get("auto_invoke_potential", False),
            "triggers": [{"type": "manual", "description": t} for t in idea.get("potential_triggers", [])],
        },
        "created_at": now,
        "updated_at": now,
        "promoted_from": idea_id,
    }

    data.setdefault("commands", []).append(new_command)

    # Mark idea as implemented
    idea["status"] = "implemented"
    idea["implemented_at"] = now

    save_command_center_data(data)

    return {
        "success": True,
        "command": new_command,
        "note": "Command created as 'planned'. Create .md file and sync to activate.",
    }


@router.delete("/ideas/{idea_id}")
async def delete_idea(idea_id: str):
    """Delete an idea from the brainstorm list."""
    data = load_command_center_data()

    original_count = len(data.get("ideas", []))
    data["ideas"] = [i for i in data.get("ideas", []) if i.get("id") != idea_id]

    if len(data["ideas"]) == original_count:
        raise HTTPException(status_code=404, detail=f"Idea '{idea_id}' not found")

    save_command_center_data(data)
    return {"success": True}


# =============================================================================
# CATEGORIES ENDPOINTS
# =============================================================================

@router.get("/categories/all")
async def list_categories():
    """List all command categories."""
    data = load_command_center_data()
    return {
        "success": True,
        "categories": data.get("categories", {}),
    }


@router.post("/categories")
async def create_category(
    id: str = Query(..., min_length=2),
    name: str = Query(..., min_length=2),
    description: str = Query(...),
    icon: str = Query(""),
):
    """Create a new category for organizing commands."""
    data = load_command_center_data()

    if id in data.get("categories", {}):
        raise HTTPException(status_code=400, detail=f"Category '{id}' already exists")

    new_category = {
        "id": id,
        "name": name,
        "description": description,
        "icon": icon,
        "sort_order": len(data.get("categories", {})),
    }

    data.setdefault("categories", {})[id] = new_category
    save_command_center_data(data)

    return {"success": True, "category": new_category}


# =============================================================================
# SYNC ENDPOINTS
# =============================================================================

@router.post("/sync")
async def sync_from_filesystem():
    """
    Sync commands from harness/commands/ directory.

    Discovers new commands, updates changed ones, and marks
    removed ones as deprecated.
    """
    result = sync_commands()
    return {
        "success": True,
        **result,
    }


@router.get("/sync/status")
async def get_sync_status():
    """
    Check sync status between data store and file system.

    Returns list of commands that differ from their source files.
    """
    data = load_command_center_data()

    file_commands = set()
    for md_file in COMMANDS_DIR.glob("*.md"):
        file_commands.add(md_file.stem)

    data_commands = set(cmd.get("id") for cmd in data.get("commands", []) if cmd.get("source") == "file")

    return {
        "success": True,
        "in_files": list(file_commands),
        "in_data": list(data_commands),
        "missing_in_data": list(file_commands - data_commands),
        "missing_in_files": list(data_commands - file_commands),
        "last_sync": data.get("metadata", {}).get("last_sync"),
    }


# =============================================================================
# SEARCH ENDPOINT
# =============================================================================

@router.get("/search")
async def search_commands(
    q: str = Query(..., min_length=2, description="Search query"),
    include_ideas: bool = Query(True, description="Also search ideas"),
):
    """
    Search across commands and ideas.

    Searches in name, description, and usage fields.
    """
    data = load_command_center_data()
    query_lower = q.lower()

    results = {
        "commands": [],
        "ideas": [],
    }

    # Search commands
    for cmd in data.get("commands", []):
        if (
            query_lower in cmd.get("name", "").lower()
            or query_lower in cmd.get("description", "").lower()
            or query_lower in cmd.get("short_desc", cmd.get("shortDesc", "")).lower()
            or query_lower in cmd.get("usage", "").lower()
        ):
            results["commands"].append({
                "id": cmd.get("id"),
                "name": cmd.get("name"),
                "shortDesc": cmd.get("short_desc", cmd.get("shortDesc", "")),
                "category": cmd.get("category"),
            })

    # Search ideas
    if include_ideas:
        for idea in data.get("ideas", []):
            if (
                query_lower in idea.get("name", "").lower()
                or query_lower in idea.get("description", "").lower()
            ):
                results["ideas"].append({
                    "id": idea.get("id"),
                    "name": idea.get("name"),
                    "description": idea.get("description")[:100],
                    "status": idea.get("status"),
                })

    return {
        "success": True,
        "query": q,
        "total": len(results["commands"]) + len(results["ideas"]),
        **results,
    }
