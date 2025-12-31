"""
Test input validation for blackboard API endpoints.

Run with: python -m pytest tests/test_input_validation.py -v
"""
import pytest
from fastapi.testclient import TestClient
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from api.main import app

client = TestClient(app)


class TestBlackboardValidation:
    """Test blackboard endpoint input validation."""

    def test_valid_message_accepted(self):
        """Valid message should be accepted."""
        response = client.post("/api/blackboard", json={
            "agent": "frontend-dev",
            "message": "Test message",
            "msg_type": "STATUS"
        })
        # May fail if blackboard not initialized, but should not be validation error
        assert response.status_code in [200, 400, 503]  # Not 422

    def test_agent_path_traversal_rejected(self):
        """Agent name with path traversal should be rejected."""
        response = client.post("/api/blackboard", json={
            "agent": "../../etc/passwd",
            "message": "Test"
        })
        assert response.status_code == 422
        data = response.json()
        assert data["success"] is False
        assert "agent" in data["error"]["message"].lower()

    def test_agent_xss_rejected(self):
        """Agent name with XSS attempt should be rejected."""
        response = client.post("/api/blackboard", json={
            "agent": "<script>alert(1)</script>",
            "message": "Test"
        })
        assert response.status_code == 422

    def test_agent_sql_injection_rejected(self):
        """Agent name with SQL injection attempt should be rejected."""
        response = client.post("/api/blackboard", json={
            "agent": "'; DROP TABLE agents--",
            "message": "Test"
        })
        assert response.status_code == 422

    def test_agent_too_long_rejected(self):
        """Agent name exceeding max length should be rejected."""
        response = client.post("/api/blackboard", json={
            "agent": "a" * 51,
            "message": "Test"
        })
        assert response.status_code == 422

    def test_message_too_long_rejected(self):
        """Message exceeding max length should be rejected."""
        response = client.post("/api/blackboard", json={
            "agent": "test-agent",
            "message": "a" * 5001
        })
        assert response.status_code == 422

    def test_empty_agent_rejected(self):
        """Empty agent name should be rejected."""
        response = client.post("/api/blackboard", json={
            "agent": "",
            "message": "Test"
        })
        assert response.status_code == 422

    def test_empty_message_rejected(self):
        """Empty message should be rejected."""
        response = client.post("/api/blackboard", json={
            "agent": "test-agent",
            "message": ""
        })
        assert response.status_code == 422

    def test_invalid_msg_type_rejected(self):
        """Invalid message type (lowercase) should be rejected."""
        response = client.post("/api/blackboard", json={
            "agent": "test-agent",
            "message": "Test",
            "msg_type": "invalid-type"
        })
        assert response.status_code == 422

    def test_valid_msg_types_accepted(self):
        """Valid message types should be accepted."""
        valid_types = ["DONE", "QUESTION", "DELIVERABLE", "BLOCKER", "STATUS_UPDATE"]
        for msg_type in valid_types:
            response = client.post("/api/blackboard", json={
                "agent": "test-agent",
                "message": "Test",
                "msg_type": msg_type
            })
            # May fail if blackboard not initialized, but should not be validation error
            assert response.status_code in [200, 400, 503], f"Failed for {msg_type}"


class TestBlackboardInitValidation:
    """Test blackboard initialization input validation."""

    def test_empty_agents_list_rejected(self):
        """Empty agents list should be rejected."""
        response = client.post("/api/blackboard/init", json={
            "feature": "Test feature",
            "agents": []
        })
        assert response.status_code == 422

    def test_too_many_agents_rejected(self):
        """More than 20 agents should be rejected."""
        agents = [f"agent-{i}" for i in range(21)]
        response = client.post("/api/blackboard/init", json={
            "feature": "Test feature",
            "agents": agents
        })
        assert response.status_code == 422

    def test_invalid_agent_name_in_list_rejected(self):
        """Invalid agent name in list should be rejected."""
        response = client.post("/api/blackboard/init", json={
            "feature": "Test feature",
            "agents": ["valid-agent", "../../etc/passwd"]
        })
        assert response.status_code == 422

    def test_feature_too_long_rejected(self):
        """Feature description exceeding max length should be rejected."""
        response = client.post("/api/blackboard/init", json={
            "feature": "a" * 501,
            "agents": ["test-agent"]
        })
        assert response.status_code == 422

    def test_valid_init_accepted(self):
        """Valid init request should be accepted."""
        response = client.post("/api/blackboard/init", json={
            "feature": "Test feature",
            "agents": ["frontend-dev", "backend-dev", "qa-tester"]
        })
        # May succeed or fail based on system state, but should not be validation error
        assert response.status_code in [200, 400, 503]


class TestSpawnRequestValidation:
    """Test team spawn request validation."""

    def test_valid_spawn_accepted(self):
        """Valid spawn request should be accepted."""
        response = client.post("/api/team/spawn", json={
            "prompt": "Build a feature",
            "project": "workspace"
        })
        # Should not fail on validation
        assert response.status_code != 422

    def test_prompt_too_long_rejected(self):
        """Prompt exceeding max length should be rejected."""
        response = client.post("/api/team/spawn", json={
            "prompt": "a" * 5001,
            "project": "workspace"
        })
        assert response.status_code == 422

    def test_custom_agents_with_invalid_name_rejected(self):
        """Custom agents with invalid names should be rejected."""
        response = client.post("/api/team/spawn", json={
            "prompt": "Build a feature",
            "project": "workspace",
            "agents": ["valid-agent", "<script>alert(1)</script>"]
        })
        assert response.status_code == 422

    def test_custom_agents_too_many_rejected(self):
        """More than 20 custom agents should be rejected."""
        agents = [f"agent-{i}" for i in range(21)]
        response = client.post("/api/team/spawn", json={
            "prompt": "Build a feature",
            "project": "workspace",
            "agents": agents
        })
        assert response.status_code == 422


class TestErrorResponseFormat:
    """Test standardized error response format."""

    def test_validation_error_format(self):
        """Validation errors should have standardized format."""
        response = client.post("/api/blackboard", json={
            "agent": "../../etc/passwd",
            "message": "Test"
        })
        data = response.json()

        # Check structure
        assert "success" in data
        assert data["success"] is False
        assert "error" in data
        assert "type" in data["error"]
        assert "message" in data["error"]

        # Check error type
        assert data["error"]["type"] == "ValidationError"

        # Check message is descriptive
        assert len(data["error"]["message"]) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
