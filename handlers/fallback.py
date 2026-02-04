"""Deterministic fallback for brain pipeline.

Safety nets for when the LLM misses date/time extraction or returns
contaminated summaries. Pure regex/stdlib -- no new dependencies.
"""
import re
import logging
from datetime import date, datetime, timedelta
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
_BARE_TIME_OF_DAY_RE = re.compile(
    r"\b(morning|afternoon|evening)\b", re.IGNORECASE
)
_TIME_NOON_RE = re.compile(r"\bat\s+(noon|midnight)\b", re.IGNORECASE)

# Time range: "8:30am-10:30am", "3pm to 5pm", "8am - 10:30am"
_TIME_RANGE_RE = re.compile(
    r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\s*(?:[-\u2013\u2014]|to)\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b",
    re.IGNORECASE,
)

# Bare 12h time without "at" prefix: "8:30am", "3pm"
_BARE_TIME_12H_RE = re.compile(
    r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b",
    re.IGNORECASE,
)

# Stopwords for summary overlap check
_STOPWORDS = frozenset(
    "a an the is are was were be been being have has had do does did "
    "will would shall should may might can could i me my we our you your "
    "he him his she her it its they them their this that these those "
    "and but or nor for so yet at by in of on to from with as if not "
    "no up out about into over after all also".split()
)

# ── Keyword-based calendar detection (third-tier fallback) ────────

_DAYS_OF_WEEK = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
    "mon": 0, "tue": 1, "tues": 1, "wed": 2, "thu": 3, "thur": 3,
    "thurs": 3, "fri": 4, "sat": 5, "sun": 6,
}

# Tier 1: STRONG triggers — fire alone
_STRONG_RELATIVE_DATES = {
    "tomorrow", "tonight", "day after tomorrow",
}

_STRONG_RELATIVE_DAY_RE = re.compile(
    r"\b(next|this)\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday"
    r"|mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun)\b",
    re.IGNORECASE,
)

# Bare day-of-week without prefix: "Friday", "Monday"
# Full names only to avoid false positives ("sat" = past tense of "sit")
_BARE_DAY_RE = re.compile(
    r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
    re.IGNORECASE,
)

_STRONG_RELATIVE_PERIOD_RE = re.compile(
    r"\b(this\s+weekend|next\s+week|next\s+weekend|next\s+month|end\s+of\s+(?:the\s+)?month)\b",
    re.IGNORECASE,
)

_SCHEDULING_NOUNS = {
    "appointment", "meeting", "reservation", "deadline", "due date",
    "standup", "sync", "huddle", "1:1", "rsvp", "flight", "interview",
    "ceremony",
}

_DEADLINE_PHRASE_RE = re.compile(
    r"\b(by|due|before)\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday"
    r"|mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun"
    r"|eod|end\s+of\s+day|the\s+\d{1,2}(?:st|nd|rd|th)?)\b",
    re.IGNORECASE,
)

# Tier 2: MEDIUM triggers — need action verb within 15-word window
_MEDIUM_TIME_OF_DAY = {
    "morning", "afternoon", "evening", "midnight", "noon",
    "dawn", "sunrise", "sunset", "dusk", "midday",
}

_MEDIUM_MEAL_RE = re.compile(
    r"\b(before\s+lunch|after\s+lunch|lunchtime|before\s+dinner"
    r"|after\s+dinner|breakfast\s+time|supper)\b",
    re.IGNORECASE,
)

_MEDIUM_FUZZY_FUTURE_RE = re.compile(
    r"\b(this|next)\s+(spring|summer|fall|winter)\b"
    r"|\bover\s+the\s+weekend\b"
    r"|\bin\s+a\s+few\s+days\b"
    r"|\bin\s+a\s+couple\s+(?:of\s+)?weeks\b",
    re.IGNORECASE,
)

_MEDIUM_DURATION_RE = re.compile(
    r"\bin\s+(\d+)\s+(days?|weeks?)\b"
    r"|\b(\d+)\s+(days?|weeks?)\s+from\s+now\b",
    re.IGNORECASE,
)

# Tier 3: CONTEXTUAL triggers — need action verb + future-tense marker
_CONTEXTUAL_VAGUE = {
    "soon", "later", "eventually", "asap", "right away",
    "one of these days",
}

