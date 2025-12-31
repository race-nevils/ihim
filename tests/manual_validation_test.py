"""
Manual validation test - run without pytest.
Tests the Pydantic models directly.
"""
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from api.main import (
    BlackboardMessageRequest,
    BlackboardInitRequest,
    SpawnRequest,
)
from pydantic import ValidationError


def test_valid_request():
    """Test that valid requests work."""
    print("\n[TEST] Valid message request...")
    try:
        msg = BlackboardMessageRequest(
            agent="frontend-dev",
            message="Test message",
            msg_type="DONE"
        )
        print(f"  PASS: {msg.agent}, {msg.message}")
    except ValidationError as e:
        print(f"  FAIL: {e}")
        return False
    return True


def test_path_traversal():
    """Test that path traversal is blocked."""
    print("\n[TEST] Path traversal in agent name...")
    try:
        msg = BlackboardMessageRequest(
            agent="../../etc/passwd",
            message="Test"
        )
        print(f"  FAIL: Should have been rejected, got {msg.agent}")
        return False
    except ValidationError as e:
        print(f"  PASS: Blocked - {e.errors()[0]['msg']}")
        return True


def test_xss_attempt():
    """Test that XSS is blocked."""
    print("\n[TEST] XSS in agent name...")
    try:
        msg = BlackboardMessageRequest(
            agent="<script>alert(1)</script>",
            message="Test"
        )
        print(f"  FAIL: Should have been rejected")
        return False
    except ValidationError as e:
        print(f"  PASS: Blocked - {e.errors()[0]['msg']}")
        return True


def test_message_too_long():
    """Test that oversized messages are blocked."""
    print("\n[TEST] Message exceeding max length...")
    try:
        msg = BlackboardMessageRequest(
            agent="test-agent",
            message="a" * 5001
        )
        print(f"  FAIL: Should have been rejected")
        return False
    except ValidationError as e:
        print(f"  PASS: Blocked - {e.errors()[0]['msg']}")
        return True


def test_empty_agents_list():
    """Test that empty agents list is blocked."""
    print("\n[TEST] Empty agents list...")
    try:
        init = BlackboardInitRequest(
            feature="Test",
            agents=[]
        )
        print(f"  FAIL: Should have been rejected")
        return False
    except ValidationError as e:
        print(f"  PASS: Blocked - {e.errors()[0]['msg']}")
        return True


def test_too_many_agents():
    """Test that too many agents are blocked."""
    print("\n[TEST] More than 20 agents...")
    agents = [f"agent-{i}" for i in range(21)]
    try:
        init = BlackboardInitRequest(
            feature="Test",
            agents=agents
        )
        print(f"  FAIL: Should have been rejected")
        return False
    except ValidationError as e:
        print(f"  PASS: Blocked - {e.errors()[0]['msg']}")
        return True


def test_invalid_agent_in_list():
    """Test that invalid agent names in list are blocked."""
    print("\n[TEST] Invalid agent name in init list...")
    try:
        init = BlackboardInitRequest(
            feature="Test",
            agents=["valid-agent", "../../etc/passwd"]
        )
        print(f"  FAIL: Should have been rejected")
        return False
    except ValidationError as e:
        print(f"  PASS: Blocked - {e.errors()[0]['msg']}")
        return True


def test_invalid_msg_type():
    """Test that invalid message types are blocked."""
    print("\n[TEST] Invalid message type (lowercase)...")
    try:
        msg = BlackboardMessageRequest(
            agent="test-agent",
            message="Test",
            msg_type="invalid-type"
        )
        print(f"  FAIL: Should have been rejected")
        return False
    except ValidationError as e:
        print(f"  PASS: Blocked - {e.errors()[0]['msg']}")
        return True


def test_valid_spawn():
    """Test that valid spawn request works."""
    print("\n[TEST] Valid spawn request...")
    try:
        spawn = SpawnRequest(
            prompt="Build a feature",
            project="workspace"
        )
        print(f"  PASS: {spawn.prompt[:30]}...")
        return True
    except ValidationError as e:
        print(f"  FAIL: {e}")
        return False


def test_spawn_with_custom_agents():
    """Test spawn with custom agents."""
    print("\n[TEST] Spawn with valid custom agents...")
    try:
        spawn = SpawnRequest(
            prompt="Build a feature",
            project="workspace",
            agents=["frontend-dev", "backend-dev"]
        )
        print(f"  PASS: {len(spawn.agents)} agents")
        return True
    except ValidationError as e:
        print(f"  FAIL: {e}")
        return False


def test_spawn_invalid_agent_names():
    """Test that spawn with invalid agent names is blocked."""
    print("\n[TEST] Spawn with invalid agent names...")
    try:
        spawn = SpawnRequest(
            prompt="Build a feature",
            project="workspace",
            agents=["valid-agent", "<script>alert(1)</script>"]
        )
        print(f"  FAIL: Should have been rejected")
        return False
    except ValidationError as e:
        print(f"  PASS: Blocked - {e.errors()[0]['msg']}")
        return True


def main():
    """Run all tests."""
    print("=" * 60)
    print("Input Validation Tests")
    print("=" * 60)

    tests = [
        test_valid_request,
        test_path_traversal,
        test_xss_attempt,
        test_message_too_long,
        test_empty_agents_list,
        test_too_many_agents,
        test_invalid_agent_in_list,
        test_invalid_msg_type,
        test_valid_spawn,
        test_spawn_with_custom_agents,
        test_spawn_invalid_agent_names,
    ]

    results = []
    for test in tests:
        results.append(test())

    print("\n" + "=" * 60)
    print(f"Results: {sum(results)}/{len(results)} tests passed")
    print("=" * 60)

    if all(results):
        print("\nALL TESTS PASSED")
        return 0
    else:
        print("\nSOME TESTS FAILED")
        return 1


if __name__ == "__main__":
    sys.exit(main())
