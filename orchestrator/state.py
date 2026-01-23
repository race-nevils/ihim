"""State schema for the orchestrator graph."""
from typing import TypedDict, Literal, Optional, Any


Intent = Literal["brain", "chat", "calendar", "task", "unknown"]


class OrchestratorState(TypedDict, total=False):
    """State passed through the orchestrator graph.

    Attributes:
        input_text: The raw input text to process
        source_file: Path to the source file (if from inbox watcher)
        intent: Detected intent type
        intent_confidence: Confidence score for intent detection (0.0-1.0)
        result: Output from the handler that processed this item
        error: Error message if processing failed
        metadata: Additional metadata from processing
    """
    # Input
    input_text: str
    source_file: Optional[str]

    # Intent detection
    intent: Optional[Intent]
    intent_confidence: Optional[float]

    # Processing result
    result: Optional[dict[str, Any]]
    error: Optional[str]

    # Metadata
    metadata: Optional[dict[str, Any]]
