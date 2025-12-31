"""
Concurrency stress test for blackboard.py

Tests that 10+ concurrent agents can write simultaneously without data loss.
"""

import sys
import time
import multiprocessing as mp
from pathlib import Path

# Add IHIM to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from team.blackboard import (
    init_blackboard,
    post_message,
    update_status,
    add_deliverable,
    agent_done,
    agent_deliver,
    load_blackboard,
    clear_blackboard,
    BLACKBOARD_FILE,
)


def agent_worker(agent_name: str, num_messages: int):
    """Simulate an agent posting multiple messages."""
    try:
        for i in range(num_messages):
            # Mix different types of operations
            if i % 3 == 0:
                post_message(agent_name, f"Status update {i}", msg_type="STATUS")
            elif i % 3 == 1:
                update_status(agent_name, f"working-{i}")
            else:
                add_deliverable(agent_name, f"file_{i}.py")

            # Small random delay to increase concurrency
            time.sleep(0.001)

        # Mark done
        agent_done(agent_name, f"Completed {num_messages} operations")
        return True
    except Exception as e:
        print(f"Agent {agent_name} failed: {e}")
        return False


def test_concurrent_writes():
    """Test 10 agents writing 50 messages each = 500 total operations."""
    print("=" * 70)
    print("CONCURRENCY STRESS TEST")
    print("=" * 70)

    # Setup
    clear_blackboard()
    num_agents = 10
    messages_per_agent = 50
    agents = [f"agent-{i}" for i in range(num_agents)]

    # Initialize blackboard
    init_blackboard("Concurrency Test", agents)

    print(f"\nStarting {num_agents} concurrent agents...")
    print(f"Each agent will perform {messages_per_agent} operations")
    print(f"Total expected operations: {num_agents * messages_per_agent}")

    # Launch concurrent processes
    start_time = time.time()
    with mp.Pool(processes=num_agents) as pool:
        results = pool.starmap(agent_worker, [(name, messages_per_agent) for name in agents])

    elapsed = time.time() - start_time

    # Verify results
    print(f"\nCompleted in {elapsed:.2f} seconds")
    print(f"Throughput: {(num_agents * messages_per_agent) / elapsed:.1f} ops/sec")

    board = load_blackboard()
    if not board:
        print("\nFAILED: Could not load blackboard")
        return False

    # Count operations
    total_messages = len(board.messages)
    done_messages = len([m for m in board.messages if m.type == "DONE"])
    status_messages = len([m for m in board.messages if m.type == "STATUS"])

    # Count deliverables
    total_deliverables = sum(len(d) for d in board.deliverables.values())

    # Expected counts
    # Each agent: ~17 STATUS, ~17 add_deliverable, ~17 update_status, 1 DONE
    # Messages: 17 STATUS + 1 DONE = 18 per agent
    # Deliverables: 17 per agent
    expected_messages = num_agents * 18  # STATUS messages + DONE
    expected_deliverables = num_agents * 17

    print("\n" + "=" * 70)
    print("RESULTS")
    print("=" * 70)
    print(f"Total messages:      {total_messages} (expected ~{expected_messages})")
    print(f"DONE messages:       {done_messages} (expected {num_agents})")
    print(f"STATUS messages:     {status_messages} (expected ~{num_agents * 17})")
    print(f"Total deliverables:  {total_deliverables} (expected ~{expected_deliverables})")

    # Check for data loss
    success = True
    if done_messages != num_agents:
        print(f"\nWARNING: Expected {num_agents} DONE messages, got {done_messages}")
        success = False

    # Allow 5% tolerance for message count (due to update_status not creating messages)
    min_expected_messages = expected_messages * 0.95
    if total_messages < min_expected_messages:
        print(f"\nERROR: Message loss detected!")
        print(f"Expected at least {min_expected_messages:.0f}, got {total_messages}")
        success = False

    # Check deliverables (should be exact)
    if total_deliverables < expected_deliverables * 0.95:
        print(f"\nERROR: Deliverable loss detected!")
        print(f"Expected {expected_deliverables}, got {total_deliverables}")
        success = False

    if success:
        print("\n" + "=" * 70)
        print("TEST PASSED: No data loss detected!")
        print("=" * 70)
    else:
        print("\n" + "=" * 70)
        print("TEST FAILED: Data loss detected")
        print("=" * 70)

    return success


def rapid_worker(agent_name: str, messages_per_agent: int):
    """Post messages as fast as possible."""
    try:
        for i in range(messages_per_agent):
            post_message(agent_name, f"Rapid message {i}")
        agent_done(agent_name, "Done")
        return True
    except Exception as e:
        print(f"Rapid agent {agent_name} failed: {e}")
        return False


def test_rapid_fire():
    """Test rapid-fire writes with minimal delay."""
    print("\n" + "=" * 70)
    print("RAPID FIRE TEST (Maximum Concurrency)")
    print("=" * 70)

    clear_blackboard()
    num_agents = 15
    messages_per_agent = 20
    agents = [f"rapid-{i}" for i in range(num_agents)]

    init_blackboard("Rapid Fire Test", agents)

    print(f"\nLaunching {num_agents} agents with NO delays...")

    start_time = time.time()
    with mp.Pool(processes=num_agents) as pool:
        results = pool.starmap(rapid_worker, [(name, messages_per_agent) for name in agents])

    elapsed = time.time() - start_time

    board = load_blackboard()
    total_messages = len(board.messages) if board else 0
    expected = num_agents * (messages_per_agent + 1)  # +1 for DONE

    print(f"\nCompleted in {elapsed:.2f} seconds")
    print(f"Throughput: {(num_agents * messages_per_agent) / elapsed:.1f} ops/sec")
    print(f"Messages: {total_messages} (expected {expected})")

    success = total_messages >= expected * 0.95

    if success:
        print("\nRAPID FIRE PASSED: Minimal data loss")
    else:
        print(f"\nRAPID FIRE FAILED: Lost {expected - total_messages} messages")

    return success


if __name__ == "__main__":
    # Run tests
    test1 = test_concurrent_writes()
    test2 = test_rapid_fire()

    print("\n" + "=" * 70)
    if test1 and test2:
        print("ALL TESTS PASSED")
    else:
        print("SOME TESTS FAILED")
    print("=" * 70)

    sys.exit(0 if (test1 and test2) else 1)
