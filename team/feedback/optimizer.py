"""
Prompt Optimizer - Refine agent prompts based on feedback.

This module analyzes feedback history and generates optimizations
that can be injected into future agent prompts to avoid past issues.
"""

import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Optional

from .schemas import PromptOptimization, SessionFeedback
from .metrics import load_metrics


DATA_PATH = Path("C:/Users/<user>/workspace/IHIM/team/data")
OPTIMIZATIONS_FILE = DATA_PATH / "optimizations.json"


def load_optimizations() -> list[PromptOptimization]:
    """
    Load current optimizations from disk.
    """
    if OPTIMIZATIONS_FILE.exists():
        try:
            data = json.loads(OPTIMIZATIONS_FILE.read_text(encoding="utf-8"))
            return [PromptOptimization(**opt) for opt in data]
        except Exception:
            pass
    return []


def save_optimizations(optimizations: list[PromptOptimization]) -> None:
    """
    Save optimizations to disk.
    """
    DATA_PATH.mkdir(parents=True, exist_ok=True)
    data = [opt.model_dump(mode="json") for opt in optimizations]
    OPTIMIZATIONS_FILE.write_text(
        json.dumps(data, indent=2, default=str),
        encoding="utf-8"
    )


def analyze_blockers(sessions: list[dict]) -> list[PromptOptimization]:
    """
    Analyze blockers to generate preventive optimizations.

    If a blocker appears 3+ times, add a reminder to prevent it.
    """
    optimizations = []

    # Collect all blockers with agent info
    blocker_by_agent = {}
    for session in sessions:
        gaps = session.get("coordination_gaps", [])
        for gap in gaps:
            # Extract agent from gap message if possible
            if "frontend" in gap.lower():
                agent = "frontend-dev"
            elif "backend" in gap.lower():
                agent = "backend-dev"
            elif "qa" in gap.lower() or "test" in gap.lower():
                agent = "qa-tester"
            elif "security" in gap.lower():
                agent = "security-reviewer"
            else:
                agent = "all"

            if agent not in blocker_by_agent:
                blocker_by_agent[agent] = []
            blocker_by_agent[agent].append(gap)

    # Generate optimizations for repeated issues
    for agent, blockers in blocker_by_agent.items():
        counts = Counter(blockers)
        for blocker, count in counts.most_common(3):
            if count >= 2:  # Lower threshold for now
                optimizations.append(PromptOptimization(
                    agent=agent,
                    type="reminder",
                    content=f"IMPORTANT: {blocker}. This has caused issues {count}x before.",
                    reason=f"Blocker seen {count} times",
                    times_triggered=count,
                ))

    return optimizations


def analyze_patterns(sessions: list[dict]) -> list[PromptOptimization]:
    """
    Analyze successful patterns to reinforce good behaviors.
    """
    optimizations = []

    # Collect learnings that correlate with high scores
    high_score_learnings = []
    for session in sessions:
        scores = session.get("agent_scores", {})
        avg_score = sum(scores.values()) / len(scores) if scores else 0

        if avg_score >= 0.7:  # High-performing session
            high_score_learnings.extend(session.get("learnings", []))

    # Find patterns that appear in successful sessions
    pattern_counts = Counter(high_score_learnings)
    for pattern, count in pattern_counts.most_common(3):
        if count >= 2:
            optimizations.append(PromptOptimization(
                agent="all",
                type="prepend",
                content=f"Best Practice: {pattern}",
                reason=f"Correlated with success in {count} sessions",
                times_triggered=count,
            ))

    return optimizations


def generate_optimizations(session_feedback: Optional[SessionFeedback] = None) -> list[PromptOptimization]:
    """
    Generate new optimizations based on feedback history.

    Args:
        session_feedback: Optional new session to include

    Returns:
        List of optimizations to apply
    """
    # Load session history
    sessions_file = DATA_PATH / "sessions_history.json"
    sessions = []
    if sessions_file.exists():
        try:
            sessions = json.loads(sessions_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            sessions = []

    if session_feedback:
        sessions.append(session_feedback.model_dump())

    if len(sessions) < 2:
        return []  # Not enough data

    optimizations = []

    # Analyze blockers for preventive measures
    optimizations.extend(analyze_blockers(sessions))

    # Analyze patterns for reinforcement
    optimizations.extend(analyze_patterns(sessions))

    # Dedupe by content
    seen_content = set()
    unique_opts = []
    for opt in optimizations:
        if opt.content not in seen_content:
            unique_opts.append(opt)
            seen_content.add(opt.content)

    # Save
    save_optimizations(unique_opts)

    return unique_opts


def get_optimizations_for_agent(agent: str) -> list[PromptOptimization]:
    """
    Get all applicable optimizations for a specific agent.

    Returns optimizations for the agent + "all" agents.
    """
    all_opts = load_optimizations()
    return [opt for opt in all_opts if opt.agent in [agent, "all"]]


def apply_optimizations_to_prompt(agent: str, base_prompt: str) -> str:
    """
    Apply optimizations to a base prompt.

    Args:
        agent: The agent this prompt is for
        base_prompt: The original prompt

    Returns:
        Enhanced prompt with optimizations
    """
    optimizations = get_optimizations_for_agent(agent)

    if not optimizations:
        return base_prompt

    # Separate by type
    prepends = [opt for opt in optimizations if opt.type == "prepend"]
    appends = [opt for opt in optimizations if opt.type == "append"]
    reminders = [opt for opt in optimizations if opt.type == "reminder"]

    # Build enhanced prompt
    parts = []

    # Add prepends
    for opt in prepends[:2]:  # Max 2 prepends
        parts.append(f"[LEARNED] {opt.content}")

    # Add reminders
    for opt in reminders[:3]:  # Max 3 reminders
        parts.append(f"[REMINDER] {opt.content}")

    # Add base prompt
    parts.append(base_prompt)

    # Add appends
    for opt in appends[:2]:  # Max 2 appends
        parts.append(f"[NOTE] {opt.content}")

    return "\n\n".join(parts)


def clear_stale_optimizations(max_age_days: int = 30) -> int:
    """
    Remove optimizations older than max_age_days.

    Returns:
        Number of optimizations removed
    """
    optimizations = load_optimizations()
    now = datetime.now()

    fresh = []
    removed = 0
    for opt in optimizations:
        age = (now - opt.added_at).days if opt.added_at else 0
        if age <= max_age_days:
            fresh.append(opt)
        else:
            removed += 1

    if removed > 0:
        save_optimizations(fresh)

    return removed
