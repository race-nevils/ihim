"""Entity type detection from patterns.

Deterministic detection of entity types (People, Projects, etc.)
based on pattern matching. Overrides LLM classification when confident.

Layer 2 of the Content/Instruction Separation System.
"""
import json
import re
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

IHIM_ROOT = Path(__file__).parent.parent
LEXICON_PATH = IHIM_ROOT / "data" / "lexicon" / "instruction_lexicon_v1.0.json"


class EntityPatternMatcher:
    """Pattern-based entity type detection."""

    def __init__(self, lexicon_path: Path):
        self._data = json.loads(lexicon_path.read_text(encoding="utf-8"))
        self._patterns = self._data.get("entity_patterns", [])
        logger.info(f"Loaded entity patterns: {len(self._patterns)} patterns")

    def get_patterns(self) -> list[dict]:
        """Get all entity patterns."""
        return self._patterns


# Singleton
_matcher: Optional[EntityPatternMatcher] = None


def get_entity_matcher() -> EntityPatternMatcher:
    """Get or create the singleton EntityPatternMatcher instance."""
    global _matcher
    if _matcher is None:
        _matcher = EntityPatternMatcher(LEXICON_PATH)
    return _matcher


def detect_entity_type(content: str, title: str = "") -> Optional[dict]:
    """Detect entity type from title and content patterns.

    Checks:
    1. Patterns from instruction lexicon (birthday, contact, etc.)
    2. Learned patterns from user corrections (future: corrections.py)

    Args:
        content: Note content
        title: Note title (if available)

    Returns:
        {"entity_type": "People", "pattern": "birthday", "confidence": 1.0}
        or None if no confident match
    """
    matcher = get_entity_matcher()

    # Combine title and content for matching
    text = f"{title} {content}" if title else content

    # Check each pattern
    for pattern_def in matcher.get_patterns():
        regex = pattern_def["pattern_regex"]
        entity_type = pattern_def["entity_type"]
        confidence = pattern_def.get("confidence", 0.8)

        try:
            if re.search(regex, text, re.IGNORECASE):
                match = re.search(regex, text, re.IGNORECASE)
                matched_text = match.group(0) if match else ""

                logger.info(
                    f"[entity-type] Detected pattern '{matched_text}' -> {entity_type} "
                    f"(confidence={confidence})"
                )

                return {
                    "entity_type": entity_type,
                    "pattern": pattern_def.get("notes", regex),
                    "matched_text": matched_text,
                    "confidence": confidence,
                }
        except re.error as e:
            logger.warning(f"Invalid regex pattern: {regex} - {e}")
            continue

    # Future: check learned patterns from corrections.py
    # learned = check_learned_patterns(content, title)
    # if learned:
    #     return learned

    return None
