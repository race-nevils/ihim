"""
Test Suite: Slash Command Content Validation
QA Tester: Deep validation of command content, workflow steps, and consistency.

Tests cover:
- Step-by-step workflow validation
- Code block syntax checking
- Cross-command consistency
- Memory system integration
"""

import os
import re
from pathlib import Path

WORKSPACE_ROOT = Path("C:/Users/<user>/workspace")
COMMANDS_DIR = WORKSPACE_ROOT / "harness dir" / "commands"


class TestResults:
    """Track test results for reporting."""
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.errors = []
        self.warnings = []

    def pass_test(self, test_name):
        self.passed += 1
        print(f"  PASS: {test_name}")

    def fail_test(self, test_name, reason):
        self.failed += 1
        self.errors.append(f"{test_name}: {reason}")
        print(f"  FAIL: {test_name} - {reason}")

    def warn(self, warning):
        self.warnings.append(warning)
        print(f"  WARN: {warning}")


def test_save_workflow_steps(results: TestResults):
    """Test: /save should have ordered steps (Step 1, Step 2, etc.)."""
    save_path = COMMANDS_DIR / "save.md"
    if not save_path.exists():
        results.fail_test("Save workflow steps", "save.md not found")
        return

    content = save_path.read_text(encoding="utf-8")
    steps = re.findall(r"## Step (\d+)", content)

    if len(steps) >= 3:
        results.pass_test(f"Save has {len(steps)} workflow steps")
    else:
        results.fail_test("Save workflow steps", f"Expected 3+ steps, found {len(steps)}")

    # Check steps are sequential
    expected = list(range(1, len(steps) + 1))
    actual = [int(s) for s in steps]
    if actual == expected:
        results.pass_test("Save steps are sequential")
    else:
        results.fail_test("Save steps sequential", f"Expected {expected}, got {actual}")


def test_endsession_workflow_steps(results: TestResults):
    """Test: /endsession should have comprehensive workflow steps."""
    path = COMMANDS_DIR / "endsession.md"
    if not path.exists():
        results.fail_test("Endsession workflow", "endsession.md not found")
        return

    content = path.read_text(encoding="utf-8")
    # Check for numbered sections
    sections = re.findall(r"## (\d+)\.", content)

    if len(sections) >= 5:
        results.pass_test(f"Endsession has {len(sections)} workflow sections")
    else:
        results.fail_test("Endsession sections", f"Expected 5+ sections, found {len(sections)}")


def test_commands_have_code_blocks(results: TestResults):
    """Test: Commands should have code blocks for executable steps."""
    commands_with_code = ["save.md", "endsession.md", "push-workspace.md"]

    for cmd in commands_with_code:
        path = COMMANDS_DIR / cmd
        if path.exists():
            content = path.read_text(encoding="utf-8")
            code_blocks = re.findall(r"```(\w+)?", content)
            if len(code_blocks) > 0:
                results.pass_test(f"Code blocks in {cmd}: {len(code_blocks)} found")
            else:
                results.fail_test(f"Code blocks in {cmd}", "No code blocks found")


def test_code_blocks_have_language(results: TestResults):
    """Test: Code blocks should specify language for syntax highlighting."""
    for cmd_file in COMMANDS_DIR.glob("*.md"):
        content = cmd_file.read_text(encoding="utf-8")
        # Find code blocks without language specifier
        untyped_blocks = re.findall(r"```\n", content)
        typed_blocks = re.findall(r"```\w+", content)

        if len(untyped_blocks) > 0:
            results.warn(f"{cmd_file.name}: {len(untyped_blocks)} code blocks without language")
        elif len(typed_blocks) > 0:
            results.pass_test(f"{cmd_file.name}: All code blocks have language")


def test_consistent_confirmation_format(results: TestResults):
    """Test: Commands should have consistent confirmation format."""
    confirmation_patterns = []

    for cmd_file in COMMANDS_DIR.glob("*.md"):
        content = cmd_file.read_text(encoding="utf-8")
        # Look for emoji + text pattern at end
        if "Confirm" in content or "confirm" in content:
            # Check for emoji in confirmation
            emoji_match = re.search(r"[📝💾🚀🔍📋]", content)
            if emoji_match:
                confirmation_patterns.append((cmd_file.name, "has emoji"))
            else:
                confirmation_patterns.append((cmd_file.name, "no emoji"))

    # Check consistency
    has_emoji = [p for p in confirmation_patterns if p[1] == "has emoji"]
    no_emoji = [p for p in confirmation_patterns if p[1] == "no emoji"]

    if len(has_emoji) > 0 and len(no_emoji) == 0:
        results.pass_test("Consistent confirmation format (all have emoji)")
    elif len(no_emoji) > 0 and len(has_emoji) == 0:
        results.pass_test("Consistent confirmation format (none have emoji)")
    else:
        results.warn(f"Inconsistent emoji use: {len(has_emoji)} with, {len(no_emoji)} without")


