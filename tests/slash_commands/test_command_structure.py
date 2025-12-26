"""
Test Suite: Slash Command Structure Validation
QA Tester: Validates that all commands follow the expected format and conventions.

Tests cover:
- File existence and naming
- Required sections in command files
- Frontmatter validation (where applicable)
- Cross-references between commands
"""

import os
import re
from pathlib import Path

# Constants
WORKSPACE_ROOT = Path("C:/Users/<user>/workspace")
COMMANDS_DIR = WORKSPACE_ROOT / "harness dir" / "commands"
SKILLS_DIR = WORKSPACE_ROOT / "harness dir" / "skills"

# Expected commands based on discovery
EXPECTED_COMMANDS = [
    "save.md",
    "endsession.md",
    "audit.md",
    "push-workspace.md",
    "meeting-prep.md",
]

# Required sections for commands (at minimum)
REQUIRED_SECTIONS_BASIC = ["#"]  # At least one heading


class TestResults:
    """Track test results for reporting."""
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.errors = []
        self.edge_cases = []
        self.bugs = []

    def pass_test(self, test_name):
        self.passed += 1
        print(f"  PASS: {test_name}")

    def fail_test(self, test_name, reason):
        self.failed += 1
        self.errors.append(f"{test_name}: {reason}")
        print(f"  FAIL: {test_name} - {reason}")

    def add_edge_case(self, case):
        self.edge_cases.append(case)

    def add_bug(self, bug):
        self.bugs.append(bug)


def test_commands_directory_exists(results: TestResults):
    """Test: Commands directory should exist."""
    if COMMANDS_DIR.exists():
        results.pass_test("Commands directory exists")
    else:
        results.fail_test("Commands directory exists", f"Directory not found: {COMMANDS_DIR}")


def test_all_expected_commands_exist(results: TestResults):
    """Test: All expected command files should exist."""
    for cmd in EXPECTED_COMMANDS:
        cmd_path = COMMANDS_DIR / cmd
        if cmd_path.exists():
            results.pass_test(f"Command file exists: {cmd}")
        else:
            results.fail_test(f"Command file exists: {cmd}", "File not found")


def test_command_files_not_empty(results: TestResults):
    """Test: Command files should not be empty."""
    for cmd in EXPECTED_COMMANDS:
        cmd_path = COMMANDS_DIR / cmd
        if cmd_path.exists():
            content = cmd_path.read_text(encoding="utf-8")
            if len(content.strip()) > 0:
                results.pass_test(f"Command not empty: {cmd}")
            else:
                results.fail_test(f"Command not empty: {cmd}", "File is empty")


def test_command_has_heading(results: TestResults):
    """Test: Each command should have at least one markdown heading."""
    for cmd in EXPECTED_COMMANDS:
        cmd_path = COMMANDS_DIR / cmd
        if cmd_path.exists():
            content = cmd_path.read_text(encoding="utf-8")
            if re.search(r"^#+ ", content, re.MULTILINE):
                results.pass_test(f"Command has heading: {cmd}")
            else:
                results.fail_test(f"Command has heading: {cmd}", "No markdown heading found")


def test_command_naming_convention(results: TestResults):
    """Test: Command files should follow kebab-case naming."""
    for cmd_file in COMMANDS_DIR.glob("*.md"):
        name = cmd_file.stem
        # kebab-case: lowercase letters and hyphens only
        if re.match(r"^[a-z]+(-[a-z]+)*$", name):
            results.pass_test(f"Naming convention: {cmd_file.name}")
        else:
            results.fail_test(f"Naming convention: {cmd_file.name}",
                            f"Should be kebab-case, got: {name}")
            results.add_edge_case(f"Non-standard name: {name}")


def test_skills_directory_exists(results: TestResults):
    """Test: Skills directory should exist."""
    if SKILLS_DIR.exists():
        results.pass_test("Skills directory exists")
    else:
        results.fail_test("Skills directory exists", f"Directory not found: {SKILLS_DIR}")


def test_skills_have_skill_md(results: TestResults):
    """Test: Each skill folder should have a skill.md file."""
    if not SKILLS_DIR.exists():
        return

    for skill_folder in SKILLS_DIR.iterdir():
        if skill_folder.is_dir():
            skill_file = skill_folder / "skill.md"
            if skill_file.exists():
                results.pass_test(f"Skill has skill.md: {skill_folder.name}")
            else:
                results.fail_test(f"Skill has skill.md: {skill_folder.name}",
                                "skill.md not found in folder")


def test_skill_has_frontmatter(results: TestResults):
    """Test: Each skill.md should have YAML frontmatter with name and description."""
    if not SKILLS_DIR.exists():
        return

    for skill_folder in SKILLS_DIR.iterdir():
        if skill_folder.is_dir():
            skill_file = skill_folder / "skill.md"
            if skill_file.exists():
                content = skill_file.read_text(encoding="utf-8")
                # Check for frontmatter delimiters
                if content.startswith("---"):
                    # Check for name and description in frontmatter
                    frontmatter_match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
                    if frontmatter_match:
                        frontmatter = frontmatter_match.group(1)
                        has_name = "name:" in frontmatter
                        has_desc = "description:" in frontmatter
                        if has_name and has_desc:
                            results.pass_test(f"Skill frontmatter valid: {skill_folder.name}")
                        else:
                            missing = []
                            if not has_name:
                                missing.append("name")
                            if not has_desc:
                                missing.append("description")
                            results.fail_test(f"Skill frontmatter valid: {skill_folder.name}",
                                            f"Missing: {', '.join(missing)}")
                else:
                    results.fail_test(f"Skill frontmatter valid: {skill_folder.name}",
                                    "No frontmatter found (should start with ---)")


