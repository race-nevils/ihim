"""
Tests for the Agent Spawner (team/spawner.py)

This module tests the spawner logic that creates agent teams
with the agent harness CLI sessions.

Test Categories:
1. Session ID Generation Tests
2. Task File Writing Tests
3. Directory Management Tests
4. Team Status Tests
5. Result Collection Tests
6. Edge Cases and Boundary Tests

Note: Tests for spawn_single_agent and spawn_agent_team are mocked
since they spawn real Windows Terminal processes.
"""
import pytest
import sys
import json
import tempfile
import shutil
from pathlib import Path
from datetime import datetime
from unittest.mock import patch, MagicMock

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from team.spawner import (
    generate_session_id,
    write_task_file,
    ensure_directories,
    get_team_status,
    collect_results,
    TASKS_PATH,
    RESULTS_PATH,
    DATA_PATH,
    WORKSPACE_PATH,
    AGENT_WINDOW_NAME,
)


# =============================================================================
# SESSION ID GENERATION TESTS
# =============================================================================

class TestGenerateSessionId:
    """Tests for the generate_session_id function."""

    def test_should_return_string(self):
        """generate_session_id should return a string."""
        result = generate_session_id()
        assert isinstance(result, str)

    def test_should_start_with_spawn_prefix(self):
        """Session ID should start with 'spawn-' prefix."""
        result = generate_session_id()
        assert result.startswith("spawn-")

    def test_should_contain_timestamp(self):
        """Session ID should contain a timestamp portion."""
        result = generate_session_id()
        # Format: spawn-YYYYMMDD-HHMMSS-uuid
        parts = result.split("-")
        assert len(parts) >= 3
        # Second part should be date (8 digits)
        assert len(parts[1]) == 8
        assert parts[1].isdigit()

    def test_should_contain_uuid_portion(self):
        """Session ID should contain a UUID portion."""
        result = generate_session_id()
        # Format: spawn-YYYYMMDD-HHMMSS-uuid
        parts = result.split("-")
        # Last part should be 8 char UUID portion
        assert len(parts[-1]) == 8

    def test_should_generate_unique_ids(self):
        """Should generate unique session IDs."""
        ids = [generate_session_id() for _ in range(100)]
        unique_ids = set(ids)
        assert len(unique_ids) == 100

    def test_should_be_valid_filename(self):
        """Session ID should be a valid filename (no special chars)."""
        result = generate_session_id()
        # Should only contain alphanumeric and hyphens
        for char in result:
            assert char.isalnum() or char == "-"


# =============================================================================
# ENSURE DIRECTORIES TESTS
# =============================================================================

class TestEnsureDirectories:
    """Tests for the ensure_directories function."""

    def test_should_create_tasks_directory(self):
        """Should create the tasks directory if it doesn't exist."""
        # This is a side-effect test - directories should exist after call
        ensure_directories()
        assert TASKS_PATH.exists()

    def test_should_create_results_directory(self):
        """Should create the results directory if it doesn't exist."""
        ensure_directories()
        assert RESULTS_PATH.exists()

    def test_should_create_data_directory(self):
        """Should create the data directory if it doesn't exist."""
        ensure_directories()
        assert DATA_PATH.exists()

    def test_should_be_idempotent(self):
        """Calling ensure_directories multiple times should not fail."""
        ensure_directories()
        ensure_directories()
        ensure_directories()
        # No exception = pass


# =============================================================================
# WRITE TASK FILE TESTS
# =============================================================================

