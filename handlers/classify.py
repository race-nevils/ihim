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
    calendar_date_overridden = False
    summary_fallback_used = False

    # Always run deterministic date parsing as validation layer.
    # Small LLMs can't do calendar math for relative dates ("next week", "tomorrow").
    # Deterministic parsing is authoritative for date/time when it matches.
    regex_calendar = extract_date(content)
    keyword_calendar = detect_calendar_by_keywords(content) if not regex_calendar else None
    deterministic_calendar = regex_calendar or keyword_calendar

    calendar_data = classification.get("calendar")
    if not calendar_data or not calendar_data.get("is_event"):
        # LLM missed calendar entirely — use deterministic if available
        if deterministic_calendar:
            classification["calendar"] = deterministic_calendar
            calendar_fallback_used = True
            keyword_fallback_used = bool(keyword_calendar)
            logger.info(f"[{'keyword' if keyword_calendar else 'regex'}-fallback] "
                        f"Extracted calendar: {deterministic_calendar.get('date')}")
    else:
        # LLM returned calendar data — validate date/time with deterministic
        if deterministic_calendar:
            llm_date = calendar_data.get("date", "")
            det_date = deterministic_calendar["date"]
            if llm_date != det_date:
                logger.warning(
                    f"[date-validation] LLM date={llm_date} overridden by "
                    f"deterministic={det_date} (source: {'keyword' if keyword_calendar else 'regex'})"
                )
                calendar_date_overridden = True
            calendar_data["date"] = det_date
            if deterministic_calendar.get("time"):
                calendar_data["time"] = deterministic_calendar["time"]
                calendar_data["all_day"] = False
            calendar_fallback_used = True
            keyword_fallback_used = bool(keyword_calendar)

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
            "calendar_date_overridden": calendar_date_overridden,
            "summary_fallback_used": summary_fallback_used,
        }
    )

    cal_info = ""
    if calendar_data and calendar_data.get("is_event"):
        fallback_tag = " [date-override]" if calendar_date_overridden else (
            " [keyword-fallback]" if keyword_fallback_used else (
                " [regex-fallback]" if calendar_fallback_used else ""))
        cal_info = f" | Calendar{fallback_tag}: {calendar_data.get('date')} {'all-day' if calendar_data.get('all_day') else calendar_data.get('time', '')}"

    logger.info(
        f"Classified as {classification.get('category')} "
        f"(confidence={classification.get('confidence', 0):.2f}){cal_info}"
    )

    return classification
