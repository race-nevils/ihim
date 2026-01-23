"""LangGraph workflow definition for the Second Brain orchestrator."""
import sys
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from langgraph.graph import StateGraph, END

from orchestrator.state import OrchestratorState
from orchestrator.intent import detect_intent, route_by_intent
from handlers import brain, chat, calendar, task


def create_orchestrator():
    """Create and compile the LangGraph orchestrator workflow.

    The workflow:
    1. Receives input text
    2. Detects intent using the fast model
    3. Routes to appropriate handler based on intent
    4. Handler processes the input and returns result

    Returns:
        Compiled LangGraph workflow ready for invocation
    """
    # Create the state graph
    graph = StateGraph(OrchestratorState)

    # Add nodes
    graph.add_node("detect_intent", detect_intent)
    graph.add_node("brain_handler", brain.handle)
    graph.add_node("chat_handler", chat.handle)
    graph.add_node("calendar_handler", calendar.handle)
    graph.add_node("task_handler", task.handle)

    # Set entry point
    graph.set_entry_point("detect_intent")

    # Add conditional routing based on intent
    graph.add_conditional_edges(
        "detect_intent",
        route_by_intent,
        {
            "brain_handler": "brain_handler",
            "chat_handler": "chat_handler",
            "calendar_handler": "calendar_handler",
            "task_handler": "task_handler"
        }
    )

    # All handlers terminate the graph
    graph.add_edge("brain_handler", END)
    graph.add_edge("chat_handler", END)
    graph.add_edge("calendar_handler", END)
    graph.add_edge("task_handler", END)

    # Compile and return
    return graph.compile()


# For quick testing
if __name__ == "__main__":
    orchestrator = create_orchestrator()

    # Test cases
    test_inputs = [
        "Meeting with John at 5pm Thursday",
        "What's the capital of France?",
        "Remember to buy milk",
        "Interesting idea about neural networks and consciousness...",
    ]

    print("Testing orchestrator with sample inputs:\n")
    for text in test_inputs:
        print(f"Input: {text}")
        result = orchestrator.invoke({"input_text": text})
        print(f"  Intent: {result.get('intent')} (confidence: {result.get('intent_confidence', 0):.2f})")
        print(f"  Result: {result.get('result')}")
        print()
