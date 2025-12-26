"""
Feedback Aggregator - Combine feedback from all agents in a session.

This module takes individual FeedbackEntry objects and combines them
into SessionFeedback, detecting patterns and coordination gaps.
"""

import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Optional

from .schemas import FeedbackEntry, SessionFeedback
from .processor import process_session_results


DATA_PATH = Path("C:/Users/<user>/workspace/IHIM/team/data")


def detect_coordination_gaps(entries: list[FeedbackEntry]) -> list[str]:
    """
    Detect coordination gaps between agents.

    Looks for patterns like:
    - Frontend blocked waiting for backend
    - Multiple agents touching same files
    - Handoff requests that weren't fulfilled
    """
    gaps = []

    # Check for handoff requests that weren't fulfilled
    all_handoffs = []
    for entry in entries:
        for handoff in entry.handoff_requests:
            all_handoffs.append((entry.agent, handoff))

    if all_handoffs:
        gaps.append(f"{len(all_handoffs)} handoff requests made")

    # Check for blockers that affected multiple agents
    all_blockers = []
    for entry in entries:
        all_blockers.extend(entry.blockers)

    blocker_counts = Counter(all_blockers)
    for blocker, count in blocker_counts.items():
        if count > 1:
            gaps.append(f"Blocker affected {count} agents: {blocker[:50]}")

    # Check for agents with low scores (might indicate coordination issues)
    low_score_agents = [e.agent for e in entries if e.quality_score < 0.5]
    if low_score_agents:
        gaps.append(f"Low performance: {', '.join(low_score_agents)}")

    return gaps


def find_repeated_blockers(entries: list[FeedbackEntry], history: list[dict]) -> list[str]:
    """
    Find blockers that keep recurring across sessions.

    If the same type of blocker appears 3+ times, it's a systemic issue.
    """
    # Collect all blockers from current session
    current_blockers = []
    for entry in entries:
        current_blockers.extend(entry.blockers)

    # Collect blockers from history
    historical_blockers = []
    for hist_entry in history[-50:]:  # Last 50 entries
        historical_blockers.extend(hist_entry.get("blockers", []))

    # Find patterns (simple keyword matching)
    all_blockers = current_blockers + historical_blockers
    blocker_keywords = Counter()
    for blocker in all_blockers:
        # Extract key phrases
        words = blocker.lower().split()
        for word in words:
            if len(word) > 4:  # Skip short words
                blocker_keywords[word] += 1

    # Return keywords that appear 3+ times
    repeated = []
    for keyword, count in blocker_keywords.most_common(5):
        if count >= 3:
            repeated.append(f"{keyword} (seen {count}x)")

    return repeated


def extract_learnings(entries: list[FeedbackEntry]) -> list[str]:
    """
    Extract and deduplicate learnings from all agents.
    """
    learnings = []
    seen = set()

    for entry in entries:
        # Convert patterns to learnings
        for pattern in entry.patterns_used:
            learning = f"Used {pattern} pattern"
            if learning not in seen:
                learnings.append(learning)
                seen.add(learning)

    # Add learnings from blockers (what to avoid)
    for entry in entries:
        for blocker in entry.blockers:
            learning = f"Avoid: {blocker[:50]}"
            if learning not in seen:
                learnings.append(learning)
                seen.add(learning)

    return learnings[:10]  # Cap at 10


def aggregate_session(session_id: str, prompt: str = "") -> SessionFeedback:
    """
    Aggregate all feedback from a spawn session.

    Args:
        session_id: The session to aggregate
        prompt: The original user prompt

    Returns:
        SessionFeedback with combined metrics and learnings
    """
    # Process all results for this session
    entries = process_session_results(session_id)

    if not entries:
        return SessionFeedback(
            session_id=session_id,
            prompt=prompt,
            overall_success=False,
            learnings=["No agent results found"],
        )

    # Load historical feedback for pattern detection
    history = []
    history_file = DATA_PATH / "feedback_history.json"
    if history_file.exists():
        try:
            history = json.loads(history_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            history = []

    # Calculate aggregate metrics
    agent_scores = {e.agent: e.quality_score for e in entries}
    total_files = sum(len(e.files_touched) for e in entries)
    total_duration = sum(e.duration_seconds or 0 for e in entries)
    completed = sum(1 for e in entries if e.success)
    failed = len(entries) - completed

    # Overall success: at least 80% of agents succeeded
    overall_success = (completed / len(entries)) >= 0.8 if entries else False

    return SessionFeedback(
        session_id=session_id,
        prompt=prompt,
        overall_success=overall_success,
        agent_scores=agent_scores,
        coordination_gaps=detect_coordination_gaps(entries),
        repeated_blockers=find_repeated_blockers(entries, history),
        learnings=extract_learnings(entries),
        total_files_modified=total_files,
        total_duration_seconds=total_duration,
        agents_completed=completed,
        agents_failed=failed,
        timestamp=datetime.now(),
    )


def save_session_feedback(feedback: SessionFeedback) -> Path:
    """
    Save session feedback to the data directory.
    """
    DATA_PATH.mkdir(parents=True, exist_ok=True)

    # Save individual session
    session_file = DATA_PATH / f"session_{feedback.session_id}.json"
    session_file.write_text(
        feedback.model_dump_json(indent=2),
        encoding="utf-8"
    )

    # Append to sessions history
    sessions_file = DATA_PATH / "sessions_history.json"
    sessions = []
    if sessions_file.exists():
        try:
            sessions = json.loads(sessions_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            sessions = []

    sessions.append(feedback.model_dump(mode="json"))

    # Keep last 50 sessions
    if len(sessions) > 50:
        sessions = sessions[-50:]

    sessions_file.write_text(
        json.dumps(sessions, indent=2, default=str),
        encoding="utf-8"
    )

    return session_file


def get_session_feedback(session_id: str) -> Optional[SessionFeedback]:
    """
    Retrieve saved session feedback.
    """
    session_file = DATA_PATH / f"session_{session_id}.json"
    if session_file.exists():
        try:
            data = json.loads(session_file.read_text(encoding="utf-8"))
            return SessionFeedback(**data)
        except Exception:
            pass
    return None
