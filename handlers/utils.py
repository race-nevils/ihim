"""Shared utilities for brain handlers.

Extracted from the original brain.py for modularity.
"""
import hashlib
import re
from datetime import date
from pathlib import Path
from typing import Optional

# Valid categories (Misc is catch-all for low-confidence items)
# Based on MECE principle: Mutually Exclusive, Collectively Exhaustive
CATEGORIES = ["Tasks", "Projects", "People", "Ideas", "Reference", "Misc"]

# Confidence threshold for routing to specific category vs Misc
# Higher = more strict, more goes to Misc when uncertain
CONFIDENCE_THRESHOLD = 0.8

# LLM classification prompt - Decision tree for mutual exclusivity
# Tasks = dated/calendar items, Projects = undated action items
CLASSIFY_PROMPT = """Classify this note into exactly ONE category by following this decision tree IN ORDER:

STEP 1: Is this about a PERSON (name mentioned, relationship, contact info, conversation)?
  → YES: Category = "People"
  → NO: Continue to Step 2

STEP 2: Does it have a SPECIFIC DATE or TIME for an action, appointment, or deadline?
  → YES: Category = "Tasks"
  → NO: Continue to Step 3

STEP 3: Is there an ACTION to complete but NO specific date? (verb like: clean, call, buy, fix, build, send, check)
  → YES: Category = "Projects"
  → NO: Continue to Step 4

STEP 4: Is this a MULTI-STEP initiative or thing being built (no specific deadline)?
  → YES: Category = "Projects"
  → NO: Continue to Step 5

STEP 5: Is this EXPLORATION or BRAINSTORMING? (what if, maybe, wondering, idea, concept, no commitment)
  → YES: Category = "Ideas"
  → NO: Continue to Step 6

STEP 6: Is this STATIC INFORMATION to remember? (facts, addresses, how-to, reference, documentation)
  → YES: Category = "Reference"
  → NO: Category = "Ideas" (default for unclear content)

KEY DISTINCTION - Tasks vs Projects:
- Tasks = has a specific date/time, goes on calendar, displayed chronologically
- Projects = no specific date, "anytime" items that just need to get done eventually

CALENDAR DETECTION (check independently of category):
Does this note mention a SPECIFIC DATE or TIME for an event, appointment, meeting, or deadline?
  → YES: Set "calendar" with extracted date info
  → NO: Set "calendar" to null

Calendar rules:
- Date + time mentioned → all_day = false, include time
- Date only, no time → all_day = true, time = null
- No specific date → calendar = null
- Use ISO format for date: YYYY-MM-DD
- Use 24h format for time: HH:MM
- If a time RANGE is given (e.g., "8am-10am", "8:30am to 10:30am"), set both "time" (start) and "end_time" (end)
- If only start time, set "end_time" to null
- Day name alone ("Friday") → resolve to the UPCOMING occurrence from today's date
- "next Friday" → the Friday of NEXT week (always 7+ days away)
- "this Friday" → the Friday of THIS week

EXAMPLES:
- "Dentist appointment February 2nd" → Tasks, calendar: {{"is_event": true, "title": "Dentist Appointment", "date": "2026-02-02", "time": null, "all_day": true}}
- "Meeting with Sarah at 3pm on Feb 4th" → People, calendar: {{"is_event": true, "title": "Meeting with Sarah", "date": "2026-02-04", "time": "15:00", "all_day": false}}
- "Tax documents due by Feb 16th" → Tasks, calendar: {{"is_event": true, "title": "Tax Documents Due", "date": "2026-02-16", "time": null, "all_day": true}}
- "Need to clean oil from prop" → Projects, calendar: null (action but no date = Project)
- "Build a waitlist signup feature" → Projects, calendar: null (multi-step, no deadline)
- "What if we used Redis?" → Ideas, calendar: null (no date, no action)
- "Sarah's phone number is 555-1234" → People, calendar: null (no date)

Return ONLY valid JSON:
{{"category": "<Tasks|People|Projects|Ideas|Reference>", "confidence": <0.0-1.0>, "summary": "<1 sentence describing the note>", "calendar": null | {{"is_event": true, "title": "<short event title>", "date": "<YYYY-MM-DD>", "time": "<HH:MM>" | null, "end_time": "<HH:MM>" | null, "all_day": <true|false>}}}}

Today's date: {{today}}

Note: {content}

JSON response:"""


def get_classify_prompt(content: str) -> str:
    """Format the classification prompt with today's date and day-of-week injected."""
    today = date.today()
    today_str = f"{today.isoformat()} ({today.strftime('%A')})"
    return CLASSIFY_PROMPT.replace("{{today}}", today_str).format(content=content)


def slugify(text: str) -> str:
    """Convert text to a filename-safe slug (for JSON-LD layer)."""
    text = text.lower().strip()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[\s_]+', '-', text)
    text = re.sub(r'-+', '-', text)
    return text[:50]


def sanitize_title(text: str) -> str:
    """Sanitize title for use as Obsidian filename (human-readable).

    Removes characters not allowed in Windows filenames: \\ / : * ? " < > |
    """
    text = text.strip()
    text = re.sub(r'[\\/:*?"<>|]', '', text)
    text = re.sub(r'\s+', ' ', text)
    return text[:60]


def compute_content_hash(content: str) -> str:
    """Compute SHA-256 hash of content for change detection.

    Returns first 16 chars of hex digest (enough for uniqueness).
    """
    return hashlib.sha256(content.encode('utf-8')).hexdigest()[:16]


def extract_title(content: str, source_filename: Optional[str] = None) -> str:
    """Extract title from frontmatter or filename - DO NOT generate or infer.

    Title priority:
    1. Frontmatter 'title:' field (from capture widget)
    2. Source filename stem (what user saved as)
    3. "Untitled" fallback

    Args:
        content: The note content (checked for frontmatter title)
        source_filename: Original filename (e.g., "My Note.md")

    Returns:
        Title from frontmatter, filename stem, or "Untitled"
    """
    # Check frontmatter for title
    if content and content.startswith("---"):
        # Find end of frontmatter
        end_idx = content.find("---", 3)
        if end_idx > 0:
            frontmatter = content[3:end_idx]
            # Look for title: "..." or title: '...' or title: ...
            for line in frontmatter.split("\n"):
                line = line.strip()
                if line.startswith("title:"):
                    title_val = line[6:].strip()
                    # Remove quotes if present
                    if (title_val.startswith('"') and title_val.endswith('"')) or \
                       (title_val.startswith("'") and title_val.endswith("'")):
                        title_val = title_val[1:-1]
                    if title_val:
                        return title_val

    # Fallback to filename
    if source_filename:
        stem = Path(source_filename).stem
        # Ignore timestamp-only filenames (e.g., 20260129_042620_6d06ddad)
        if not re.match(r"^\d{8}_\d{6}_[a-f0-9]+$", stem):
            return stem

    return "Untitled"


def yaml_escape(text: str) -> str:
    """Escape a string for safe use in YAML double-quoted values."""
    if not text:
        return ""
    text = text.replace("\\", "\\\\")
    text = text.replace('"', '\\"')
    text = text.replace("\n", "\\n")
    return text
