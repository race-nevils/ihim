"""Deterministic fallback for brain pipeline.

Safety nets for when the LLM misses date/time extraction or returns
contaminated summaries. Pure regex/stdlib -- no new dependencies.
"""
import re
import logging
from datetime import date, datetime
from typing import Optional

logger = logging.getLogger(__name__)

# Month name -> number mapping
_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2,
    "mar": 3, "march": 3, "apr": 4, "april": 4,
    "may": 5, "jun": 6, "june": 6,
    "jul": 7, "july": 7, "aug": 8, "august": 8,
    "sep": 9, "september": 9, "oct": 10, "october": 10,
    "nov": 11, "november": 11, "dec": 12, "december": 12,
}

# Ordinal suffix stripping
_ORDINAL_RE = re.compile(r"(\d{1,2})(?:st|nd|rd|th)\b", re.IGNORECASE)

# Pattern: "Feb 2nd", "February 2", "Feb 2nd, 2026"
_MONTH_DAY_RE = re.compile(
    r"\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|"
    r"jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|"
    r"nov(?:ember)?|dec(?:ember)?)"
    r"\s+"
    r"(\d{1,2})(?:st|nd|rd|th)?"
    r"(?:\s*,?\s*(\d{4}))?",
    re.IGNORECASE,
)

# Pattern: "1/15/2026" or "1/15"
_NUMERIC_DATE_RE = re.compile(
    r"\b(\d{1,2})/(\d{1,2})(?:/(\d{4}))?\b"
)

# Time patterns
_TIME_12H_RE = re.compile(
    r"\bat\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", re.IGNORECASE
)
_TIME_OF_DAY_RE = re.compile(
    r"\bin\s+the\s+(morning|afternoon|evening)\b", re.IGNORECASE
)
_TIME_NOON_RE = re.compile(r"\bat\s+(noon|midnight)\b", re.IGNORECASE)

# Stopwords for summary overlap check
_STOPWORDS = frozenset(
    "a an the is are was were be been being have has had do does did "
    "will would shall should may might can could i me my we our you your "
    "he him his she her it its they them their this that these those "
    "and but or nor for so yet at by in of on to from with as if not "
    "no up out about into over after all also".split()
)


def extract_date(content: str) -> Optional[dict]:
    """Extract date/time from content using regex patterns.

    Returns a calendar dict in the same format as the LLM output,
    or None if no date is found.
    """
    if not content:
        return None

    today = date.today()
    extracted_month = None
    extracted_day = None
    extracted_year = None

    # Try month-name pattern first (more reliable)
    m = _MONTH_DAY_RE.search(content)
    if m:
        month_str = m.group(1).lower()
        # Handle abbreviated months by looking up full key
        for key, val in _MONTHS.items():
            if month_str == key or month_str.startswith(key[:3]):
                extracted_month = val
                break
        if extracted_month is None:
            extracted_month = _MONTHS.get(month_str)
        extracted_day = int(m.group(2))
        extracted_year = int(m.group(3)) if m.group(3) else None
    else:
        # Try numeric date pattern
        m = _NUMERIC_DATE_RE.search(content)
        if m:
            extracted_month = int(m.group(1))
            extracted_day = int(m.group(2))
            extracted_year = int(m.group(3)) if m.group(3) else None

    if extracted_month is None or extracted_day is None:
        return None

    # Validate month/day ranges
    if not (1 <= extracted_month <= 12) or not (1 <= extracted_day <= 31):
        return None

    # Year inference: if no year given, use current year;
    # if that date already passed, use next year
    if extracted_year is None:
        extracted_year = today.year
        try:
            candidate = date(extracted_year, extracted_month, extracted_day)
        except ValueError:
            return None  # Invalid date (e.g., Feb 30)
        if candidate < today:
            extracted_year += 1

    # Final validation
    try:
        event_date = date(extracted_year, extracted_month, extracted_day)
    except ValueError:
        return None

    date_iso = event_date.isoformat()

    # Extract time
    time_str = None
    all_day = True

    tm = _TIME_12H_RE.search(content)
    if tm:
        hour = int(tm.group(1))
        minute = int(tm.group(2)) if tm.group(2) else 0
        period = tm.group(3).lower()
        if period == "pm" and hour != 12:
            hour += 12
        elif period == "am" and hour == 12:
            hour = 0
        time_str = f"{hour:02d}:{minute:02d}"
        all_day = False
    else:
        tm = _TIME_NOON_RE.search(content)
        if tm:
            word = tm.group(1).lower()
            time_str = "12:00" if word == "noon" else "00:00"
            all_day = False
        else:
            tm = _TIME_OF_DAY_RE.search(content)
            if tm:
                period = tm.group(1).lower()
                time_str = {"morning": "09:00", "afternoon": "14:00", "evening": "18:00"}[period]
                all_day = False

    # Build title from content (first ~8 words, title-cased)
    # Strip frontmatter first
    text = content
    if text.startswith("---"):
        end = text.find("---", 3)
        if end > 0:
            text = text[end + 3:].strip()
    words = text.split()[:8]
    title = " ".join(words).strip(".,!?;:")
    if len(title) > 60:
        title = title[:57] + "..."
    title = title.title()

    return {
        "is_event": True,
        "title": title,
        "date": date_iso,
        "time": time_str,
        "all_day": all_day,
    }


def validate_summary(content: str, summary: Optional[str]) -> str:
    """Validate that a summary actually relates to the content.

    Uses word-overlap ratio to detect contaminated summaries
    (where the LLM returned a summary from a different note).

    Args:
        content: Original note content
        summary: LLM-generated summary

    Returns:
        Original summary if valid, or content-derived fallback
    """
    if not summary or not summary.strip():
        return _derive_summary(content)

    if not content or not content.strip():
        return summary

    content_words = _tokenize(content)
    summary_words = _tokenize(summary)

    if not summary_words:
        return _derive_summary(content)

    # Check what fraction of summary words appear in the content
    overlap = sum(1 for w in summary_words if w in content_words)
    ratio = overlap / len(summary_words) if summary_words else 0

    if ratio < 0.3:
        logger.warning(
            f"Summary contamination detected (overlap={ratio:.2f}). "
            f"Falling back to content-derived summary."
        )
        return _derive_summary(content)

    return summary


def _tokenize(text: str) -> set:
    """Extract meaningful words from text (lowercase, no stopwords)."""
    words = re.findall(r"[a-z']+", text.lower())
    return {w for w in words if w not in _STOPWORDS and len(w) > 1}


def _derive_summary(content: str) -> str:
    """Derive a summary from the first sentence of content."""
    if not content or not content.strip():
        return "No content"

    # Strip frontmatter
    text = content.strip()
    if text.startswith("---"):
        end = text.find("---", 3)
        if end > 0:
            text = text[end + 3:].strip()

    # Take first sentence (up to period, question mark, or exclamation)
    sentence_end = re.search(r"[.!?]", text)
    if sentence_end:
        result = text[: sentence_end.end()].strip()
    else:
        result = text.strip()

    # Truncate to 120 chars
    if len(result) > 120:
        result = result[:117] + "..."

    return result if result else "No content"
