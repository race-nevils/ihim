"""Shared utilities for brain handlers.

Extracted from the original brain.py for modularity.
"""
import hashlib
import re
from datetime import date
from pathlib import Path
from typing import Optional

# Confidence threshold for routing to specific category vs Misc
# Higher = more strict, more goes to Misc when uncertain
CONFIDENCE_THRESHOLD = 0.8


def get_classify_prompt(content: str, title: str = "") -> str:
    """Format the classification prompt with today's date and title injected.

    The prompt template is generated from categories.json via the registry.
    """
    from handlers.category_registry import get_registry

    today = date.today()
    today_str = f"{today.isoformat()} ({today.strftime('%A')})"
    prompt = get_registry().generate_classify_prompt()
    prompt = prompt.replace("{{today}}", today_str)
    if title:
        return prompt.replace("{content}", f"Title: {title}\n\n{content}")
    return prompt.replace("{content}", content)


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


def _resolve_two_digit_year(yy: int) -> int:
    """Resolve 2-digit year: 00-49 → 2000s, 50-99 → 1900s."""
    if yy <= 49:
        return 2000 + yy
    return 1900 + yy


def extract_date_from_filename(filename: str) -> Optional[str]:
    """Extract date from filename prefix. Flexible input, uniform output.

    Accepts any of these at the start of the filename:
        03082026 Gratitude     → 2026-03-08  (MMDDYYYY, 8 digits)
        3/11/26 Gratitude      → 2026-03-11  (M/DD/YY with slashes)
        3-11-2026 Gratitude    → 2026-03-11  (M-DD-YYYY with dashes)
        3.8.26 Gratitude       → 2026-03-08  (M.D.YY with dots)
        03/08/2026 Gratitude   → 2026-03-08  (MM/DD/YYYY)

    2-digit year: 00-49 → 2000s, 50-99 → 1900s.

    Returns YYYY-MM-DD or None.
    """
    # Work with the raw filename (strip extension manually) so that
    # separators like / aren't eaten by Path() as directory components.
    basename = Path(filename).name if '/' not in filename and '\\' not in filename else filename
    stem = re.sub(r'\.[^.]+$', '', basename)

    # Pattern 1: 8 consecutive digits (MMDDYYYY) — the canonical format
    m = re.match(r'^(\d{8})\b', stem)
    if m:
        digits = m.group(1)
        month, day, year = int(digits[0:2]), int(digits[2:4]), int(digits[4:8])
        if 1 <= month <= 12 and 1 <= day <= 31:
            return f"{year:04d}-{month:02d}-{day:02d}"

    # Pattern 2: Separated format (slashes, dashes, or dots)
    # M/D/YY, M/D/YYYY, MM/DD/YY, MM/DD/YYYY — any separator
    m = re.match(r'^(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})\b', stem)
    if m:
        month, day, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if year < 100:
            year = _resolve_two_digit_year(year)
        if 1 <= month <= 12 and 1 <= day <= 31:
            return f"{year:04d}-{month:02d}-{day:02d}"

    return None


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