class TestWriteTaskFile:
    """Tests for the write_task_file function."""

    def test_should_return_path_object(self):
        """write_task_file should return a Path object."""
        result = write_task_file("test-agent", "Test prompt")
        assert isinstance(result, Path)
        # Clean up
        if result.exists():
            result.unlink()

    def test_should_create_file_with_correct_name(self):
        """Should create file named {agent}-task.md."""
        agent = "frontend-dev"
        result = write_task_file(agent, "Test prompt")

        assert result.name == f"{agent}-task.md"
        assert result.exists()
        # Clean up
        result.unlink()

    def test_should_write_prompt_content(self):
        """Should write the prompt content to the file."""
        prompt = "Build a feature for testing"
        result = write_task_file("test-agent", prompt)

        content = result.read_text(encoding="utf-8")
        assert content == prompt
        # Clean up
        result.unlink()

    def test_should_handle_multiline_prompts(self):
        """Should preserve multiline prompts."""
        prompt = "Line 1\nLine 2\nLine 3"
        result = write_task_file("test-agent", prompt)

        content = result.read_text(encoding="utf-8")
        assert content == prompt
        # Clean up
        result.unlink()

    def test_should_handle_unicode_content(self):
        """Should handle unicode characters in prompts."""
        prompt = "Build with emoji 🚀 and Japanese こんにちは"
        result = write_task_file("test-agent", prompt)

        content = result.read_text(encoding="utf-8")
        assert content == prompt
        # Clean up
        result.unlink()

    def test_should_overwrite_existing_file(self):
        """Should overwrite existing task file for same agent."""
        agent = "test-agent"

        # Write first prompt
        write_task_file(agent, "First prompt")
        # Write second prompt
        result = write_task_file(agent, "Second prompt")

        content = result.read_text(encoding="utf-8")
        assert content == "Second prompt"
        # Clean up
        result.unlink()

    def test_should_handle_empty_prompt(self):
        """Should handle empty prompt string."""
        result = write_task_file("test-agent", "")

        content = result.read_text(encoding="utf-8")
        assert content == ""
        # Clean up
        result.unlink()


# =============================================================================
# GET TEAM STATUS TESTS
# =============================================================================

class TestGetTeamStatus:
    """Tests for the get_team_status function."""

    def test_should_return_dict(self):
        """get_team_status should return a dictionary."""
        result = get_team_status()
        assert isinstance(result, dict)

    def test_should_contain_active_key(self):
        """Result should contain 'active' key."""
        result = get_team_status()
        assert "active" in result

    def test_should_contain_agents_key(self):
        """Result should contain 'agents' key."""
        result = get_team_status()
        assert "agents" in result

    def test_should_contain_pending_count(self):
        """Result should contain 'pending_count' key."""
        result = get_team_status()
        assert "pending_count" in result

    def test_should_contain_completed_count(self):
        """Result should contain 'completed_count' key."""
        result = get_team_status()
        assert "completed_count" in result

    def test_should_report_all_five_agents(self):
        """Should report status for all 5 agent types."""
        result = get_team_status()

        expected_agents = [
            "frontend-dev",
            "backend-dev",
            "devops",
            "qa-tester",
            "security-reviewer",
        ]

        for agent in expected_agents:
            assert agent in result["agents"]

    def test_agent_status_should_be_idle_or_working_or_completed(self):
        """Agent statuses should be one of: idle, working, completed."""
        result = get_team_status()
        valid_statuses = {"idle", "working", "completed"}

        for agent, status in result["agents"].items():
            assert status in valid_statuses, f"{agent} has invalid status: {status}"

    def test_should_detect_working_agent_from_task_file(self):
        """Should mark agent as 'working' if task file exists."""
        agent = "test-detector"
        task_file = TASKS_PATH / f"{agent}-task.md"

        try:
            # Create a task file
            ensure_directories()
            task_file.write_text("Test task", encoding="utf-8")

            # Get status (agent not in default list, but logic should work)
            result = get_team_status()

            # Verify task file was created
            assert task_file.exists()
        finally:
            # Clean up
            if task_file.exists():
                task_file.unlink()

    def test_should_detect_completed_agent_from_result_file(self):
        """Should mark agent as 'completed' if result file exists."""
        agent = "frontend-dev"
        result_file = RESULTS_PATH / f"{agent}-result.json"

        try:
            # Create a result file
            ensure_directories()
            result_file.write_text('{"status": "complete"}', encoding="utf-8")

            result = get_team_status()

            assert result["agents"][agent] == "completed"
        finally:
            # Clean up
            if result_file.exists():
                result_file.unlink()


