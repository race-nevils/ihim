"""Privilege system routes — governance infrastructure."""

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from typing import Optional

from api.errors import problem

router = APIRouter(prefix="/api/privilege", tags=["privilege"])

# Lazy imports — privilege system may not be installed
try:
    from privilege import (
        PrivilegeLevel,
        get_trust_state,
        update_trust,
        can_perform_operation,
        classify_operation,
        OperationType,
    )
    from privilege.escalation import (
        request_escalation,
        approve_escalation,
        deny_escalation,
        get_pending_escalations,
        get_escalation_by_id,
    )
    from privilege.monitor import (
        check_for_anomalies,
        get_recent_alerts,
        get_unacknowledged_alerts,
        acknowledge_alert,
        get_monitor_status,
    )
    from privilege.rollback import (
        create_checkpoint,
        rollback_to_checkpoint,
        list_checkpoints,
        get_rollback_status,
        CheckpointTrigger,
    )
    PRIVILEGE_AVAILABLE = True
except ImportError as e:
    print(f"Warning: Privilege system not available: {e}")
    PRIVILEGE_AVAILABLE = False


class PrivilegeCheckRequest(BaseModel):
    """Request model for privilege boundary check."""
    operation_type: str = Field(..., description="Type of operation (file_read, file_write, etc.)")
    target: Optional[str] = Field(None, description="Target path, process name, etc.")
    details: Optional[dict] = Field(None, description="Additional operation details")


class EscalationRequestModel(BaseModel):
    """Request model for privilege escalation."""
    from_level: str = Field(..., pattern=r'^L[012]$', description="Current level (L0, L1, L2)")
    to_level: str = Field(..., pattern=r'^L[012]$', description="Requested level (L0, L1, L2)")
    reason: str = Field(..., min_length=1, max_length=500, description="Why escalation is needed")
    operation: str = Field(..., min_length=1, max_length=200, description="What operation requires this")


def _check_available(request: Request):
    if not PRIVILEGE_AVAILABLE:
        return problem(503, "Privilege system not available", instance=request.url.path)
    return None


@router.get("/status")
async def privilege_status(request: Request):
    """Get current privilege status."""
    if err := _check_available(request):
        return err

    try:
        state = get_trust_state()
        monitor = get_monitor_status()
        rollback = get_rollback_status()

        return {
            "success": True,
            "trust": {
                "score": state.current_score,
                "level": state.current_level,
                "level_display": PrivilegeLevel(state.current_level).display_name,
                "successful_ops": state.total_successful_ops,
                "failed_ops": state.total_failed_ops,
                "in_recovery": state.is_in_recovery(),
                "recovery_until": state.recovery_until,
            },
            "monitor": monitor,
            "rollback": rollback,
        }
    except Exception as e:
        return problem(500, f"Failed to get privilege status: {str(e)}", instance=request.url.path)


@router.post("/check")
async def privilege_check(req: PrivilegeCheckRequest, request: Request):
    """Check if an operation is allowed at current privilege level."""
    if err := _check_available(request):
        return err

    try:
        try:
            op_type = OperationType(req.operation_type)
        except ValueError:
            return problem(
                400,
                f"Unknown operation type: {req.operation_type}. "
                f"Valid types: {[ot.value for ot in OperationType]}",
                instance=request.url.path,
            )

        result = can_perform_operation(op_type, req.target, req.details)

        return {
            "success": True,
            "allowed": result.allowed,
            "required_level": result.required_level.value,
            "required_level_display": result.required_level.display_name,
            "current_level": result.current_level.value,
            "current_level_display": result.current_level.display_name,
            "reason": result.reason,
            "trust_score": result.trust_score,
            "can_escalate": result.can_escalate,
            "escalation_path": result.escalation_path,
        }
    except Exception as e:
        return problem(500, f"Privilege check failed: {str(e)}", instance=request.url.path)


@router.post("/escalate")
async def privilege_escalate(req: EscalationRequestModel, request: Request):
    """Request privilege escalation."""
    if err := _check_available(request):
        return err

    try:
        from_level = PrivilegeLevel(req.from_level)
        to_level = PrivilegeLevel(req.to_level)

        result = request_escalation(from_level, to_level, req.reason, req.operation)

        return {
            "success": True,
            "request_id": result.id,
            "status": result.status,
            "auto_approved": result.status == "auto_approved",
            "message": f"Escalation request {result.status}",
            "created_at": result.created_at,
            "resolved_at": result.resolved_at,
        }
    except Exception as e:
        return problem(500, f"Escalation request failed: {str(e)}", instance=request.url.path)