def test_save_command_references_sanity_check(results: TestResults):
    """Test: /save command should reference the sanity check script."""
    save_path = COMMANDS_DIR / "save.md"
    if save_path.exists():
        content = save_path.read_text(encoding="utf-8")
        if "sanity" in content.lower() and "check.py" in content:
            results.pass_test("Save command references sanity check")
        else:
            results.fail_test("Save command references sanity check",
                            "Expected reference to sanity/check.py")


def test_endsession_references_memory_files(results: TestResults):
    """Test: /endsession should reference both MEMORY.md and NOTES.md."""
    endsession_path = COMMANDS_DIR / "endsession.md"
    if endsession_path.exists():
        content = endsession_path.read_text(encoding="utf-8")
        has_memory = "MEMORY.md" in content
        has_notes_doc = "NOTES.md" in content
        if has_memory and has_notes_doc:
            results.pass_test("Endsession references both memories")
        else:
            missing = []
            if not has_memory:
                missing.append("MEMORY.md")
            if not has_notes_doc:
                missing.append("NOTES.md")
            results.fail_test("Endsession references both memories",
                            f"Missing references: {', '.join(missing)}")


def test_push_workspace_has_safety_checks(results: TestResults):
    """Test: /push-workspace should include safety warnings."""
    push_path = COMMANDS_DIR / "push-workspace.md"
    if push_path.exists():
        content = push_path.read_text(encoding="utf-8").lower()
        has_safety = "safety" in content or "never force push" in content
        has_secrets = "secret" in content or ".env" in content
        if has_safety and has_secrets:
            results.pass_test("Push command has safety checks")
        else:
            results.fail_test("Push command has safety checks",
                            "Missing safety warnings about force push or secrets")


def test_no_duplicate_command_names(results: TestResults):
    """Test: No duplicate command names should exist."""
    if not COMMANDS_DIR.exists():
        return

    names = []
    for cmd_file in COMMANDS_DIR.glob("*.md"):
        name = cmd_file.stem
        if name in names:
            results.fail_test(f"No duplicate commands", f"Duplicate found: {name}")
            results.add_bug(f"Duplicate command name: {name}")
        else:
            names.append(name)

    if len(names) == len(set(names)):
        results.pass_test("No duplicate command names")


def identify_edge_cases(results: TestResults):
    """Identify edge cases for the commands system."""

    # Edge case 1: What happens with very long command names?
    results.add_edge_case("Long command names: No validation for max length")

    # Edge case 2: Special characters in command names
    results.add_edge_case("Special characters in names: Underscores, numbers not tested")

    # Edge case 3: Empty frontmatter
    results.add_edge_case("Empty frontmatter: Skills with empty name/description")

    # Edge case 4: Commands referencing non-existent files
    results.add_edge_case("Broken references: Commands may reference missing files")

    # Edge case 5: Circular dependencies between commands
    results.add_edge_case("Circular deps: /save references sanity check, but what if sanity check fails?")

    # Edge case 6: Unicode in command content
    results.add_edge_case("Unicode content: Emoji and special chars in command descriptions")


def identify_potential_bugs(results: TestResults):
    """Identify potential bugs discovered during testing."""

    # Check for common issues

    # Bug 1: Check if any command references hardcoded paths that might not exist
    for cmd in EXPECTED_COMMANDS:
        cmd_path = COMMANDS_DIR / cmd
        if cmd_path.exists():
            content = cmd_path.read_text(encoding="utf-8")
            # Look for Windows paths
            windows_paths = re.findall(r"C:\\[^\s\"'`]+", content)
            for path in windows_paths:
                # Check if path exists (simplified check)
                results.add_bug(f"Hardcoded path in {cmd}: {path} (may not exist on other machines)")


def run_all_tests():
    """Run all tests and return results."""
    results = TestResults()

    print("\n" + "=" * 60)
    print("SLASH COMMAND STRUCTURE TESTS")
    print("=" * 60 + "\n")

    print("--- Directory Structure ---")
    test_commands_directory_exists(results)
    test_skills_directory_exists(results)

    print("\n--- Command File Existence ---")
    test_all_expected_commands_exist(results)

    print("\n--- Command Content Validation ---")
    test_command_files_not_empty(results)
    test_command_has_heading(results)
    test_command_naming_convention(results)

    print("\n--- Skill Validation ---")
    test_skills_have_skill_md(results)
    test_skill_has_frontmatter(results)

    print("\n--- Command-Specific Checks ---")
    test_save_command_references_sanity_check(results)
    test_endsession_references_memory_files(results)
    test_push_workspace_has_safety_checks(results)

    print("\n--- Consistency Checks ---")
    test_no_duplicate_command_names(results)

    print("\n--- Edge Case Identification ---")
    identify_edge_cases(results)

    print("\n--- Bug Hunting ---")
    identify_potential_bugs(results)

    print("\n" + "=" * 60)
    print(f"RESULTS: {results.passed} passed, {results.failed} failed")
    print("=" * 60)

    return results


if __name__ == "__main__":
    results = run_all_tests()

    if results.edge_cases:
        print("\n--- EDGE CASES IDENTIFIED ---")
        for ec in results.edge_cases:
            print(f"  - {ec}")

    if results.bugs:
        print("\n--- POTENTIAL BUGS ---")
        for bug in results.bugs:
            print(f"  - {bug}")

    if results.errors:
        print("\n--- FAILURES ---")
        for err in results.errors:
            print(f"  - {err}")
