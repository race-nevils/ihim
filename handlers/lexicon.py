"""Time Lexicon - structured time expression resolution.

Loads the master JSON lexicon and provides lookup functions for:
- Holiday detection and date resolution
- Recurrence pattern detection and RRULE generation
- Time-of-day term resolution
- Shorthand expansion (EOD, COB, etc.)

Data source: IHIM/data/lexicon/time_lexicon_v1.0.json
"""
import json
import re
import logging
from datetime import date
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

IHIM_ROOT = Path(__file__).parent.parent
LEXICON_PATH = IHIM_ROOT / "data" / "lexicon" / "time_lexicon_v1.0.json"


class TimeLexicon:
    """Time Lexicon - structured time expression resolution."""

    def __init__(self, lexicon_path: Path):
        self._data = json.loads(lexicon_path.read_text(encoding="utf-8"))
        self._terms = {t["term"].lower(): t for t in self._data.get("lexicon_terms", [])}
        self._holidays = self._build_holiday_index()
        self._holiday_aliases = self._build_holiday_aliases()
        self._recurrence = {
            r["phrase"].lower(): r
            for r in self._data.get("recurrence_templates", [])
        }
        # Sort recurrence phrases longest-first to avoid partial matches
        self._recurrence_phrases_sorted = sorted(
            self._recurrence.keys(), key=len, reverse=True
        )
        logger.info(
            f"Loaded lexicon: {len(self._terms)} terms, "
            f"{len(self._holidays)} holidays, "
            f"{len(self._recurrence)} recurrence patterns"
        )

    def _build_holiday_index(self) -> dict:
        """Build name -> {year -> date_str} index from computed_dates."""
        holidays = self._data.get("holidays", {})
        computed = holidays.get("computed_dates", [])
        index: dict[str, dict[int, str]] = {}
        for entry in computed:
            name = entry["name"].lower()
            year = entry["year"]
            date_str = entry.get("observed_date") or entry["date"]
            if name not in index:
                index[name] = {}
            index[name][year] = date_str
        return index

    def _build_holiday_aliases(self) -> dict:
        """Build alias -> canonical name mapping for common holiday names."""
        aliases: dict[str, str] = {}
        for name in self._holidays:
            aliases[name] = name
            # Generate common aliases
            name_lower = name.lower()
            if "thanksgiving" in name_lower:
                aliases["thanksgiving"] = name
            if "christmas" in name_lower:
                aliases["christmas"] = name
                aliases["xmas"] = name
            if "independence day" in name_lower:
                aliases["4th of july"] = name
                aliases["fourth of july"] = name
                aliases["july 4th"] = name
                aliases["july fourth"] = name
            if "valentine" in name_lower:
                aliases["valentine's day"] = name
                aliases["valentines day"] = name
                aliases["valentines"] = name
            if "halloween" in name_lower:
                aliases["halloween"] = name
            if "easter" in name_lower:
                aliases["easter"] = name
            if "memorial day" in name_lower:
                aliases["memorial day"] = name
            if "labor day" in name_lower:
                aliases["labor day"] = name
            if "presidents" in name_lower or "washington" in name_lower:
                aliases["presidents day"] = name
                aliases["president's day"] = name
                aliases["presidents' day"] = name
            if "martin luther king" in name_lower:
                aliases["mlk day"] = name
                aliases["mlk"] = name
            if "new year's day" in name_lower:
                aliases["new year's day"] = name
                aliases["new years day"] = name
                aliases["new years"] = name
                aliases["new year's"] = name
            if "new year's eve" in name_lower:
                aliases["new year's eve"] = name
                aliases["new years eve"] = name
                aliases["nye"] = name
            if "veterans" in name_lower:
                aliases["veterans day"] = name
                aliases["veteran's day"] = name
            if "juneteenth" in name_lower:
                aliases["juneteenth"] = name
            if "good friday" in name_lower:
                aliases["good friday"] = name
            if "ash wednesday" in name_lower:
                aliases["ash wednesday"] = name
            if "mother" in name_lower:
                aliases["mother's day"] = name
                aliases["mothers day"] = name
            if "father" in name_lower:
                aliases["father's day"] = name
                aliases["fathers day"] = name
            if "black friday" in name_lower:
                aliases["black friday"] = name
            if "cyber monday" in name_lower:
                aliases["cyber monday"] = name
            if "columbus" in name_lower:
                aliases["columbus day"] = name
        return aliases

    def resolve_holiday(self, name: str, year: int) -> Optional[str]:
        """Resolve holiday name + year to ISO date string."""
        canonical = self._holiday_aliases.get(name.lower())
        if not canonical:
            return None
        dates = self._holidays.get(canonical, {})
        return dates.get(year)

    def resolve_recurrence(self, phrase: str) -> Optional[str]:
        """Resolve recurrence phrase to RRULE string."""
        entry = self._recurrence.get(phrase.lower())
        if entry:
            return entry.get("rrule_template")
        return None

    def resolve_term(self, term: str) -> Optional[dict]:
        """Resolve a time term to its semantics dict."""
        entry = self._terms.get(term.lower())
        if entry:
            return entry.get("semantics")
        return None

    def resolve_shorthand(self, shorthand: str) -> Optional[str]:
        """Resolve shorthand like EOD, COB to a time string."""
        entry = self._terms.get(shorthand.lower())
        if entry:
            semantics = entry.get("semantics", {})
            maps_to = semantics.get("maps_to")
            if maps_to:
                # Look up what it maps to
                target = self._terms.get(maps_to.lower())
                if target:
                    return target.get("semantics", {}).get("default_time")
        return None

    def get_holiday_names(self) -> list[str]:
        """Get all known holiday alias names for matching."""
        return list(self._holiday_aliases.keys())


