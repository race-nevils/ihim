"""Track user corrections for pattern learning.

When the operator moves a file from Tasks/ to People/, record that correction
so the system can learn from it.

Layer 10 of the Content/Instruction Separation System.
"""
import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

IHIM_ROOT = Path(__file__).parent.parent
CORRECTIONS_FILE = IHIM_ROOT / "data" / "local" / "brain" / "corrections.jsonl"


def record_correction(
    entry_id: str,
    from_category: str,
    to_category: str,
    title: str,
    content_sample: str
):
    """Record a user correction to the corrections log.

    Args:
        entry_id: JSON-LD entry ID
        from_category: Original category (e.g., "Tasks")
        to_category: Corrected category (e.g., "People")
        title: Entry title
        content_sample: First 200 chars of content
    """
    CORRECTIONS_FILE.parent.mkdir(parents=True, exist_ok=True)

    correction = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "entry_id": entry_id,
        "from_category": from_category,
        "to_category": to_category,
        "title": title,
        "content_sample": content_sample[:200],
    }

    with CORRECTIONS_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(correction) + "\n")

    logger.info(
        f"[correction] Recorded: {from_category} -> {to_category} | {title}"
    )


def get_corrections() -> list[dict]:
    """Load all corrections from the log file.

    Returns:
        List of correction dicts
    """
    if not CORRECTIONS_FILE.exists():
        return []

    corrections = []
    with CORRECTIONS_FILE.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    corrections.append(json.loads(line))
                except json.JSONDecodeError as e:
                    logger.warning(f"Invalid JSON in corrections file: {e}")
                    continue

    return corrections


def get_correction_patterns() -> list[dict]:
    """Analyze corrections to find recurring patterns.

    Looks for common words/phrases in titles that were corrected
    from one category to another.

    Returns:
        List of patterns like:
        {"pattern": "b-day", "from": "Tasks", "to": "People", "count": 3}
    """
    corrections = get_corrections()

    # Group by from->to category pair
    patterns = {}

    for corr in corrections:
        from_cat = corr["from_category"]
        to_cat = corr["to_category"]
        title = corr["title"].lower()

        key = (from_cat, to_cat)
        if key not in patterns:
            patterns[key] = {"titles": [], "from": from_cat, "to": to_cat}
        patterns[key]["titles"].append(title)

    # Find common words in titles for each pattern
    result = []
    for (from_cat, to_cat), data in patterns.items():
        titles = data["titles"]
        # Very simple pattern extraction: find words that appear in >50% of titles
        word_counts = {}
        for title in titles:
            words = title.split()
            for word in words:
                word_counts[word] = word_counts.get(word, 0) + 1

        threshold = len(titles) * 0.5
        common_words = [w for w, count in word_counts.items() if count >= threshold]

        if common_words:
            result.append({
                "pattern": " ".join(common_words),
                "from": from_cat,
                "to": to_cat,
                "count": len(titles),
                "example_titles": titles[:3],
            })

    return result


def check_correction_match(content: str, title: str) -> Optional[str]:
    """Check if content matches a learned correction pattern.

    Args:
        content: Note content
        title: Note title

    Returns:
        Corrected category name if match found, else None
    """
    patterns = get_correction_patterns()

    text = f"{title} {content}".lower()

    for pattern_def in patterns:
        pattern = pattern_def["pattern"].lower()
        # Simple substring match for now
        # Future: use fuzzy matching or regex
        if pattern in text:
            to_category = pattern_def["to"]
            logger.info(
                f"[learned-pattern] Matched '{pattern}' -> {to_category} "
                f"(learned from {pattern_def['count']} correction(s))"
            )
            return to_category

    return None