# Action verbs (for tier 2 + 3 pairing)
_ACTION_VERBS = {
    # Scheduling
    "remind", "schedule", "book", "reserve", "set up", "block off", "confirm",
    # Doing
    "pick up", "drop off", "call", "meet", "go to", "take", "bring", "get",
    "finish", "submit", "pay", "send", "deliver",
    # Moderate
    "do", "work on", "prepare", "plan", "organize", "make", "create",
    "build", "write", "check", "review", "clean",
}

# Future-tense markers (for tier 3)
_FUTURE_MARKERS = {
    "need to", "have to", "gotta", "must", "should", "going to", "gonna",
    "will", "want to", "planning to", "don't forget", "remember to",
    "make sure to",
}

# Negation / retrospective filters (suppress detection)
_NEGATION_RE = re.compile(
    r"\b(won'?t|can'?t\s+make\s+it|not\s+going\s+to|cancel(?:led|ed)?|didn'?t)\b",
    re.IGNORECASE,
)
_RETROSPECTIVE_RE = re.compile(
    r"\b(remember\s+when|i\s+was\s+thinking\s+about|back\s+when|used\s+to|the\s+other\s+day)\b",
    re.IGNORECASE,
)
_PAST_TENSE_DOMINANT_RE = re.compile(
    r"\b(was|were|did|had)\s+\w+",
    re.IGNORECASE,
)

# Time-of-day resolution map
_TIME_OF_DAY_MAP = {
    "morning": "09:00", "dawn": "06:00", "sunrise": "06:00",
    "noon": "12:00", "midday": "12:00", "lunchtime": "12:00",
    "afternoon": "14:00",
    "evening": "18:00", "sunset": "18:00", "dusk": "19:00",
    "tonight": "20:00",
    "midnight": "00:00",
    "before lunch": "11:00", "after lunch": "13:00",
    "before dinner": "17:00", "after dinner": "20:00",
    "breakfast time": "07:00", "supper": "18:00",
}


def _parse_12h(hour: int, minute: int, period: str) -> tuple:
    """Convert 12-hour time to 24-hour format. Returns (hour, minute)."""
    period = period.lower()
    if period == "pm" and hour != 12:
        hour += 12
    elif period == "am" and hour == 12:
        hour = 0
    return hour, minute


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

    # Extract time (check range first, then single time patterns)
    time_str = None
    end_time_str = None
    all_day = True

    # Time range: "8:30am-10:30am", "3pm to 5pm"
    trm = _TIME_RANGE_RE.search(content)
    if trm:
        sh, sm = _parse_12h(int(trm.group(1)), int(trm.group(2) or 0), trm.group(3))
        eh, em = _parse_12h(int(trm.group(4)), int(trm.group(5) or 0), trm.group(6))
        time_str = f"{sh:02d}:{sm:02d}"
        end_time_str = f"{eh:02d}:{em:02d}"
        all_day = False
    else:
        # "at 8:30am"
        tm = _TIME_12H_RE.search(content)
        if tm:
            h, m = _parse_12h(int(tm.group(1)), int(tm.group(2) or 0), tm.group(3))
            time_str = f"{h:02d}:{m:02d}"
            all_day = False
        else:
            tm = _TIME_NOON_RE.search(content)
            if tm:
                word = tm.group(1).lower()
                time_str = "12:00" if word == "noon" else "00:00"
                all_day = False
            else:
                # Bare time: "8:30am" (no "at" prefix)
                tm = _BARE_TIME_12H_RE.search(content)
                if tm:
                    h, m = _parse_12h(int(tm.group(1)), int(tm.group(2) or 0), tm.group(3))
                    time_str = f"{h:02d}:{m:02d}"
                    all_day = False
                else:
                    tm = _TIME_OF_DAY_RE.search(content)
                    if not tm:
                        tm = _BARE_TIME_OF_DAY_RE.search(content)
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

    result = {
        "is_event": True,
        "title": title,
        "date": date_iso,
        "time": time_str,
        "all_day": all_day,
    }
    if end_time_str:
        result["end_time"] = end_time_str
    return result


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


# ── Keyword detection helpers ────────────────────────────────────


