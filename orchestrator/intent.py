"""Intent detection for the orchestrator."""
import sys
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from adapters.ollama import OllamaAdapter
from orchestrator.state import OrchestratorState


INTENT_PROMPT = """Analyze this input and determine the user's intent.
Return ONLY valid JSON with no extra text: {"intent": "<type>", "confidence": <0.0-1.0>}

Intent types:
- brain: storing a thought, note, memory, observation, idea, reference
- chat: asking a question, wanting a conversation, seeking information
- calendar: scheduling, meetings, appointments, dates, reminders with specific times
- task: creating a todo, action item, task without specific time

Examples:
- "Meeting with John at 5pm Thursday" -> {"intent": "calendar", "confidence": 0.95}
- "What's the capital of France?" -> {"intent": "chat", "confidence": 0.90}
- "Remember to buy milk" -> {"intent": "task", "confidence": 0.85}
- "Interesting idea about neural networks..." -> {"intent": "brain", "confidence": 0.88}

Input: {input_text}

JSON response:"""


def detect_intent(state: OrchestratorState) -> OrchestratorState:
    """Detect the intent of the input text using the fast model.

    Args:
        state: Current orchestrator state

    Returns:
        Updated state with intent and confidence
    """
    adapter = OllamaAdapter()
    input_text = state.get("input_text", "")

    if not input_text.strip():
        state["intent"] = "unknown"
        state["intent_confidence"] = 0.0
        return state

    try:
        result = adapter.generate_json(
            INTENT_PROMPT.format(input_text=input_text),
            model=OllamaAdapter.FAST_MODEL
        )
        state["intent"] = result.get("intent", "unknown")
        state["intent_confidence"] = float(result.get("confidence", 0.0))

        # Validate intent type
        valid_intents = {"brain", "chat", "calendar", "task", "unknown"}
        if state["intent"] not in valid_intents:
            state["intent"] = "unknown"

    except Exception as e:
        # On error, default to brain (safest fallback)
        state["intent"] = "brain"
        state["intent_confidence"] = 0.5
        state["error"] = f"Intent detection error: {str(e)}"

    return state


def route_by_intent(state: OrchestratorState) -> str:
    """Route to the appropriate handler based on detected intent.

    Args:
        state: Current orchestrator state with intent

    Returns:
        Handler node name to route to
    """
    intent = state.get("intent", "unknown")

    # Map intent to handler node names
    routes = {
        "brain": "brain_handler",
        "chat": "chat_handler",
        "calendar": "calendar_handler",
        "task": "task_handler",
        "unknown": "brain_handler"  # Default to brain for unknown
    }

    return routes.get(intent, "brain_handler")
