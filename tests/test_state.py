"""
Tests for Team State Management (team/state.py)

This module tests the TeamState dataclass and related functions
that track the state of the agent team.

Test Categories:
1. TeamState Dataclass Tests
2. State Persistence Tests
3. State Transition Tests
4. Edge Cases and Boundary Tests
"""
import pytest
import sys
import json
from pathlib import Path
from datetime import datetime
import time

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from team.state import (
    TeamState,
    AgentStatus,
    get_team_state,
    reset_team_state,
    STATE_FILE,
    RESULTS_PATH,
)


@pytest.fixture(autouse=True)
def clean_state():
    """Clean up state files before and after each test."""
    # Setup: Reset state
    reset_team_state()
    yield
    # Teardown: Reset state
    reset_team_state()


# =============================================================================
# TEAMSTATE DATACLASS TESTS
# =============================================================================

class TestTeamStateDataclass:
    """Tests for the TeamState dataclass."""

    def test_should_have_default_values(self):
        """TeamState should have sensible defaults."""
        state = TeamState()

        assert state.active is False
        assert state.spawned_at is None
        assert state.collapsed_at is None
        assert state.original_prompt is None
        assert state.project is None
        assert state.agents == {}

    def test_should_initialize_agents_to_empty_dict(self):
        """agents should be empty dict if not provided."""
        state = TeamState()
        assert state.agents == {}
        assert isinstance(state.agents, dict)

    def test_should_accept_all_parameters(self):
        """Should accept all parameters in constructor."""
        state = TeamState(
            active=True,
            spawned_at="2025-01-01T00:00:00",
            collapsed_at="2025-01-01T01:00:00",
            original_prompt="Test prompt",
            project="TestProject",
            agents={"agent1": {"status": "working"}}
        )

        assert state.active is True
        assert state.spawned_at == "2025-01-01T00:00:00"
        assert state.collapsed_at == "2025-01-01T01:00:00"
        assert state.original_prompt == "Test prompt"
        assert state.project == "TestProject"
        assert "agent1" in state.agents


class TestTeamStatePersistence:
    """Tests for state save/load functionality."""

    def test_save_should_create_file(self):
        """save() should create the state file."""
        state = TeamState(active=True)
        state.save()

        assert STATE_FILE.exists()

    def test_save_should_write_valid_json(self):
        """save() should write valid JSON to file."""
        state = TeamState(active=True, project="TestProject")
        state.save()

        content = STATE_FILE.read_text(encoding="utf-8")
        data = json.loads(content)  # Should not raise

        assert data["active"] is True
        assert data["project"] == "TestProject"

    def test_load_should_return_teamstate(self):
        """load() should return a TeamState instance."""
        state = TeamState.load()
        assert isinstance(state, TeamState)

    def test_load_should_restore_saved_state(self):
        """load() should restore previously saved state."""
        # Save state
        original = TeamState(
            active=True,
            project="MyProject",
            original_prompt="Test prompt"
        )
        original.save()

        # Load it back
        loaded = TeamState.load()

        assert loaded.active is True
        assert loaded.project == "MyProject"
        assert loaded.original_prompt == "Test prompt"

    def test_load_should_return_default_if_file_missing(self):
        """load() should return default state if file doesn't exist."""
        # Ensure file doesn't exist
        if STATE_FILE.exists():
            STATE_FILE.unlink()

        state = TeamState.load()

        assert state.active is False
        assert state.agents == {}

    def test_load_should_return_default_if_file_invalid(self):
        """load() should return default state if file contains invalid JSON."""
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text("not valid json {{{", encoding="utf-8")

        state = TeamState.load()

        assert state.active is False


