"""
Blackboard System - Shared communication for agent collaboration

The blackboard is a shared JSON file that agents read/write to coordinate.
Agents poll the blackboard periodically to see updates from other agents.

Design principles:
- Simple JSON format (easy to read/write)
- Minimal schema (3 core fields, 2 optional)
- Agents write naturally, system adapts
"""

import json
import time
import random
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field
from enum import Enum


# Paths
TEAM_PATH = Path(__file__).parent
BLACKBOARD_FILE = TEAM_PATH / "blackboard.json"


class Phase(str, Enum):
    """Build phases for hybrid approach."""
    PHASE_1_BUILD = "build"        # Parallel work
    PHASE_2_SYNC = "sync"          # Share what was built
    PHASE_3_INTEGRATE = "integrate" # Wire things together
    PHASE_4_VERIFY = "verify"      # DevOps verifies it works
    COMPLETE = "complete"


@dataclass
class Message:
    """
    A message on the blackboard.

    Core fields (required):
        agent: Who posted (serializes as "from")
        timestamp: When
        message: What they said

    Optional fields (add when needed):
        type: "DONE", "QUESTION", "DELIVERABLE", etc.
        to: Target agent for directed messages
    """
    agent: str          # Who posted
    timestamp: str      # When
    message: str        # What they said
    type: Optional[str] = None   # Optional: DONE, QUESTION, DELIVERABLE, BLOCKER
    to: Optional[str] = None     # Optional: Target agent

    def to_dict(self) -> dict:
        """Serialize to JSON-friendly dict. Uses 'from' key for agent."""
        d = {
            "from": self.agent,
            "timestamp": self.timestamp,
            "message": self.message,
        }
        if self.type:
            d["type"] = self.type
        if self.to:
            d["to"] = self.to
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "Message":
        """Parse from JSON dict. Accepts both 'from' and 'agent' keys."""
        return cls(
            agent=data.get("from") or data.get("agent", "unknown"),
            timestamp=data.get("timestamp", ""),
            message=data.get("message") or data.get("content", ""),
            type=data.get("type"),
            to=data.get("to") or data.get("target"),
        )


