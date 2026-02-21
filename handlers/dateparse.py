"""Dateparser integration (Tier 2.5) for brain pipeline.

Wraps the dateparser library to provide broad natural-language date coverage
when the regex tier misses. Returns same dict format as fallback.extract_date().

Settings: future-preferring, configurable timezone, rejects past dates.
"""
import logging
import os
from datetime import date, datetime
from typing import Optional

logger = logging.getLogger(__name__)

try:
    import dateparser
    _DATEPARSER_AVAILABLE = True
except ImportError:
    _DATEPARSER_AVAILABLE = False
    logger.warning("dateparser not installed, Tier 2.5 disabled")

_DATEPARSE_TIMEZONE = os.environ.get("IHIM_TIMEZONE", "America/Chicago")
if not os.environ.get("IHIM_TIMEZONE"):
    logger.warning("IHIM_TIMEZONE not set, defaulting to America/Chicago")

_DATEPARSER_SETTINGS = {
    "PREFER_DATES_FROM": "future",
    "TIMEZONE": _DATEPARSE_TIMEZONE,
    "RETURN_AS_TIMEZONE_AWARE": False,
    "RELATIVE_BASE": None,  # Set dynamically
}

# Phrases that dateparser tends to misparse
_SKIP_PHRASES = frozenset({
    "now", "just now", "ago", "yesterday", "last night",
    "day before yesterday", "last week", "last month", "last year",
})


def extract_date_dateparser(content: str) -> Optional[dict]:
    """Extract date/time from content using dateparser library.

    Returns a calendar dict compatible with the pipeline format,
    or None if no future date is found.
    """
    if not _DATEPARSER_AVAILABLE or not content:
        return None

    # Skip content that's clearly retrospective
    content_lower = content.lower()
    for skip in _SKIP_PHRASES:
        if skip in content_lower:
            return None

    today = date.today()
    settings = dict(_DATEPARSER_SETTINGS)
    settings["RELATIVE_BASE"] = datetime.now()

    parsed = dateparser.parse(content, settings=settings)
    if not parsed:
        return None

    parsed_date = parsed.date()

    # Reject past dates (we only want future events)
    if parsed_date < today:
        return None

    date_iso = parsed_date.isoformat()

    # Check if the original content actually specifies a time.
    # dateparser inherits the current time from RELATIVE_BASE for date-only inputs,
    # so we only trust the time if the input explicitly contains time indicators.
    import re
    _TIME_INDICATORS = re.compile(
        r"\b(\d{1,2}:\d{2}|\d{1,2}\s*(am|pm)|at\s+\d|noon|midnight|morning|afternoon|evening)\b",
        re.IGNORECASE,
    )
    content_has_time = bool(_TIME_INDICATORS.search(content))

    time_str = None
    all_day = True
    if content_has_time and (parsed.hour != 0 or parsed.minute != 0):
        time_str = parsed.strftime("%H:%M")
        all_day = False

    # Build title from content
    text = content.strip()
    if text.startswith("---"):
        end = text.find("---", 3)
        if end > 0:
            text = text[end + 3:].strip()
    words = text.split()[:8]
    title = " ".join(words).strip(".,!?;:")
    if len(title) > 60:
        title = title[:57] + "..."
    title = title.title()

    logger.info(f"[dateparser] Extracted date={date_iso}, time={time_str}")

    return {
        "is_event": True,
        "title": title,
        "date": date_iso,
        "time": time_str,
        "all_day": all_day,
    }
