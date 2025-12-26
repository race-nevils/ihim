"""
Tests for the Smart Router (team/router.py)

This module tests the prompt routing logic that morphs 1 user prompt
into 5 tailored prompts for each specialist agent.

Test Categories:
1. Route Prompt Function Tests
2. Prompt Analysis Tests
3. Agent Selection Tests
4. Edge Cases and Boundary Tests
"""
import pytest
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from team.router import (
    route_prompt,
    get_agents_for_task,
    analyze_prompt,
    SOFTWARE_DEV_AGENTS,
)


# =============================================================================
# ROUTE PROMPT FUNCTION TESTS
# =============================================================================

class TestRoutePromptFunction:
    """Tests for the route_prompt function."""

    def test_should_return_dict(self):
        """route_prompt should return a dictionary."""
        result = route_prompt("Build a feature")
        assert isinstance(result, dict)

    def test_should_return_prompts_for_all_default_agents(self):
        """Should return prompts for all 5 default agents."""
        result = route_prompt("Build a feature")

        assert len(result) == 5
        assert "frontend-dev" in result
        assert "backend-dev" in result
        assert "devops" in result
        assert "qa-tester" in result
        assert "security-reviewer" in result

    def test_should_include_original_prompt_in_each_agent_prompt(self):
        """Each agent prompt should contain the original prompt."""
        original = "Build a waitlist feature"
        result = route_prompt(original)

        for agent, prompt in result.items():
            assert original in prompt, f"{agent} prompt should contain original"

    def test_should_include_project_name_in_prompts(self):
        """Each agent prompt should contain the project name."""
        result = route_prompt("Build a feature", project="MyProject")

        for agent, prompt in result.items():
            assert "MyProject" in prompt, f"{agent} prompt should contain project name"

    def test_should_include_working_dir_in_prompts(self):
        """Each agent prompt should contain the working directory."""
        working_dir = "C:/test/path"
        result = route_prompt("Build a feature", working_dir=working_dir)

        for agent, prompt in result.items():
            assert working_dir in prompt, f"{agent} prompt should contain working dir"

    def test_should_use_default_working_dir_if_not_specified(self):
        """Should use default workspace path if working_dir not specified."""
        result = route_prompt("Build a feature")

        # Default is C:/Users/<user>/workspace (may use backslashes on Windows)
        for agent, prompt in result.items():
            # Check for either slash style
            assert "Users" in prompt and "<user>" in prompt and "workspace" in prompt

    def test_should_route_to_specific_agents_when_specified(self):
        """Should only route to specified agents."""
        agents = ["frontend-dev", "backend-dev"]
        result = route_prompt("Build a feature", agents=agents)

        assert len(result) == 2
        assert "frontend-dev" in result
        assert "backend-dev" in result
        assert "devops" not in result

    def test_should_route_to_single_agent(self):
        """Should handle routing to a single agent."""
        result = route_prompt("Build a feature", agents=["qa-tester"])

        assert len(result) == 1
        assert "qa-tester" in result


class TestRoutePromptWithDifferentPrompts:
    """Tests for route_prompt with various prompt types."""

    def test_should_handle_empty_prompt(self):
        """Should handle empty prompt string."""
        result = route_prompt("")

        assert len(result) == 5
        # Each agent should still get a formatted prompt (even if task is empty)
        for agent, prompt in result.items():
            assert "Task for" in prompt

    def test_should_handle_very_long_prompt(self):
        """Should handle very long prompt strings."""
        long_prompt = "Build a feature " * 1000
        result = route_prompt(long_prompt)

        assert len(result) == 5
        for agent, prompt in result.items():
            assert long_prompt in prompt

    def test_should_handle_multiline_prompt(self):
        """Should handle multiline prompts."""
        multiline = "Build a feature\nWith these requirements:\n- Req 1\n- Req 2"
        result = route_prompt(multiline)

        assert len(result) == 5
        for agent, prompt in result.items():
            assert multiline in prompt

    def test_should_handle_special_characters(self):
        """Should handle special characters in prompt."""
        special = "Build {feature} with <tags> & 'quotes' \"double\""
        result = route_prompt(special)

        for agent, prompt in result.items():
            assert special in prompt

    def test_should_handle_unicode_prompt(self):
        """Should handle unicode characters in prompt."""
        unicode_prompt = "Build feature with emoji \U0001F680 and Japanese \u3053\u3093\u306b\u3061\u306f"
        result = route_prompt(unicode_prompt)

        for agent, prompt in result.items():
            assert unicode_prompt in prompt


