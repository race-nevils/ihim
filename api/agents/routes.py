"""
Agent Configuration API - CRUD operations for agent definitions.
Stores agent configs in harness/agents/ directory for the agent harness integration.
"""

from fastapi import APIRouter
from pydantic import BaseModel
from typing import List, Optional
from pathlib import Path
import json

router = APIRouter(prefix="/api/agents", tags=["agents"])

# Storage location - harness/agents/ in workspace root
WORKSPACE_ROOT = Path(__file__).parent.parent.parent.parent
AGENTS_DIR = WORKSPACE_ROOT / "harness dir" / "agents"
AGENTS_FILE = AGENTS_DIR / "agents.json"


class AgentConfig(BaseModel):
    id: str
    name: str
    tier: str  # haiku, sonnet, opus
    description: str
    skills: List[str] = []


def ensure_storage():
    """Ensure the agents storage directory and file exist."""
    AGENTS_DIR.mkdir(parents=True, exist_ok=True)
    if not AGENTS_FILE.exists():
        AGENTS_FILE.write_text("[]", encoding="utf-8")


def load_agents() -> List[dict]:
    """Load all agents from storage."""
    ensure_storage()
    try:
        return json.loads(AGENTS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, FileNotFoundError):
        return []


def save_agents(agents: List[dict]):
    """Save agents to storage."""
    ensure_storage()
    AGENTS_FILE.write_text(
        json.dumps(agents, indent=2),
        encoding="utf-8"
    )


@router.get("")
async def get_agents():
    """Get all saved agent configurations."""
    agents = load_agents()
    return {"agents": agents, "count": len(agents)}


@router.post("")
async def save_agent(agent: AgentConfig):
    """Save or update an agent configuration."""
    agents = load_agents()

    # Check if agent exists (update) or is new (create)
    existing_idx = next(
        (i for i, a in enumerate(agents) if a["id"] == agent.id),
        None
    )

    agent_dict = agent.model_dump()

    if existing_idx is not None:
        agents[existing_idx] = agent_dict
        action = "updated"
    else:
        agents.append(agent_dict)
        action = "created"

    save_agents(agents)

    return {
        "success": True,
        "message": f"Agent '{agent.name}' {action}",
        "agent": agent_dict
    }


@router.delete("/{agent_id}")
async def delete_agent(agent_id: str):
    """Delete an agent configuration."""
    agents = load_agents()

    original_count = len(agents)
    agents = [a for a in agents if a["id"] != agent_id]

    if len(agents) == original_count:
        return {"success": False, "message": f"Agent '{agent_id}' not found"}

    save_agents(agents)
    return {"success": True, "message": f"Agent '{agent_id}' deleted"}


@router.get("/{agent_id}")
async def get_agent(agent_id: str):
    """Get a specific agent configuration."""
    agents = load_agents()
    agent = next((a for a in agents if a["id"] == agent_id), None)

    if not agent:
        return {"success": False, "message": f"Agent '{agent_id}' not found"}

    return {"success": True, "agent": agent}
