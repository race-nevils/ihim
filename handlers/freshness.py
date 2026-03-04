"""Category-aware freshness scoring for Knowledge Graph.

ARCHITECTURE ROLE: Freshness Engine
====================================
Computes time-decay weights per entry, respecting category semantics:
    - Evergreen categories (People, Legal, Health) never decay
    - Fast-decay categories (Tasks, Meetings) have 21-day half-life
    - Moderate categories (Research, Projects) decay and get flagged for triage
    - Slow-decay categories (Business, Ideas, Reference) decay gradually

Design decision from KNOWLEDGE-GRAPH.md Q11:
    Freshness means different things for different data types.
    A uniform decay is wrong. Category-aware exponential decay is correct.
"""

import logging
import math
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# =============================================================================
# Category Decay Profiles
# =============================================================================

# Half-life in days. None = evergreen (no decay, always 1.0)
DECAY_PROFILES: dict[str, Optional[int]] = {
    "People": None,      # Evergreen — relationships don't expire
    "Legal": None,       # Evergreen — legal docs stay relevant
    "Health": None,      # Evergreen — health info stays relevant
    "Tasks": 21,         # Fast decay — 21-day half-life
    "Meetings": 21,      # Fast decay — meetings age quickly
    "Business": 60,      # Slow decay
    "Ideas": 60,         # Slow decay
    "Reference": 90,     # Very slow decay
    "Research": 45,      # Moderate — flagged for triage when stale
    "Projects": 45,      # Moderate — flagged for triage when stale
}

# Categories that get surfaced for human review when stale
TRIAGE_CATEGORIES = {"Research", "Projects"}

DEFAULT_HALF_LIFE = 45


def compute_freshness(date_created: str, category: str) -> float:
    """Compute freshness score for an entry based on age and category.

    Evergreen categories always return 1.0.
    Others use exponential decay: 0.5 ^ (age_days / half_life)

    Args:
        date_created: ISO 8601 timestamp string
        category: Entry category (must match categories.json)

    Returns:
        Float 0.0–1.0 (1.0 = perfectly fresh, 0.0 = ancient)
    """
    half_life = DECAY_PROFILES.get(category)
    if half_life is None:
        return 1.0  # Evergreen

    age_days = _age_in_days(date_created)
    if age_days <= 0:
        return 1.0

    return math.pow(0.5, age_days / half_life)


def get_stale_entries(threshold: float = 0.3) -> list[dict]:
    """Return entries in triage categories where freshness < threshold.

    These are candidates for the operator's binary review (refresh or fade).

    Args:
        threshold: Freshness score below which entries are considered stale

    Returns:
        List of dicts with id, title, category, freshness, age_days, degree
    """
    from data.database import get_connection

    conn = get_connection()
    try:
        # Get entries in triage categories with their relation counts
        rows = conn.execute("""
            SELECT e.id, e.title, e.category, e.first_seen_at,
                   COALESCE(e.deprioritized, 0) as deprioritized
            FROM entries e
            WHERE e.category IN ({})
            AND COALESCE(e.deprioritized, 0) = 0
        """.format(",".join("?" for _ in TRIAGE_CATEGORIES)),
            list(TRIAGE_CATEGORIES)
        ).fetchall()

        # Get degree counts for all entries
        degree_map = {}
        degree_rows = conn.execute("""
            SELECT eid, COUNT(*) as degree FROM (
                SELECT source_id as eid FROM entry_relations
                UNION ALL
                SELECT target_id as eid FROM entry_relations
            ) GROUP BY eid
        """).fetchall()
        for dr in degree_rows:
            degree_map[dr["eid"]] = dr["degree"]

        stale = []
        for row in rows:
            created = row["first_seen_at"] or ""
            cat = row["category"]
            freshness = compute_freshness(created, cat)

            if freshness < threshold:
                age_days = _age_in_days(created)
                stale.append({
                    "id": row["id"],
                    "title": row["title"],
                    "category": cat,
                    "freshness": round(freshness, 3),
                    "age_days": age_days,
                    "degree": degree_map.get(row["id"], 0),
                })

        # Sort by freshness ascending (stalest first)
        stale.sort(key=lambda x: x["freshness"])
        return stale
    finally:
        conn.close()


def _age_in_days(date_str: str) -> int:
    """Parse an ISO date string and return age in days from now."""
    if not date_str:
        return 0
    try:
        created = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        return max(0, (now - created).days)
    except (ValueError, TypeError):
        return 0
