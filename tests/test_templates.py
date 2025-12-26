"""
Tests for Agent Prompt Templates (team/templates.py)

This module tests the prompt templating system that creates
role-specific prompts for each specialist agent.

Test Categories:
1. Template Structure Tests
2. Template Formatting Tests
3. Edge Cases and Boundary Tests
"""
import pytest
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from team.templates import (
    AGENT_TEMPLATES,
    get_agent_template,
    format_agent_prompt,
)


# =============================================================================
# AGENT_TEMPLATES CONSTANT TESTS
# =============================================================================

class TestAgentTemplatesConstant:
    """Tests for the AGENT_TEMPLATES constant."""

    def test_should_contain_five_agent_templates(self):
        """Should contain templates for all 5 agents."""
        assert len(AGENT_TEMPLATES) == 5

    def test_should_have_frontend_dev_template(self):
        """Should have frontend-dev template."""
        assert "frontend-dev" in AGENT_TEMPLATES
        assert len(AGENT_TEMPLATES["frontend-dev"]) > 0

    def test_should_have_backend_dev_template(self):
        """Should have backend-dev template."""
        assert "backend-dev" in AGENT_TEMPLATES
        assert len(AGENT_TEMPLATES["backend-dev"]) > 0

    def test_should_have_devops_template(self):
        """Should have devops template."""
        assert "devops" in AGENT_TEMPLATES
        assert len(AGENT_TEMPLATES["devops"]) > 0

    def test_should_have_qa_tester_template(self):
        """Should have qa-tester template."""
        assert "qa-tester" in AGENT_TEMPLATES
        assert len(AGENT_TEMPLATES["qa-tester"]) > 0

    def test_should_have_security_reviewer_template(self):
        """Should have security-reviewer template."""
        assert "security-reviewer" in AGENT_TEMPLATES
        assert len(AGENT_TEMPLATES["security-reviewer"]) > 0


class TestTemplateStructure:
    """Tests for the structure of each template."""

    @pytest.fixture
    def all_agents(self):
        return ["frontend-dev", "backend-dev", "devops", "qa-tester", "security-reviewer"]

    def test_all_templates_should_have_task_header(self, all_agents):
        """All templates should have a task header section."""
        for agent in all_agents:
            template = AGENT_TEMPLATES[agent]
            assert "# Task for" in template, f"{agent} template missing task header"

    def test_all_templates_should_have_prompt_placeholder(self, all_agents):
        """All templates should have {prompt} placeholder."""
        for agent in all_agents:
            template = AGENT_TEMPLATES[agent]
            assert "{prompt}" in template, f"{agent} template missing prompt placeholder"

    def test_all_templates_should_have_project_placeholder(self, all_agents):
        """All templates should have {project} placeholder."""
        for agent in all_agents:
            template = AGENT_TEMPLATES[agent]
            assert "{project}" in template, f"{agent} template missing project placeholder"

    def test_all_templates_should_have_working_dir_placeholder(self, all_agents):
        """All templates should have {working_dir} placeholder."""
        for agent in all_agents:
            template = AGENT_TEMPLATES[agent]
            assert "{working_dir}" in template, f"{agent} template missing working_dir placeholder"

    def test_all_templates_should_have_instructions_section(self, all_agents):
        """All templates should have an instructions section."""
        for agent in all_agents:
            template = AGENT_TEMPLATES[agent]
            assert "## Instructions" in template, f"{agent} template missing instructions"

    def test_all_templates_should_have_constraints_section(self, all_agents):
        """All templates should have a constraints section."""
        for agent in all_agents:
            template = AGENT_TEMPLATES[agent]
            assert "## Constraints" in template, f"{agent} template missing constraints"

    def test_all_templates_should_reference_result_file(self, all_agents):
        """All templates should reference a result file path."""
        for agent in all_agents:
            template = AGENT_TEMPLATES[agent]
            assert "IHIM/team/results/" in template, f"{agent} template missing result file path"
            assert "-result.json" in template, f"{agent} template missing result file extension"


