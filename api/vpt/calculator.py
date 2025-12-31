"""
VPT (Value Per Token) Calculator

Calculates efficiency and quality scores for AI interactions.
Based on VPT_DESIGN.md specification.

Core Formula:
    VPT = (composite_value_score / total_tokens) × 1000

Where composite_value_score is a weighted combination of:
    - success (20%)
    - outcome_quality (20%)
    - efficiency_ratio (25%)
    - dead_ends penalty (-5 each, cap -15)
    - pivots penalty (-3 each, cap -9)
    - reusability (15%)
    - learning_value (15%)
"""

from typing import Tuple


def calculate_composite_score(
    success: bool,
    outcome_quality: int,  # 1-5
    efficiency_ratio: float,  # 0-1
    dead_ends: int,
    pivots: int,
    reusability: int = 3,  # 1-5, default middle
    learning_value: int = 3  # 1-5, default middle
) -> float:
    """
    Calculate composite value score (0-100).

    Weighted combination of 7 metrics per VPT design spec:

    composite_score =
      (success × 20) +                    // Did it work? (boolean → 0 or 20)
      (outcome_quality × 4 × 20) +        // Quality (1-5 scale → 0-20)
      (efficiency_ratio × 25) +           // Effective/total actions (0-1 → 0-25)
      (-dead_ends × 5) +                  // Penalty for dead ends (cap at -15)
      (-pivots × 3) +                     // Penalty for pivots (cap at -9)
      (reusability × 3 × 20) +            // Future value (1-5 → 0-15)
      (learning_value × 3 × 20)           // Heuristic generation (1-5 → 0-15)

    Args:
        success: Did the task succeed? (True/False)
        outcome_quality: Quality of solution (1-5 scale)
        efficiency_ratio: Effective actions / total actions (0-1)
        dead_ends: Number of dead-end paths taken
        pivots: Number of strategy pivots required
        reusability: How reusable is the result? (1-5, default 3)
        learning_value: Did this generate heuristics? (1-5, default 3)

    Returns:
        Composite score (0-100)
    """
    # Validate inputs
    outcome_quality = max(1, min(5, outcome_quality))
    efficiency_ratio = max(0.0, min(1.0, efficiency_ratio))
    reusability = max(1, min(5, reusability))
    learning_value = max(1, min(5, learning_value))
    dead_ends = max(0, dead_ends)
    pivots = max(0, pivots)

    # Calculate weighted components
    success_score = 20.0 if success else 0.0
    quality_score = (outcome_quality / 5.0) * 20.0  # Normalize 1-5 to 0-20
    efficiency_score = efficiency_ratio * 25.0
    dead_ends_penalty = min(dead_ends * 5, 15)  # Cap at -15
    pivots_penalty = min(pivots * 3, 9)  # Cap at -9
    reusability_score = (reusability / 5.0) * 15.0  # Normalize 1-5 to 0-15
    learning_score = (learning_value / 5.0) * 15.0  # Normalize 1-5 to 0-15

    # Combine
    composite = (
        success_score +
        quality_score +
        efficiency_score -
        dead_ends_penalty -
        pivots_penalty +
        reusability_score +
        learning_score
    )

    # Clamp to 0-100
    return max(0.0, min(100.0, composite))


def calculate_vpt(composite_score: float, total_tokens: int) -> float:
    """
    Calculate VPT = (composite_score / total_tokens) × 1000.

    Multiplier of 1000 makes numbers human-readable (50 instead of 0.05).

    Args:
        composite_score: Composite value score (0-100)
        total_tokens: Total input + output tokens used

    Returns:
        VPT score (typically 0-200, exceptional cases can go higher)
    """
    if total_tokens <= 0:
        return 0.0

    return (composite_score / total_tokens) * 1000.0


def get_vpt_rating(vpt_score: float) -> str:
    """
    Return star rating based on VPT score.

    Benchmarks per VPT_DESIGN.md:
    - 100+ = ★★★★★ (Exceptional efficiency)
    - 50-100 = ★★★★ (High value)
    - 25-50 = ★★★ (Good, room for improvement)
    - 10-25 = ★★ (Acceptable, review for optimization)
    - <10 = ★ (Low efficiency, investigate)

    Args:
        vpt_score: Calculated VPT score

    Returns:
        Star rating string (★ to ★★★★★)
    """
    if vpt_score >= 100:
        return "★★★★★"
    elif vpt_score >= 50:
        return "★★★★"
    elif vpt_score >= 25:
        return "★★★"
    elif vpt_score >= 10:
        return "★★"
    else:
        return "★"


def estimate_tokens_from_commands(total_commands: int) -> int:
    """
    Rough estimate: 500 tokens per command.

    This is a heuristic for when exact token counts aren't available.
    Assumes each command includes:
    - Context (~200 tokens)
    - User prompt (~100 tokens)
    - Agent response (~200 tokens)

    Args:
        total_commands: Number of commands in a session

    Returns:
        Estimated total tokens
    """
    return total_commands * 500