# Singleton
_lexicon: Optional[TimeLexicon] = None


def get_lexicon() -> TimeLexicon:
    """Get or create the singleton TimeLexicon instance."""
    global _lexicon
    if _lexicon is None:
        _lexicon = TimeLexicon(LEXICON_PATH)
    return _lexicon


def detect_holiday(content: str) -> Optional[dict]:
    """Detect holiday references in note content, resolve to date.

    Matches holiday names and common aliases against content.
    Returns calendar dict compatible with pipeline format, or None.
    """
    if not content:
        return None

    content_lower = content.lower()
    lexicon = get_lexicon()

    today = date.today()
    current_year = today.year

    # Sort aliases longest-first to prevent partial matches
    aliases = sorted(lexicon.get_holiday_names(), key=len, reverse=True)

    for alias in aliases:
        # Word-boundary-ish check: alias must not be a substring of a larger word
        pattern = r"\b" + re.escape(alias) + r"\b"
        if re.search(pattern, content_lower):
            # Try current year first, fall forward to next year if past
            date_str = lexicon.resolve_holiday(alias, current_year)
            if date_str:
                if date_str < today.isoformat():
                    # This year's occurrence is past, try next year
                    date_str = lexicon.resolve_holiday(alias, current_year + 1)
            else:
                # No entry for current year, try next
                date_str = lexicon.resolve_holiday(alias, current_year + 1)

            if not date_str:
                continue

            # Get canonical name for title
            canonical = lexicon._holiday_aliases.get(alias, alias)

            logger.info(f"[holiday] Detected '{alias}' -> {canonical} on {date_str}")

            return {
                "is_event": True,
                "title": canonical.title(),
                "date": date_str,
                "time": None,
                "all_day": True,
            }

    return None


# Day name -> RRULE abbreviation
_DAY_ABBREVS = {
    "monday": "MO", "tuesday": "TU", "wednesday": "WE",
    "thursday": "TH", "friday": "FR", "saturday": "SA", "sunday": "SU",
    "mon": "MO", "tue": "TU", "tues": "TU", "wed": "WE",
    "thu": "TH", "thur": "TH", "thurs": "TH", "fri": "FR",
    "sat": "SA", "sun": "SU",
}

# Regex for "every N days/weeks/months"
_EVERY_N_RE = re.compile(
    r"\bevery\s+(\d+)\s+(days?|weeks?|months?|years?)\b",
    re.IGNORECASE,
)

# Regex for "every Mon/Wed/Fri" or "every Monday, Wednesday, and Friday"
_EVERY_DAYS_RE = re.compile(
    r"\bevery\s+((?:(?:mon(?:day)?|tue(?:s(?:day)?)?|wed(?:nesday)?|thu(?:r(?:s(?:day)?)?)?|"
    r"fri(?:day)?|sat(?:urday)?|sun(?:day)?)(?:\s*[,/&]\s*(?:and\s+)?)?)+)\b",
    re.IGNORECASE,
)


def detect_recurrence(content: str) -> Optional[dict]:
    """Detect recurrence patterns in content, return RRULE template.

    Returns dict with rrule, phrase, and ambiguity fields, or None.
    """
    if not content:
        return None

    content_lower = content.lower()
    lexicon = get_lexicon()

    # Check static phrases from lexicon (longest-first)
    for phrase in lexicon._recurrence_phrases_sorted:
        # Skip template patterns (contain brackets)
        if "[" in phrase:
            continue
        pattern = r"\b" + re.escape(phrase) + r"\b"
        if re.search(pattern, content_lower):
            entry = lexicon._recurrence[phrase]
            rrule = entry.get("rrule_template", "")
            ambiguity = entry.get("ambiguity", "")
            logger.info(f"[recurrence] Detected '{phrase}' -> {rrule}")
            return {"rrule": rrule, "phrase": phrase, "ambiguity": ambiguity}

    # Check "every N days/weeks/months" dynamically
    m = _EVERY_N_RE.search(content_lower)
    if m:
        n = int(m.group(1))
        unit = m.group(2).lower().rstrip("s")
        freq_map = {"day": "DAILY", "week": "WEEKLY", "month": "MONTHLY", "year": "YEARLY"}
        freq = freq_map.get(unit)
        if freq:
            rrule = f"RRULE:FREQ={freq};INTERVAL={n}"
            phrase = m.group(0)
            logger.info(f"[recurrence] Detected '{phrase}' -> {rrule}")
            return {"rrule": rrule, "phrase": phrase, "ambiguity": ""}

    # Check "every Mon/Wed/Fri" style day lists
    m = _EVERY_DAYS_RE.search(content_lower)
    if m:
        days_text = m.group(1)
        day_names = re.findall(
            r"mon(?:day)?|tue(?:s(?:day)?)?|wed(?:nesday)?|thu(?:r(?:s(?:day)?)?)?|"
            r"fri(?:day)?|sat(?:urday)?|sun(?:day)?",
            days_text, re.IGNORECASE
        )
        if day_names:
            byday = ",".join(
                _DAY_ABBREVS.get(d.lower(), d[:2].upper())
                for d in day_names
            )
            rrule = f"RRULE:FREQ=WEEKLY;BYDAY={byday}"
            phrase = m.group(0)
            logger.info(f"[recurrence] Detected '{phrase}' -> {rrule}")
            return {"rrule": rrule, "phrase": phrase, "ambiguity": ""}

    return None
