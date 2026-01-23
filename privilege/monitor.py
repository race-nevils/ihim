"""
Self-Monitoring System

Recursive system that watches itself for anomalies:
- Trust manipulation (unusual score jumps)
- Boundary probing (systematic testing)
- Escalation abuse (repeated requests)

The watcher watches the watcher - auditable all the way down.
"""

import json
from pathlib import Path
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict, field
from typing import List, Optional, Dict, Any
from enum import Enum

from .trust import get_trust_state, TrustState


# Alert log file
ALERT_LOG_FILE = Path(__file__).parent.parent / "data" / "privilege_alerts.json"


class AlertSeverity(Enum):
    """Severity levels for privilege alerts."""

    INFO = "info"           # Normal activity, logged for audit
    WARNING = "warning"     # Unusual but not necessarily malicious
    CRITICAL = "critical"   # Requires immediate attention


class AlertType(Enum):
    """Types of privilege-related alerts."""

    TRUST_JUMP = "trust_jump"                   # Unusual trust score change
    BOUNDARY_PROBE = "boundary_probe"           # Systematic boundary testing
    ESCALATION_FLOOD = "escalation_flood"       # Many escalation requests
    LEVEL_DOWNGRADE = "level_downgrade"         # Lost a privilege level
    RECOVERY_TRIGGERED = "recovery_triggered"   # Entered recovery mode
    ANOMALY_DETECTED = "anomaly_detected"       # General anomaly


@dataclass
class PrivilegeAlert:
    """An alert from the privilege monitoring system."""

    id: str
    alert_type: str
    severity: str
    message: str
    details: Dict[str, Any]
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    acknowledged: bool = False
    acknowledged_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PrivilegeAlert":
        return cls(**data)


def load_alerts() -> List[PrivilegeAlert]:
    """Load alerts from disk."""
    if ALERT_LOG_FILE.exists():
        try:
            data = json.loads(ALERT_LOG_FILE.read_text(encoding="utf-8"))
            return [PrivilegeAlert.from_dict(a) for a in data.get("alerts", [])]
        except Exception as e:
            print(f"Warning: Failed to load alerts: {e}")
    return []


def save_alerts(alerts: List[PrivilegeAlert]) -> None:
    """Save alerts to disk."""
    ALERT_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "alerts": [a.to_dict() for a in alerts],
        "updated_at": datetime.utcnow().isoformat() + "Z",
    }
    ALERT_LOG_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def generate_alert_id() -> str:
    """Generate a unique alert ID."""
    import uuid
    return f"alert-{uuid.uuid4().hex[:8]}"


def create_alert(
    alert_type: AlertType,
    severity: AlertSeverity,
    message: str,
    details: Optional[Dict[str, Any]] = None,
) -> PrivilegeAlert:
    """
    Create and save a new privilege alert.

    Args:
        alert_type: Type of alert
        severity: Alert severity
        message: Human-readable message
        details: Additional context

    Returns:
        Created PrivilegeAlert
    """
    alert = PrivilegeAlert(
        id=generate_alert_id(),
        alert_type=alert_type.value,
        severity=severity.value,
        message=message,
        details=details or {},
    )

    alerts = load_alerts()
    alerts.append(alert)

    # Keep bounded (last 500 alerts)
    if len(alerts) > 500:
        alerts = alerts[-500:]

    save_alerts(alerts)
    return alert


