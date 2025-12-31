"""
Compliance Loader - Loads and manages regulatory compliance modules at runtime

Integrates with workspace boot sequence to inject compliance controls into agent prompts
and enable runtime enforcement.

Architecture:
    Boot: CLAUDE.md → MEMORY.md → GUARDRAILS.md → [Compliance Modules] → Agent Spawn
    Runtime: Action → Enforcement Hooks → Evidence Collection → Violation Handling

Usage:
    # In spawner.py
    from compliance.loader import ComplianceLoader

    loader = ComplianceLoader()
    active_modules = loader.load_active_modules()
    compliance_prompt = loader.enhance_prompt(base_prompt, active_modules)
"""

import json
import re
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from datetime import datetime
from dataclasses import dataclass, field
from enum import Enum


# =============================================================================
# DATA MODELS
# =============================================================================

class EnforcementLevel(Enum):
    """Enforcement levels for compliance controls."""
    BLOCK = "BLOCK"          # Prevent action, require approval
    REDACT = "REDACT"        # Allow with data masked
    WARN = "WARN"            # Allow, log warning
    AUDIT = "AUDIT"          # Allow, record for review


@dataclass
class ComplianceRule:
    """A single compliance rule within a control."""
    type: str                           # pattern_block, file_type_check, etc.
    pattern: Optional[str] = None       # Regex pattern (if applicable)
    description: str = ""               # Human-readable description
    action: str = "block"               # block_and_redact, warn, audit
    redaction: str = "[REDACTED]"       # Replacement text for redaction
    compiled_pattern: Optional[re.Pattern] = field(default=None, repr=False)

    def __post_init__(self):
        """Compile regex pattern if provided."""
        if self.pattern:
            try:
                self.compiled_pattern = re.compile(self.pattern)
            except re.error as e:
                raise ValueError(f"Invalid regex pattern '{self.pattern}': {e}")


@dataclass
class ComplianceControl:
    """A compliance control with rules and enforcement settings."""
    control_id: str
    name: str
    description: str
    enforcement_level: EnforcementLevel
    triggers: List[str]                 # file_write, api_call, blackboard_post, etc.
    rules: List[ComplianceRule]
    evidence_required: bool = True
    evidence_retention_days: int = 2555  # 7 years default (HIPAA)

    @classmethod
    def from_dict(cls, data: dict) -> 'ComplianceControl':
        """Create ComplianceControl from JSON dict."""
        rules = [ComplianceRule(**rule) for rule in data.get("rules", [])]
        return cls(
            control_id=data["control_id"],
            name=data["name"],
            description=data["description"],
            enforcement_level=EnforcementLevel(data["enforcement_level"]),
            triggers=data["triggers"],
            rules=rules,
            evidence_required=data.get("evidence_required", True),
            evidence_retention_days=data.get("evidence_retention_days", 2555)
        )


@dataclass
class ComplianceModule:
    """A complete compliance module (HIPAA, SOC 2, GDPR, etc.)."""
    module_id: str
    version: str
    name: str
    category: str
    enabled: bool
    priority: int                       # Higher priority wins conflicts
    controls: List[ComplianceControl]
    agent_instructions: str
    guardrail_additions: List[str]
    metadata: Dict

    @classmethod
    def from_dict(cls, data: dict) -> 'ComplianceModule':
        """Create ComplianceModule from JSON dict."""
        controls = [ComplianceControl.from_dict(c) for c in data.get("controls", [])]
        return cls(
            module_id=data["module_id"],
            version=data["version"],
            name=data["name"],
            category=data["category"],
            enabled=data.get("enabled", False),
            priority=data.get("priority", 50),
            controls=controls,
            agent_instructions=data.get("agent_instructions", ""),
            guardrail_additions=data.get("guardrail_additions", []),
            metadata=data.get("metadata", {})
        )

    def get_controls_for_trigger(self, trigger: str) -> List[ComplianceControl]:
        """Get all controls that apply to a specific trigger."""
        return [c for c in self.controls if trigger in c.triggers]


# =============================================================================
# COMPLIANCE LOADER
# =============================================================================