def calculate_vpt_full(
    success: bool,
    outcome_quality: int,
    efficiency_ratio: float,
    dead_ends: int,
    pivots: int,
    total_tokens: int,
    reusability: int = 3,
    learning_value: int = 3
) -> Tuple[float, float, str]:
    """
    Calculate VPT with all components in one call.

    Convenience function that returns composite score, VPT, and rating.

    Args:
        success: Did the task succeed?
        outcome_quality: Quality of solution (1-5)
        efficiency_ratio: Effective/total actions (0-1)
        dead_ends: Number of dead ends
        pivots: Number of pivots
        total_tokens: Total tokens used
        reusability: Future value (1-5, default 3)
        learning_value: Heuristic value (1-5, default 3)

    Returns:
        Tuple of (composite_score, vpt_score, rating)
    """
    composite = calculate_composite_score(
        success=success,
        outcome_quality=outcome_quality,
        efficiency_ratio=efficiency_ratio,
        dead_ends=dead_ends,
        pivots=pivots,
        reusability=reusability,
        learning_value=learning_value
    )

    vpt = calculate_vpt(composite, total_tokens)
    rating = get_vpt_rating(vpt)

    return (composite, vpt, rating)


def calculate_swarm_vpt(
    agents_vpt: list[float],
    redundancy_ratio: float,
    speedup: float,
    synthesis_quality: float,
    conflicts: int,
    total_tokens: int
) -> dict:
    """
    Calculate composite VPT for multi-agent swarm operations.

    Swarm VPT accounts for parallelism benefits, redundancy costs, coordination
    overhead, and synthesis quality. Formula:

    swarm_composite =
      (avg_agent_vpt × 0.4) +              // Base agent performance (40%)
      (unique_findings_ratio × 25) +       // Deduplication efficiency (25 points)
      (speedup_factor × 10) +              // Parallelism benefit (10 points)
      (synthesis_quality × 15) +           // Output quality (15 points)
      max(-conflicts × 5, -10)             // Coordination penalty (cap at -10)

    Args:
        agents_vpt: List of individual agent VPT scores
        redundancy_ratio: Unique findings / total findings (0-1)
            - 1.0 = perfect deduplication (all findings unique)
            - 0.5 = 50% redundancy
            - 0.0 = total redundancy (all duplicates)
        speedup: Actual speedup factor (wall_time / sequential_baseline)
            - 10.0 = 10x speedup
            - 1.0 = no speedup (sequential)
            - 0.5 = slower than sequential (coordination overhead dominated)
        synthesis_quality: Quality of aggregated output (0-1 scale)
            - 1.0 = excellent synthesis, clear actionable insights
            - 0.5 = moderate synthesis, some useful insights
            - 0.0 = poor synthesis, hard to extract value
        conflicts: Number of coordination conflicts (file locks, race conditions)
        total_tokens: Total tokens consumed by all agents in swarm

    Returns:
        Dict with:
            - composite_score: Weighted swarm composite (0-100)
            - vpt_score: Final swarm VPT (composite / total_tokens × 1000)
            - rating: Star rating (★ to ★★★★★)
            - breakdown: Component scores for analysis
    """
    # Validate inputs
    redundancy_ratio = max(0.0, min(1.0, redundancy_ratio))
    speedup = max(0.0, speedup)
    synthesis_quality = max(0.0, min(1.0, synthesis_quality))
    conflicts = max(0, conflicts)

    # Calculate average agent VPT (if any agents completed)
    avg_agent_vpt = sum(agents_vpt) / len(agents_vpt) if agents_vpt else 0.0

    # Component calculations
    # Agent performance baseline (normalized to 0-40 scale)
    # Assume typical VPT range is 0-100, so normalize to 0-40
    agent_score = min(avg_agent_vpt * 0.4, 40.0)

    # Deduplication efficiency (0-25 points)
    # Higher redundancy_ratio = more unique findings = better score
    dedup_score = redundancy_ratio * 25.0

    # Parallelism benefit (0-10 points)
    # Cap at 10x speedup for scoring purposes (beyond that is bonus)
    speedup_score = min(speedup, 10.0) * 1.0

    # Synthesis quality (0-15 points)
    synthesis_score = synthesis_quality * 15.0

    # Coordination penalty (0 to -10)
    # Each conflict costs 5 points, capped at -10
    conflict_penalty = min(conflicts * 5, 10)

    # Swarm composite score
    swarm_composite = (
        agent_score +
        dedup_score +
        speedup_score +
        synthesis_score -
        conflict_penalty
    )

    # Clamp to 0-100
    swarm_composite = max(0.0, min(100.0, swarm_composite))

    # Calculate VPT
    swarm_vpt = calculate_vpt(swarm_composite, total_tokens)
    rating = get_vpt_rating(swarm_vpt)

    return {
        "composite_score": round(swarm_composite, 2),
        "vpt_score": round(swarm_vpt, 2),
        "rating": rating,
        "breakdown": {
            "agent_performance": round(agent_score, 2),
            "deduplication": round(dedup_score, 2),
            "speedup": round(speedup_score, 2),
            "synthesis": round(synthesis_score, 2),
            "conflict_penalty": -round(conflict_penalty, 2)
        }
    }
