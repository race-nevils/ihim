"""Feedback loop module for agent self-improvement."""

from .schemas import (
    AgentResult,
    FeedbackEntry,
    SessionFeedback,
    BlackboardMessage,
    MetricsSnapshot,
)
from .processor import process_result
from .aggregator import aggregate_session
from .metrics import get_metrics, update_metrics

__all__ = [
    "AgentResult",
    "FeedbackEntry",
    "SessionFeedback",
    "BlackboardMessage",
    "MetricsSnapshot",
    "process_result",
    "aggregate_session",
    "get_metrics",
    "update_metrics",
]
