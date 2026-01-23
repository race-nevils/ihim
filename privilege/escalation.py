"""
Privilege Escalation Workflow

Handles requests to escalate from one privilege level to another.

Key principle:
- L0 -> L1 (workspace -> OS): Can auto-approve if trust threshold met
- L1 -> L2 (OS -> Admin): NEVER auto-approved, requires the operator
"""

import json
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, asdict, field
from typing import List, Optional, Dict, Any
from enum import Enum

from .levels import PrivilegeLevel, PRIVILEGE_THRESHOLDS
from .trust import get_trust_state, update_trust, TrustState


# Escalation requests file
ESCALATION_FILE = Path(__file__).parent.parent / "data" / "escalation_requests.json"


class EscalationStatus(Enum):
    """Status of an escalation request."""

    PENDING = "pending"
    AUTO_APPROVED = "auto_approved"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"


@dataclass
class EscalationRequest:
    """A request to escalate privileges."""

    id: str
    from_level: str
    to_level: str
    reason: str
    operation: str
    status: str = EscalationStatus.PENDING.value
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    resolved_at: Optional[str] = None
    resolved_by: Optional[str] = None  # "auto" or "human"
    trust_score_at_request: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EscalationRequest":
        return cls(**data)


def load_escalation_requests() -> List[EscalationRequest]:
    """Load all escalation requests from disk."""
    if ESCALATION_FILE.exists():
        try:
            data = json.loads(ESCALATION_FILE.read_text(encoding="utf-8"))
            return [EscalationRequest.from_dict(r) for r in data.get("requests", [])]
        except Exception as e:
            print(f"Warning: Failed to load escalation requests: {e}")
    return []


def save_escalation_requests(requests: List[EscalationRequest]) -> None:
    """Save escalation requests to disk."""
    ESCALATION_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "requests": [r.to_dict() for r in requests],
        "updated_at": datetime.utcnow().isoformat() + "Z",
    }
    ESCALATION_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def generate_request_id() -> str:
    """Generate a unique request ID."""
    import uuid
    return f"esc-{uuid.uuid4().hex[:8]}"


def request_escalation(
    from_level: PrivilegeLevel,
    to_level: PrivilegeLevel,
    reason: str,
    operation: str,
) -> EscalationRequest:
    """
    Request privilege escalation.

    Args:
        from_level: Current privilege level
        to_level: Requested privilege level
        reason: Why escalation is needed
        operation: What operation requires this escalation

    Returns:
        EscalationRequest with status (may be auto-approved for L0->L1)
    """
    state = get_trust_state()

    request = EscalationRequest(
        id=generate_request_id(),
        from_level=from_level.value,
        to_level=to_level.value,
        reason=reason,
        operation=operation,
        trust_score_at_request=state.current_score,
    )

    # Check for auto-approval (L0 -> L1 only)
    if from_level == PrivilegeLevel.L0_WORKSPACE and to_level == PrivilegeLevel.L1_OS:
        if state.can_reach_level(PrivilegeLevel.L1_OS):
            request.status = EscalationStatus.AUTO_APPROVED.value
            request.resolved_at = datetime.utcnow().isoformat() + "Z"
            request.resolved_by = "auto"

            # Record the escalation
            update_trust(
                event_type="level_change",
                level="L1",
                operation=f"Auto-approved escalation: {operation}",
                success=True,
                details=reason,
            )

    # L2 requests are never auto-approved
    if to_level == PrivilegeLevel.L2_ADMIN:
        request.status = EscalationStatus.PENDING.value
        # Note: This will remain pending until the operator approves

    # Save the request
    requests = load_escalation_requests()
    requests.append(request)
    save_escalation_requests(requests)

    return request


def approve_escalation(request_id: str, approver: str = "human") -> Optional[EscalationRequest]:
    """
    Approve a pending escalation request.

    Only used for manual approval (L2 requests).

    Args:
        request_id: ID of the request to approve
        approver: Who is approving (should be "human" for L2)

    Returns:
        Updated EscalationRequest or None if not found
    """
    requests = load_escalation_requests()

    for request in requests:
        if request.id == request_id and request.status == EscalationStatus.PENDING.value:
            request.status = EscalationStatus.APPROVED.value
            request.resolved_at = datetime.utcnow().isoformat() + "Z"
            request.resolved_by = approver

            save_escalation_requests(requests)

            # Record the approval
            update_trust(
                event_type="level_change",
                level=request.to_level,
                operation=f"Approved escalation: {request.operation}",
                success=True,
                details=f"Approved by {approver}",
            )

            return request

    return None


def deny_escalation(request_id: str, reason: str = "") -> Optional[EscalationRequest]:
    """
    Deny a pending escalation request.

    Args:
        request_id: ID of the request to deny
        reason: Why the request was denied

    Returns:
        Updated EscalationRequest or None if not found
    """
    requests = load_escalation_requests()

    for request in requests:
        if request.id == request_id and request.status == EscalationStatus.PENDING.value:
            request.status = EscalationStatus.DENIED.value
            request.resolved_at = datetime.utcnow().isoformat() + "Z"
            request.resolved_by = "human"

            save_escalation_requests(requests)

            # Record the denial (small trust hit for requesting denied operation)
            update_trust(
                event_type="failure",
                level=request.to_level,
                operation=f"Denied escalation: {request.operation}",
                success=False,
                details=reason,
            )

            return request

    return None


def get_pending_escalations() -> List[EscalationRequest]:
    """Get all pending escalation requests."""
    requests = load_escalation_requests()
    return [r for r in requests if r.status == EscalationStatus.PENDING.value]


def get_escalation_by_id(request_id: str) -> Optional[EscalationRequest]:
    """Get a specific escalation request by ID."""
    requests = load_escalation_requests()
    for request in requests:
        if request.id == request_id:
            return request
    return None


def cleanup_old_requests(days: int = 30) -> int:
    """
    Clean up escalation requests older than specified days.

    Args:
        days: Age threshold in days

    Returns:
        Number of requests removed
    """
    requests = load_escalation_requests()
    cutoff = datetime.utcnow().replace(tzinfo=None)

    original_count = len(requests)
    requests = [
        r for r in requests
        if (cutoff - datetime.fromisoformat(r.created_at.rstrip("Z"))).days < days
    ]

    save_escalation_requests(requests)
    return original_count - len(requests)
