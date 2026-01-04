"""
iHIM Sanity Check System

Catches common issues before they become runtime problems:
- Missing Python modules
- Action registry inconsistencies
- Import chain failures
- Template formatting bugs
- JSON data file corruption
- Naming convention drift
"""

import importlib
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from datetime import datetime


@dataclass
class CheckResult:
    """Result of a single sanity check."""
    name: str
    passed: bool
    message: str
    severity: str = "error"  # error, warning, info
    fix_hint: Optional[str] = None


@dataclass
class SanityReport:
    """Full sanity check report."""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    passed: bool = True
    checks: list = field(default_factory=list)
    errors: int = 0
    warnings: int = 0

    def add(self, result: CheckResult):
        """Add a check result to the report."""
        self.checks.append(result)
        if not result.passed:
            if result.severity == "error":
                self.errors += 1
                self.passed = False
            elif result.severity == "warning":
                self.warnings += 1

    def summary(self) -> str:
        """Generate human-readable summary."""
        status = "PASSED" if self.passed else "FAILED"
        lines = [
            f"Sanity Check: {status}",
            f"Errors: {self.errors} | Warnings: {self.warnings}",
            "-" * 40
        ]

        for check in self.checks:
            icon = "[OK]" if check.passed else "[FAIL]" if check.severity == "error" else "[WARN]"
            lines.append(f"{icon} {check.name}: {check.message}")
            if not check.passed and check.fix_hint:
                lines.append(f"     Fix: {check.fix_hint}")

        return "\n".join(lines)


# =============================================================================
# CHECK FUNCTIONS
# =============================================================================

def check_required_modules(report: SanityReport):
    """Check that all required Python modules are installed."""
    required = [
        ("fastapi", "pip install fastapi"),
        ("uvicorn", "pip install uvicorn"),
        ("pydantic", "pip install pydantic"),
        ("psutil", "pip install psutil"),
    ]

    for module_name, fix_cmd in required:
        try:
            importlib.import_module(module_name)
            report.add(CheckResult(
                name=f"Module: {module_name}",
                passed=True,
                message="installed"
            ))
        except ImportError:
            report.add(CheckResult(
                name=f"Module: {module_name}",
                passed=False,
                message="NOT INSTALLED",
                severity="error",
                fix_hint=fix_cmd
            ))


def check_ihim_imports(report: SanityReport):
    """Check that all iHIM modules can be imported."""
    ihim_root = Path(__file__).parent.parent

    # Ensure iHIM is in path
    if str(ihim_root) not in sys.path:
        sys.path.insert(0, str(ihim_root))

    modules_to_check = [
        ("actions.registry", "Core action registry"),
        ("actions.utils", "Action utilities"),
        ("team.router", "Prompt router"),
        ("team.spawner", "Agent spawner"),
        ("team.templates", "Agent templates"),
        ("team.state", "Team state management"),
        ("team.feedback.schemas", "Feedback data models"),
        ("team.feedback.processor", "Result processor"),
        ("team.feedback.aggregator", "Feedback aggregator"),
        ("team.feedback.optimizer", "Prompt optimizer"),
        ("team.feedback.metrics", "Metrics tracker"),
        ("api.flightpath.scanner", "Flight path scanner"),
    ]

    for module_path, description in modules_to_check:
        try:
            importlib.import_module(module_path)
            report.add(CheckResult(
                name=f"Import: {module_path}",
                passed=True,
                message=description
            ))
        except Exception as e:
            report.add(CheckResult(
                name=f"Import: {module_path}",
                passed=False,
                message=f"{description} - {str(e)[:50]}",
                severity="error",
                fix_hint=f"Check {module_path.replace('.', '/')}.py for errors"
            ))


def check_action_registry(report: SanityReport):
    """Check that action registry is consistent."""
    try:
        from actions.registry import ACTIONS, run_action

        # Check each action has required fields
        required_fields = ["name", "description", "icon", "category"]

        for action_id, config in ACTIONS.items():
            missing = [f for f in required_fields if f not in config]
            if missing:
                report.add(CheckResult(
                    name=f"Action: {action_id}",
                    passed=False,
                    message=f"Missing fields: {missing}",
                    severity="error",
                    fix_hint=f"Add {missing} to ACTIONS['{action_id}'] in registry.py"
                ))
            else:
                report.add(CheckResult(
                    name=f"Action: {action_id}",
                    passed=True,
                    message=config["name"]
                ))

        # Check that run_action handles all registered actions
        for action_id in ACTIONS.keys():
            # We can't actually run actions, but we can check the function signature
            pass

    except Exception as e:
        report.add(CheckResult(
            name="Action Registry",
            passed=False,
            message=str(e)[:100],
            severity="error"
        ))


def check_template_formatting(report: SanityReport):
    """Check that templates don't have formatting issues."""
    try:
        from team.templates import AGENT_TEMPLATES
        BLACKBOARD_INSTRUCTIONS = ""  # Blackboard archived

        # Test that templates can be formatted without KeyErrors
        test_vars = {
            "prompt": "Test prompt",
            "project": "TestProject",
            "working_dir": "/test/dir",
            "agent": "test-agent"  # For END_SEQUENCE file paths
        }

        for agent_name, template in AGENT_TEMPLATES.items():
            try:
                # Try formatting the template
                result = template.format(**test_vars)
                report.add(CheckResult(
                    name=f"Template: {agent_name}",
                    passed=True,
                    message="formats correctly"
                ))
            except KeyError as e:
                report.add(CheckResult(
                    name=f"Template: {agent_name}",
                    passed=False,
                    message=f"KeyError: {e}",
                    severity="error",
                    fix_hint="Use .replace() instead of .format() for JSON content"
                ))

    except Exception as e:
        report.add(CheckResult(
            name="Template System",
            passed=False,
            message=str(e)[:100],
            severity="error"
        ))


