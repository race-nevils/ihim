"""
Privilege Level Definitions

Maps to the system architecture:
- L0 (workspace): Incubator environment, mistakes have limited blast radius
- L1 (OS): User-space Windows, can affect system behavior
- L2 (Admin): Registry/services/system - NEVER automated, human only

Maps to Periodic Table tiers:
- the agent (Scout) -> L0 only (READ-ONLY within workspace)
- the agent (Operator) -> L0 with R/W
- the agent (Architect) -> L0-L1 (can graduate to OS level)
- Human -> L0-L2 (only human touches Admin)
"""

from enum import Enum
from dataclasses import dataclass
from typing import Dict, List


class PrivilegeLevel(Enum):
    """Privilege levels for iHIM operations."""

    L0_WORKSPACE = "L0"       # Virtual Workstation (incubator) - default
    L1_OS = "L1"        # User-space Windows operations
    L2_ADMIN = "L2"     # Admin/system - HUMAN ONLY

    @property
    def display_name(self) -> str:
        names = {
            "L0": "workspace (Virtual Workstation)",
            "L1": "OS (User-space)",
            "L2": "Admin (Human Only)",
        }
        return names.get(self.value, self.value)

    @property
    def can_automate(self) -> bool:
        """L2 cannot be automated - only human operates there."""
        return self != PrivilegeLevel.L2_ADMIN

    def __lt__(self, other):
        if not isinstance(other, PrivilegeLevel):
            return NotImplemented
        order = ["L0", "L1", "L2"]
        return order.index(self.value) < order.index(other.value)

    def __le__(self, other):
        return self == other or self < other


@dataclass
class PrivilegeThreshold:
    """Trust score thresholds for privilege levels."""

    level: PrivilegeLevel
    min_trust_score: float      # Minimum score to reach this level
    min_successful_ops: int     # Minimum successful operations
    max_failures_24h: int       # Maximum failures in last 24h
    recovery_penalty_days: int  # Days of halved recovery after incident


# Thresholds for each privilege level
PRIVILEGE_THRESHOLDS: Dict[PrivilegeLevel, PrivilegeThreshold] = {
    PrivilegeLevel.L0_WORKSPACE: PrivilegeThreshold(
        level=PrivilegeLevel.L0_WORKSPACE,
        min_trust_score=0.0,      # Always available
        min_successful_ops=0,      # No minimum
        max_failures_24h=100,      # Very lenient in incubator
        recovery_penalty_days=0,   # No penalty
    ),
    PrivilegeLevel.L1_OS: PrivilegeThreshold(
        level=PrivilegeLevel.L1_OS,
        min_trust_score=50.0,      # Need 50+ trust score
        min_successful_ops=100,    # 100 successful L0 ops first
        max_failures_24h=5,        # Stricter failure tolerance
        recovery_penalty_days=7,   # 7 days halved recovery after incident
    ),
    PrivilegeLevel.L2_ADMIN: PrivilegeThreshold(
        level=PrivilegeLevel.L2_ADMIN,
        min_trust_score=float('inf'),  # Never automated
        min_successful_ops=float('inf'),
        max_failures_24h=0,
        recovery_penalty_days=float('inf'),
    ),
}


# Operation scoring for trust accumulation/depletion
TRUST_SCORES = {
    "success": {
        "L0": 0.1,   # Small increment for workspace ops
        "L1": 0.5,   # Larger increment for OS ops
    },
    "failure": {
        "L0": -0.5,  # Small penalty in incubator
        "L1": -5.0,  # Significant penalty at OS level
    },
    "boundary_violation_attempt": -10.0,  # Trying to exceed privilege
    "idle_decay_per_day": -0.1,            # Slight decay when idle
}


# Examples of operations by privilege level
OPERATION_EXAMPLES: Dict[PrivilegeLevel, List[str]] = {
    PrivilegeLevel.L0_WORKSPACE: [
        "Read files in workspace directory",
        "Write files in workspace directory",
        "Run Python scripts in workspace",
        "Start iHIM services",
        "Access localhost:7777",
        "Modify iHIM configuration",
    ],
    PrivilegeLevel.L1_OS: [
        "Move/resize non-elevated windows",
        "Start user-space applications",
        "Access user's Documents/Desktop",
        "Modify user environment variables",
        "Create scheduled tasks (user level)",
    ],
    PrivilegeLevel.L2_ADMIN: [
        "Modify Windows Registry",
        "Start/stop system services",
        "Move elevated windows (Task Manager)",
        "Modify system PATH",
        "Install system-wide software",
        "Change firewall rules",
    ],
}