class ComplianceLoader:
    """
    Loads and manages compliance modules.

    Responsibilities:
        - Load modules from JSON files
        - Validate module integrity
        - Merge multiple modules (priority-based)
        - Inject compliance context into agent prompts
        - Provide enforcement hooks for runtime

    Integration Points:
        - spawner.py: enhance_prompt() called during agent spawn
        - enforcer.py: get_active_controls() called during runtime hooks
        - evidence.py: Evidence collector uses module retention policies
    """

    def __init__(self, modules_dir: Optional[Path] = None, state_file: Optional[Path] = None):
        """
        Initialize the compliance loader.

        Args:
            modules_dir: Directory containing compliance module JSON files
            state_file: JSON file tracking active modules
        """
        # Default paths relative to workspace structure
        ihim_path = Path(__file__).parent.parent  # IHIM/
        self.modules_dir = modules_dir or (ihim_path / "compliance" / "modules")
        self.state_file = state_file or (ihim_path / "data" / "compliance_state.json")

        # In-memory cache
        self._available_modules: Dict[str, ComplianceModule] = {}
        self._active_modules: Dict[str, ComplianceModule] = {}

        # Ensure directories exist
        self.modules_dir.mkdir(parents=True, exist_ok=True)
        self.state_file.parent.mkdir(parents=True, exist_ok=True)

    # -------------------------------------------------------------------------
    # MODULE DISCOVERY & LOADING
    # -------------------------------------------------------------------------

    def discover_modules(self) -> List[str]:
        """
        Discover all available compliance modules.

        Returns:
            List of module IDs found in modules directory
        """
        if not self.modules_dir.exists():
            return []

        module_files = list(self.modules_dir.glob("*.json"))
        # Exclude schema.json
        module_files = [f for f in module_files if f.stem != "schema"]

        module_ids = []
        for module_file in module_files:
            try:
                with open(module_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    module_ids.append(data.get("module_id", module_file.stem))
            except Exception:
                continue

        return module_ids

    def load_module(self, module_id: str) -> Optional[ComplianceModule]:
        """
        Load a single compliance module from disk.

        Args:
            module_id: ID of the module to load (e.g., "hipaa-2024")

        Returns:
            ComplianceModule if found and valid, None otherwise
        """
        module_file = self.modules_dir / f"{module_id}.json"
        if not module_file.exists():
            return None

        try:
            with open(module_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # Validate basic structure
            required_fields = ["module_id", "version", "name", "category"]
            if not all(field in data for field in required_fields):
                raise ValueError(f"Module {module_id} missing required fields")

            module = ComplianceModule.from_dict(data)
            self._available_modules[module_id] = module
            return module

        except Exception as e:
            print(f"Error loading compliance module {module_id}: {e}")
            return None

    def load_all_modules(self) -> Dict[str, ComplianceModule]:
        """
        Load all available compliance modules.

        Returns:
            Dict mapping module_id to ComplianceModule
        """
        module_ids = self.discover_modules()
        for module_id in module_ids:
            self.load_module(module_id)

        return self._available_modules

    # -------------------------------------------------------------------------
    # STATE MANAGEMENT
    # -------------------------------------------------------------------------

    def load_state(self) -> Dict:
        """
        Load compliance state from JSON file.

        State tracks which modules are active and their configuration.

        Returns:
            State dict with 'active_modules', 'config', etc.
        """
        if not self.state_file.exists():
            return {
                "active_modules": [],
                "config": {
                    "enforcement_enabled": True,
                    "evidence_collection": True,
                    "auto_escalate": True
                },
                "last_updated": None
            }

        try:
            with open(self.state_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {"active_modules": [], "config": {}}

    def save_state(self, state: Dict):
        """Save compliance state to JSON file."""
        state["last_updated"] = datetime.utcnow().isoformat() + "Z"
        with open(self.state_file, 'w', encoding='utf-8') as f:
            json.dump(state, f, indent=2)

    def load_active_modules(self) -> List[ComplianceModule]:
        """
        Load currently active compliance modules.

        Returns:
            List of active ComplianceModule instances (sorted by priority desc)
        """
        # Load state to see what's active
        state = self.load_state()
        active_ids = state.get("active_modules", [])

        # Load all available modules
        self.load_all_modules()

        # Filter to active only (based on state file, not module.enabled flag)
        active = []
        for module_id in active_ids:
            if module_id in self._available_modules:
                module = self._available_modules[module_id]
                # Mark as enabled since it's in active list
                module.enabled = True
                active.append(module)
                self._active_modules[module_id] = module

        # Sort by priority (highest first)
        active.sort(key=lambda m: m.priority, reverse=True)

        return active

    def activate_module(self, module_id: str) -> bool:
        """
        Activate a compliance module.

        Args:
            module_id: ID of module to activate

        Returns:
            True if activated successfully, False otherwise
        """
        # Load module if not already loaded
        if module_id not in self._available_modules:
            module = self.load_module(module_id)
            if not module:
                return False

        # Update state
        state = self.load_state()
        if module_id not in state["active_modules"]:
            state["active_modules"].append(module_id)
            self.save_state(state)

        # Enable in memory
        module = self._available_modules[module_id]
        module.enabled = True
        self._active_modules[module_id] = module

        return True

    def deactivate_module(self, module_id: str) -> bool:
        """
        Deactivate a compliance module.

        Args:
            module_id: ID of module to deactivate

        Returns:
            True if deactivated successfully, False otherwise
        """
        state = self.load_state()
        if module_id in state["active_modules"]:
            state["active_modules"].remove(module_id)
            self.save_state(state)

        # Disable in memory
        if module_id in self._active_modules:
            del self._active_modules[module_id]

        if module_id in self._available_modules:
            self._available_modules[module_id].enabled = False

        return True

    # -------------------------------------------------------------------------
    # PROMPT ENHANCEMENT (Integration with Spawner)
    # -------------------------------------------------------------------------

    def enhance_prompt(self, base_prompt: str, active_modules: Optional[List[ComplianceModule]] = None) -> str:
        """
        Enhance agent prompt with compliance context.

        Called by spawner.py during agent spawn to inject compliance
        instructions and guardrails.

        Args:
            base_prompt: Original agent prompt
            active_modules: List of active modules (loads if not provided)

        Returns:
            Enhanced prompt with compliance context appended
        """
        if active_modules is None:
            active_modules = self.load_active_modules()

        if not active_modules:
            return base_prompt  # No compliance active

        # Build compliance section
        compliance_section = self._build_compliance_section(active_modules)

        # Append to base prompt
        enhanced = f"{base_prompt}\n\n{compliance_section}"
        return enhanced

    def _build_compliance_section(self, modules: List[ComplianceModule]) -> str:
        """Build the compliance context section for agent prompts."""
        lines = [
            "---",
            "",
            "## COMPLIANCE CONTEXT",
            "",
            "**NOTICE:** You are operating under the following regulatory compliance frameworks:",
            ""
        ]

        for module in modules:
            lines.append(f"### {module.name}")
            if module.agent_instructions:
                lines.append(module.agent_instructions)
            lines.append("")

            if module.guardrail_additions:
                lines.append("**Additional Guardrails:**")
                for guardrail in module.guardrail_additions:
                    lines.append(f"- {guardrail}")
                lines.append("")

        # Summary
        module_names = ", ".join([f"{m.name} ({m.version})" for m in modules])
        lines.extend([
            f"**Active Compliance Modules:** {module_names}",
            f"**Enforcement Active:** Runtime hooks enabled for {len(modules)} module(s)",
            "",
            "**CRITICAL:** Compliance violations will trigger immediate escalation. When in doubt, ask for approval.",
            ""
        ])

        return "\n".join(lines)

    def format_agent_instructions(self, modules: List[ComplianceModule]) -> str:
        """
        Format agent instructions for all active modules.

        Returns:
            Combined instructions string
        """
        instructions = []
        for module in modules:
            if module.agent_instructions:
                instructions.append(f"[{module.name}] {module.agent_instructions}")

        return "\n\n".join(instructions)

    # -------------------------------------------------------------------------
    # RUNTIME ENFORCEMENT SUPPORT
    # -------------------------------------------------------------------------

    def get_controls_for_trigger(self, trigger: str) -> List[Tuple[ComplianceModule, ComplianceControl]]:
        """
        Get all active controls that apply to a specific trigger.

        Used by enforcement hooks at runtime.

        Args:
            trigger: Event type (file_write, api_call, blackboard_post, etc.)

        Returns:
            List of (module, control) tuples sorted by priority
        """
        results = []

        for module in self._active_modules.values():
            controls = module.get_controls_for_trigger(trigger)
            for control in controls:
                results.append((module, control))

        # Sort by module priority (highest first)
        results.sort(key=lambda x: x[0].priority, reverse=True)

        return results

    def merge_enforcement_levels(self, controls: List[ComplianceControl]) -> EnforcementLevel:
        """
        Merge enforcement levels from multiple controls.

        Strategy: Most restrictive wins (BLOCK > REDACT > WARN > AUDIT)

        Args:
            controls: List of controls to merge

        Returns:
            Merged enforcement level
        """
        if not controls:
            return EnforcementLevel.AUDIT

        # Priority order (most restrictive first)
        priority_order = [
            EnforcementLevel.BLOCK,
            EnforcementLevel.REDACT,
            EnforcementLevel.WARN,
            EnforcementLevel.AUDIT
        ]

        for level in priority_order:
            if any(c.enforcement_level == level for c in controls):
                return level

        return EnforcementLevel.AUDIT

    # -------------------------------------------------------------------------
    # VALIDATION & HEALTH CHECKS
    # -------------------------------------------------------------------------

    def validate_module(self, module: ComplianceModule) -> Tuple[bool, List[str]]:
        """
        Validate a compliance module.

        Checks:
            - All regex patterns compile
            - No duplicate control IDs
            - Valid enforcement levels
            - Retention days within limits

        Args:
            module: Module to validate

        Returns:
            (is_valid, error_messages)
        """
        errors = []

        # Check for duplicate control IDs
        control_ids = [c.control_id for c in module.controls]
        duplicates = set([cid for cid in control_ids if control_ids.count(cid) > 1])
        if duplicates:
            errors.append(f"Duplicate control IDs: {duplicates}")

        # Validate each control
        for control in module.controls:
            # Validate enforcement level
            if control.enforcement_level not in EnforcementLevel:
                errors.append(f"Invalid enforcement level for {control.control_id}")

            # Validate retention days (max 10 years)
            if control.evidence_retention_days > 3650:
                errors.append(f"Retention days too long for {control.control_id} (max 10 years)")

            # Validate rules
            for rule in control.rules:
                if rule.pattern and not rule.compiled_pattern:
                    errors.append(f"Failed to compile pattern for {control.control_id}: {rule.pattern}")

        return len(errors) == 0, errors

    def health_check(self) -> Dict:
        """
        Run health check on compliance system.

        Returns:
            Health status dict with details
        """
        status = {
            "healthy": True,
            "active_modules": len(self._active_modules),
            "available_modules": len(self._available_modules),
            "errors": [],
            "warnings": []
        }

        # Check state file exists and is readable
        if not self.state_file.exists():
            status["warnings"].append("No compliance state file found (will create on first activation)")

        # Check modules directory exists
        if not self.modules_dir.exists():
            status["errors"].append(f"Modules directory not found: {self.modules_dir}")
            status["healthy"] = False

        # Validate active modules
        for module_id, module in self._active_modules.items():
            is_valid, errors = self.validate_module(module)
            if not is_valid:
                status["errors"].extend([f"{module_id}: {err}" for err in errors])
                status["healthy"] = False

        return status


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def create_sample_state() -> Dict:
    """Create a sample compliance state file."""
    return {
        "active_modules": [],  # Empty by default - user must activate
        "config": {
            "enforcement_enabled": True,
            "evidence_collection": True,
            "auto_escalate": True,
            "escalation_timeout_seconds": 300
        },
        "last_updated": datetime.utcnow().isoformat() + "Z"
    }


# =============================================================================
# MAIN (for testing)
# =============================================================================

if __name__ == "__main__":
    """Test the compliance loader."""
    loader = ComplianceLoader()

    print("=== Compliance Loader Test ===\n")

    # Health check
    print("Running health check...")
    health = loader.health_check()
    print(f"Healthy: {health['healthy']}")
    print(f"Active modules: {health['active_modules']}")
    print(f"Available modules: {health['available_modules']}")
    if health['errors']:
        print(f"Errors: {health['errors']}")
    if health['warnings']:
        print(f"Warnings: {health['warnings']}")

    print("\n" + "="*50 + "\n")

    # Discover modules
    print("Discovering modules...")
    module_ids = loader.discover_modules()
    print(f"Found modules: {module_ids}")

    print("\n" + "="*50 + "\n")

    # Load active modules
    print("Loading active modules...")
    active = loader.load_active_modules()
    if active:
        print(f"Loaded {len(active)} active module(s):")
        for module in active:
            print(f"  - {module.name} (v{module.version})")
            print(f"    Controls: {len(module.controls)}")
            print(f"    Priority: {module.priority}")
    else:
        print("No active modules (activate modules via API or state file)")

    print("\n" + "="*50 + "\n")

    # Test prompt enhancement
    print("Testing prompt enhancement...")
    base_prompt = "You are a backend developer. Build a user management API."
    enhanced = loader.enhance_prompt(base_prompt, active)
    print(f"Base prompt length: {len(base_prompt)} chars")
    print(f"Enhanced prompt length: {len(enhanced)} chars")
    print("\nEnhanced prompt preview:")
    print(enhanced[:500] + "..." if len(enhanced) > 500 else enhanced)
