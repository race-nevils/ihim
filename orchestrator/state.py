"""State schema for the orchestrator graph.

ARCHITECTURE NOTE
=================
This state flows through the LangGraph orchestrator pipeline:
    input → brain_handler → result

The result ultimately drives:
1. JSON-LD file creation (source of truth)
2. Database index update (derived)
3. Markdown generation (derived, for Obsidian)

File lifecycle (settling, ready, processed, stale) is handled by
the FileTracker in the watcher layer - only READY files enter
this pipeline.

Deduplication (new vs update) is handled by the database via
source_filename + content_hash columns.

See CLAUDE.md → iHIM Data Architecture for full context.
"""
from typing import TypedDict, Optional, Any


class PipelineState(TypedDict, total=False):
    """State passed through the orchestrator graph.

    Attributes:
        input_text: The raw input text to process
        source_file: Path to the source file (if from inbox watcher)
        result: Output from the handler that processed this item
        error: Error message if processing failed
        metadata: Additional metadata from processing
    """
    # Input
    input_text: str
    source_file: Optional[str]

    # Processing result
    result: Optional[dict[str, Any]]
    error: Optional[str]

    # Metadata
    metadata: Optional[dict[str, Any]]


# Backwards compatibility alias
OrchestratorState = PipelineState
