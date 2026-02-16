"""
Team Builder API Routes

Endpoints for creating, managing, and spawning custom agent teams.

Routers:
  - ``router``       → /api/teams  (template CRUD, structured spawn, instances)
  - ``team_router``  → /api/team   (basic spawn/status/collapse/results/reset)
"""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from typing import Optional, List
import re
import sys
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from team import route_prompt, spawn_agent_team, collapse_team
from team.team_builder import (
    # Models
    AgentRole,
    TeamTemplate,
    TeamInstance,
    # Template CRUD
    load_templates,
    get_template,
    create_template,
    update_template,
    delete_template,
    # Instance management
    create_instance,
    update_instance_status,
    get_active_instances,
    get_instance,
    # Prompt generation
    route_to_team,
)

from team.spawner import get_team_status, collect_results
from team.state import get_team_state, reset_team_state

router = APIRouter(prefix="/api/teams", tags=["Team Builder"])


# =============================================================================
# HELPERS
# =============================================================================

def count_tiers(agents: list) -> dict:
    """
    Count the agent vs the agent agents in a template.

    Heuristic: If agent ID contains 'sonnet' or lacks 'scout/worker/observer/haiku',
    and constraints don't include 'READ ONLY', it's a the agent.
    """
    sonnet_count = 0
    haiku_count = 0

    for agent in agents:
        agent_id = agent.id.lower() if hasattr(agent, 'id') else agent.get('id', '').lower()
        constraints = agent.constraints if hasattr(agent, 'constraints') else agent.get('constraints', [])

        # Check if READ ONLY constraint (typically the agent)
        is_read_only = any('read only' in c.lower() for c in constraints)

        # Check ID patterns
        haiku_patterns = ['scout', 'worker', 'observer', 'haiku', 'verifier']
        is_haiku_pattern = any(p in agent_id for p in haiku_patterns)

        if is_read_only or is_haiku_pattern:
            haiku_count += 1
        else:
            sonnet_count += 1

    return {"sonnet": sonnet_count, "haiku": haiku_count}


# =============================================================================
# REQUEST/RESPONSE MODELS
# =============================================================================

class CreateTemplateRequest(BaseModel):
    """Request to create a new team template."""
    id: str = Field(..., min_length=2, max_length=50, pattern="^[a-z0-9-]+$",
                    description="Unique ID (lowercase, hyphens only)")
    name: str = Field(..., min_length=2, max_length=100)
    description: str = Field(..., min_length=10, max_length=500)
    agents: list[AgentRole] = Field(..., min_length=2, max_length=10)
    min_agents: int = Field(default=3, ge=1, le=5)
    max_agents: int = Field(default=5, ge=3, le=10)
    tags: list[str] = Field(default_factory=list)


class UpdateTemplateRequest(BaseModel):
    """Request to update an existing template."""
    name: Optional[str] = Field(None, min_length=2, max_length=100)
    description: Optional[str] = Field(None, min_length=10, max_length=500)
    agents: Optional[list[AgentRole]] = None
    tags: Optional[list[str]] = None


class SpawnTeamRequest(BaseModel):
    """Request to spawn a team from a template."""
    template_id: str = Field(..., description="Which template to use")
    task_description: str = Field(..., min_length=10, max_length=2000,
                                   description="What the team should work on")
    project: str = Field(default="workspace", description="Project name")
    agent_subset: Optional[list[str]] = Field(None, description="Optional: spawn only these agents")


class QuickSpawnRequest(BaseModel):
    """Quick spawn with minimal config - just describe what you need."""
    description: str = Field(..., min_length=10, max_length=2000,
                             description="Describe what you need the team to do")
    team_size: int = Field(default=3, ge=2, le=10,
                          description="How many agents (2-10)")
    project: str = Field(default="workspace")


# =============================================================================
# TEMPLATE ENDPOINTS
# =============================================================================