# =============================================================================
# ANALYZE PROMPT TESTS
# =============================================================================

class TestAnalyzePrompt:
    """Tests for the analyze_prompt function."""

    def test_should_return_dict_with_required_keys(self):
        """Should return dict with agents_needed and complexity."""
        result = analyze_prompt("Build a feature")

        assert isinstance(result, dict)
        assert "agents_needed" in result
        assert "complexity" in result

    def test_should_detect_frontend_keywords(self):
        """Should detect frontend-related keywords."""
        prompts = [
            "Build a React component",
            "Create a UI for the dashboard",
            "Add a button to the form",
            "Style the page with CSS",
        ]

        for prompt in prompts:
            result = analyze_prompt(prompt)
            assert "frontend-dev" in result["agents_needed"], f"Should detect frontend in: {prompt}"

    def test_should_detect_backend_keywords(self):
        """Should detect backend-related keywords."""
        prompts = [
            "Create an API endpoint",
            "Set up the database schema",
            "Add authentication to the server",
            "Implement the route handler",
        ]

        for prompt in prompts:
            result = analyze_prompt(prompt)
            assert "backend-dev" in result["agents_needed"], f"Should detect backend in: {prompt}"

    def test_should_detect_devops_keywords(self):
        """Should detect DevOps-related keywords."""
        prompts = [
            "Set up Docker containers",
            "Configure the CI/CD pipeline",
            "Deploy to production",
            "Update the build configuration",
        ]

        for prompt in prompts:
            result = analyze_prompt(prompt)
            assert "devops" in result["agents_needed"], f"Should detect devops in: {prompt}"

    def test_should_detect_qa_keywords(self):
        """Should detect QA-related keywords."""
        prompts = [
            "Write tests for the feature",
            "Find and fix the bug",
            "Improve test coverage",
            "Identify edge cases",
        ]

        for prompt in prompts:
            result = analyze_prompt(prompt)
            assert "qa-tester" in result["agents_needed"], f"Should detect qa in: {prompt}"

    def test_should_detect_security_keywords(self):
        """Should detect security-related keywords."""
        prompts = [
            "Review security of the auth system",
            "Check for vulnerabilities",
            "Secure the password handling",
            "Review token management",
        ]

        for prompt in prompts:
            result = analyze_prompt(prompt)
            assert "security-reviewer" in result["agents_needed"], f"Should detect security in: {prompt}"

    def test_should_detect_multiple_agent_types(self):
        """Should detect when multiple agent types are needed."""
        prompt = "Build a React UI with an API endpoint and tests"
        result = analyze_prompt(prompt)

        assert "frontend-dev" in result["agents_needed"]
        assert "backend-dev" in result["agents_needed"]
        assert "qa-tester" in result["agents_needed"]

    def test_should_return_all_agents_when_no_keywords_detected(self):
        """Should return all agents when no specific keywords are found."""
        prompt = "Do something interesting"
        result = analyze_prompt(prompt)

        assert result["agents_needed"] == SOFTWARE_DEV_AGENTS

    def test_should_be_case_insensitive(self):
        """Keyword detection should be case-insensitive."""
        prompts = [
            "BUILD A REACT COMPONENT",
            "Create an API Endpoint",
            "Set up DOCKER containers",
        ]

        for prompt in prompts:
            result = analyze_prompt(prompt)
            assert len(result["agents_needed"]) > 0


