"""LangGraph workflow definition for the Second Brain orchestrator.

Pipeline flow:
    input → brain_handler → END

All notes route through the brain handler, which handles classification,
deduplication, storage, and calendar auto-push.
"""
import sys
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from langgraph.graph import StateGraph, END

from orchestrator.state import PipelineState
from handlers import brain


def create_orchestrator():
    """Create and compile the LangGraph orchestrator workflow.

    The workflow:
    1. Receives input text (from a READY file)
    2. Routes directly to brain handler for classification + storage
    3. Brain handler processes: classify → dedup → store → calendar push

    Returns:
        Compiled LangGraph workflow ready for invocation
    """
    # Create the state graph
    graph = StateGraph(PipelineState)

    # Single node — brain handles everything
    graph.add_node("brain_handler", brain.handle)

    # Entry straight to brain
    graph.set_entry_point("brain_handler")

    # Handler terminates the graph
    graph.add_edge("brain_handler", END)

    # Compile and return
    return graph.compile()


# For quick testing
if __name__ == "__main__":
    orchestrator = create_orchestrator()

    # Test cases
    test_inputs = [
        "Remember to buy milk",
        "What's the capital of France?",
        "Interesting idea about neural networks and consciousness...",
        "Meeting with John at 5pm Thursday",
    ]

    print("Testing orchestrator with sample inputs:\n")
    for text in test_inputs:
        print(f"Input: {text}")
        result = orchestrator.invoke({"input_text": text})
        print(f"  Result: {result.get('result')}")
        print()