@router.get("/templates")
async def list_templates(tag: Optional[str] = None):
    """
    List all available team templates.

    Optionally filter by tag (e.g., ?tag=development).

    Returns:
        List of templates with basic info.
    """
    templates = load_templates()

    if tag:
        templates = [t for t in templates if tag.lower() in [x.lower() for x in t.tags]]

    return {
        "count": len(templates),
        "templates": [
            {
                "id": t.id,
                "name": t.name,
                "description": t.description,
                "agent_count": len(t.agents),
                "tiers": count_tiers(t.agents),
                "tags": t.tags,
                "use_count": t.use_count
            }
            for t in templates
        ]
    }


@router.get("/templates/{template_id}")
async def get_template_details(template_id: str):
    """
    Get full details of a specific template.

    Returns:
        Complete template including all agent definitions.
    """
    template = get_template(template_id)

    if not template:
        raise HTTPException(status_code=404, detail=f"Template '{template_id}' not found")

    return {
        "success": True,
        "template": template.model_dump()
    }


@router.post("/templates", status_code=201)
async def create_new_template(request: CreateTemplateRequest):
    """
    Create a new team template.

    Define your own specialized team with custom agents.

    Returns:
        The created template.
    """
    try:
        template = TeamTemplate(
            id=request.id,
            name=request.name,
            description=request.description,
            agents=request.agents,
            min_agents=request.min_agents,
            max_agents=request.max_agents,
            tags=request.tags
        )
        created = create_template(template)
        return {
            "success": True,
            "template": created.model_dump()
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/templates/{template_id}")
async def update_existing_template(template_id: str, request: UpdateTemplateRequest):
    """
    Update an existing template.

    Only provided fields will be updated.

    Returns:
        The updated template.
    """
    updates = request.model_dump(exclude_none=True)

    if not updates:
        raise HTTPException(status_code=400, detail="No updates provided")

    updated = update_template(template_id, updates)

    if not updated:
        raise HTTPException(status_code=404, detail=f"Template '{template_id}' not found")

    return {
        "success": True,
        "template": updated.model_dump()
    }


@router.delete("/templates/{template_id}")
async def delete_existing_template(template_id: str):
    """
    Delete a template.

    Cannot delete built-in templates (software-dev, project-management, etc.).
    """
    # Protect built-in templates
    protected = ["software-dev", "project-management", "research", "security-audit"]
    if template_id in protected:
        raise HTTPException(status_code=403, detail=f"Cannot delete built-in template '{template_id}'")

    deleted = delete_template(template_id)

    if not deleted:
        raise HTTPException(status_code=404, detail=f"Template '{template_id}' not found")

    return {"success": True, "message": f"Template '{template_id}' deleted"}


# =============================================================================
# SPAWN ENDPOINTS
# =============================================================================

@router.post("/spawn")
async def spawn_team(request: SpawnTeamRequest):
    """
    Spawn a team from a template.

    Opens the agent harness CLI sessions in Windows Terminal,
    one tab per agent. Each agent gets a tailored prompt.

    Args:
        template_id: Which template to use
        task_description: What the team should work on
        project: Project name (default: workspace)
        agent_subset: Optional list of agent IDs to spawn (defaults to all)

    Returns:
        Spawn status with session info.
    """
    # Get template
    template = get_template(request.template_id)
    if not template:
        raise HTTPException(status_code=404, detail=f"Template '{request.template_id}' not found")

    # Validate agent subset if provided
    if request.agent_subset:
        valid_agents = {a.id for a in template.agents}
        invalid = set(request.agent_subset) - valid_agents
        if invalid:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid agent IDs: {invalid}. Valid: {valid_agents}"
            )
        # Ensure subset is not empty after validation
        if not request.agent_subset:
            raise HTTPException(
                status_code=400,
                detail="Agent subset cannot be empty"
            )

    # Route task to agents (generate tailored prompts)
    try:
        routed_prompts = route_to_team(
            template=template,
            task_description=request.task_description,
            project=request.project,
            agent_subset=request.agent_subset
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate agent prompts: {str(e)}"
        )

    # Spawn the agents
    result = spawn_agent_team(
        routed_prompts=routed_prompts,
        feature_description=request.task_description
    )

    if result["success"]:
        # Create instance record
        try:
            instance = create_instance(
                template_id=request.template_id,
                task_description=request.task_description,
                agent_ids=list(routed_prompts.keys()),
                session_id=result.get("session_id")
            )

            # Update team state
            state = get_team_state()
            state.spawn(
                prompt=request.task_description,
                project=request.project,
                agents=list(routed_prompts.keys())
            )
        except Exception as e:
            # State update failed, but agents are spawned
            # Log the error but don't fail the entire operation
            print(f"WARNING: Failed to update team state/instance: {e}")
            instance = None

        return {
            "success": True,
            "message": f"Spawned {len(routed_prompts)} agents from '{template.name}'",
            "instance_id": instance.id if instance else None,
            "session_id": result.get("session_id"),
            "agents": list(routed_prompts.keys()),
            "template": template.name,
            "spawned_at": result.get("spawned_at"),
            "blackboard": result.get("blackboard")
        }
    else:
        return {
            "success": False,
            "message": result.get("message", "Spawn failed"),
            "agents": []
        }