def _has_action_verb(text: str, anchor_pos: int = -1, window: int = 15) -> bool:
    """Check whether an action verb appears near the anchor position.

    If anchor_pos == -1, search the whole text.
    Otherwise, search within *window* words of the anchor word index.
    """
    words_lower = text.lower().split()
    text_lower = text.lower()

    # Multi-word verbs: check entire text (or windowed slice)
    for verb in _ACTION_VERBS:
        if " " in verb:
            if verb in text_lower:
                return True
        else:
            if anchor_pos < 0:
                if verb in words_lower:
                    return True
            else:
                start = max(0, anchor_pos - window)
                end = min(len(words_lower), anchor_pos + window + 1)
                if verb in words_lower[start:end]:
                    return True
    return False


def _has_future_marker(text: str) -> bool:
    """Check whether a future-tense marker appears in the text."""
    text_lower = text.lower()
    return any(marker in text_lower for marker in _FUTURE_MARKERS)


def _is_negated_or_retrospective(text: str) -> bool:
    """Return True if the text contains negation or retrospective patterns."""
    if _NEGATION_RE.search(text):
        return True
    if _RETROSPECTIVE_RE.search(text):
        return True
    # Past-tense dominant: only if no future marker overrides
    if _PAST_TENSE_DOMINANT_RE.search(text) and not _has_future_marker(text):
        # Check that past tense verbs are the *main* signal
        text_lower = text.lower()
        # If there's a strong relative date, don't suppress
        for kw in _STRONG_RELATIVE_DATES:
            if kw in text_lower:
                return False
        return True
    return False


def _resolve_date_from_keyword(keyword: str, today: date) -> str:
    """Resolve a keyword to an ISO date string."""
    kw = keyword.lower().strip()

    if kw == "tomorrow":
        return (today + timedelta(days=1)).isoformat()
    if kw == "tonight":
        return today.isoformat()
    if kw == "day after tomorrow":
        return (today + timedelta(days=2)).isoformat()
    if kw == "this weekend":
        # Next Saturday
        days_until_sat = (5 - today.weekday()) % 7
        if days_until_sat == 0:
            days_until_sat = 0  # Today is Saturday, use today
        return (today + timedelta(days=days_until_sat)).isoformat()
    if kw == "next week":
        days_until_mon = (0 - today.weekday()) % 7
        if days_until_mon == 0:
            days_until_mon = 7
        return (today + timedelta(days=days_until_mon)).isoformat()
    if kw == "next weekend":
        days_until_sat = (5 - today.weekday()) % 7
        if days_until_sat == 0:
            days_until_sat = 7
        return (today + timedelta(days=days_until_sat)).isoformat()
    if kw == "next month":
        month = today.month + 1
        year = today.year
        if month > 12:
            month = 1
            year += 1
        return date(year, month, 1).isoformat()
    if kw.startswith("end of") and "month" in kw:
        # Last day of current month
        month = today.month
        year = today.year
        if month == 12:
            last_day = date(year + 1, 1, 1) - timedelta(days=1)
        else:
            last_day = date(year, month + 1, 1) - timedelta(days=1)
        return last_day.isoformat()
    if kw == "in a few days":
        return (today + timedelta(days=3)).isoformat()
    if kw.startswith("in a couple") and "week" in kw:
        return (today + timedelta(days=14)).isoformat()

    # "this [day]" or "next [day]"
    parts = kw.split()
    if len(parts) == 2 and parts[0] in ("this", "next"):
        day_name = parts[1]
        target_dow = _DAYS_OF_WEEK.get(day_name)
        if target_dow is not None:
            days_ahead = (target_dow - today.weekday()) % 7
            if parts[0] == "next":
                if days_ahead == 0:
                    days_ahead = 7
                elif days_ahead < 7:
                    days_ahead += 7  # Always >= 7 days away
            else:  # "this"
                if days_ahead == 0:
                    days_ahead = 0  # Today
            return (today + timedelta(days=days_ahead)).isoformat()

    # Scheduling noun with no date → tomorrow
    return (today + timedelta(days=1)).isoformat()


