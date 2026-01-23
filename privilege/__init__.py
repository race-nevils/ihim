"""
iHIM Privilege Management System

Governance layer for auditable AI with trust-based privilege escalation.

Privilege Levels:
- L0 (workspace): Virtual Workstation scope - iHIM default
- L1 (OS): User-space Windows operations - earned after trust threshold
- L2 (Admin): Registry, services, system - HUMAN ONLY (never automated)

Core Principles:
- Trust is earned through demonstrated reliability
- Every action is auditable
- Origin and history of all artifacts traceable (C2PA/provenance)
- the operator controls all data flows (LDUX/sovereignty)
"""

from .levels import PrivilegeLevel, PRIVILEGE_THRESHOLDS
from .trust import TrustState, get_trust_state, update_trust
from .boundary import can_perform_operation, classify_operation, OperationType

__all__ = [
    "PrivilegeLevel",
    "PRIVILEGE_THRESHOLDS",
    "TrustState",
    "get_trust_state",
    "update_trust",
    "can_perform_operation",
    "classify_operation",
    "OperationType",
]
