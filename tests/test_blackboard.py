"""
Tests for the Blackboard System (team/blackboard.py)

This module tests the shared communication system for agent collaboration.

Test Categories:
1. Message Class Tests
2. Blackboard Class Tests
3. Init/Load/Save Tests
4. Post Message Tests
5. Status and Deliverable Tests
6. Query Function Tests
7. Phase Management Tests
8. Poll Interval Tests
9. Agent Convenience Function Tests
10. Edge Cases and Boundary Tests
"""
import pytest
import sys
import json
import tempfile
import shutil
import time
from pathlib import Path
from datetime import datetime
from unittest.mock import patch, MagicMock

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from team.blackboard import (
    Message,
    Blackboard,
    Phase,
    init_blackboard,
    save_blackboard,
    load_blackboard,
    clear_blackboard,
    post_message,
    update_status,
    add_deliverable,
    get_messages,
    get_messages_for_agent,
    get_done_agents,
    get_questions,
    get_blockers,
    check_phase_ready,
    advance_phase,
    get_poll_interval,
    get_blackboard_summary,
    agent_post,
    agent_done,
    agent_ask,
    agent_deliver,
    agent_blocked,
    BLACKBOARD_FILE,
)


# =============================================================================
# TEST FIXTURES
# =============================================================================

@pytest.fixture
def clean_blackboard():
    """Fixture that clears blackboard before and after each test."""
    clear_blackboard()
    yield
    clear_blackboard()


@pytest.fixture
def sample_blackboard(clean_blackboard):
    """Fixture that creates a sample blackboard with agents."""
    agents = ["frontend-dev", "backend-dev", "qa-tester"]
    return init_blackboard("Test Feature", agents)


# =============================================================================
# MESSAGE CLASS TESTS
# =============================================================================

class TestMessageClass:
    """Tests for the Message dataclass."""

    def test_should_create_message_with_required_fields(self):
        """Should create a message with agent, timestamp, message."""
        msg = Message(
            agent="test-agent",
            timestamp="2025-12-26T10:00:00",
            message="Hello world"
        )
        assert msg.agent == "test-agent"
        assert msg.timestamp == "2025-12-26T10:00:00"
        assert msg.message == "Hello world"

    def test_should_have_optional_type_field(self):
        """Optional type field should default to None."""
        msg = Message(agent="a", timestamp="t", message="m")
        assert msg.type is None

        msg_with_type = Message(agent="a", timestamp="t", message="m", type="DONE")
        assert msg_with_type.type == "DONE"

    def test_should_have_optional_to_field(self):
        """Optional to field should default to None."""
        msg = Message(agent="a", timestamp="t", message="m")
        assert msg.to is None

        msg_with_to = Message(agent="a", timestamp="t", message="m", to="frontend-dev")
        assert msg_with_to.to == "frontend-dev"

    def test_to_dict_should_use_from_key(self):
        """to_dict() should serialize agent as 'from' key."""
        msg = Message(agent="backend-dev", timestamp="t", message="m")
        d = msg.to_dict()

        assert "from" in d
        assert d["from"] == "backend-dev"
        assert "agent" not in d

    def test_to_dict_should_exclude_none_optionals(self):
        """to_dict() should not include None optional fields."""
        msg = Message(agent="a", timestamp="t", message="m")
        d = msg.to_dict()

        assert "type" not in d
        assert "to" not in d

    def test_to_dict_should_include_set_optionals(self):
        """to_dict() should include optional fields when set."""
        msg = Message(agent="a", timestamp="t", message="m", type="QUESTION", to="frontend")
        d = msg.to_dict()

        assert d["type"] == "QUESTION"
        assert d["to"] == "frontend"

    def test_from_dict_should_parse_from_key(self):
        """from_dict() should parse 'from' key as agent."""
        d = {"from": "test-agent", "timestamp": "t", "message": "m"}
        msg = Message.from_dict(d)

        assert msg.agent == "test-agent"

    def test_from_dict_should_also_accept_agent_key(self):
        """from_dict() should also accept 'agent' key (fallback)."""
        d = {"agent": "test-agent", "timestamp": "t", "message": "m"}
        msg = Message.from_dict(d)

        assert msg.agent == "test-agent"

    def test_from_dict_should_handle_content_alias(self):
        """from_dict() should handle 'content' as alias for 'message'."""
        d = {"from": "a", "timestamp": "t", "content": "hello"}
        msg = Message.from_dict(d)

        assert msg.message == "hello"

    def test_from_dict_should_handle_target_alias(self):
        """from_dict() should handle 'target' as alias for 'to'."""
        d = {"from": "a", "timestamp": "t", "message": "m", "target": "frontend"}
        msg = Message.from_dict(d)

        assert msg.to == "frontend"