def check_data_files(report: SanityReport):
    """Check that JSON data files are valid."""
    data_dir = Path(__file__).parent.parent / "data"

    json_files = [
        "tasks.json",
        "notes.json",
        "metrics.json",
        "feedback_history.json",
    ]

    for filename in json_files:
        filepath = data_dir / filename
        if not filepath.exists():
            report.add(CheckResult(
                name=f"Data: {filename}",
                passed=True,
                message="(not created yet - OK)",
                severity="info"
            ))
            continue

        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                json.load(f)
            report.add(CheckResult(
                name=f"Data: {filename}",
                passed=True,
                message="valid JSON"
            ))
        except json.JSONDecodeError as e:
            report.add(CheckResult(
                name=f"Data: {filename}",
                passed=False,
                message=f"Invalid JSON: {str(e)[:50]}",
                severity="error",
                fix_hint=f"Fix or delete {filepath}"
            ))


def check_directory_structure(report: SanityReport):
    """Check that expected directories exist."""
    ihim_root = Path(__file__).parent.parent

    expected_dirs = [
        "actions",
        "api",
        "api/flightpath",
        "team",
        "team/feedback",
        "team/results",
        "team/tasks",
        "ui",
        "ui/static",
        "data",
        "sanity",
    ]

    for dir_path in expected_dirs:
        full_path = ihim_root / dir_path
        if full_path.exists() and full_path.is_dir():
            report.add(CheckResult(
                name=f"Dir: {dir_path}",
                passed=True,
                message="exists"
            ))
        else:
            report.add(CheckResult(
                name=f"Dir: {dir_path}",
                passed=False,
                message="MISSING",
                severity="warning",
                fix_hint=f"mkdir {full_path}"
            ))


def check_naming_conventions(report: SanityReport):
    """Check for naming consistency across the codebase."""
    issues = []

    # Check agent names are consistent between templates and registry
    try:
        from team.templates import AGENT_TEMPLATES
        from actions.registry import ACTIONS

        expected_agents = {"frontend-dev", "backend-dev", "devops", "qa-tester", "security-reviewer"}
        template_agents = set(AGENT_TEMPLATES.keys())

        if template_agents != expected_agents:
            missing = expected_agents - template_agents
            extra = template_agents - expected_agents
            if missing:
                issues.append(f"Missing templates: {missing}")
            if extra:
                issues.append(f"Extra templates: {extra}")

        if issues:
            report.add(CheckResult(
                name="Naming: Agent Templates",
                passed=False,
                message="; ".join(issues),
                severity="warning"
            ))
        else:
            report.add(CheckResult(
                name="Naming: Agent Templates",
                passed=True,
                message="all 5 agents defined"
            ))

    except Exception as e:
        report.add(CheckResult(
            name="Naming: Agent Templates",
            passed=False,
            message=str(e)[:50],
            severity="error"
        ))


def check_api_server_readiness(report: SanityReport):
    """Check if API server can be started (import test)."""
    try:
        # This imports will fail if there are issues
        from api.main import app
        report.add(CheckResult(
            name="API Server",
            passed=True,
            message="ready to start"
        ))
    except Exception as e:
        report.add(CheckResult(
            name="API Server",
            passed=False,
            message=str(e)[:100],
            severity="error",
            fix_hint="Check api/main.py imports and dependencies"
        ))


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

def run_sanity_check(verbose: bool = True) -> SanityReport:
    """
    Run all sanity checks and return a report.

    Args:
        verbose: If True, print results as checks run

    Returns:
        SanityReport with all check results
    """
    report = SanityReport()

    # Add iHIM to path
    ihim_root = Path(__file__).parent.parent
    if str(ihim_root) not in sys.path:
        sys.path.insert(0, str(ihim_root))

    checks = [
        ("Required Modules", check_required_modules),
        ("Directory Structure", check_directory_structure),
        ("iHIM Imports", check_ihim_imports),
        ("Action Registry", check_action_registry),
        ("Template Formatting", check_template_formatting),
        ("Data Files", check_data_files),
        ("Naming Conventions", check_naming_conventions),
        ("API Server", check_api_server_readiness),
    ]

    for check_name, check_fn in checks:
        if verbose:
            print(f"Checking {check_name}...", end=" ", flush=True)
        try:
            check_fn(report)
            if verbose:
                print("done")
        except Exception as e:
            report.add(CheckResult(
                name=check_name,
                passed=False,
                message=f"Check crashed: {str(e)[:50]}",
                severity="error"
            ))
            if verbose:
                print(f"FAILED: {e}")

    return report


# CLI entry point
if __name__ == "__main__":
    print("iHIM Sanity Check")
    print("=" * 40)
    print()

    report = run_sanity_check(verbose=True)

    print()
    print("=" * 40)
    print(report.summary())