def check_for_anomalies() -> List[PrivilegeAlert]:
    """
    Run anomaly detection on current trust state.

    Checks for:
    - Unusual trust score jumps
    - Boundary probing patterns
    - Escalation request floods
    - Recovery mode entry

    Returns:
        List of new alerts generated
    """
    state = get_trust_state()
    new_alerts = []

    # Check for trust jumps (score changed by more than 5 in recent events)
    if state.history:
        recent_events = state.history[-10:]  # Last 10 events
        total_delta = sum(e.get("delta", 0) for e in recent_events)

        if abs(total_delta) > 5:
            direction = "increase" if total_delta > 0 else "decrease"
            alert = create_alert(
                AlertType.TRUST_JUMP,
                AlertSeverity.WARNING,
                f"Unusual trust score {direction}: {total_delta:+.1f} in last 10 events",
                {"total_delta": total_delta, "events": len(recent_events)},
            )
            new_alerts.append(alert)

    # Check for boundary probing (multiple boundary violations in short time)
    boundary_violations = [
        e for e in state.history[-20:]
        if e.get("event_type") == "boundary_violation"
    ]

    if len(boundary_violations) >= 3:
        alert = create_alert(
            AlertType.BOUNDARY_PROBE,
            AlertSeverity.CRITICAL,
            f"Possible boundary probing detected: {len(boundary_violations)} violations in recent history",
            {"violation_count": len(boundary_violations)},
        )
        new_alerts.append(alert)

    # Check for recovery mode entry
    if state.is_in_recovery():
        # Check if this is a new recovery period
        if state.last_incident:
            incident_time = datetime.fromisoformat(state.last_incident.rstrip("Z"))
            if (datetime.utcnow() - incident_time).total_seconds() < 60:  # Within last minute
                alert = create_alert(
                    AlertType.RECOVERY_TRIGGERED,
                    AlertSeverity.WARNING,
                    f"Recovery mode triggered. Trust accumulation halved until {state.recovery_until}",
                    {
                        "incident_time": state.last_incident,
                        "recovery_until": state.recovery_until,
                    },
                )
                new_alerts.append(alert)

    # Check for level downgrade
    current_level = state.current_level
    if state.history and len(state.history) >= 2:
        prev_event = state.history[-2]
        if prev_event.get("event_type") == "level_change":
            # This was a level change - check if downgrade
            if prev_event.get("level") == "L0" and current_level == "L0":
                # Could be a downgrade from L1 to L0
                for event in reversed(state.history[:-1]):
                    if event.get("level") == "L1":
                        alert = create_alert(
                            AlertType.LEVEL_DOWNGRADE,
                            AlertSeverity.WARNING,
                            "Privilege level downgraded from L1 to L0",
                            {"previous_level": "L1", "current_level": "L0"},
                        )
                        new_alerts.append(alert)
                        break

    return new_alerts


def get_recent_alerts(hours: int = 24) -> List[PrivilegeAlert]:
    """Get alerts from the last N hours."""
    alerts = load_alerts()
    cutoff = datetime.utcnow() - timedelta(hours=hours)

    return [
        a for a in alerts
        if datetime.fromisoformat(a.timestamp.rstrip("Z")) > cutoff
    ]


def get_unacknowledged_alerts() -> List[PrivilegeAlert]:
    """Get all unacknowledged alerts."""
    alerts = load_alerts()
    return [a for a in alerts if not a.acknowledged]


def acknowledge_alert(alert_id: str) -> Optional[PrivilegeAlert]:
    """
    Acknowledge an alert.

    Args:
        alert_id: ID of alert to acknowledge

    Returns:
        Updated alert or None if not found
    """
    alerts = load_alerts()

    for alert in alerts:
        if alert.id == alert_id:
            alert.acknowledged = True
            alert.acknowledged_at = datetime.utcnow().isoformat() + "Z"
            save_alerts(alerts)
            return alert

    return None


def get_monitor_status() -> Dict[str, Any]:
    """
    Get current monitor status for health checks.

    Returns:
        Status dict with alert counts and trust summary
    """
    state = get_trust_state()
    alerts = load_alerts()
    unacked = [a for a in alerts if not a.acknowledged]

    critical_unacked = [a for a in unacked if a.severity == AlertSeverity.CRITICAL.value]

    return {
        "status": "healthy" if not critical_unacked else "alert",
        "trust_score": state.current_score,
        "current_level": state.current_level,
        "in_recovery": state.is_in_recovery(),
        "alerts": {
            "total": len(alerts),
            "unacknowledged": len(unacked),
            "critical_unacked": len(critical_unacked),
        },
        "last_check": datetime.utcnow().isoformat() + "Z",
    }