class TestTemplateContent:
    """Tests for specific content in each template."""

    def test_frontend_template_mentions_react(self):
        """Frontend template should mention React/frontend technologies."""
        template = AGENT_TEMPLATES["frontend-dev"]
        assert "React" in template or "frontend" in template.lower()

    def test_frontend_template_mentions_typescript(self):
        """Frontend template should mention TypeScript."""
        template = AGENT_TEMPLATES["frontend-dev"]
        assert "TypeScript" in template

    def test_backend_template_mentions_api(self):
        """Backend template should mention API/backend concerns."""
        template = AGENT_TEMPLATES["backend-dev"]
        assert "API" in template or "api" in template

    def test_backend_template_mentions_error_handling(self):
        """Backend template should mention error handling."""
        template = AGENT_TEMPLATES["backend-dev"]
        assert "error" in template.lower()

    def test_devops_template_mentions_docker(self):
        """DevOps template should mention Docker."""
        template = AGENT_TEMPLATES["devops"]
        assert "Docker" in template

    def test_devops_template_mentions_cicd(self):
        """DevOps template should mention CI/CD."""
        template = AGENT_TEMPLATES["devops"]
        assert "CI" in template or "CD" in template

    def test_qa_template_mentions_testing(self):
        """QA template should mention testing."""
        template = AGENT_TEMPLATES["qa-tester"]
        assert "test" in template.lower()

    def test_qa_template_mentions_edge_cases(self):
        """QA template should mention edge cases."""
        template = AGENT_TEMPLATES["qa-tester"]
        assert "edge case" in template.lower()

    def test_security_template_mentions_owasp(self):
        """Security template should mention OWASP."""
        template = AGENT_TEMPLATES["security-reviewer"]
        assert "OWASP" in template

    def test_security_template_is_read_only(self):
        """Security template should emphasize read-only review."""
        template = AGENT_TEMPLATES["security-reviewer"]
        assert "READ ONLY" in template or "REVIEW ONLY" in template


# =============================================================================
# GET_AGENT_TEMPLATE FUNCTION TESTS
# =============================================================================

class TestGetAgentTemplate:
    """Tests for the get_agent_template function."""

    def test_should_return_correct_template(self):
        """Should return the correct template for each agent."""
        for agent_name in AGENT_TEMPLATES.keys():
            template = get_agent_template(agent_name)
            assert template == AGENT_TEMPLATES[agent_name]

    def test_should_return_empty_string_for_unknown_agent(self):
        """Should return empty string for unknown agent."""
        template = get_agent_template("unknown-agent")
        assert template == ""

    def test_should_handle_none_agent_name(self):
        """Should handle None agent name."""
        template = get_agent_template(None)
        assert template == ""

    def test_should_handle_empty_string_agent_name(self):
        """Should handle empty string agent name."""
        template = get_agent_template("")
        assert template == ""


# =============================================================================
# FORMAT_AGENT_PROMPT FUNCTION TESTS
# =============================================================================

class TestFormatAgentPrompt:
    """Tests for the format_agent_prompt function."""

    def test_should_return_formatted_prompt(self):
        """Should return a formatted prompt string."""
        result = format_agent_prompt(
            agent_name="frontend-dev",
            prompt="Build a button",
            project="TestProject",
            working_dir="/test/path"
        )

        assert isinstance(result, str)
        assert len(result) > 0

    def test_should_include_prompt_in_output(self):
        """Should include the prompt in the output."""
        result = format_agent_prompt(
            agent_name="frontend-dev",
            prompt="Build a React component",
            project="TestProject",
            working_dir="/test/path"
        )

        assert "Build a React component" in result

    def test_should_include_project_in_output(self):
        """Should include the project name in the output."""
        result = format_agent_prompt(
            agent_name="backend-dev",
            prompt="Test",
            project="MyAwesomeProject",
            working_dir="/test"
        )

        assert "MyAwesomeProject" in result

    def test_should_include_working_dir_in_output(self):
        """Should include the working directory in the output."""
        result = format_agent_prompt(
            agent_name="devops",
            prompt="Test",
            project="Project",
            working_dir="/custom/working/directory"
        )

        assert "/custom/working/directory" in result

    def test_should_return_raw_prompt_for_unknown_agent(self):
        """Should return raw prompt when agent template not found."""
        result = format_agent_prompt(
            agent_name="unknown-agent",
            prompt="Original prompt",
            project="Project",
            working_dir="/path"
        )

        assert result == "Original prompt"

    def test_should_format_all_five_agents(self):
        """Should successfully format prompts for all 5 agents."""
        agents = ["frontend-dev", "backend-dev", "devops", "qa-tester", "security-reviewer"]

        for agent in agents:
            result = format_agent_prompt(
                agent_name=agent,
                prompt="Test task",
                project="TestProject",
                working_dir="/test"
            )

            assert "Test task" in result
            assert "TestProject" in result
            assert "/test" in result


