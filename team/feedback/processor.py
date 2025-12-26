"""
Result Processor - Parse agent results and extract learnings.

This module takes raw agent output and converts it into structured
FeedbackEntry objects that can be aggregated and analyzed.
"""

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from .schemas import (
    AgentResult,
    FeedbackEntry,
    FileModification,
    Blocker,
    QualityIndicators,
)


# Paths
RESULTS_PATH = Path("C:/Users/<user>/workspace/IHIM/team/results")


def parse_agent_output(raw_output: str) -> Optional[dict]:
    """
    Parse raw agent output to extract JSON result.

    Agents may output markdown, text, and JSON mixed together.
    This function extracts the structured result JSON.
    """
    # Try to find JSON block in markdown code fence
    json_match = re.search(r'```json\s*\n(.*?)\n```', raw_output, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except json.JSONDecodeError:
            pass

    # Try to find raw JSON object
    json_match = re.search(r'\{[^{}]*"agent"[^{}]*\}', raw_output, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(0))
        except json.JSONDecodeError:
            pass

    # Try parsing entire output as JSON
    try:
        return json.loads(raw_output)
    except json.JSONDecodeError:
        pass

    return None


def calculate_quality_score(result: AgentResult) -> float:
    """
    Calculate a quality score (0.0 to 1.0) based on indicators.

    Scoring:
    - Base: 0.5 for completing
    - +0.1 for each quality indicator
    - +0.1 for having learnings
    - -0.1 for each unresolved blocker
    - -0.2 for failed status
    """
    score = 0.5  # Base score for completing

    # Status modifier
    if result.status == "complete":
        score += 0.1
    elif result.status == "partial":
        score += 0.0
    elif result.status == "blocked":
        score -= 0.1
    elif result.status == "failed":
        score -= 0.2

    # Quality indicators
    qi = result.quality_indicators
    if qi.tests_written:
        score += 0.1
    if qi.types_added:
        score += 0.1
    if qi.error_handling:
        score += 0.1
    if qi.documentation:
        score += 0.05

    # Learnings bonus
    if result.learnings:
        score += 0.1

    # Blocker penalty
    unresolved = sum(1 for b in result.blockers if not b.resolved)
    score -= unresolved * 0.1

    # Clamp to 0.0-1.0
    return max(0.0, min(1.0, score))


def detect_patterns(result: AgentResult) -> list[str]:
    """
    Detect coding patterns used based on files modified and summary.
    """
    patterns = []

    # Check file patterns
    for file_mod in result.files_modified:
        path = file_mod.path.lower()
        if "component" in path or path.endswith(".tsx"):
            patterns.append("component")
        if "api" in path or "route" in path:
            patterns.append("api-endpoint")
        if "test" in path or ".test." in path or ".spec." in path:
            patterns.append("testing")
        if "hook" in path or "use" in Path(path).stem:
            patterns.append("react-hook")
        if "util" in path or "helper" in path:
            patterns.append("utility")
        if "type" in path or path.endswith(".d.ts"):
            patterns.append("types")

    # Check summary for patterns
    summary_lower = result.summary.lower()
    if "form" in summary_lower:
        patterns.append("form-handling")
    if "validation" in summary_lower:
        patterns.append("validation")
    if "auth" in summary_lower:
        patterns.append("authentication")
    if "fetch" in summary_lower or "api call" in summary_lower:
        patterns.append("api-call")
    if "error" in summary_lower and "handling" in summary_lower:
        patterns.append("error-handling")

    return list(set(patterns))  # Dedupe


def process_result(agent: str, result_data: dict) -> FeedbackEntry:
    """
    Process a single agent result into a FeedbackEntry.

    Args:
        agent: Agent name (e.g., "frontend-dev")
        result_data: Raw result dict from agent

    Returns:
        FeedbackEntry with extracted learnings
    """
    # Parse into AgentResult model
    try:
        result = AgentResult(**result_data)
    except Exception:
        # Fallback for malformed results
        result = AgentResult(
            agent=agent,
            session_id=result_data.get("session_id", "unknown"),
            status=result_data.get("status", "unknown"),
            summary=result_data.get("summary", str(result_data)),
        )

    # Calculate duration if timestamps present
    duration = None
    if result.started_at and result.completed_at:
        duration = (result.completed_at - result.started_at).total_seconds()

    # Build FeedbackEntry
    return FeedbackEntry(
        agent=agent,
        session_id=result.session_id,
        success=result.status in ["complete", "partial"],
        files_touched=[fm.path for fm in result.files_modified],
        patterns_used=detect_patterns(result),
        blockers=[b.description for b in result.blockers if not b.resolved],
        handoff_requests=[cr.message for cr in result.coordination_requests],
        quality_score=calculate_quality_score(result),
        duration_seconds=duration,
        timestamp=datetime.now(),
    )


def process_session_results(session_id: str) -> list[FeedbackEntry]:
    """
    Process all agent results for a session.

    Reads result files from RESULTS_PATH and processes each one.
    """
    entries = []

    for result_file in RESULTS_PATH.glob(f"*-result.json"):
        try:
            data = json.loads(result_file.read_text(encoding="utf-8"))
            # Check if this result is for our session
            if data.get("session_id") == session_id:
                agent = result_file.stem.replace("-result", "")
                entry = process_result(agent, data)
                entries.append(entry)
        except Exception as e:
            print(f"Error processing {result_file}: {e}")

    return entries


def save_feedback_entry(entry: FeedbackEntry) -> Path:
    """
    Save a feedback entry to the data directory.
    """
    data_path = Path("C:/Users/<user>/workspace/IHIM/team/data")
    data_path.mkdir(parents=True, exist_ok=True)

    # Append to feedback history
    history_file = data_path / "feedback_history.json"
    history = []
    if history_file.exists():
        try:
            history = json.loads(history_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            history = []

    history.append(entry.model_dump(mode="json"))

    # Keep last 100 entries
    if len(history) > 100:
        history = history[-100:]

    history_file.write_text(json.dumps(history, indent=2, default=str), encoding="utf-8")

    return history_file