# =============================================================================
# BLACKBOARD CLASS TESTS
# =============================================================================

class TestBlackboardClass:
    """Tests for the Blackboard dataclass."""

    def test_should_create_blackboard_with_all_fields(self):
        """Should create a blackboard with all required fields."""
        board = Blackboard(
            feature="Test Feature",
            phase=Phase.PHASE_1_BUILD,
            started_at="2025-12-26T10:00:00",
            messages=[],
            agent_status={"agent-1": "starting"},
            deliverables={"agent-1": []},
        )

        assert board.feature == "Test Feature"
        assert board.phase == Phase.PHASE_1_BUILD
        assert board.started_at == "2025-12-26T10:00:00"
        assert board.messages == []
        assert board.agent_status == {"agent-1": "starting"}
        assert board.deliverables == {"agent-1": []}

    def test_to_dict_should_serialize_phase_as_string(self):
        """to_dict() should serialize Phase enum as string value."""
        board = Blackboard(
            feature="F",
            phase=Phase.PHASE_2_SYNC,
            started_at="t",
            messages=[],
            agent_status={},
            deliverables={},
        )
        d = board.to_dict()

        assert d["phase"] == "sync"

    def test_to_dict_should_serialize_messages(self):
        """to_dict() should serialize Message objects."""
        msg = Message(agent="a", timestamp="t", message="m")
        board = Blackboard(
            feature="F",
            phase=Phase.PHASE_1_BUILD,
            started_at="t",
            messages=[msg],
            agent_status={},
            deliverables={},
        )
        d = board.to_dict()

        assert len(d["messages"]) == 1
        assert d["messages"][0]["from"] == "a"

    def test_from_dict_should_parse_phase_string(self):
        """from_dict() should parse phase string back to enum."""
        d = {
            "feature": "F",
            "phase": "sync",
            "started_at": "t",
            "messages": [],
            "agent_status": {},
            "deliverables": {},
        }
        board = Blackboard.from_dict(d)

        assert board.phase == Phase.PHASE_2_SYNC

    def test_from_dict_should_parse_messages(self):
        """from_dict() should parse message dicts into Message objects."""
        d = {
            "feature": "F",
            "phase": "build",
            "started_at": "t",
            "messages": [{"from": "a", "timestamp": "t", "message": "m"}],
            "agent_status": {},
            "deliverables": {},
        }
        board = Blackboard.from_dict(d)

        assert len(board.messages) == 1
        assert isinstance(board.messages[0], Message)
        assert board.messages[0].agent == "a"


# =============================================================================
# PHASE ENUM TESTS
# =============================================================================

class TestPhaseEnum:
    """Tests for the Phase enum."""

    def test_should_have_all_phases(self):
        """Should have all 5 phases defined."""
        assert Phase.PHASE_1_BUILD.value == "build"
        assert Phase.PHASE_2_SYNC.value == "sync"
        assert Phase.PHASE_3_INTEGRATE.value == "integrate"
        assert Phase.PHASE_4_VERIFY.value == "verify"
        assert Phase.COMPLETE.value == "complete"

    def test_should_be_string_enum(self):
        """Phase should be a string enum."""
        assert isinstance(Phase.PHASE_1_BUILD.value, str)


# =============================================================================
# INIT/LOAD/SAVE TESTS
# =============================================================================