@router.get("/templates/{template_id}/agents")
async def list_template_agents(template_id: str):
    """
    Get the agents available in a template.

    Useful for UI that lets users select which agents to spawn.

    Returns:
        List of agents with their roles and expertise.
    """
    template = get_template(template_id)

    if not template:
        raise HTTPException(status_code=404, detail=f"Template '{template_id}' not found")

    return {
        "template_id": template_id,
        "template_name": template.name,
        "agents": [
            {
                "id": a.id,
                "name": a.name,
                "expertise": a.expertise,
                "responsibilities": a.responsibilities[:3] if a.responsibilities else [],  # First 3
                "collaborates_with": a.collaborates_with
            }
            for a in template.agents
        ]
    }


# =============================================================================
# INSTANCE ENDPOINTS
# =============================================================================

@router.get("/instances")
async def list_instances(active_only: bool = True):
    """
    List team instances.

    Args:
        active_only: If true, only return non-completed instances.

    Returns:
        List of team instances.
    """
    if active_only:
        instances = get_active_instances()
    else:
        from team.team_builder import load_instances
        instances = load_instances()

    return {
        "count": len(instances),
        "instances": [i.model_dump() for i in instances]
    }


@router.get("/instances/{instance_id}")
async def get_instance_details(instance_id: str):
    """
    Get details of a specific instance.

    Returns:
        Instance info including status and agents.
    """
    instance = get_instance(instance_id)

    if not instance:
        raise HTTPException(status_code=404, detail=f"Instance '{instance_id}' not found")

    return {
        "success": True,
        "instance": instance.model_dump()
    }


@router.put("/instances/{instance_id}/status")
async def update_instance(instance_id: str, status: str):
    """
    Update an instance's status.

    Valid statuses: spawning, active, completed, failed

    Returns:
        Updated instance.
    """
    valid_statuses = ["spawning", "active", "completed", "failed"]
    if status not in valid_statuses:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status. Must be one of: {valid_statuses}"
        )

    updated = update_instance_status(instance_id, status)

    if not updated:
        raise HTTPException(status_code=404, detail=f"Instance '{instance_id}' not found")

    return {
        "success": True,
        "instance": updated.model_dump()
    }


# =============================================================================
# QUICK ACTIONS
# =============================================================================

@router.get("/quick")
async def get_quick_options():
    """
    Get quick spawn options for the UI.

    Returns template suggestions based on common use cases.
    """
    templates = load_templates()

    return {
        "suggestions": [
            {
                "id": t.id,
                "name": t.name,
                "description": t.description,
                "agent_count": len(t.agents),
                "popularity": t.use_count
            }
            for t in sorted(templates, key=lambda x: x.use_count, reverse=True)[:5]
        ],
        "prompts": [
            {"label": "Build a new feature", "template": "software-dev"},
            {"label": "Plan a project", "template": "project-management"},
            {"label": "Research a topic", "template": "research"},
            {"label": "Security audit", "template": "security-audit"},
        ]
    }