class TestFormatAgentPromptEdgeCases:
    """Tests for edge cases in format_agent_prompt."""

    def test_should_handle_empty_prompt(self):
        """Should handle empty prompt string."""
        result = format_agent_prompt(
            agent_name="frontend-dev",
            prompt="",
            project="Project",
            working_dir="/path"
        )

        # Should still have the template structure
        assert "# Task for" in result

    def test_should_handle_multiline_prompt(self):
        """Should handle multiline prompt."""
        multiline = "Line 1\nLine 2\nLine 3"
        result = format_agent_prompt(
            agent_name="backend-dev",
            prompt=multiline,
            project="Project",
            working_dir="/path"
        )

        assert "Line 1\nLine 2\nLine 3" in result

    def test_should_handle_special_characters_in_prompt(self):
        """Should handle special characters in prompt."""
        special = "Build {feature} with <tags> & 'quotes'"
        result = format_agent_prompt(
            agent_name="qa-tester",
            prompt=special,
            project="Project",
            working_dir="/path"
        )

        assert special in result

    def test_should_handle_unicode_in_prompt(self):
        """Should handle unicode in prompt."""
        unicode_prompt = "Build \U0001F680 rocket feature \u3053\u3093\u306b\u3061\u306f"
        result = format_agent_prompt(
            agent_name="frontend-dev",
            prompt=unicode_prompt,
            project="Project",
            working_dir="/path"
        )

        assert unicode_prompt in result

    def test_should_handle_very_long_prompt(self):
        """Should handle very long prompts."""
        long_prompt = "x" * 10000
        result = format_agent_prompt(
            agent_name="backend-dev",
            prompt=long_prompt,
            project="Project",
            working_dir="/path"
        )

        assert long_prompt in result

    def test_should_handle_windows_path(self):
        """Should handle Windows-style paths."""
        result = format_agent_prompt(
            agent_name="devops",
            prompt="Test",
            project="Project",
            working_dir="C:\\Users\\test\\project"
        )

        assert "C:\\Users\\test\\project" in result

    def test_should_handle_unix_path(self):
        """Should handle Unix-style paths."""
        result = format_agent_prompt(
            agent_name="security-reviewer",
            prompt="Test",
            project="Project",
            working_dir="/home/user/project"
        )

        assert "/home/user/project" in result

    def test_should_handle_path_with_spaces(self):
        """Should handle paths with spaces."""
        result = format_agent_prompt(
            agent_name="qa-tester",
            prompt="Test",
            project="My Project",
            working_dir="/path/with spaces/project"
        )

        assert "My Project" in result
        assert "/path/with spaces/project" in result


class TestTemplateConsistency:
    """Tests for consistency across all templates."""

    @pytest.fixture
    def formatted_prompts(self):
        """Generate formatted prompts for all agents."""
        agents = ["frontend-dev", "backend-dev", "devops", "qa-tester", "security-reviewer"]
        return {
            agent: format_agent_prompt(
                agent_name=agent,
                prompt="Common test task",
                project="TestProject",
                working_dir="/common/path"
            )
            for agent in agents
        }

    def test_all_prompts_should_contain_common_task(self, formatted_prompts):
        """All formatted prompts should contain the common task."""
        for agent, prompt in formatted_prompts.items():
            assert "Common test task" in prompt, f"{agent} missing task"

    def test_all_prompts_should_contain_project(self, formatted_prompts):
        """All formatted prompts should contain the project name."""
        for agent, prompt in formatted_prompts.items():
            assert "TestProject" in prompt, f"{agent} missing project"

    def test_all_prompts_should_contain_working_dir(self, formatted_prompts):
        """All formatted prompts should contain the working directory."""
        for agent, prompt in formatted_prompts.items():
            assert "/common/path" in prompt, f"{agent} missing working_dir"

    def test_all_prompts_should_have_unique_result_paths(self, formatted_prompts):
        """Each agent should have a unique result file path."""
        result_paths = set()
        for agent, prompt in formatted_prompts.items():
            # Extract result path
            if f"{agent}-result.json" in prompt:
                result_paths.add(f"{agent}-result.json")

        # Should have 5 unique result paths
        assert len(result_paths) == 5

    def test_all_prompts_should_mention_agent_name(self, formatted_prompts):
        """Each prompt should mention the agent's role."""
        role_mentions = {
            "frontend-dev": ["Frontend Dev", "frontend"],
            "backend-dev": ["Backend Dev", "backend"],
            "devops": ["DevOps", "devops"],
            "qa-tester": ["QA Tester", "QA", "qa"],
            "security-reviewer": ["Security Reviewer", "Security", "security"],
        }

        for agent, prompt in formatted_prompts.items():
            mentions = role_mentions[agent]
            found = any(m in prompt for m in mentions)
            assert found, f"{agent} should mention its role"