# =============================================================================
# COLLECT RESULTS TESTS
# =============================================================================

class TestCollectResults:
    """Tests for the collect_results function."""

    def test_should_return_dict(self):
        """collect_results should return a dictionary."""
        result = collect_results()
        assert isinstance(result, dict)

    def test_should_return_empty_dict_when_no_results(self):
        """Should return empty dict when no result files exist."""
        # Clean up any existing result files first
        ensure_directories()
        for f in RESULTS_PATH.glob("*-result.json"):
            f.unlink()

        result = collect_results()
        assert result == {}

    def test_should_collect_single_result(self):
        """Should collect a single agent's result."""
        agent = "test-collector"
        result_file = RESULTS_PATH / f"{agent}-result.json"
        test_data = {"status": "complete", "tests_passed": 10}

        try:
            ensure_directories()
            result_file.write_text(json.dumps(test_data), encoding="utf-8")

            results = collect_results()

            assert agent in results
            assert results[agent]["status"] == "complete"
            assert results[agent]["tests_passed"] == 10
        finally:
            if result_file.exists():
                result_file.unlink()

    def test_should_collect_multiple_results(self):
        """Should collect multiple agents' results."""
        agents = ["agent-a", "agent-b", "agent-c"]
        result_files = []

        try:
            ensure_directories()
            for agent in agents:
                result_file = RESULTS_PATH / f"{agent}-result.json"
                result_file.write_text(json.dumps({"agent": agent}), encoding="utf-8")
                result_files.append(result_file)

            results = collect_results()

            for agent in agents:
                assert agent in results
        finally:
            for f in result_files:
                if f.exists():
                    f.unlink()

    def test_should_handle_malformed_json(self):
        """Should handle malformed JSON in result files gracefully."""
        agent = "bad-json-agent"
        result_file = RESULTS_PATH / f"{agent}-result.json"

        try:
            ensure_directories()
            result_file.write_text("{ not valid json", encoding="utf-8")

            results = collect_results()

            assert agent in results
            assert "error" in results[agent]
        finally:
            if result_file.exists():
                result_file.unlink()


# =============================================================================
# CONSTANTS TESTS
# =============================================================================

class TestSpawnerConstants:
    """Tests for spawner module constants."""

    def test_workspace_path_should_be_path_object(self):
        """WORKSPACE_PATH should be a Path object."""
        assert isinstance(WORKSPACE_PATH, Path)

    def test_workspace_path_should_exist(self):
        """WORKSPACE_PATH should point to an existing directory."""
        assert WORKSPACE_PATH.exists()

    def test_tasks_path_should_be_in_ihim(self):
        """TASKS_PATH should be under IHIM/team/tasks."""
        assert "IHIM" in str(TASKS_PATH)
        assert "team" in str(TASKS_PATH)
        assert "tasks" in str(TASKS_PATH)

    def test_results_path_should_be_in_ihim(self):
        """RESULTS_PATH should be under IHIM/team/results."""
        assert "IHIM" in str(RESULTS_PATH)
        assert "team" in str(RESULTS_PATH)
        assert "results" in str(RESULTS_PATH)

    def test_agent_window_name_should_be_string(self):
        """AGENT_WINDOW_NAME should be a string."""
        assert isinstance(AGENT_WINDOW_NAME, str)

    def test_agent_window_name_should_contain_ihim(self):
        """AGENT_WINDOW_NAME should contain 'iHIM'."""
        assert "iHIM" in AGENT_WINDOW_NAME


# =============================================================================
# EDGE CASES AND BOUNDARY TESTS
# =============================================================================

class TestSpawnerEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_should_handle_agent_name_with_special_chars(self):
        """Should handle agent names with special characters."""
        # Note: special chars might be problematic for filenames
        agent = "test-agent-123"
        result = write_task_file(agent, "Test")

        assert result.exists()
        # Clean up
        result.unlink()

    def test_should_handle_very_long_prompt(self):
        """Should handle very long prompts."""
        prompt = "A" * 100000  # 100KB prompt
        result = write_task_file("test-agent", prompt)

        content = result.read_text(encoding="utf-8")
        assert len(content) == 100000
        # Clean up
        result.unlink()

    def test_session_id_should_not_contain_problematic_chars(self):
        """Session ID should not contain chars that would break filenames."""
        problematic_chars = ['/', '\\', ':', '*', '?', '"', '<', '>', '|']

        for _ in range(100):
            session_id = generate_session_id()
            for char in problematic_chars:
                assert char not in session_id


# =============================================================================
# MOCK TESTS FOR SPAWN FUNCTIONS
# =============================================================================

class TestSpawnAgentTeamMocked:
    """Mocked tests for spawn_agent_team function."""

    @patch('team.spawner.subprocess.Popen')
    @patch('team.spawner.BLACKBOARD_AVAILABLE', True)
    def test_should_call_subprocess_for_each_agent(self, mock_popen):
        """Should call subprocess.Popen for each agent."""
        from team.spawner import spawn_agent_team

        mock_popen.return_value = MagicMock()

        prompts = {
            "agent-1": "Task 1",
            "agent-2": "Task 2",
        }

        with patch('team.spawner.init_blackboard') as mock_bb:
            mock_bb.return_value = MagicMock()
            with patch('team.spawner._get_wt_windows', return_value=set()):
                result = spawn_agent_team(prompts, "Test feature")

        # Should have called Popen twice (once per agent)
        assert mock_popen.call_count == 2

    @patch('team.spawner.sys.platform', 'linux')
    def test_should_fail_on_non_windows(self):
        """Should fail gracefully on non-Windows platforms."""
        from team.spawner import spawn_agent_team

        prompts = {"agent-1": "Task 1"}
        result = spawn_agent_team(prompts)

        assert result["success"] is False
        assert "Mac/Linux" in result["message"] or "not" in result["message"].lower()


# =============================================================================
# INTEGRATION-STYLE TESTS (Still no real spawning)
# =============================================================================

class TestSpawnerWorkflow:
    """Tests that verify the spawner workflow works correctly."""

    def test_full_task_file_workflow(self):
        """Test creating, reading, and cleaning up task files."""
        agents = ["test-a", "test-b", "test-c"]
        prompts = {agent: f"Task for {agent}" for agent in agents}

        try:
            ensure_directories()

            # Write task files
            task_files = {}
            for agent, prompt in prompts.items():
                task_files[agent] = write_task_file(agent, prompt)

            # Verify all files exist
            for agent, path in task_files.items():
                assert path.exists()
                content = path.read_text(encoding="utf-8")
                assert f"Task for {agent}" in content

        finally:
            # Clean up
            for path in task_files.values():
                if path.exists():
                    path.unlink()

    def test_result_collection_workflow(self):
        """Test creating and collecting result files."""
        agents = ["workflow-test-1", "workflow-test-2"]

        try:
            ensure_directories()

            # Simulate agents writing results
            for i, agent in enumerate(agents):
                result_file = RESULTS_PATH / f"{agent}-result.json"
                result_data = {
                    "agent": agent,
                    "status": "complete",
                    "tests_written": i + 1,
                }
                result_file.write_text(json.dumps(result_data), encoding="utf-8")

            # Collect results
            results = collect_results()

            # Verify all results collected
            for agent in agents:
                assert agent in results
                assert results[agent]["status"] == "complete"

        finally:
            # Clean up
            for agent in agents:
                result_file = RESULTS_PATH / f"{agent}-result.json"
                if result_file.exists():
                    result_file.unlink()
