"""
Agent Scorer - Calculate performance scores from result.json files.

Scores agents across 4 categories (0-100 each):
- Completion: Did they finish?
- Quality: Tests, types, error handling, docs
- Efficiency: Files/time ratio, focused changes
- Collaboration: Blackboard usage, handoffs, questions answered
"""

import json
from pathlib import Path
from typing import Optional
from datetime import datetime

from .schemas import CategoryScores


RESULTS_PATH = Path("C:/Users/<user>/workspace/IHIM/team/results")


def score_completion(result: dict) -> float:
    """
    Score based on completion status.

    complete=100, partial=70, blocked=40, failed=0
    """
    status = result.get("status", "").lower()

    status_scores = {
        "complete": 100,
        "partial": 70,
        "blocked": 40,
        "failed": 0,
    }

    return status_scores.get(status, 50)


def score_quality(result: dict) -> float:
    """
    Score based on quality indicators.

    Each indicator adds 25 points:
    - tests_written
    - types_added
    - error_handling
    - documentation (or has handoff_notes)
    """
    score = 0

    # Check quality_indicators if present
    qi = result.get("quality_indicators", {})
    if qi.get("tests_written"):
        score += 25
    if qi.get("types_added"):
        score += 25
    if qi.get("error_handling"):
        score += 25
    if qi.get("documentation"):
        score += 25

    # Bonus for good handoff notes
    handoff = result.get("handoff_notes", "")
    if len(handoff) > 50:  # Substantial handoff notes
        score = min(100, score + 15)

    # Bonus for learnings documented
    learnings = result.get("learnings", [])
    if len(learnings) >= 2:
        score = min(100, score + 10)

    return score


def score_efficiency(result: dict) -> float:
    """
    Score based on efficiency of work.

    Factors:
    - Files created/modified (more = more productive)
    - No blockers = efficient
    - Clean summary = focused work
    """
    score = 50  # Base score

    # Files created/modified
    files_created = result.get("files_created", [])
    files_modified = result.get("files_modified", [])
    total_files = len(files_created) + len(files_modified)

    # More files = more productive (cap at +30)
    score += min(30, total_files * 5)

    # Penalty for blockers (unresolved)
    blockers = result.get("blockers", [])
    unresolved = [b for b in blockers if not b.get("resolved", False)]
    score -= len(unresolved) * 10

    # Bonus for having a clear summary
    summary = result.get("summary", "")
    if len(summary) > 100:  # Good summary
        score += 10

    # Bonus for having API endpoints documented (backend efficiency)
    if result.get("api_endpoints"):
        score += 10

    return max(0, min(100, score))


def score_collaboration(result: dict) -> float:
    """
    Score based on collaboration quality.

    Factors:
    - Has handoff_notes (communication)
    - Questions for team (seeking alignment)
    - Needs review from (inviting review)
    - No coordination_requests left hanging
    """
    score = 50  # Base score

    # Handoff notes = good communication
    handoff = result.get("handoff_notes", "")
    if handoff:
        score += 15
        if "@" in handoff:  # Directed at specific agent
            score += 5

    # Questions for team = proactive coordination
    questions = result.get("questions_for_team", [])
    if questions:
        score += min(20, len(questions) * 5)

    # Needs review = inviting collaboration
    needs_review = result.get("needs_review_from", [])
    if needs_review:
        score += 10

    # Penalty for hanging coordination requests
    coord_requests = result.get("coordination_requests", [])
    score -= len(coord_requests) * 5

    return max(0, min(100, score))


def score_agent_result(result: dict) -> CategoryScores:
    """
    Calculate all category scores for an agent result.
    """
    return CategoryScores(
        completion=score_completion(result),
        quality=score_quality(result),
        efficiency=score_efficiency(result),
        collaboration=score_collaboration(result),
    )


def load_and_score_result(agent_name: str) -> Optional[CategoryScores]:
    """
    Load a result.json file and calculate scores.
    """
    result_file = RESULTS_PATH / f"{agent_name}-result.json"

    if not result_file.exists():
        return None

    try:
        result = json.loads(result_file.read_text(encoding="utf-8"))
        return score_agent_result(result)
    except Exception as e:
        print(f"Error scoring {agent_name}: {e}")
        return None


def score_all_results() -> dict[str, CategoryScores]:
    """
    Score all result.json files in the results directory.

    Returns dict of agent_name -> CategoryScores
    """
    scores = {}

    if not RESULTS_PATH.exists():
        return scores

    for result_file in RESULTS_PATH.glob("*-result.json"):
        agent_name = result_file.stem.replace("-result", "")
        try:
            result = json.loads(result_file.read_text(encoding="utf-8"))
            scores[agent_name] = score_agent_result(result)
        except Exception as e:
            print(f"Error scoring {agent_name}: {e}")

    return scores


def calculate_average_scores(all_scores: dict[str, CategoryScores]) -> CategoryScores:
    """
    Calculate average scores across all agents.
    """
    if not all_scores:
        return CategoryScores()

    n = len(all_scores)
    return CategoryScores(
        completion=sum(s.completion for s in all_scores.values()) / n,
        quality=sum(s.quality for s in all_scores.values()) / n,
        efficiency=sum(s.efficiency for s in all_scores.values()) / n,
        collaboration=sum(s.collaboration for s in all_scores.values()) / n,
    )


def get_current_scores() -> dict:
    """
    Get current scores for display.

    Returns dict with:
    - agents: per-agent scores
    - average: average across all agents
    - timestamp: when calculated
    """
    all_scores = score_all_results()
    avg_scores = calculate_average_scores(all_scores)

    return {
        "agents": {name: scores.to_dict() for name, scores in all_scores.items()},
        "average": avg_scores.to_dict(),
        "agent_count": len(all_scores),
        "timestamp": datetime.now().isoformat(),
    }
