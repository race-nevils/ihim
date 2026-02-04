"""LLM classification for brain handler.

Single responsibility: classify content into categories using LLM.
All classification logic is traced via Langfuse.
Includes deterministic fallbacks for date extraction and summary validation.
"""
import logging
from typing import Optional

from handlers.tracing import observe, langfuse_context

from adapters.ollama import OllamaAdapter
from handlers.utils import get_classify_prompt, extract_title
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

    # LLM classification (today's date injected for relative date resolution)
    classification = adapter.generate_json(
        get_classify_prompt(content),
        model=OllamaAdapter.FAST_MODEL
    )

    # Guard: if LLM returned an error or unexpected type, provide safe defaults
    if classification.get("error"):
        logger.warning(f"LLM classification failed: {classification.get('error')}, using defaults")
        classification = {
            "category": "Misc",
            "confidence": 0.0,
            "summary": content[:100],
            "calendar": None,
        }

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

    # Normalize: LLM may return a list of calendar events for multi-task notes.
    # Keep the list in classification for multi-event push, use first item for validation.
    raw_calendar = classification.get("calendar")
    if isinstance(raw_calendar, list):
        calendar_data = next(
            (c for c in raw_calendar if isinstance(c, dict) and c.get("is_event")),
            None
        )
        logger.info(f"LLM returned {len(raw_calendar)} calendar items, using first valid event")
    else:
        calendar_data = raw_calendar

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
            if deterministic_calendar.get("end_time"):
                calendar_data["end_time"] = deterministic_calendar["end_time"]
            calendar_fallback_used = True
            keyword_fallback_used = bool(keyword_calendar)

        # If LLM returned a list, store normalized list with validated first item
        if isinstance(raw_calendar, list):
            # Replace first valid event with validated version, keep the rest
            normalized = []
            first_replaced = False
            for item in raw_calendar:
                if not first_replaced and isinstance(item, dict) and item.get("is_event"):
                    normalized.append(calendar_data)
                    first_replaced = True
                else:
                    normalized.append(item)
            classification["calendar"] = normalized
        else:
            classification["calendar"] = calendar_data

    # Summary validation: catch contaminated summaries
    raw_summary = classification.get("summary", "")
    validated_summary = validate_summary(content, raw_summary)
    if validated_summary != raw_summary:
        classification["summary"] = validated_summary
        summary_fallback_used = True
        logger.info(f"[fallback] Summary replaced (contamination detected)")

    # Log to Langfuse — resolve calendar to single dict for metadata
    final_calendar = classification.get("calendar")
    if isinstance(final_calendar, list):
        log_cal = next((c for c in final_calendar if isinstance(c, dict) and c.get("is_event")), None)
    else:
        log_cal = final_calendar

    langfuse_context.update_current_observation(
        model=OllamaAdapter.FAST_MODEL,
        input=content[:500],  # Truncate for readability
        output=classification,
        metadata={
            "source_filename": source_filename,
            "category": classification.get("category"),
            "confidence": classification.get("confidence"),
            "has_calendar_event": bool(log_cal and log_cal.get("is_event")),
            "calendar_event_count": len(final_calendar) if isinstance(final_calendar, list) else (1 if log_cal else 0),
            "calendar_fallback_used": calendar_fallback_used,
            "keyword_fallback_used": keyword_fallback_used,
            "calendar_date_overridden": calendar_date_overridden,
            "summary_fallback_used": summary_fallback_used,
        }
    )

    cal_info = ""
    if log_cal and log_cal.get("is_event"):
        event_count = len(final_calendar) if isinstance(final_calendar, list) else 1
        count_tag = f" ({event_count} events)" if event_count > 1 else ""
        fallback_tag = " [date-override]" if calendar_date_overridden else (
            " [keyword-fallback]" if keyword_fallback_used else (
                " [regex-fallback]" if calendar_fallback_used else ""))
        cal_info = f" | Calendar{fallback_tag}{count_tag}: {log_cal.get('date')} {'all-day' if log_cal.get('all_day') else log_cal.get('time', '')}"

    logger.info(
        f"Classified as {classification.get('category')} "
        f"(confidence={classification.get('confidence', 0):.2f}){cal_info}"
    )

    return classification