@dataclass
class Blackboard:
    """The shared blackboard state."""
    feature: str                    # What we're building
    phase: Phase                    # Current phase
    started_at: str                 # When spawn started
    messages: List[Message]         # All messages
    agent_status: Dict[str, str]    # agent -> status
    deliverables: Dict[str, List[str]]  # agent -> list of files/endpoints created

    def to_dict(self) -> dict:
        return {
            "feature": self.feature,
            "phase": self.phase.value if isinstance(self.phase, Phase) else self.phase,
            "started_at": self.started_at,
            "messages": [m.to_dict() for m in self.messages],
            "agent_status": self.agent_status,
            "deliverables": self.deliverables,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Blackboard":
        return cls(
            feature=data["feature"],
            phase=Phase(data["phase"]) if data["phase"] in [e.value for e in Phase] else data["phase"],
            started_at=data["started_at"],
            messages=[Message.from_dict(m) for m in data.get("messages", [])],
            agent_status=data.get("agent_status", {}),
            deliverables=data.get("deliverables", {}),
        )


def init_blackboard(feature: str, agents: List[str]) -> Blackboard:
    """
    Initialize a fresh blackboard for a new feature build.

    Args:
        feature: Description of what we're building
        agents: List of agent names participating

    Returns:
        Initialized Blackboard
    """
    board = Blackboard(
        feature=feature,
        phase=Phase.PHASE_1_BUILD,
        started_at=datetime.now().isoformat(),
        messages=[],
        agent_status={agent: "starting" for agent in agents},
        deliverables={agent: [] for agent in agents},
    )
    save_blackboard(board)
    return board


def save_blackboard(board: Blackboard) -> bool:
    """
    Save blackboard to file with file locking.

    Uses a simple retry mechanism to handle concurrent writes.
    """
    max_retries = 3
    for attempt in range(max_retries):
        try:
            # Write to temp file first, then rename (atomic on most systems)
            temp_file = BLACKBOARD_FILE.with_suffix('.tmp')
            temp_file.write_text(
                json.dumps(board.to_dict(), indent=2),
                encoding="utf-8"
            )
            temp_file.replace(BLACKBOARD_FILE)
            return True
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(0.1 * (attempt + 1))  # Backoff
            else:
                print(f"Failed to save blackboard: {e}")
                return False
    return False


def load_blackboard() -> Optional[Blackboard]:
    """Load blackboard from file."""
    if not BLACKBOARD_FILE.exists():
        return None

    try:
        data = json.loads(BLACKBOARD_FILE.read_text(encoding="utf-8"))
        return Blackboard.from_dict(data)
    except Exception as e:
        print(f"Failed to load blackboard: {e}")
        return None


def post_message(
    agent: str,
    message: str,
    msg_type: Optional[str] = None,
    to: Optional[str] = None,
) -> bool:
    """
    Post a message to the blackboard.

    Args:
        agent: Who is posting
        message: What they're saying
        msg_type: Optional type (DONE, QUESTION, DELIVERABLE, etc.)
        to: Optional target agent

    Returns:
        True if successful
    """
    board = load_blackboard()
    if not board:
        return False

    msg = Message(
        agent=agent,
        timestamp=datetime.now().isoformat(),
        message=message,
        type=msg_type,
        to=to,
    )

    board.messages.append(msg)
    return save_blackboard(board)


def update_status(agent: str, status: str) -> bool:
    """Update an agent's status."""
    board = load_blackboard()
    if not board:
        return False

    board.agent_status[agent] = status
    return save_blackboard(board)


def add_deliverable(agent: str, deliverable: str) -> bool:
    """Record something an agent created."""
    board = load_blackboard()
    if not board:
        return False

    if agent not in board.deliverables:
        board.deliverables[agent] = []
    board.deliverables[agent].append(deliverable)

    return save_blackboard(board)


def get_messages_for_agent(agent: str) -> List[Message]:
    """Get messages targeted at a specific agent (or broadcast to all)."""
    board = load_blackboard()
    if not board:
        return []

    return [m for m in board.messages if m.to is None or m.to == agent]


def get_messages(
    msg_type: Optional[str] = None,
    for_agent: Optional[str] = None
) -> List[Message]:
    """
    Get messages from the blackboard with optional filters.

    Args:
        msg_type: Filter by type (e.g., "QUESTION", "DONE")
        for_agent: Filter by target agent

    Returns:
        List of matching messages
    """
    board = load_blackboard()
    if not board:
        return []

    messages = board.messages

    if msg_type:
        messages = [m for m in messages if m.type and m.type.upper() == msg_type.upper()]

    if for_agent:
        messages = [m for m in messages if m.to == for_agent or m.to is None]

    return messages


def get_done_agents() -> List[str]:
    """Get list of agents that have posted DONE status."""
    board = load_blackboard()
    if not board:
        return []

    return [
        m.agent for m in board.messages
        if m.type and m.type.upper() == "DONE"
    ]


def get_questions(for_agent: Optional[str] = None) -> List[Message]:
    """Get questions, optionally filtered by target agent."""
    board = load_blackboard()
    if not board:
        return []

    questions = [m for m in board.messages if m.type and m.type.upper() == "QUESTION"]

    if for_agent:
        questions = [q for q in questions if q.to == for_agent]

    return questions


def get_blockers() -> List[Message]:
    """Get blocker messages."""
    board = load_blackboard()
    if not board:
        return []

    return [m for m in board.messages if m.type and m.type.upper() == "BLOCKER"]


def check_phase_ready() -> bool:
    """Check if all agents are done with current phase."""
    board = load_blackboard()
    if not board:
        return False

    # All agents must have status "complete" or posted DONE
    done_agents = set(get_done_agents())
    complete_agents = {a for a, s in board.agent_status.items() if s == "complete"}

    all_done = done_agents | complete_agents
    return len(all_done) >= len(board.agent_status)


def advance_phase() -> Optional[Phase]:
    """Advance to the next phase if all agents ready."""
    board = load_blackboard()
    if not board:
        return None

    phase_order = [
        Phase.PHASE_1_BUILD,
        Phase.PHASE_2_SYNC,
        Phase.PHASE_3_INTEGRATE,
        Phase.PHASE_4_VERIFY,
        Phase.COMPLETE,
    ]

    current_idx = phase_order.index(board.phase)
    if current_idx < len(phase_order) - 1:
        board.phase = phase_order[current_idx + 1]
        save_blackboard(board)
        return board.phase

    return board.phase


def get_poll_interval(agent: str) -> float:
    """
    Get staggered poll interval for an agent.

    Each agent gets a slightly different base interval to avoid
    all agents hitting the file at the same time.

    Base: 8 seconds
    Jitter: ±2 seconds
    Stagger: 1 second offset per agent

    Result: agents poll roughly every 8-12 seconds, staggered
    """
    # Create deterministic offset based on agent name
    agent_hash = int(hashlib.md5(agent.encode()).hexdigest()[:4], 16)
    offset = (agent_hash % 5)  # 0-4 second offset

    base_interval = 8.0
    jitter = random.uniform(-2.0, 2.0)

    return base_interval + offset + jitter


def poll_loop(agent: str, callback, max_iterations: Optional[int] = None):
    """
    Poll the blackboard and call callback with updates.

    Args:
        agent: This agent's name
        callback: Function to call with (board, new_messages)
        max_iterations: Optional limit (for testing)
    """
    last_msg_count = 0
    iterations = 0

    while max_iterations is None or iterations < max_iterations:
        interval = get_poll_interval(agent)
        time.sleep(interval)

        board = load_blackboard()
        if not board:
            continue

        # Check for new messages
        new_messages = board.messages[last_msg_count:]
        last_msg_count = len(board.messages)

        # Filter to messages relevant to this agent
        relevant = [
            m for m in new_messages
            if m.target is None or m.target == agent
        ]

        if relevant or board.phase != Phase.PHASE_1_BUILD:
            callback(board, relevant)

        iterations += 1


def clear_blackboard() -> bool:
    """Clear the blackboard (for reset)."""
    if BLACKBOARD_FILE.exists():
        BLACKBOARD_FILE.unlink()
    return True


# === Convenience functions for agents ===

def agent_post(agent: str, message: str, msg_type: Optional[str] = None, to: Optional[str] = None) -> bool:
    """Post a message to the blackboard."""
    return post_message(agent, message, msg_type=msg_type, to=to)


def agent_done(agent: str, summary: str) -> bool:
    """Mark agent as done with summary of work."""
    update_status(agent, "complete")
    return post_message(agent, summary, msg_type="DONE")


def agent_ask(agent: str, target: str, question: str) -> bool:
    """Ask another agent a question."""
    return post_message(agent, question, msg_type="QUESTION", to=target)


def agent_deliver(agent: str, description: str, files: List[str]) -> bool:
    """Record a deliverable."""
    for f in files:
        add_deliverable(agent, f)
    return post_message(agent, f"{description}: {', '.join(files)}", msg_type="DELIVERABLE")


def agent_blocked(agent: str, blocker: str) -> bool:
    """Report being blocked."""
    update_status(agent, "blocked")
    return post_message(agent, blocker, msg_type="BLOCKER")


def get_blackboard_summary() -> dict:
    """Get a summary of the current blackboard state."""
    board = load_blackboard()
    if not board:
        return {"active": False, "message": "No blackboard initialized"}

    return {
        "active": True,
        "feature": board.feature,
        "phase": board.phase.value if isinstance(board.phase, Phase) else board.phase,
        "started_at": board.started_at,
        "message_count": len(board.messages),
        "agents": board.agent_status,
        "deliverables_count": sum(len(d) for d in board.deliverables.values()),
        "blockers": len(get_blockers()),
        "questions": len(get_questions()),
        "done_agents": get_done_agents(),
    }


# ============================================================================
# AGENT INSTRUCTIONS - Injected into agent prompts for coordination
# ============================================================================

BLACKBOARD_INSTRUCTIONS = """
## Agent Coordination via Blackboard

You are part of a multi-agent team. Use the blackboard file for coordination.

**Blackboard file**: `C:/Users/<user>/workspace/IHIM/team/blackboard.json`

### Message Format (Simple)

Add to the "messages" array:
```json
{
  "from": "YOUR_AGENT_NAME",
  "timestamp": "2025-12-26T10:00:00Z",
  "message": "What you did or what you need"
}
```

That's it. Three fields. Add optional fields only when needed:
- `"type": "QUESTION"` - when asking another agent something
- `"type": "DONE"` - when you're finished
- `"to": "frontend-dev"` - when targeting a specific agent

### Examples

Status update:
```json
{"from": "qa-tester", "timestamp": "...", "message": "Test suite complete. 45 tests passed."}
```

Question to another agent:
```json
{"from": "backend-dev", "type": "QUESTION", "to": "frontend-dev", "timestamp": "...", "message": "What endpoint format do you expect?"}
```

Done with work:
```json
{"from": "frontend-dev", "type": "DONE", "timestamp": "...", "message": "Modal complete. Added search, categories, click-to-copy."}
```

### When You're Done

1. Post a message summarizing what you built
2. Update your status in `agent_status` to "complete"
3. Add files you created to `deliverables`
4. Write result to: `C:/Users/<user>/workspace/IHIM/team/results/{YOUR_AGENT_NAME}-result.json`
"""