@router.get("/escalations")
async def get_escalations(request: Request):
    """Get all pending escalation requests."""
    if err := _check_available(request):
        return err

    try:
        pending = get_pending_escalations()
        return {
            "success": True,
            "count": len(pending),
            "requests": [r.to_dict() for r in pending],
        }
    except Exception as e:
        return problem(500, f"Failed to get escalations: {str(e)}", instance=request.url.path)


@router.post("/escalations/{request_id}/approve")
async def approve_escalation_endpoint(request_id: str, request: Request):
    """Approve a pending escalation request."""
    if err := _check_available(request):
        return err

    try:
        result = approve_escalation(request_id, approver="human")
        if result:
            return {"success": True, "request": result.to_dict(), "message": "Escalation approved"}
        return problem(404, f"Escalation request not found: {request_id}", instance=request.url.path)
    except Exception as e:
        return problem(500, f"Approval failed: {str(e)}", instance=request.url.path)


@router.post("/escalations/{request_id}/deny")
async def deny_escalation_endpoint(request_id: str, request: Request, reason: str = ""):
    """Deny a pending escalation request."""
    if err := _check_available(request):
        return err

    try:
        result = deny_escalation(request_id, reason)
        if result:
            return {"success": True, "request": result.to_dict(), "message": "Escalation denied"}
        return problem(404, f"Escalation request not found: {request_id}", instance=request.url.path)
    except Exception as e:
        return problem(500, f"Denial failed: {str(e)}", instance=request.url.path)


@router.get("/alerts")
async def get_privilege_alerts(request: Request, hours: int = 24, unacknowledged_only: bool = False):
    """Get privilege system alerts."""
    if err := _check_available(request):
        return err

    try:
        if unacknowledged_only:
            alerts = get_unacknowledged_alerts()
        else:
            alerts = get_recent_alerts(hours)

        return {
            "success": True,
            "count": len(alerts),
            "alerts": [a.to_dict() for a in alerts],
        }
    except Exception as e:
        return problem(500, f"Failed to get alerts: {str(e)}", instance=request.url.path)


@router.post("/alerts/{alert_id}/acknowledge")
async def acknowledge_privilege_alert(alert_id: str, request: Request):
    """Acknowledge a privilege alert."""
    if err := _check_available(request):
        return err

    try:
        result = acknowledge_alert(alert_id)
        if result:
            return {"success": True, "alert": result.to_dict(), "message": "Alert acknowledged"}
        return problem(404, f"Alert not found: {alert_id}", instance=request.url.path)
    except Exception as e:
        return problem(500, f"Acknowledgment failed: {str(e)}", instance=request.url.path)


@router.post("/anomaly-check")
async def run_anomaly_check(request: Request):
    """Run anomaly detection on current privilege state."""
    if err := _check_available(request):
        return err

    try:
        new_alerts = check_for_anomalies()
        return {
            "success": True,
            "alerts_generated": len(new_alerts),
            "alerts": [a.to_dict() for a in new_alerts],
        }
    except Exception as e:
        return problem(500, f"Anomaly check failed: {str(e)}", instance=request.url.path)


@router.get("/checkpoints")
async def get_checkpoints(request: Request, limit: int = 20):
    """List recent privilege state checkpoints."""
    if err := _check_available(request):
        return err

    try:
        checkpoints = list_checkpoints(limit)
        return {
            "success": True,
            "count": len(checkpoints),
            "checkpoints": [c.to_dict() for c in checkpoints],
        }
    except Exception as e:
        return problem(500, f"Failed to list checkpoints: {str(e)}", instance=request.url.path)


@router.post("/checkpoints")
async def create_checkpoint_endpoint(request: Request, description: str = "Manual checkpoint"):
    """Create a manual privilege state checkpoint."""
    if err := _check_available(request):
        return err

    try:
        checkpoint = create_checkpoint(CheckpointTrigger.MANUAL, description)
        return {"success": True, "checkpoint": checkpoint.to_dict(), "message": "Checkpoint created"}
    except Exception as e:
        return problem(500, f"Checkpoint creation failed: {str(e)}", instance=request.url.path)


@router.post("/checkpoints/{checkpoint_id}/rollback")
async def rollback_checkpoint(checkpoint_id: str, request: Request):
    """Rollback to a specific checkpoint."""
    if err := _check_available(request):
        return err

    try:
        result = rollback_to_checkpoint(checkpoint_id)
        if result:
            return {
                "success": True,
                "restored_state": {
                    "trust_score": result.current_score,
                    "level": result.current_level,
                },
                "message": f"Rolled back to checkpoint {checkpoint_id}",
            }
        return problem(404, f"Checkpoint not found: {checkpoint_id}", instance=request.url.path)
    except Exception as e:
        return problem(500, f"Rollback failed: {str(e)}", instance=request.url.path)