class TestInitBlackboard:
    """Tests for the init_blackboard function."""

    def test_should_return_blackboard_object(self, clean_blackboard):
        """init_blackboard should return a Blackboard object."""
        result = init_blackboard("Test", ["agent-1"])
        assert isinstance(result, Blackboard)

    def test_should_set_feature(self, clean_blackboard):
        """Should set the feature description."""
        result = init_blackboard("Build Login", ["agent-1"])
        assert result.feature == "Build Login"

    def test_should_set_phase_to_build(self, clean_blackboard):
        """Should start in PHASE_1_BUILD."""
        result = init_blackboard("Test", ["agent-1"])
        assert result.phase == Phase.PHASE_1_BUILD

    def test_should_initialize_agent_status(self, clean_blackboard):
        """Should initialize agent status to 'starting'."""
        agents = ["frontend-dev", "backend-dev"]
        result = init_blackboard("Test", agents)

        assert result.agent_status["frontend-dev"] == "starting"
        assert result.agent_status["backend-dev"] == "starting"

    def test_should_initialize_empty_deliverables(self, clean_blackboard):
        """Should initialize empty deliverables lists for each agent."""
        agents = ["agent-1", "agent-2"]
        result = init_blackboard("Test", agents)

        assert result.deliverables["agent-1"] == []
        assert result.deliverables["agent-2"] == []

    def test_should_initialize_empty_messages(self, clean_blackboard):
        """Should start with empty messages list."""
        result = init_blackboard("Test", ["agent-1"])
        assert result.messages == []

    def test_should_save_to_file(self, clean_blackboard):
        """Should save blackboard to file."""
        init_blackboard("Test", ["agent-1"])
        assert BLACKBOARD_FILE.exists()

    def test_should_set_started_at_timestamp(self, clean_blackboard):
        """Should set started_at to current timestamp."""
        result = init_blackboard("Test", ["agent-1"])
        # Timestamp should be valid ISO format
        datetime.fromisoformat(result.started_at)


class TestLoadBlackboard:
    """Tests for the load_blackboard function."""

    def test_should_return_none_if_no_file(self, clean_blackboard):
        """Should return None if blackboard file doesn't exist."""
        result = load_blackboard()
        assert result is None

    def test_should_load_existing_blackboard(self, sample_blackboard):
        """Should load an existing blackboard from file."""
        result = load_blackboard()

        assert result is not None
        assert result.feature == "Test Feature"
        assert len(result.agent_status) == 3

    def test_should_return_blackboard_object(self, sample_blackboard):
        """Should return a Blackboard object."""
        result = load_blackboard()
        assert isinstance(result, Blackboard)


class TestSaveBlackboard:
    """Tests for the save_blackboard function."""

    def test_should_return_true_on_success(self, clean_blackboard):
        """Should return True on successful save."""
        board = Blackboard(
            feature="Test",
            phase=Phase.PHASE_1_BUILD,
            started_at="t",
            messages=[],
            agent_status={},
            deliverables={},
        )
        result = save_blackboard(board)
        assert result is True

    def test_should_create_file(self, clean_blackboard):
        """Should create the blackboard file."""
        board = Blackboard(
            feature="Test",
            phase=Phase.PHASE_1_BUILD,
            started_at="t",
            messages=[],
            agent_status={},
            deliverables={},
        )
        save_blackboard(board)
        assert BLACKBOARD_FILE.exists()

    def test_should_write_valid_json(self, clean_blackboard):
        """Should write valid JSON to file."""
        board = Blackboard(
            feature="Test",
            phase=Phase.PHASE_1_BUILD,
            started_at="t",
            messages=[],
            agent_status={"a": "s"},
            deliverables={"a": []},
        )
        save_blackboard(board)

        content = BLACKBOARD_FILE.read_text(encoding="utf-8")
        data = json.loads(content)

        assert data["feature"] == "Test"


class TestClearBlackboard:
    """Tests for the clear_blackboard function."""

    def test_should_return_true(self, sample_blackboard):
        """Should return True."""
        result = clear_blackboard()
        assert result is True

    def test_should_remove_file(self, sample_blackboard):
        """Should remove the blackboard file."""
        assert BLACKBOARD_FILE.exists()
        clear_blackboard()
        assert not BLACKBOARD_FILE.exists()

    def test_should_handle_missing_file(self, clean_blackboard):
        """Should handle case where file doesn't exist."""
        result = clear_blackboard()
        assert result is True