class TestTeamStateSpawn:
    """Tests for the spawn() method."""

    def test_spawn_should_set_active_true(self):
        """spawn() should set active to True."""
        state = TeamState()
        state.spawn("Test prompt", "TestProject", ["agent1", "agent2"])

        assert state.active is True

    def test_spawn_should_record_prompt(self):
        """spawn() should record the original prompt."""
        state = TeamState()
        state.spawn("Build a feature", "TestProject", ["agent1"])

        assert state.original_prompt == "Build a feature"

    def test_spawn_should_record_project(self):
        """spawn() should record the project name."""
        state = TeamState()
        state.spawn("Test prompt", "MyProject", ["agent1"])

        assert state.project == "MyProject"

    def test_spawn_should_set_spawned_at_timestamp(self):
        """spawn() should set spawned_at to current time."""
        state = TeamState()
        before = datetime.now().isoformat()
        state.spawn("Test", "Project", ["agent1"])
        after = datetime.now().isoformat()

        assert state.spawned_at is not None
        assert before <= state.spawned_at <= after

    def test_spawn_should_clear_collapsed_at(self):
        """spawn() should clear any previous collapsed_at."""
        state = TeamState(collapsed_at="2025-01-01T00:00:00")
        state.spawn("Test", "Project", ["agent1"])

        assert state.collapsed_at is None

    def test_spawn_should_create_agent_entries(self):
        """spawn() should create entries for all agents."""
        agents = ["frontend-dev", "backend-dev", "qa-tester"]
        state = TeamState()
        state.spawn("Test", "Project", agents)

        assert len(state.agents) == 3
        assert "frontend-dev" in state.agents
        assert "backend-dev" in state.agents
        assert "qa-tester" in state.agents

    def test_spawn_should_set_agents_to_working(self):
        """spawn() should set all agents to 'working' status."""
        state = TeamState()
        state.spawn("Test", "Project", ["agent1", "agent2"])

        for agent_name, agent_info in state.agents.items():
            assert agent_info["status"] == "working"

    def test_spawn_should_set_agent_started_at(self):
        """spawn() should set started_at for each agent."""
        state = TeamState()
        state.spawn("Test", "Project", ["agent1"])

        assert "started_at" in state.agents["agent1"]
        assert state.agents["agent1"]["started_at"] is not None

    def test_spawn_should_save_state(self):
        """spawn() should automatically save the state."""
        state = TeamState()
        state.spawn("Test", "Project", ["agent1"])

        # Load from file and verify
        loaded = TeamState.load()
        assert loaded.active is True
        assert loaded.original_prompt == "Test"


class TestTeamStateCollapse:
    """Tests for the collapse() method."""

    def test_collapse_should_set_active_false(self):
        """collapse() should set active to False."""
        state = TeamState(active=True)
        state.collapse()

        assert state.active is False

    def test_collapse_should_set_collapsed_at_timestamp(self):
        """collapse() should set collapsed_at to current time."""
        state = TeamState(active=True)
        before = datetime.now().isoformat()
        state.collapse()
        after = datetime.now().isoformat()

        assert state.collapsed_at is not None
        assert before <= state.collapsed_at <= after

    def test_collapse_should_cancel_working_agents(self):
        """collapse() should set working agents to 'cancelled'."""
        state = TeamState()
        state.spawn("Test", "Project", ["agent1", "agent2"])
        state.collapse()

        for agent_name, agent_info in state.agents.items():
            assert agent_info["status"] == "cancelled"

    def test_collapse_should_not_change_completed_agents(self):
        """collapse() should not change agents that completed."""
        state = TeamState()
        state.spawn("Test", "Project", ["agent1", "agent2"])
        state.mark_completed("agent1")
        state.collapse()

        assert state.agents["agent1"]["status"] == "completed"
        assert state.agents["agent2"]["status"] == "cancelled"

    def test_collapse_should_save_state(self):
        """collapse() should automatically save the state."""
        state = TeamState(active=True)
        state.collapse()

        loaded = TeamState.load()
        assert loaded.active is False


class TestTeamStateMarkCompleted:
    """Tests for the mark_completed() method."""

    def test_should_set_agent_status_to_completed(self):
        """mark_completed() should set agent status to 'completed'."""
        state = TeamState()
        state.spawn("Test", "Project", ["agent1"])
        state.mark_completed("agent1")

        assert state.agents["agent1"]["status"] == "completed"

    def test_should_set_completed_at_timestamp(self):
        """mark_completed() should set completed_at timestamp."""
        state = TeamState()
        state.spawn("Test", "Project", ["agent1"])
        before = datetime.now().isoformat()
        state.mark_completed("agent1")

        assert "completed_at" in state.agents["agent1"]
        assert state.agents["agent1"]["completed_at"] >= before

    def test_should_store_result_if_provided(self):
        """mark_completed() should store result dict if provided."""
        state = TeamState()
        state.spawn("Test", "Project", ["agent1"])
        result = {"files_created": ["test.py"], "tests_written": 5}
        state.mark_completed("agent1", result=result)

        assert state.agents["agent1"]["result"] == result

    def test_should_save_state(self):
        """mark_completed() should automatically save the state."""
        state = TeamState()
        state.spawn("Test", "Project", ["agent1"])
        state.mark_completed("agent1")

        loaded = TeamState.load()
        assert loaded.agents["agent1"]["status"] == "completed"

    def test_should_handle_nonexistent_agent(self):
        """mark_completed() should handle non-existent agent gracefully."""
        state = TeamState()
        state.spawn("Test", "Project", ["agent1"])
        state.mark_completed("nonexistent")  # Should not raise

        assert "nonexistent" not in state.agents


