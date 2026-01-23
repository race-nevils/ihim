"""
Trust State Management

Trust is earned through demonstrated reliability. This module tracks:
- Current trust score
- Operation history
- Level transitions
- Incident recovery state
"""

import json
from pathlib import Path
from datetime import datetime, timedelta
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any

from .levels import PrivilegeLevel, PRIVILEGE_THRESHOLDS, TRUST_SCORES


# State file location
TRUST_STATE_FILE = Path(__file__).parent.parent / "data" / "trust_state.json"


@dataclass
class TrustEvent:
    """A single trust-affecting event."""

    timestamp: str
    event_type: str  # "success", "failure", "boundary_violation", "level_change"
    level: str       # L0, L1, L2
    operation: str   # Description of what was attempted
    delta: float     # Change in trust score
    details: Optional[str] = None


@dataclass
class TrustState:
    """Current trust state with history."""

    current_score: float = 0.0
    current_level: str = "L0"
    total_successful_ops: int = 0
    total_failed_ops: int = 0
    failures_24h: int = 0
    last_incident: Optional[str] = None  # ISO timestamp of last major incident
    recovery_until: Optional[str] = None # ISO timestamp when recovery penalty ends
    history: List[Dict[str, Any]] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TrustState":
        return cls(**data)

    def is_in_recovery(self) -> bool:
        """Check if currently in recovery penalty period."""
        if not self.recovery_until:
            return False
        recovery_end = datetime.fromisoformat(self.recovery_until.rstrip("Z"))
        return datetime.utcnow() < recovery_end

    def effective_recovery_rate(self) -> float:
        """Get effective recovery rate (halved during penalty period)."""
        return 0.5 if self.is_in_recovery() else 1.0

    def can_reach_level(self, level: PrivilegeLevel) -> bool:
        """Check if current trust allows reaching a privilege level."""
        threshold = PRIVILEGE_THRESHOLDS.get(level)
        if not threshold:
            return False

        if level == PrivilegeLevel.L2_ADMIN:
            return False  # Never automated

        return (
            self.current_score >= threshold.min_trust_score and
            self.total_successful_ops >= threshold.min_successful_ops and
            self.failures_24h <= threshold.max_failures_24h
        )

    def get_current_privilege_level(self) -> PrivilegeLevel:
        """Determine current privilege level based on trust state."""
        # Check L1 first, then fall back to L0
        if self.can_reach_level(PrivilegeLevel.L1_OS):
            return PrivilegeLevel.L1_OS
        return PrivilegeLevel.L0_WORKSPACE


def load_trust_state() -> TrustState:
    """Load trust state from disk."""
    if TRUST_STATE_FILE.exists():
        try:
            data = json.loads(TRUST_STATE_FILE.read_text(encoding="utf-8"))
            return TrustState.from_dict(data)
        except Exception as e:
            print(f"Warning: Failed to load trust state: {e}")
    return TrustState()


def save_trust_state(state: TrustState) -> None:
    """Save trust state to disk."""
    state.updated_at = datetime.utcnow().isoformat() + "Z"
    TRUST_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    TRUST_STATE_FILE.write_text(
        json.dumps(state.to_dict(), indent=2),
        encoding="utf-8"
    )


def get_trust_state() -> TrustState:
    """Get current trust state (convenience function)."""
    return load_trust_state()


def update_trust(
    event_type: str,
    level: str,
    operation: str,
    success: bool = True,
    details: Optional[str] = None,
) -> TrustState:
    """
    Update trust score based on an operation result.

    Args:
        event_type: Type of event (success, failure, boundary_violation)
        level: Privilege level of the operation (L0, L1, L2)
        operation: Description of the operation
        success: Whether the operation succeeded
        details: Optional additional details

    Returns:
        Updated TrustState
    """
    state = load_trust_state()

    # Calculate trust delta
    if event_type == "boundary_violation":
        delta = TRUST_SCORES["boundary_violation_attempt"]
        state.last_incident = datetime.utcnow().isoformat() + "Z"
        # Set recovery penalty
        threshold = PRIVILEGE_THRESHOLDS.get(PrivilegeLevel.L1_OS)
        if threshold:
            recovery_end = datetime.utcnow() + timedelta(days=threshold.recovery_penalty_days)
            state.recovery_until = recovery_end.isoformat() + "Z"
    elif success:
        delta = TRUST_SCORES["success"].get(level, 0.1)
        delta *= state.effective_recovery_rate()
        state.total_successful_ops += 1
    else:
        delta = TRUST_SCORES["failure"].get(level, -0.5)
        state.total_failed_ops += 1
        state.failures_24h += 1

    # Apply delta
    state.current_score = max(0.0, state.current_score + delta)

    # Update current level
    state.current_level = state.get_current_privilege_level().value

    # Record event
    event = TrustEvent(
        timestamp=datetime.utcnow().isoformat() + "Z",
        event_type=event_type,
        level=level,
        operation=operation,
        delta=delta,
        details=details,
    )
    state.history.append(asdict(event))

    # Keep history bounded (last 1000 events)
    if len(state.history) > 1000:
        state.history = state.history[-1000:]

    save_trust_state(state)
    return state


def apply_idle_decay() -> TrustState:
    """Apply daily idle decay to trust score."""
    state = load_trust_state()

    delta = TRUST_SCORES["idle_decay_per_day"]
    state.current_score = max(0.0, state.current_score + delta)

    # Reset 24h failure counter
    state.failures_24h = 0

    save_trust_state(state)
    return state


def reset_trust_state() -> TrustState:
    """Reset trust state to initial values (for testing)."""
    state = TrustState()
    save_trust_state(state)
    return state