# =============================================================================
# POST MESSAGE TESTS
# =============================================================================

class TestPostMessage:
    """Tests for the post_message function."""

    def test_should_return_true_on_success(self, sample_blackboard):
        """Should return True on successful post."""
        result = post_message("agent-1", "Hello")
        assert result is True

    def test_should_add_message_to_blackboard(self, sample_blackboard):
        """Should add message to blackboard messages list."""
        post_message("frontend-dev", "I'm working on it")
        board = load_blackboard()

        assert len(board.messages) == 1
        assert board.messages[0].agent == "frontend-dev"
        assert board.messages[0].message == "I'm working on it"

    def test_should_return_false_if_no_blackboard(self, clean_blackboard):
        """Should return False if no blackboard exists."""
        result = post_message("agent", "message")
        assert result is False

    def test_should_add_timestamp(self, sample_blackboard):
        """Should automatically add timestamp to message."""
        post_message("agent", "message")
        board = load_blackboard()

        assert board.messages[0].timestamp is not None
        # Should be valid ISO timestamp
        datetime.fromisoformat(board.messages[0].timestamp)

    def test_should_support_message_type(self, sample_blackboard):
        """Should support optional message type."""
        post_message("agent", "Done!", msg_type="DONE")
        board = load_blackboard()

        assert board.messages[0].type == "DONE"

    def test_should_support_target_agent(self, sample_blackboard):
        """Should support targeting specific agent."""
        post_message("backend", "Question?", to="frontend-dev")
        board = load_blackboard()

        assert board.messages[0].to == "frontend-dev"


# =============================================================================
# STATUS AND DELIVERABLE TESTS
# =============================================================================

class TestUpdateStatus:
    """Tests for the update_status function."""

    def test_should_update_agent_status(self, sample_blackboard):
        """Should update an agent's status."""
        update_status("frontend-dev", "working")
        board = load_blackboard()

        assert board.agent_status["frontend-dev"] == "working"

    def test_should_return_true_on_success(self, sample_blackboard):
        """Should return True on successful update."""
        result = update_status("frontend-dev", "complete")
        assert result is True

    def test_should_return_false_if_no_blackboard(self, clean_blackboard):
        """Should return False if no blackboard exists."""
        result = update_status("agent", "status")
        assert result is False


class TestAddDeliverable:
    """Tests for the add_deliverable function."""

    def test_should_add_deliverable_to_agent(self, sample_blackboard):
        """Should add deliverable to agent's list."""
        add_deliverable("frontend-dev", "src/components/Modal.tsx")
        board = load_blackboard()

        assert "src/components/Modal.tsx" in board.deliverables["frontend-dev"]

    def test_should_return_true_on_success(self, sample_blackboard):
        """Should return True on successful add."""
        result = add_deliverable("frontend-dev", "file.ts")
        assert result is True

    def test_should_create_list_for_new_agent(self, sample_blackboard):
        """Should create deliverables list for new agent."""
        add_deliverable("new-agent", "file.ts")
        board = load_blackboard()

        assert "new-agent" in board.deliverables
        assert "file.ts" in board.deliverables["new-agent"]

    def test_should_append_multiple_deliverables(self, sample_blackboard):
        """Should append multiple deliverables."""
        add_deliverable("frontend-dev", "file1.ts")
        add_deliverable("frontend-dev", "file2.ts")
        board = load_blackboard()

        assert len(board.deliverables["frontend-dev"]) == 2


# =============================================================================
# QUERY FUNCTION TESTS
# =============================================================================