class TestTeamStateMarkError:
    """Tests for the mark_error() method."""

    def test_should_set_agent_status_to_error(self):
        """mark_error() should set agent status to 'error'."""
        state = TeamState()
        state.spawn("Test", "Project", ["agent1"])
        state.mark_error("agent1", "Something went wrong")

        assert state.agents["agent1"]["status"] == "error"

    def test_should_store_error_message(self):
        """mark_error() should store the error message."""
        state = TeamState()
        state.spawn("Test", "Project", ["agent1"])
        state.mark_error("agent1", "Connection failed")

        assert state.agents["agent1"]["error"] == "Connection failed"

    def test_should_save_state(self):
        """mark_error() should automatically save the state."""
        state = TeamState()
        state.spawn("Test", "Project", ["agent1"])
        state.mark_error("agent1", "Error!")

        loaded = TeamState.load()
        assert loaded.agents["agent1"]["status"] == "error"


class TestTeamStateStatusSummary:
    """Tests for the get_status_summary() method."""

    def test_should_return_inactive_when_not_active(self):
        """get_status_summary() should indicate inactive state."""
        state = TeamState(active=False)
        summary = state.get_status_summary()

        assert summary["active"] is False
        assert "message" in summary

    def test_should_return_full_summary_when_active(self):
        """get_status_summary() should return full summary when active."""
        state = TeamState()
        state.spawn("Test prompt", "TestProject", ["agent1", "agent2"])
        summary = state.get_status_summary()

        assert summary["active"] is True
        assert summary["original_prompt"] == "Test prompt"
        assert summary["project"] == "TestProject"
        assert "agents" in summary

    def test_should_count_working_agents(self):
        """get_status_summary() should count working agents."""
        state = TeamState()
        state.spawn("Test", "Project", ["a1", "a2", "a3"])
        summary = state.get_status_summary()

        assert summary["working"] == 3

    def test_should_count_completed_agents(self):
        """get_status_summary() should count completed agents."""
        state = TeamState()
        state.spawn("Test", "Project", ["a1", "a2", "a3"])
        state.mark_completed("a1")
        state.mark_completed("a2")
        summary = state.get_status_summary()

        assert summary["completed"] == 2
        assert summary["working"] == 1

    def test_should_count_error_agents(self):
        """get_status_summary() should count error agents."""
        state = TeamState()
        state.spawn("Test", "Project", ["a1", "a2"])
        state.mark_error("a1", "Failed")
        summary = state.get_status_summary()

        assert summary["error"] == 1
        assert summary["working"] == 1


class TestTeamStateAllCompleted:
    """Tests for the all_completed() method."""

    def test_should_return_false_when_no_agents(self):
        """all_completed() should return False when no agents."""
        state = TeamState()
        assert state.all_completed() is False

    def test_should_return_false_when_agents_working(self):
        """all_completed() should return False when agents are working."""
        state = TeamState()
        state.spawn("Test", "Project", ["a1", "a2"])
        assert state.all_completed() is False

    def test_should_return_true_when_all_completed(self):
        """all_completed() should return True when all agents completed."""
        state = TeamState()
        state.spawn("Test", "Project", ["a1", "a2"])
        state.mark_completed("a1")
        state.mark_completed("a2")

        assert state.all_completed() is True

    def test_should_return_true_when_all_error_or_cancelled(self):
        """all_completed() should return True for error/cancelled states."""
        state = TeamState()
        state.spawn("Test", "Project", ["a1", "a2", "a3"])
        state.mark_completed("a1")
        state.mark_error("a2", "Error")
        state.agents["a3"]["status"] = "cancelled"

        assert state.all_completed() is True


