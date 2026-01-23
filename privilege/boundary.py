"""
Privilege Boundary Checking

Classifies operations by required privilege level and checks
if the current trust state allows the operation.

The One Jump Rule:
- workspace -> OS: Can auto-approve if trust threshold met
- OS -> Admin: NEVER automated, only the operator operates there
"""

import re
from enum import Enum
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, Tuple, Dict, List

from .levels import PrivilegeLevel, PRIVILEGE_THRESHOLDS
from .trust import get_trust_state, update_trust


class OperationType(Enum):
    """Categories of operations."""

    FILE_READ = "file_read"
    FILE_WRITE = "file_write"
    FILE_DELETE = "file_delete"
    PROCESS_START = "process_start"
    PROCESS_KILL = "process_kill"
    WINDOW_MOVE = "window_move"
    NETWORK_LISTEN = "network_listen"
    NETWORK_CONNECT = "network_connect"
    REGISTRY_READ = "registry_read"
    REGISTRY_WRITE = "registry_write"
    SERVICE_CONTROL = "service_control"
    ENV_VAR_READ = "env_var_read"
    ENV_VAR_WRITE = "env_var_write"
    SCHEDULED_TASK = "scheduled_task"


@dataclass
class BoundaryCheck:
    """Result of a boundary check."""

    allowed: bool
    required_level: PrivilegeLevel
    current_level: PrivilegeLevel
    reason: str
    trust_score: float
    can_escalate: bool = False
    escalation_path: Optional[str] = None


# workspace directory for L0 scope checks
WORKSPACE_ROOT = Path("C:/Users/<user>/workspace")


# Patterns for operation classification
ELEVATED_PROCESSES = [
    "taskmgr.exe",
    "regedit.exe",
    "services.msc",
    "mmc.exe",
    "compmgmt.msc",
    "devmgmt.msc",
    "diskmgmt.msc",
    "eventvwr.exe",
    "secpol.msc",
    "gpedit.msc",
]

SYSTEM_PATHS = [
    r"C:\Windows",
    r"C:\Program Files",
    r"C:\Program Files (x86)",
    r"C:\ProgramData",
]


def is_within_workspace(path: str) -> bool:
    """Check if a path is within the workspace directory."""
    try:
        target = Path(path).resolve()
        return str(target).startswith(str(WORKSPACE_ROOT))
    except Exception:
        return False


def is_system_path(path: str) -> bool:
    """Check if a path is a protected system location."""
    normalized = path.replace("/", "\\")
    return any(normalized.lower().startswith(sp.lower()) for sp in SYSTEM_PATHS)


def is_elevated_process(process_name: str) -> bool:
    """Check if a process typically runs elevated."""
    return process_name.lower() in [p.lower() for p in ELEVATED_PROCESSES]


def classify_operation(
    op_type: OperationType,
    target: Optional[str] = None,
    details: Optional[Dict] = None,
) -> PrivilegeLevel:
    """
    Classify an operation by required privilege level.

    Args:
        op_type: Type of operation
        target: Target path, process name, etc.
        details: Additional operation details

    Returns:
        Required PrivilegeLevel for this operation
    """
    details = details or {}

    # Registry and service operations always require L2
    if op_type in [
        OperationType.REGISTRY_READ,
        OperationType.REGISTRY_WRITE,
        OperationType.SERVICE_CONTROL,
    ]:
        return PrivilegeLevel.L2_ADMIN

    # System-wide env vars require L2
    if op_type == OperationType.ENV_VAR_WRITE:
        if details.get("scope") == "system":
            return PrivilegeLevel.L2_ADMIN
        return PrivilegeLevel.L1_OS

    # File operations
    if op_type in [OperationType.FILE_READ, OperationType.FILE_WRITE, OperationType.FILE_DELETE]:
        if target:
            if is_within_workspace(target):
                return PrivilegeLevel.L0_WORKSPACE
            if is_system_path(target):
                return PrivilegeLevel.L2_ADMIN
            return PrivilegeLevel.L1_OS
        return PrivilegeLevel.L0_WORKSPACE

    # Process operations
    if op_type in [OperationType.PROCESS_START, OperationType.PROCESS_KILL]:
        if target and is_elevated_process(target):
            return PrivilegeLevel.L2_ADMIN
        return PrivilegeLevel.L1_OS

    # Window operations
    if op_type == OperationType.WINDOW_MOVE:
        if target and is_elevated_process(target):
            return PrivilegeLevel.L2_ADMIN
        return PrivilegeLevel.L1_OS

    # Network operations
    if op_type == OperationType.NETWORK_LISTEN:
        port = details.get("port", 0)
        if port < 1024:
            return PrivilegeLevel.L2_ADMIN
        if details.get("bind_address") == "0.0.0.0":
            return PrivilegeLevel.L1_OS  # Still allowed but flagged
        return PrivilegeLevel.L0_WORKSPACE

    if op_type == OperationType.NETWORK_CONNECT:
        return PrivilegeLevel.L0_WORKSPACE  # Outbound connections are L0

    # Scheduled tasks
    if op_type == OperationType.SCHEDULED_TASK:
        if details.get("scope") == "system":
            return PrivilegeLevel.L2_ADMIN
        return PrivilegeLevel.L1_OS

    # Default to L0
    return PrivilegeLevel.L0_WORKSPACE