def _resolve_time_from_text(text: str) -> tuple:
    """Extract time-of-day from text using patterns and keyword map.

    Returns (start_time_str or None, end_time_str or None, all_day: bool).
    """
    text_lower = text.lower()

    # Time range: "8:30am-10:30am", "3pm to 5pm"
    m = _TIME_RANGE_RE.search(text)
    if m:
        sh, sm = _parse_12h(int(m.group(1)), int(m.group(2) or 0), m.group(3))
        eh, em = _parse_12h(int(m.group(4)), int(m.group(5) or 0), m.group(6))
        return f"{sh:02d}:{sm:02d}", f"{eh:02d}:{em:02d}", False

    # Bare 12h time: "8:30am", "3pm"
    m = _BARE_TIME_12H_RE.search(text)
    if m:
        h, mi = _parse_12h(int(m.group(1)), int(m.group(2) or 0), m.group(3))
        return f"{h:02d}:{mi:02d}", None, False

    # Check multi-word time phrases first
    for phrase in ("before lunch", "after lunch", "before dinner",
                   "after dinner", "breakfast time"):
        if phrase in text_lower:
            return _TIME_OF_DAY_MAP[phrase], None, False

    # Check "lunchtime" and "supper"
    for word in ("lunchtime", "supper"):
        if word in text_lower:
            return _TIME_OF_DAY_MAP[word], None, False

    # Single-word time-of-day
    words = set(re.findall(r"[a-z]+", text_lower))
    for kw in ("midnight", "noon", "midday", "dawn", "sunrise",
               "morning", "afternoon", "evening", "sunset", "dusk",
               "tonight"):
        if kw in words:
            return _TIME_OF_DAY_MAP[kw], None, False

    return None, None, True


def _build_title(content: str) -> str:
    """Build a title from the first ~8 words (same logic as extract_date)."""
    text = content
    if text.startswith("---"):
        end = text.find("---", 3)
        if end > 0:
            text = text[end + 3:].strip()
    words = text.split()[:8]
    title = " ".join(words).strip(".,!?;:")
    if len(title) > 60:
        title = title[:57] + "..."
    return title.title()


