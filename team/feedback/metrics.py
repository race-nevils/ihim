"""
Metrics Tracker - Track improvement over time.

This module maintains metrics about agent performance and
calculates improvement trends to show the system is learning.
"""

import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Optional

from .schemas import MetricsSnapshot, SessionFeedback, CategoryScores, CategoryTrends
from .scorer import score_all_results, calculate_average_scores, get_current_scores


DATA_PATH = Path("C:/Users/<user>/workspace/IHIM/team/data")
METRICS_FILE = DATA_PATH / "metrics.json"


def load_metrics() -> MetricsSnapshot:
    """
    Load current metrics from disk.
    """
    if METRICS_FILE.exists():
        try:
            data = json.loads(METRICS_FILE.read_text(encoding="utf-8"))
            return MetricsSnapshot(**data)
        except Exception:
            pass
    return MetricsSnapshot()


def save_metrics(metrics: MetricsSnapshot) -> None:
    """
    Save metrics to disk.
    """
    DATA_PATH.mkdir(parents=True, exist_ok=True)
    METRICS_FILE.write_text(
        metrics.model_dump_json(indent=2),
        encoding="utf-8"
    )


def calculate_improvement_trend(sessions: list[dict]) -> float:
    """
    Calculate improvement trend from session history.

    Compares average success rate of recent sessions vs older sessions.
    Positive value = improving, negative = declining.
    """
    if len(sessions) < 4:
        return 0.0

    # Split into halves
    mid = len(sessions) // 2
    older = sessions[:mid]
    recent = sessions[mid:]

    # Calculate average success rates
    older_rate = sum(1 for s in older if s.get("overall_success", False)) / len(older)
    recent_rate = sum(1 for s in recent if s.get("overall_success", False)) / len(recent)

    # Calculate average quality scores
    older_scores = [
        score
        for s in older
        for score in s.get("agent_scores", {}).values()
    ]
    recent_scores = [
        score
        for s in recent
        for score in s.get("agent_scores", {}).values()
    ]

    older_avg_score = sum(older_scores) / len(older_scores) if older_scores else 0.5
    recent_avg_score = sum(recent_scores) / len(recent_scores) if recent_scores else 0.5

    # Combine success rate change and score change
    rate_change = recent_rate - older_rate
    score_change = recent_avg_score - older_avg_score

    return (rate_change + score_change) / 2


def extract_top_learnings(sessions: list[dict], limit: int = 5) -> list[str]:
    """
    Extract most common/important learnings across sessions.
    """
    all_learnings = []
    for session in sessions:
        all_learnings.extend(session.get("learnings", []))

    # Count occurrences
    learning_counts = Counter(all_learnings)

    # Return top N
    return [learning for learning, _ in learning_counts.most_common(limit)]


def extract_common_blockers(sessions: list[dict], limit: int = 5) -> list[str]:
    """
    Extract most common blockers across sessions.
    """
    all_blockers = []
    for session in sessions:
        all_blockers.extend(session.get("repeated_blockers", []))

    blocker_counts = Counter(all_blockers)
    return [blocker for blocker, _ in blocker_counts.most_common(limit)]


def update_metrics(session_feedback: SessionFeedback) -> MetricsSnapshot:
    """
    Update metrics with new session feedback.

    Args:
        session_feedback: The session to incorporate

    Returns:
        Updated MetricsSnapshot
    """
    metrics = load_metrics()

    # Load session history for trend calculation
    sessions_file = DATA_PATH / "sessions_history.json"
    sessions = []
    if sessions_file.exists():
        try:
            sessions = json.loads(sessions_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            sessions = []

    # Update counts
    metrics.total_sessions += 1
    metrics.total_agents_spawned += len(session_feedback.agent_scores)

    # Calculate averages
    all_scores = []
    all_success = []
    for session in sessions:
        all_scores.extend(session.get("agent_scores", {}).values())
        all_success.append(session.get("overall_success", False))

    # Add current session
    all_scores.extend(session_feedback.agent_scores.values())
    all_success.append(session_feedback.overall_success)

    if all_scores:
        metrics.avg_quality_score = sum(all_scores) / len(all_scores)
    if all_success:
        metrics.avg_success_rate = sum(1 for s in all_success if s) / len(all_success)

    # Update learnings and blockers
    metrics.top_learnings = extract_top_learnings(sessions + [session_feedback.model_dump()])
    metrics.common_blockers = extract_common_blockers(sessions + [session_feedback.model_dump()])

    # Calculate trend
    metrics.improvement_trend = calculate_improvement_trend(sessions + [session_feedback.model_dump()])

    # Update metadata
    metrics.last_session_id = session_feedback.session_id
    metrics.last_updated = datetime.now()

    # Save
    save_metrics(metrics)

    return metrics


def get_metrics() -> MetricsSnapshot:
    """
    Get current metrics.
    """
    return load_metrics()


def get_metrics_summary() -> dict:
    """
    Get a human-readable summary of current metrics.
    """
    metrics = load_metrics()

    # Get current scores from result files
    current = get_current_scores()

    # Format trend as percentage with direction
    if metrics.improvement_trend > 0:
        trend_str = f"+{metrics.improvement_trend * 100:.1f}%"
    elif metrics.improvement_trend < 0:
        trend_str = f"{metrics.improvement_trend * 100:.1f}%"
    else:
        trend_str = "0%"

    return {
        "sessions": metrics.total_sessions,
        "agents_spawned": metrics.total_agents_spawned,
        "success_rate": f"{metrics.avg_success_rate * 100:.0f}%",
        # Category scores
        "scores": current["average"],
        "agent_scores": current["agents"],
        "agent_count": current["agent_count"],
        # Legacy
        "quality_score": f"{metrics.avg_quality_score:.2f}",
        "trend": trend_str,
        "trends": {
            "completion": metrics.trends.completion if hasattr(metrics, 'trends') else 0,
            "quality": metrics.trends.quality if hasattr(metrics, 'trends') else 0,
            "efficiency": metrics.trends.efficiency if hasattr(metrics, 'trends') else 0,
            "collaboration": metrics.trends.collaboration if hasattr(metrics, 'trends') else 0,
            "overall": metrics.trends.overall if hasattr(metrics, 'trends') else 0,
        },
        "top_learnings": metrics.top_learnings[:3],
        "common_blockers": metrics.common_blockers[:3],
        "last_updated": metrics.last_updated.isoformat() if metrics.last_updated else None,
    }
