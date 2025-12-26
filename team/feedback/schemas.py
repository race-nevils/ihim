"""
Pydantic models for the feedback system.

These schemas define the structure for:
- Agent results (what each agent outputs)
- Feedback entries (processed learnings from results)
- Session feedback (aggregated feedback from all agents)
- Blackboard messages (real-time coordination)
- Metrics snapshots (improvement tracking)
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class FileModification(BaseModel):
    """A file that was modified by an agent."""
    path: str
    action: str = "modified"  # created, modified, deleted
    lines: int = 0


class Blocker(BaseModel):
    """A blocker encountered during execution."""
    type: str  # dependency, missing_info, error, timeout
    description: str
    resolved: bool = False


class QualityIndicators(BaseModel):
    """Quality indicators for agent work."""
    tests_written: bool = False
    types_added: bool = False
    error_handling: bool = False
    documentation: bool = False


class CoordinationRequest(BaseModel):
    """A request to another agent."""
    to: str  # target agent name
    message: str
    priority: str = "normal"  # low, normal, high, critical


class AgentResult(BaseModel):
    """
    Standardized result from an agent.
    Every agent MUST output this structure.
    """
    agent: str
    session_id: str
    status: str = "complete"  # complete, partial, blocked, failed
    files_modified: list[FileModification] = Field(default_factory=list)
    summary: str = ""
    blockers: list[Blocker] = Field(default_factory=list)
    handoff_notes: str = ""
    quality_indicators: QualityIndicators = Field(default_factory=QualityIndicators)
    learnings: list[str] = Field(default_factory=list)
    coordination_requests: list[CoordinationRequest] = Field(default_factory=list)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class FeedbackEntry(BaseModel):
    """
    Processed feedback from a single agent result.
    This is what the processor extracts from AgentResult.
    """
    agent: str
    session_id: str
    success: bool
    files_touched: list[str] = Field(default_factory=list)
    patterns_used: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    handoff_requests: list[str] = Field(default_factory=list)
    quality_score: float = 0.0  # 0.0 to 1.0
    duration_seconds: Optional[float] = None
    timestamp: datetime = Field(default_factory=datetime.now)


class SessionFeedback(BaseModel):
    """
    Aggregated feedback from all agents in a spawn session.
    """
    session_id: str
    prompt: str
    overall_success: bool
    agent_scores: dict[str, float] = Field(default_factory=dict)
    coordination_gaps: list[str] = Field(default_factory=list)
    repeated_blockers: list[str] = Field(default_factory=list)
    learnings: list[str] = Field(default_factory=list)
    total_files_modified: int = 0
    total_duration_seconds: float = 0.0
    agents_completed: int = 0
    agents_failed: int = 0
    timestamp: datetime = Field(default_factory=datetime.now)


class BlackboardMessage(BaseModel):
    """
    A message on the blackboard for agent coordination.
    """
    from_agent: str = Field(alias="from")
    type: str  # BLOCKED, DONE, UNBLOCKED, REQUEST, INFO
    message: str
    target_agent: Optional[str] = None  # If message is for specific agent
    timestamp: datetime = Field(default_factory=datetime.now)

    class Config:
        populate_by_name = True


class BlackboardState(BaseModel):
    """
    Current state of the blackboard.
    """
    session_id: str
    messages: list[BlackboardMessage] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.now)
    last_updated: datetime = Field(default_factory=datetime.now)


class CategoryScores(BaseModel):
    """
    Scores broken down by category (0-100 each).
    """
    completion: float = 0.0    # Did they finish the task?
    quality: float = 0.0       # Tests, types, error handling, docs
    efficiency: float = 0.0    # Clean focused changes, files/time
    collaboration: float = 0.0 # Blackboard usage, handoffs, questions

    @property
    def overall(self) -> float:
        """Weighted average of all categories."""
        weights = {"completion": 0.35, "quality": 0.30, "efficiency": 0.20, "collaboration": 0.15}
        return (
            self.completion * weights["completion"] +
            self.quality * weights["quality"] +
            self.efficiency * weights["efficiency"] +
            self.collaboration * weights["collaboration"]
        )

    def to_dict(self) -> dict:
        return {
            "completion": round(self.completion, 1),
            "quality": round(self.quality, 1),
            "efficiency": round(self.efficiency, 1),
            "collaboration": round(self.collaboration, 1),
            "overall": round(self.overall, 1),
        }


class CategoryTrends(BaseModel):
    """
    Trends for each category (positive = improving).
    """
    completion: float = 0.0
    quality: float = 0.0
    efficiency: float = 0.0
    collaboration: float = 0.0
    overall: float = 0.0


class MetricsSnapshot(BaseModel):
    """
    Metrics snapshot for tracking improvement over time.
    """
    total_sessions: int = 0
    total_agents_spawned: int = 0
    avg_success_rate: float = 0.0
    # Category-based scoring
    avg_scores: CategoryScores = Field(default_factory=CategoryScores)
    trends: CategoryTrends = Field(default_factory=CategoryTrends)
    # Legacy field for backward compatibility
    avg_quality_score: float = 0.0
    top_learnings: list[str] = Field(default_factory=list)
    common_blockers: list[str] = Field(default_factory=list)
    improvement_trend: float = 0.0  # positive = improving
    last_session_id: Optional[str] = None
    last_updated: datetime = Field(default_factory=datetime.now)


class PromptOptimization(BaseModel):
    """
    An optimization to apply to agent prompts.
    """
    agent: str  # Which agent this applies to, or "all"
    type: str  # prepend, append, replace, reminder
    content: str
    reason: str  # Why this optimization was added
    times_triggered: int = 0
    added_at: datetime = Field(default_factory=datetime.now)