def can_perform_operation(
    op_type: OperationType,
    target: Optional[str] = None,
    details: Optional[Dict] = None,
) -> BoundaryCheck:
    """
    Check if an operation is allowed given current trust state.

    Args:
        op_type: Type of operation
        target: Target path, process name, etc.
        details: Additional operation details

    Returns:
        BoundaryCheck with allowed status and details
    """
    state = get_trust_state()
    required_level = classify_operation(op_type, target, details)
    current_level = state.get_current_privilege_level()

    # L2 is never allowed for automation
    if required_level == PrivilegeLevel.L2_ADMIN:
        return BoundaryCheck(
            allowed=False,
            required_level=required_level,
            current_level=current_level,
            reason="L2 (Admin) operations require human authorization. "
                   "iHIM cannot automate registry, service, or system operations.",
            trust_score=state.current_score,
            can_escalate=False,
            escalation_path="Request the operator to perform this operation manually.",
        )

    # Check if current level is sufficient
    if current_level >= required_level:
        return BoundaryCheck(
            allowed=True,
            required_level=required_level,
            current_level=current_level,
            reason=f"Operation allowed at {current_level.display_name}",
            trust_score=state.current_score,
        )

    # Check if can escalate (L0 -> L1)
    if required_level == PrivilegeLevel.L1_OS:
        threshold = PRIVILEGE_THRESHOLDS[PrivilegeLevel.L1_OS]
        can_escalate = (
            state.current_score >= threshold.min_trust_score * 0.8 and  # 80% of threshold
            state.total_successful_ops >= threshold.min_successful_ops * 0.8
        )

        if can_escalate:
            return BoundaryCheck(
                allowed=False,
                required_level=required_level,
                current_level=current_level,
                reason=f"Operation requires {required_level.display_name}. "
                       f"Trust score: {state.current_score:.1f}/{threshold.min_trust_score}",
                trust_score=state.current_score,
                can_escalate=True,
                escalation_path=f"Continue L0 operations to build trust. "
                               f"Need {threshold.min_successful_ops - state.total_successful_ops} more successful ops.",
            )

        return BoundaryCheck(
            allowed=False,
            required_level=required_level,
            current_level=current_level,
            reason=f"Operation requires {required_level.display_name}. "
                   f"Trust score: {state.current_score:.1f}/{threshold.min_trust_score}",
            trust_score=state.current_score,
            can_escalate=False,
            escalation_path=f"Build trust through successful L0 operations first.",
        )

    return BoundaryCheck(
        allowed=False,
        required_level=required_level,
        current_level=current_level,
        reason=f"Insufficient privilege level",
        trust_score=state.current_score,
    )


def record_boundary_attempt(
    op_type: OperationType,
    target: Optional[str],
    check_result: BoundaryCheck,
    actually_attempted: bool = False,
) -> None:
    """
    Record a boundary check/attempt for auditing.

    Args:
        op_type: Type of operation
        target: Target of operation
        check_result: Result of boundary check
        actually_attempted: Whether the operation was actually attempted
    """
    operation_desc = f"{op_type.value}"
    if target:
        operation_desc += f" on {target}"

    if not check_result.allowed and actually_attempted:
        # This is a boundary violation attempt
        update_trust(
            event_type="boundary_violation",
            level=check_result.required_level.value,
            operation=operation_desc,
            success=False,
            details=f"Attempted {check_result.required_level.display_name} operation "
                   f"with {check_result.current_level.display_name} privileges",
        )
