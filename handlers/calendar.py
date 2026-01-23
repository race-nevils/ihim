"""Calendar handler: parse and schedule calendar events (stub)."""
import sys
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from orchestrator.state import OrchestratorState


def handle(state: OrchestratorState) -> OrchestratorState:
    """Handle calendar intent: parse date/time and schedule event.

    This is a stub - calendar integration will be implemented later.
    Future plans:
    - Parse natural language dates/times
    - Integrate with Google Calendar or Outlook
    - Support recurring events

    Args:
        state: Current orchestrator state

    Returns:
        Updated state with stub result
    """
    content = state.get("input_text", "")

    # For now, just acknowledge the intent
    state["result"] = {
        "action": "calendar_stub",
        "message": "Calendar integration not implemented yet",
        "detected_input": content[:100] + "..." if len(content) > 100 else content,
        "future_features": [
            "Natural language date parsing",
            "Google Calendar integration",
            "Outlook integration",
            "Recurring events"
        ]
    }

    return state