# =============================================================================
# BASIC TEAM ROUTES (legacy /api/team/ prefix — moved from main.py)
# =============================================================================

team_router = APIRouter(prefix="/api/team", tags=["Team"])


class SpawnRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=5000, description="Task description")
    project: str = Field(default="workspace", min_length=1, max_length=100)
    agents: Optional[List[str]] = Field(None, min_items=1, max_items=20, description="Custom agent list")
    team_name: Optional[str] = Field(None, min_length=1, max_length=100, description="Name for custom teams")

    @classmethod
    def validate_agent_names(cls, v):
        if v is None:
            return v
        pattern = re.compile(r'^[a-zA-Z0-9_-]+$')
        for agent in v:
            if not pattern.match(agent):
                raise ValueError(f"Invalid agent name '{agent}'. Only alphanumeric, dash, and underscore allowed.")
            if len(agent) > 50:
                raise ValueError(f"Agent name '{agent}' exceeds max length of 50 characters.")
        return v


class CustomSpawnRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=5000, description="Task description")
    team_type: str = Field(default="auto", min_length=1, max_length=50, pattern=r'^[a-zA-Z0-9_-]+$')
    team_size: int = Field(default=3, ge=1, le=20, description="Number of agents (1-20)")
    project: str = Field(default="workspace", min_length=1, max_length=100)
    options: Optional[dict] = None


@team_router.post("/spawn")
async def basic_spawn_team(request: SpawnRequest):
    """Spawn an agent team (basic — one prompt, morphed per agent)."""
    routed_prompts = route_prompt(
        prompt=request.prompt,
        project=request.project,
        agents=request.agents
    )

    feature_desc = request.team_name or request.prompt[:50]
    result = spawn_agent_team(routed_prompts, feature_description=feature_desc)

    if result["success"]:
        state = get_team_state()
        state.spawn(
            prompt=request.prompt,
            project=request.project,
            agents=list(routed_prompts.keys())
        )

    return result


@team_router.post("/spawn-custom")
async def spawn_custom_team(request: CustomSpawnRequest):
    """Spawn a custom agent team based on team type and size."""
    template_map = {
        "auto": "software-dev",
        "project": "project-management",
        "research": "research",
        "custom": "software-dev"
    }

    template_id = template_map.get(request.team_type, "software-dev")

    try:
        spawn_req = SpawnTeamRequest(
            template_id=template_id,
            task_description=request.prompt,
            project=request.project
        )
        result = await spawn_team(spawn_req)
        return result
    except Exception:
        pass

    # Fallback: use basic route_prompt
    routed_prompts = route_prompt(
        prompt=request.prompt,
        project=request.project
    )

    if len(routed_prompts) > request.team_size:
        agents_to_keep = list(routed_prompts.keys())[:request.team_size]
        routed_prompts = {k: v for k, v in routed_prompts.items() if k in agents_to_keep}

    result = spawn_agent_team(routed_prompts, feature_description=request.prompt[:50])

    if result["success"]:
        state = get_team_state()
        state.spawn(
            prompt=request.prompt,
            project=request.project,
            agents=list(routed_prompts.keys())
        )

    return result


@team_router.get("/status")
async def team_status():
    """Get current team status."""
    return get_team_status()


@team_router.post("/collapse")
async def collapse_team_endpoint():
    """Collapse the team — close all agent tabs."""
    result = collapse_team()
    if result["success"]:
        state = get_team_state()
        state.collapse()
    return result


@team_router.get("/results")
async def team_results():
    """Get all agent results."""
    return collect_results()


@team_router.post("/reset")
async def reset_team():
    """Reset team state and clear all files."""
    reset_team_state()
    return {"success": True, "message": "Team state reset"}