def test_memory_file_references(results: TestResults):
    """Test: Memory-related commands should reference correct file paths."""
    memory_files = ["MEMORY.md", "NOTES.md", "MEMORY_ARCHIVE.md"]

    for cmd_file in COMMANDS_DIR.glob("*.md"):
        content = cmd_file.read_text(encoding="utf-8")

        # Commands that should reference memory files
        if "memory" in cmd_file.stem or cmd_file.stem in ["save", "endsession"]:
            found_refs = [mf for mf in memory_files if mf in content]
            if len(found_refs) > 0:
                results.pass_test(f"{cmd_file.name} references: {', '.join(found_refs)}")
            else:
                results.warn(f"{cmd_file.name} might need memory file references")


def test_sanity_check_path_consistency(results: TestResults):
    """Test: Sanity check paths should be consistent across commands."""
    sanity_paths = []

    for cmd_file in COMMANDS_DIR.glob("*.md"):
        content = cmd_file.read_text(encoding="utf-8")
        # Look for sanity check references
        paths = re.findall(r"([\w/\\.-]+sanity[\w/\\.-]*check\.py)", content, re.IGNORECASE)
        for path in paths:
            sanity_paths.append((cmd_file.name, path))

    if len(sanity_paths) > 0:
        unique_paths = set([p[1] for p in sanity_paths])
        if len(unique_paths) == 1:
            results.pass_test(f"Sanity check path consistent: {list(unique_paths)[0]}")
        else:
            results.fail_test("Sanity check path consistency",
                            f"Multiple paths found: {unique_paths}")
    else:
        results.warn("No sanity check paths found in commands")


def test_audit_command_structure(results: TestResults):
    """Test: /audit command should have reflection-oriented sections."""
    path = COMMANDS_DIR / "audit.md"
    if not path.exists():
        results.fail_test("Audit structure", "audit.md not found")
        return

    content = path.read_text(encoding="utf-8")

    expected_sections = ["Scope", "Process", "Issues", "Learnings"]
    found = [s for s in expected_sections if s.lower() in content.lower()]

    if len(found) >= 3:
        results.pass_test(f"Audit has reflection sections: {', '.join(found)}")
    else:
        results.fail_test("Audit reflection sections",
                        f"Expected 3+, found: {', '.join(found)}")


def test_meeting_prep_adaptive_learning(results: TestResults):
    """Test: /meeting-prep should reference learning from past meetings."""
    path = COMMANDS_DIR / "meeting-prep.md"
    if not path.exists():
        results.fail_test("Meeting prep learning", "meeting-prep.md not found")
        return

    content = path.read_text(encoding="utf-8")

    adaptive_keywords = ["learn", "history", "past meeting", "pattern", "adaptive"]
    found = [k for k in adaptive_keywords if k.lower() in content.lower()]

    if len(found) >= 3:
        results.pass_test(f"Meeting prep has adaptive learning: {', '.join(found)}")
    else:
        results.warn(f"Meeting prep might benefit from more adaptive keywords")


def test_push_workspace_git_commands(results: TestResults):
    """Test: /push-workspace should have correct git command sequence."""
    path = COMMANDS_DIR / "push-workspace.md"
    if not path.exists():
        results.fail_test("Push-workspace git commands", "push-workspace.md not found")
        return

    content = path.read_text(encoding="utf-8")

    # Expected git command sequence
    expected_commands = ["git status", "git add", "git commit", "git push"]
    found = [cmd for cmd in expected_commands if cmd in content]

    if len(found) == len(expected_commands):
        results.pass_test("Push-workspace has complete git workflow")
    else:
        missing = [cmd for cmd in expected_commands if cmd not in content]
        results.fail_test("Push-workspace git workflow", f"Missing: {', '.join(missing)}")


def run_all_tests():
    """Run all content tests."""
    results = TestResults()

    print("\n" + "=" * 60)
    print("SLASH COMMAND CONTENT TESTS")
    print("=" * 60 + "\n")

    print("--- Workflow Step Tests ---")
    test_save_workflow_steps(results)
    test_endsession_workflow_steps(results)

    print("\n--- Code Block Tests ---")
    test_commands_have_code_blocks(results)
    test_code_blocks_have_language(results)

    print("\n--- Consistency Tests ---")
    test_consistent_confirmation_format(results)
    test_memory_file_references(results)
    test_sanity_check_path_consistency(results)

    print("\n--- Command-Specific Tests ---")
    test_audit_command_structure(results)
    test_meeting_prep_adaptive_learning(results)
    test_push_workspace_git_commands(results)

    print("\n" + "=" * 60)
    print(f"RESULTS: {results.passed} passed, {results.failed} failed, {len(results.warnings)} warnings")
    print("=" * 60)

    return results


if __name__ == "__main__":
    results = run_all_tests()

    if results.warnings:
        print("\n--- WARNINGS ---")
        for w in results.warnings:
            print(f"  - {w}")

    if results.errors:
        print("\n--- FAILURES ---")
        for err in results.errors:
            print(f"  - {err}")
