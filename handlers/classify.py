"""LLM classification for brain handler.

Single responsibility: classify content into categories using LLM.
All classification logic is traced via Langfuse.
Includes deterministic fallbacks for date extraction and summary validation.
"""
import logging
from typing import Optional

from handlers.tracing import observe, langfuse_context

from adapters.ollama import OllamaAdapter
from handlers.utils import CLASSIFY_PROMPT, extract_title
from handlers.fallback import extract_date, validate_summary, detect_calendar_by_keywords

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

    # --- Deterministic fallbacks ---
    calendar_fallback_used = False
    keyword_fallback_used = False
    summary_fallback_used = False

    # Date extraction fallback: if LLM missed calendar data, try regex then keywords
    calendar_data = classification.get("calendar")
    if not calendar_data or not calendar_data.get("is_event"):
        regex_calendar = extract_date(content)
        if regex_calendar:
            classification["calendar"] = regex_calendar
            calendar_fallback_used = True
            logger.info(f"[regex-fallback] Extracted calendar: {regex_calendar.get('date')}")
        else:
            keyword_calendar = detect_calendar_by_keywords(content)
            if keyword_calendar:
                classification["calendar"] = keyword_calendar
                calendar_fallback_used = True
                keyword_fallback_used = True
                logger.info(f"[keyword-fallback] Extracted calendar: {keyword_calendar.get('date')}")

    # Summary validation: catch contaminated summaries
    raw_summary = classification.get("summary", "")
    validated_summary = validate_summary(content, raw_summary)
    if validated_summary != raw_summary:
        classification["summary"] = validated_summary
        summary_fallback_used = True
        logger.info(f"[fallback] Summary replaced (contamination detected)")

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
            "has_calendar_event": bool(calendar_data and calendar_data.get("is_event")),
            "calendar_fallback_used": calendar_fallback_used,
            "keyword_fallback_used": keyword_fallback_used,
            "summary_fallback_used": summary_fallback_used,
        }
    )

    cal_info = ""
    if calendar_data and calendar_data.get("is_event"):
        fallback_tag = " [keyword-fallback]" if keyword_fallback_used else (" [regex-fallback]" if calendar_fallback_used else "")
        cal_info = f" | Calendar{fallback_tag}: {calendar_data.get('date')} {'all-day' if calendar_data.get('all_day') else calendar_data.get('time', '')}"

    logger.info(
        f"Classified as {classification.get('category')} "
        f"(confidence={classification.get('confidence', 0):.2f}){cal_info}"
    )

    return classification
