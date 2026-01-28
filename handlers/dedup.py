"""Deduplication logic for brain handler.

Timestamp-first deduplication (MEMORY.md documented fix):
- Priority 1: Exact filename match (survives restarts)
- Priority 2: Weighted scoring for recent entries (catches renames, splits)

This module was extracted from the original brain.py for clarity and tracing.
"""
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from handlers.tracing import observe, langfuse_context

from data.database import get_entry_by_source_filename, get_recent_entries

logger = logging.getLogger(__name__)


@observe(name="find_existing")
def find_existing(source_file: Optional[str], content: str) -> Optional[dict]:
    """Find existing entry this content should update.

    Uses timestamp-first deduplication (MEMORY.md documented fix):
    1. Exact filename match (priority, survives restarts)
    2. Weighted scoring for recent entries (catches renames, title drift)

    Args:
        source_file: Full source file path (may be None)
        content: Current content text

    Returns:
        Existing entry dict if found, None otherwise
    """
    source_filename = Path(source_file).name if source_file else None

    # Priority 1: Exact filename match (no time limit)
    if source_filename:
        existing = get_entry_by_source_filename(source_filename)
        if existing:
            langfuse_context.update_current_observation(
                metadata={"match_type": "filename", "filename": source_filename}
            )
            logger.info(f"Found by source_filename: {existing.get('id')}")
            return existing

    # Priority 2: Weighted scoring for recent entries
    match = _find_matching_entry(source_filename, content)
    if match:
        langfuse_context.update_current_observation(
            metadata={"match_type": "weighted", "score": match.get("_score", 0)}
        )
        return match

    langfuse_context.update_current_observation(
        metadata={"match_type": "none"}
    )
    return None


def _find_matching_entry(source_filename: Optional[str], content: str) -> Optional[dict]:
    """Find existing entry using weighted scoring.

    Weights (from MEMORY.md):
    - Priority 1: first_seen_at within 5 min (weight 0.5)
    - Priority 2: Content prefix match (weight 0.3)
    - Priority 3: source_filename exact match (weight 0.15)
    - Priority 4: Title similarity (weight 0.05)

    Args:
        source_filename: Original inbox filename (may be None)
        content: Current content text

    Returns:
        Matching entry dict if found (score >= 0.5), None otherwise
    """
    recent = get_recent_entries(minutes=10)
    if not recent:
        return None

    now = datetime.now(timezone.utc)
    best_match = None
    best_score = 0.0
    content_prefix = content[:50] if content else ""

    for entry in recent:
        score = 0.0

        # Priority 1: Time proximity (highest weight - 0.5)
        first_seen = entry.get("first_seen_at")
        if first_seen:
            try:
                if isinstance(first_seen, str):
                    first_seen_dt = datetime.fromisoformat(first_seen.replace('Z', '+00:00'))
                    if first_seen_dt.tzinfo is None:
                        first_seen_dt = first_seen_dt.replace(tzinfo=timezone.utc)
                    age_seconds = (now - first_seen_dt).total_seconds()
                    age_minutes = age_seconds / 60
                    if age_minutes < 5:
                        score += 0.5 * (1 - age_minutes / 5)
            except (ValueError, TypeError):
                pass

        # Priority 2: Content prefix match (weight 0.3)
        entry_content = entry.get("content", "")
        entry_prefix = entry_content[:50] if entry_content else ""
        if content_prefix and entry_prefix and content_prefix == entry_prefix:
            score += 0.3

        # Priority 3: Source filename match (weight 0.15)
        if source_filename and source_filename == entry.get("source_filename"):
            score += 0.15

        # Priority 4: Title similarity (weight 0.05)
        entry_title = entry.get("title", "")
        if entry_title and content:
            content_start = content[:30].lower().strip()
            title_lower = entry_title.lower().strip()
            if title_lower in content_start or content_start.startswith(title_lower[:10]):
                score += 0.05

        if score > best_score:
            best_score = score
            best_match = entry

    # Threshold: 0.5 = "probably the same thought"
    if best_score >= 0.5:
        logger.info(f"Found matching entry (score={best_score:.2f}): {best_match.get('id')}")
        best_match["_score"] = best_score
        return best_match

    return None


@observe(name="is_unchanged")
def is_unchanged(existing: dict, content_hash: str) -> bool:
    """Check if content has changed since last save.

    Args:
        existing: Existing entry dict
        content_hash: Hash of current content

    Returns:
        True if unchanged, False if modified
    """
    unchanged = existing.get("content_hash") == content_hash
    langfuse_context.update_current_observation(
        metadata={"unchanged": unchanged}
    )
    return unchanged
