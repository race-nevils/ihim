"""
Team State Management

Tracks the state of the agent team:
- Is a team active?
- What agents are running?
- What are the results?
"""

import json
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, asdict
from typing import Optional, Dict, List


# Paths
IHIM_PATH = Path("C:/Users/<user>/workspace/IHIM")
STATE_FILE = IHIM_PATH / "team" / "team_state.json"
RESULTS_PATH = IHIM_PATH / "team" / "results"


@dataclass
class AgentStatus:
    """Status of a single agent."""
    name: str
    status: str  # idle, working, completed, error
    task_file: Optional[str] = None
    result_file: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


@dataclass
class TeamState:
    """State of the entire agent team."""
    active: bool = False
    spawned_at: Optional[str] = None
    collapsed_at: Optional[str] = None
    original_prompt: Optional[str] = None
    project: Optional[str] = None
    agents: Dict[str, dict] = None

    def __post_init__(self):
        if self.agents is None:
            self.agents = {}

    @classmethod
    def load(cls) -> 'TeamState':
        """Load team state from file."""
        if STATE_FILE.exists():
            try:
                data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
                return cls(**data)
            except Exception:
                pass
        return cls()

    def save(self):
        """Save team state to file."""
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(
            json.dumps(asdict(self), indent=2),
            encoding="utf-8"
        )

    def spawn(self, prompt: str, project: str, agents: List[str]):
        """Record that a team has been spawned."""
        self.active = True
        self.spawned_at = datetime.now().isoformat()
        self.collapsed_at = None
        self.original_prompt = prompt
        self.project = project
        self.agents = {
            agent: {
                "status": "working",
                "started_at": datetime.now().isoformat(),
            }
            for agent in agents
        }
        self.save()

    def collapse(self):
        """Record that the team has been collapsed."""
        self.active = False
        self.collapsed_at = datetime.now().isoformat()
        for agent in self.agents:
            if self.agents[agent]["status"] == "working":
                self.agents[agent]["status"] = "cancelled"
        self.save()

    def mark_completed(self, agent: str, result: dict = None):
        """Mark an agent as completed."""
        if agent in self.agents:
            self.agents[agent]["status"] = "completed"
            self.agents[agent]["completed_at"] = datetime.now().isoformat()
            if result:
                self.agents[agent]["result"] = result
        self.save()

    def mark_error(self, agent: str, error: str):
        """Mark an agent as errored."""
        if agent in self.agents:
            self.agents[agent]["status"] = "error"
            self.agents[agent]["error"] = error
        self.save()

    def get_status_summary(self) -> dict:
        """Get a summary of team status."""
        if not self.active:
            return {
                "active": False,
                "message": "No team active"
            }

        statuses = [a.get("status", "unknown") for a in self.agents.values()]

        return {
            "active": True,
            "spawned_at": self.spawned_at,
            "original_prompt": self.original_prompt,
            "project": self.project,
            "agents": {
                name: info.get("status", "unknown")
                for name, info in self.agents.items()
            },
            "working": statuses.count("working"),
            "completed": statuses.count("completed"),
            "error": statuses.count("error"),
        }

    def all_completed(self) -> bool:
        """Check if all agents have completed."""
        if not self.agents:
            return False
        return all(
            a.get("status") in ["completed", "error", "cancelled"]
            for a in self.agents.values()
        )


def get_team_state() -> TeamState:
    """Get the current team state."""
    return TeamState.load()


def reset_team_state():
    """Reset the team state to empty."""
    state = TeamState()
    state.save()

    # Also clear result files
    RESULTS_PATH.mkdir(parents=True, exist_ok=True)
    for result_file in RESULTS_PATH.glob("*-result.json"):
        result_file.unlink()