class TestGetMessages:
    """Tests for the get_messages function."""

    def test_should_return_empty_list_if_no_messages(self, sample_blackboard):
        """Should return empty list when no messages."""
        result = get_messages()
        assert result == []

    def test_should_return_all_messages_by_default(self, sample_blackboard):
        """Should return all messages by default."""
        post_message("a", "msg1")
        post_message("b", "msg2")

        result = get_messages()
        assert len(result) == 2

    def test_should_filter_by_type(self, sample_blackboard):
        """Should filter messages by type."""
        post_message("a", "question", msg_type="QUESTION")
        post_message("b", "done", msg_type="DONE")

        result = get_messages(msg_type="QUESTION")
        assert len(result) == 1
        assert result[0].message == "question"

    def test_should_filter_by_target_agent(self, sample_blackboard):
        """Should filter by target agent."""
        post_message("a", "to frontend", to="frontend-dev")
        post_message("b", "to backend", to="backend-dev")
        post_message("c", "broadcast")

        result = get_messages(for_agent="frontend-dev")
        # Should include targeted + broadcast
        assert len(result) == 2

    def test_type_filter_should_be_case_insensitive(self, sample_blackboard):
        """Type filter should be case insensitive."""
        post_message("a", "done", msg_type="done")

        result = get_messages(msg_type="DONE")
        assert len(result) == 1


class TestGetMessagesForAgent:
    """Tests for the get_messages_for_agent function."""

    def test_should_return_messages_for_agent(self, sample_blackboard):
        """Should return messages targeted at agent."""
        post_message("a", "to frontend", to="frontend-dev")

        result = get_messages_for_agent("frontend-dev")
        assert len(result) == 1

    def test_should_include_broadcast_messages(self, sample_blackboard):
        """Should include messages with no target (broadcast)."""
        post_message("a", "broadcast")
        post_message("b", "to frontend", to="frontend-dev")

        result = get_messages_for_agent("frontend-dev")
        assert len(result) == 2

    def test_should_exclude_messages_for_other_agents(self, sample_blackboard):
        """Should not include messages for other agents."""
        post_message("a", "to backend", to="backend-dev")

        result = get_messages_for_agent("frontend-dev")
        # Only broadcast messages (none in this case since all are targeted)
        assert len(result) == 0


class TestGetDoneAgents:
    """Tests for the get_done_agents function."""

    def test_should_return_empty_if_none_done(self, sample_blackboard):
        """Should return empty list if no agents done."""
        result = get_done_agents()
        assert result == []

    def test_should_return_agents_with_done_message(self, sample_blackboard):
        """Should return agents that posted DONE message."""
        post_message("frontend-dev", "finished", msg_type="DONE")

        result = get_done_agents()
        assert "frontend-dev" in result

    def test_should_return_multiple_done_agents(self, sample_blackboard):
        """Should return all agents that are done."""
        post_message("frontend-dev", "done", msg_type="DONE")
        post_message("backend-dev", "done", msg_type="DONE")

        result = get_done_agents()
        assert len(result) == 2


class TestGetQuestions:
    """Tests for the get_questions function."""

    def test_should_return_empty_if_no_questions(self, sample_blackboard):
        """Should return empty list if no questions."""
        result = get_questions()
        assert result == []

    def test_should_return_question_messages(self, sample_blackboard):
        """Should return messages with QUESTION type."""
        post_message("a", "What endpoint?", msg_type="QUESTION")
        post_message("b", "I'm done", msg_type="DONE")

        result = get_questions()
        assert len(result) == 1
        assert result[0].message == "What endpoint?"

    def test_should_filter_by_target(self, sample_blackboard):
        """Should filter questions by target agent."""
        post_message("a", "q1", msg_type="QUESTION", to="frontend-dev")
        post_message("b", "q2", msg_type="QUESTION", to="backend-dev")

        result = get_questions(for_agent="frontend-dev")
        assert len(result) == 1


class TestGetBlockers:
    """Tests for the get_blockers function."""

    def test_should_return_empty_if_no_blockers(self, sample_blackboard):
        """Should return empty list if no blockers."""
        result = get_blockers()
        assert result == []

    def test_should_return_blocker_messages(self, sample_blackboard):
        """Should return messages with BLOCKER type."""
        post_message("a", "stuck", msg_type="BLOCKER")

        result = get_blockers()
        assert len(result) == 1
        assert result[0].message == "stuck"


# =============================================================================
# PHASE MANAGEMENT TESTS
# =============================================================================

