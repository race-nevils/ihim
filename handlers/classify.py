"""LLM classification for brain handler.

Single responsibility: classify content into categories using LLM.
All classification logic is traced via Langfuse.
"""
import logging
from typing import Optional

from handlers.tracing import observe, langfuse_context

from adapters.ollama import OllamaAdapter
from handlers.utils import CLASSIFY_PROMPT, extract_title

logger = logging.getLogger(__name__)


@observe(name="classify_content")
def classify_content(content: str, source_filename: Optional[str] = None) -> dict:
    """Classify content into a brain category.

    Uses LLM to determine category, confidence, and summary.
    Title is extracted from filename (not LLM-generated).

    Args:
        content: Note content to classify
        source_filename: Original filename for title extraction

    Returns:
        Classification dict with: category, confidence, summary, title
    """
    adapter = OllamaAdapter()

    # LLM classification
    classification = adapter.generate_json(
        CLASSIFY_PROMPT.format(content=content),
        model=OllamaAdapter.FAST_MODEL
    )

    # Title from filename, not LLM (prevents hallucination)
    classification["title"] = extract_title(content, source_filename)

    # Log to Langfuse
    calendar_data = classification.get("calendar")
    langfuse_context.update_current_observation(
        model=OllamaAdapter.FAST_MODEL,
        input=content[:500],  # Truncate for readability
        output=classification,
        metadata={
            "source_filename": source_filename,
            "category": classification.get("category"),
            "confidence": classification.get("confidence"),
            "has_calendar_event": bool(calendar_data and calendar_data.get("is_event"))
        }
    )

    cal_info = ""
    if calendar_data and calendar_data.get("is_event"):
        cal_info = f" | Calendar: {calendar_data.get('date')} {'all-day' if calendar_data.get('all_day') else calendar_data.get('time', '')}"

    logger.info(
        f"Classified as {classification.get('category')} "
        f"(confidence={classification.get('confidence', 0):.2f}){cal_info}"
    )

    return classification