# =============================================================================
# GET AGENTS FOR TASK TESTS
# =============================================================================

class TestGetAgentsForTask:
    """Tests for the get_agents_for_task function."""

    def test_should_return_list(self):
        """Should return a list of agent names."""
        result = get_agents_for_task("Build a feature")
        assert isinstance(result, list)

    def test_should_return_all_agents_by_default(self):
        """Currently returns all agents (future: smart selection)."""
        result = get_agents_for_task("Build a feature")
        assert result == SOFTWARE_DEV_AGENTS

    def test_should_handle_empty_prompt(self):
        """Should handle empty prompt."""
        result = get_agents_for_task("")
        assert len(result) == 5


# =============================================================================
# SOFTWARE_DEV_AGENTS CONSTANT TESTS
# =============================================================================

class TestSoftwareDevAgentsConstant:
    """Tests for the SOFTWARE_DEV_AGENTS constant."""

    def test_should_contain_five_agents(self):
        """Should contain exactly 5 agents."""
        assert len(SOFTWARE_DEV_AGENTS) == 5

    def test_should_contain_expected_agents(self):
        """Should contain all expected agent types."""
        expected = [
            "frontend-dev",
            "backend-dev",
            "devops",
            "qa-tester",
            "security-reviewer",
        ]
        assert SOFTWARE_DEV_AGENTS == expected

    def test_agents_should_be_strings(self):
        """All agent names should be strings."""
        for agent in SOFTWARE_DEV_AGENTS:
            assert isinstance(agent, str)

    def test_agent_names_should_be_lowercase_with_hyphens(self):
        """Agent names should follow the kebab-case convention."""
        for agent in SOFTWARE_DEV_AGENTS:
            assert agent == agent.lower()
            assert "_" not in agent  # No underscores
            assert " " not in agent  # No spaces


# =============================================================================
# EDGE CASES AND BOUNDARY TESTS
# =============================================================================

class TestRouterEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_should_handle_none_agents_list(self):
        """Should handle None agents list (use default)."""
        result = route_prompt("Build a feature", agents=None)
        assert len(result) == 5

    def test_should_handle_empty_agents_list(self):
        """Should handle empty agents list."""
        result = route_prompt("Build a feature", agents=[])
        assert len(result) == 0

    def test_should_handle_invalid_agent_name(self):
        """Should handle unknown agent name gracefully."""
        # Unknown agent gets empty template
        result = route_prompt("Build a feature", agents=["unknown-agent"])
        assert "unknown-agent" in result
        # The prompt should just be the original (no template found)

    def test_should_handle_mixed_valid_invalid_agents(self):
        """Should handle mix of valid and invalid agent names."""
        agents = ["frontend-dev", "unknown-agent", "backend-dev"]
        result = route_prompt("Build a feature", agents=agents)

        assert len(result) == 3
        assert "frontend-dev" in result
        assert "unknown-agent" in result
        assert "backend-dev" in result

    def test_should_handle_duplicate_agents(self):
        """Should handle duplicate agent names in list."""
        agents = ["frontend-dev", "frontend-dev", "backend-dev"]
        result = route_prompt("Build a feature", agents=agents)

        # Dict keys are unique, so duplicates are overwritten
        assert len(result) == 2  # Only unique agents

    def test_should_handle_whitespace_in_prompt(self):
        """Should handle prompts with excessive whitespace."""
        prompt = "   Build   a   feature   "
        result = route_prompt(prompt)

        # Prompt should be preserved as-is
        for agent, agent_prompt in result.items():
            assert prompt in agent_prompt

    def test_should_handle_prompt_with_newlines_only(self):
        """Should handle prompt with only newlines."""
        prompt = "\n\n\n"
        result = route_prompt(prompt)

        assert len(result) == 5