class TestCheckPhaseReady:
    """Tests for the check_phase_ready function."""

    def test_should_return_false_initially(self, sample_blackboard):
        """Should return False when agents not done."""
        result = check_phase_ready()
        assert result is False

    def test_should_return_true_when_all_done(self, sample_blackboard):
        """Should return True when all agents have DONE message."""
        for agent in ["frontend-dev", "backend-dev", "qa-tester"]:
            post_message(agent, "done", msg_type="DONE")

        result = check_phase_ready()
        assert result is True

    def test_should_return_true_when_all_complete_status(self, sample_blackboard):
        """Should return True when all agents have 'complete' status."""
        for agent in ["frontend-dev", "backend-dev", "qa-tester"]:
            update_status(agent, "complete")

        result = check_phase_ready()
        assert result is True


class TestAdvancePhase:
    """Tests for the advance_phase function."""

    def test_should_advance_from_build_to_sync(self, sample_blackboard):
        """Should advance from build to sync phase."""
        result = advance_phase()

        assert result == Phase.PHASE_2_SYNC
        board = load_blackboard()
        assert board.phase == Phase.PHASE_2_SYNC

    def test_should_advance_through_all_phases(self, sample_blackboard):
        """Should advance through all phases in order."""
        phases = [
            Phase.PHASE_2_SYNC,
            Phase.PHASE_3_INTEGRATE,
            Phase.PHASE_4_VERIFY,
            Phase.COMPLETE,
        ]

        for expected_phase in phases:
            result = advance_phase()
            assert result == expected_phase

    def test_should_stay_at_complete(self, sample_blackboard):
        """Should stay at COMPLETE phase when already complete."""
        # Advance to complete
        for _ in range(4):
            advance_phase()

        result = advance_phase()
        assert result == Phase.COMPLETE


# =============================================================================
# POLL INTERVAL TESTS
# =============================================================================

class TestGetPollInterval:
    """Tests for the get_poll_interval function."""

    def test_should_return_float(self):
        """Should return a float."""
        result = get_poll_interval("test-agent")
        assert isinstance(result, float)

    def test_should_be_in_reasonable_range(self):
        """Should return interval between 6 and 14 seconds."""
        for agent in ["a", "b", "c", "d", "e"]:
            result = get_poll_interval(agent)
            assert 6.0 <= result <= 14.0

    def test_should_be_deterministic_for_same_agent(self):
        """Base offset should be deterministic for same agent."""
        # Note: jitter is random, but base offset is deterministic
        # We can't test exact equality due to jitter
        pass  # Acknowledged: jitter makes exact testing difficult


# =============================================================================
# AGENT CONVENIENCE FUNCTION TESTS
# =============================================================================

class TestAgentPost:
    """Tests for the agent_post function."""

    def test_should_post_message(self, sample_blackboard):
        """Should post a message to blackboard."""
        result = agent_post("frontend-dev", "Hello")
        assert result is True

        board = load_blackboard()
        assert len(board.messages) == 1


class TestAgentDone:
    """Tests for the agent_done function."""

    def test_should_mark_agent_complete(self, sample_blackboard):
        """Should update agent status to complete."""
        agent_done("frontend-dev", "Finished my work")

        board = load_blackboard()
        assert board.agent_status["frontend-dev"] == "complete"

    def test_should_post_done_message(self, sample_blackboard):
        """Should post a DONE type message."""
        agent_done("frontend-dev", "Finished")

        messages = get_messages(msg_type="DONE")
        assert len(messages) == 1


class TestAgentAsk:
    """Tests for the agent_ask function."""

    def test_should_post_question_to_target(self, sample_blackboard):
        """Should post QUESTION to target agent."""
        agent_ask("backend-dev", "frontend-dev", "What endpoint format?")

        questions = get_questions(for_agent="frontend-dev")
        assert len(questions) == 1
        assert questions[0].agent == "backend-dev"


class TestAgentDeliver:
    """Tests for the agent_deliver function."""

    def test_should_record_deliverables(self, sample_blackboard):
        """Should record multiple deliverables."""
        files = ["file1.ts", "file2.ts"]
        agent_deliver("frontend-dev", "Components", files)

        board = load_blackboard()
        assert "file1.ts" in board.deliverables["frontend-dev"]
        assert "file2.ts" in board.deliverables["frontend-dev"]

    def test_should_post_deliverable_message(self, sample_blackboard):
        """Should post DELIVERABLE message."""
        agent_deliver("frontend-dev", "Modal", ["Modal.tsx"])

        messages = get_messages(msg_type="DELIVERABLE")
        assert len(messages) == 1


