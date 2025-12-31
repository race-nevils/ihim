"""
Compliance Module - Regulatory compliance framework for workspace agents

Provides compliance module loading, enforcement hooks, and evidence collection
for regulatory frameworks like HIPAA, SOC 2, GDPR, etc.

Main Components:
    - loader.py: Load and manage compliance modules
    - enforcer.py: Runtime enforcement hooks (Phase 2)
    - evidence.py: Audit trail collection (Phase 2)
    - validator.py: Module integrity validation (Phase 2)

Usage:
    from compliance.loader import ComplianceLoader

    loader = ComplianceLoader()
    loader.activate_module("hipaa-2024")
    active_modules = loader.load_active_modules()

    # In spawner:
    enhanced_prompt = loader.enhance_prompt(base_prompt, active_modules)
"""

from .loader import (
    ComplianceLoader,
    ComplianceModule,
    ComplianceControl,
    ComplianceRule,
    EnforcementLevel
)

__all__ = [
    "ComplianceLoader",
    "ComplianceModule",
    "ComplianceControl",
    "ComplianceRule",
    "EnforcementLevel"
]

__version__ = "1.0.0"