# =============================================================================
# HELPER FUNCTION TESTS
# =============================================================================

class TestGetTeamState:
    """Tests for the get_team_state() function."""

    def test_should_return_teamstate(self):
        """get_team_state() should return a TeamState instance."""
        state = get_team_state()
        assert isinstance(state, TeamState)

    def test_should_load_existing_state(self):
        """get_team_state() should load existing state from file."""
        # Create and save state
        original = TeamState(active=True, project="Test")
        original.save()

        # Get it
        loaded = get_team_state()
        assert loaded.active is True
        assert loaded.project == "Test"


class TestResetTeamState:
    """Tests for the reset_team_state() function."""

    def test_should_create_empty_state(self):
        """reset_team_state() should create an empty state."""
        # First create an active state
        state = TeamState()
        state.spawn("Test", "Project", ["agent1"])
        state.save()

        # Reset it
        reset_team_state()

        # Verify reset
        loaded = TeamState.load()
        assert loaded.active is False
        assert loaded.agents == {}

    def test_should_clear_result_files(self):
        """reset_team_state() should clear result files."""
        # Create a result file
        RESULTS_PATH.mkdir(parents=True, exist_ok=True)
        test_result = RESULTS_PATH / "test-agent-result.json"
        test_result.write_text('{"test": true}', encoding="utf-8")

        # Reset
        reset_team_state()

        # Result file should be deleted
        assert not test_result.exists()


# =============================================================================
# AGENTSTATUS DATACLASS TESTS
# =============================================================================

class TestAgentStatusDataclass:
    """Tests for the AgentStatus dataclass."""

    def test_should_require_name_and_status(self):
        """AgentStatus should require name and status."""
        agent = AgentStatus(name="test-agent", status="working")

        assert agent.name == "test-agent"
        assert agent.status == "working"

    def test_should_have_optional_fields_default_to_none(self):
        """Optional fields should default to None."""
        agent = AgentStatus(name="test", status="idle")

        assert agent.task_file is None
        assert agent.result_file is None
        assert agent.started_at is None
        assert agent.completed_at is None

    def test_should_accept_all_parameters(self):
        """Should accept all parameters."""
        agent = AgentStatus(
            name="frontend-dev",
            status="completed",
            task_file="/path/to/task.md",
            result_file="/path/to/result.json",
            started_at="2025-01-01T00:00:00",
            completed_at="2025-01-01T01:00:00"
        )

        assert agent.name == "frontend-dev"
        assert agent.status == "completed"
        assert agent.task_file == "/path/to/task.md"


# =============================================================================
# EDGE CASES AND BOUNDARY TESTS
# =============================================================================

class TestStateEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_should_handle_rapid_state_changes(self):
        """Should handle rapid state changes."""
        state = TeamState()

        for i in range(10):
            state.spawn(f"Prompt {i}", f"Project {i}", [f"agent{i}"])
            time.sleep(0.01)
            state.collapse()

        # State should be consistent
        assert state.active is False

    def test_should_handle_empty_agent_list(self):
        """Should handle spawn with empty agent list."""
        state = TeamState()
        state.spawn("Test", "Project", [])

        assert state.active is True
        assert state.agents == {}

    def test_should_handle_very_long_prompt(self):
        """Should handle very long prompts."""
        long_prompt = "x" * 10000
        state = TeamState()
        state.spawn(long_prompt, "Project", ["agent1"])

        assert state.original_prompt == long_prompt

        # Reload to verify persistence
        loaded = TeamState.load()
        assert loaded.original_prompt == long_prompt

    def test_should_handle_unicode_in_state(self):
        """Should handle unicode characters in state."""
        state = TeamState()
        state.spawn("Build \U0001F680 rocket", "\u30D7\u30ED\u30B8\u30A7\u30AF\u30C8", ["agent1"])

        loaded = TeamState.load()
        assert loaded.original_prompt == "Build \U0001F680 rocket"
        assert loaded.project == "\u30D7\u30ED\u30B8\u30A7\u30AF\u30C8"

    def test_should_handle_special_characters_in_project_name(self):
        """Should handle special characters in project name."""
        state = TeamState()
        state.spawn("Test", "My Project (v2.0) - Test!", ["agent1"])

        loaded = TeamState.load()
        assert loaded.project == "My Project (v2.0) - Test!"