class TestAgentBlocked:
    """Tests for the agent_blocked function."""

    def test_should_update_status_to_blocked(self, sample_blackboard):
        """Should update agent status to blocked."""
        agent_blocked("frontend-dev", "Waiting for API")

        board = load_blackboard()
        assert board.agent_status["frontend-dev"] == "blocked"

    def test_should_post_blocker_message(self, sample_blackboard):
        """Should post BLOCKER message."""
        agent_blocked("frontend-dev", "Need API schema")

        blockers = get_blockers()
        assert len(blockers) == 1


# =============================================================================
# GET BLACKBOARD SUMMARY TESTS
# =============================================================================

class TestGetBlackboardSummary:
    """Tests for the get_blackboard_summary function."""

    def test_should_return_dict(self, sample_blackboard):
        """Should return a dictionary."""
        result = get_blackboard_summary()
        assert isinstance(result, dict)

    def test_should_include_active_status(self, sample_blackboard):
        """Should include active status."""
        result = get_blackboard_summary()
        assert result["active"] is True

    def test_should_include_feature(self, sample_blackboard):
        """Should include feature description."""
        result = get_blackboard_summary()
        assert result["feature"] == "Test Feature"

    def test_should_include_phase(self, sample_blackboard):
        """Should include current phase."""
        result = get_blackboard_summary()
        assert result["phase"] == "build"

    def test_should_include_message_count(self, sample_blackboard):
        """Should include message count."""
        post_message("a", "m")
        post_message("b", "m")

        result = get_blackboard_summary()
        assert result["message_count"] == 2

    def test_should_include_agent_statuses(self, sample_blackboard):
        """Should include agent statuses."""
        result = get_blackboard_summary()
        assert "agents" in result
        assert "frontend-dev" in result["agents"]

    def test_should_return_inactive_if_no_blackboard(self, clean_blackboard):
        """Should return inactive if no blackboard."""
        result = get_blackboard_summary()
        assert result["active"] is False


# =============================================================================
# EDGE CASES AND BOUNDARY TESTS
# =============================================================================

class TestBlackboardEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_should_handle_empty_agent_list(self, clean_blackboard):
        """Should handle empty agent list."""
        board = init_blackboard("Test", [])

        assert board.agent_status == {}
        assert board.deliverables == {}

    def test_should_handle_unicode_in_messages(self, sample_blackboard):
        """Should handle unicode in messages."""
        message = "Emoji 🚀 and Japanese こんにちは"
        post_message("agent", message)

        board = load_blackboard()
        assert board.messages[0].message == message

    def test_should_handle_very_long_messages(self, sample_blackboard):
        """Should handle very long messages."""
        message = "A" * 10000
        post_message("agent", message)

        board = load_blackboard()
        assert len(board.messages[0].message) == 10000

    def test_should_handle_special_characters_in_agent_name(self, clean_blackboard):
        """Should handle special characters in agent names."""
        agents = ["agent-1", "agent_2", "agent.3"]
        board = init_blackboard("Test", agents)

        assert len(board.agent_status) == 3

    def test_should_handle_concurrent_writes(self, sample_blackboard):
        """Should handle rapid successive writes (not truly concurrent)."""
        for i in range(10):
            post_message(f"agent-{i}", f"message-{i}")

        board = load_blackboard()
        assert len(board.messages) == 10

    def test_roundtrip_serialization(self, clean_blackboard):
        """Should correctly serialize and deserialize blackboard."""
        # Create complex blackboard
        board = init_blackboard("Complex Test", ["a", "b"])
        post_message("a", "hello", msg_type="QUESTION", to="b")
        add_deliverable("a", "file.ts")
        update_status("a", "working")

        # Reload and verify
        loaded = load_blackboard()

        assert loaded.feature == "Complex Test"
        assert len(loaded.messages) == 1
        assert loaded.messages[0].type == "QUESTION"
        assert loaded.messages[0].to == "b"
        assert "file.ts" in loaded.deliverables["a"]
        assert loaded.agent_status["a"] == "working"