def detect_calendar_by_keywords(content: str) -> Optional[dict]:
    """Keyword-based calendar event detection (third-tier fallback).

    Fires only when both LLM and regex miss. Uses three confidence tiers
    to avoid false positives.

    Returns a calendar dict in the same format as extract_date(),
    or None if no calendar signal detected.
    """
    if not content or not content.strip():
        return None

    # Strip frontmatter for analysis
    text = content.strip()
    if text.startswith("---"):
        end = text.find("---", 3)
        if end > 0:
            text = text[end + 3:].strip()

    text_lower = text.lower()

    # Step 1: Early exit — negation/retrospective
    if _is_negated_or_retrospective(text):
        return None

    today = date.today()
    matched_keyword = None
    resolved_date = None

    # Step 2: STRONG triggers
    # Check relative dates (tomorrow, tonight, day after tomorrow)
    for kw in _STRONG_RELATIVE_DATES:
        if kw in text_lower:
            matched_keyword = kw
            resolved_date = _resolve_date_from_keyword(kw, today)
            break

    # Check "next/this + day"
    if not matched_keyword:
        m = _STRONG_RELATIVE_DAY_RE.search(text)
        if m:
            matched_keyword = m.group(0).lower()
            resolved_date = _resolve_date_from_keyword(matched_keyword, today)

    # Check bare day-of-week ("Friday", "Monday" — no prefix needed)
    if not matched_keyword:
        m = _BARE_DAY_RE.search(text)
        if m:
            day_name = m.group(1).lower()
            if day_name in _DAYS_OF_WEEK:
                matched_keyword = day_name
                # Resolve as upcoming occurrence (same as "this [day]")
                resolved_date = _resolve_date_from_keyword("this " + day_name, today)

    # Check relative periods
    if not matched_keyword:
        m = _STRONG_RELATIVE_PERIOD_RE.search(text)
        if m:
            matched_keyword = m.group(0).lower()
            resolved_date = _resolve_date_from_keyword(matched_keyword, today)

    # Check scheduling nouns
    if not matched_keyword:
        for noun in _SCHEDULING_NOUNS:
            if noun in text_lower:
                matched_keyword = noun
                resolved_date = _resolve_date_from_keyword(noun, today)
                break

    # Check deadline phrases ("by Friday", "due Monday", "by EOD")
    if not matched_keyword:
        m = _DEADLINE_PHRASE_RE.search(text)
        if m:
            matched_keyword = m.group(0).lower()
            # Try to resolve the day reference
            day_part = m.group(2).lower()
            if day_part in _DAYS_OF_WEEK or any(
                day_part.startswith(d) for d in _DAYS_OF_WEEK
            ):
                resolved_date = _resolve_date_from_keyword(
                    "next " + day_part, today
                )
            elif "eod" in day_part or "end of day" in day_part:
                resolved_date = today.isoformat()
            else:
                # "the 15th" — try to extract day number
                day_num_m = re.search(r"(\d{1,2})", day_part)
                if day_num_m:
                    day_num = int(day_num_m.group(1))
                    if 1 <= day_num <= 31:
                        try:
                            candidate = date(today.year, today.month, day_num)
                            if candidate < today:
                                # Next month
                                month = today.month + 1
                                year = today.year
                                if month > 12:
                                    month = 1
                                    year += 1
                                candidate = date(year, month, day_num)
                            resolved_date = candidate.isoformat()
                        except ValueError:
                            resolved_date = (today + timedelta(days=1)).isoformat()
                    else:
                        resolved_date = (today + timedelta(days=1)).isoformat()
                else:
                    resolved_date = (today + timedelta(days=1)).isoformat()

    # Step 3: MEDIUM triggers (need action verb in 15-word window)
    if not matched_keyword:
        words_list = text_lower.split()

        # Time-of-day keywords
        for i, w in enumerate(words_list):
            if w in _MEDIUM_TIME_OF_DAY and _has_action_verb(text, i):
                matched_keyword = w
                resolved_date = (today + timedelta(days=1)).isoformat()
                break

        # Meal-anchored phrases
        if not matched_keyword:
            m = _MEDIUM_MEAL_RE.search(text)
            if m and _has_action_verb(text, -1):
                matched_keyword = m.group(0).lower()
                resolved_date = (today + timedelta(days=1)).isoformat()

        # Fuzzy future
        if not matched_keyword:
            m = _MEDIUM_FUZZY_FUTURE_RE.search(text)
            if m and _has_action_verb(text, -1):
                matched_keyword = m.group(0).lower()
                if "few days" in matched_keyword:
                    resolved_date = _resolve_date_from_keyword("in a few days", today)
                elif "couple" in matched_keyword and "week" in matched_keyword:
                    resolved_date = _resolve_date_from_keyword(
                        "in a couple weeks", today
                    )
                elif "weekend" in matched_keyword:
                    resolved_date = _resolve_date_from_keyword("this weekend", today)
                else:
                    resolved_date = (today + timedelta(days=1)).isoformat()

        # Duration: "in X days/weeks"
        if not matched_keyword:
            m = _MEDIUM_DURATION_RE.search(text)
            if m:
                num = int(m.group(1) or m.group(3))
                unit = (m.group(2) or m.group(4)).lower()
                if "week" in unit:
                    num *= 7
                resolved_date = (today + timedelta(days=num)).isoformat()
                matched_keyword = m.group(0).lower()

    # Step 4: CONTEXTUAL triggers (need action verb + future marker)
    if not matched_keyword:
        for phrase in _CONTEXTUAL_VAGUE:
            if phrase in text_lower:
                if _has_action_verb(text, -1) and _has_future_marker(text):
                    matched_keyword = phrase
                    resolved_date = (today + timedelta(days=1)).isoformat()
                    break

    # No trigger matched
    if not matched_keyword or not resolved_date:
        return None

    # Step 5: Resolve time
    time_str, end_time_str, all_day = _resolve_time_from_text(text)

    # Special case: "tonight" sets both date (today) and time (20:00)
    if matched_keyword == "tonight" and time_str is None:
        time_str = "20:00"
        all_day = False

    # Step 6: Build title
    title = _build_title(content)

    logger.info(
        f"[keyword-fallback] Detected '{matched_keyword}' → "
        f"date={resolved_date}, time={time_str}"
        f"{f', end={end_time_str}' if end_time_str else ''}"
    )

    result = {
        "is_event": True,
        "title": title,
        "date": resolved_date,
        "time": time_str,
        "all_day": all_day,
    }
    if end_time_str:
        result["end_time"] = end_time_str
    return result
