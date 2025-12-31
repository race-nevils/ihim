"""
Test the EXACT bug scenario: 10 agents writing simultaneously.

This test simulates the scenario where data loss was 70-90%.
With the fix, we expect 0% data loss.
"""

import sys
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
    load_blackboard,
    clear_blackboard,
)


def agent_10x_writes(agent_name: str):
    """
    Simulate 10 simultaneous operations per agent.
    Each agent does the same operations at roughly the same time.
    """
    try:
        # Operation 1: Post status
        post_message(agent_name, "Starting work", msg_type="STATUS")

        # Operation 2: Update status
        update_status(agent_name, "working")

        # Operations 3-7: Add deliverables
        for i in range(5):
            add_deliverable(agent_name, f"{agent_name}_file_{i}.py")

        # Operation 8: Post progress
        post_message(agent_name, "Halfway done", msg_type="STATUS")

        # Operation 9: Final status update
        update_status(agent_name, "finishing")

        # Operation 10: Mark done
        agent_done(agent_name, f"{agent_name} completed all work")

        return True
    except Exception as e:
        print(f"{agent_name} FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    print("=" * 80)
    print("10 AGENTS SIMULTANEOUS WRITE TEST")
    print("=" * 80)
    print("\nThis test simulates the exact scenario where 70-90% data loss occurred.")
    print("Expected with fix: 0% data loss\n")

    # Setup
    clear_blackboard()
    agents = [f"agent-{i}" for i in range(10)]
    init_blackboard("10 Agent Simultaneous Test", agents)

    print(f"Starting {len(agents)} agents simultaneously...")
    print("Each agent performs 10 operations:")
    print("  - 2 post_message calls")
    print("  - 2 update_status calls")
    print("  - 5 add_deliverable calls")
    print("  - 1 agent_done call (status + message)")
    print()

    # Launch all agents at once
    with mp.Pool(processes=len(agents)) as pool:
        results = pool.map(agent_10x_writes, agents)

    # Verify
    board = load_blackboard()
    if not board:
        print("FAILED: Could not load blackboard")
        return False

    # Expected counts
    # Messages: 2 STATUS + 1 DONE = 3 per agent
    # Deliverables: 5 per agent
    # Status updates: Each agent should have status = "complete" (from agent_done)

    total_messages = len(board.messages)
    done_messages = len([m for m in board.messages if m.type == "DONE"])
    status_messages = len([m for m in board.messages if m.type == "STATUS"])
    total_deliverables = sum(len(d) for d in board.deliverables.values())
    complete_agents = len([a for a, s in board.agent_status.items() if s == "complete"])

    expected_messages = len(agents) * 3  # 2 STATUS + 1 DONE
    expected_deliverables = len(agents) * 5
    expected_done = len(agents)
    expected_status = len(agents) * 2
    expected_complete = len(agents)

    print("=" * 80)
    print("RESULTS")
    print("=" * 80)
    print(f"Messages:        {total_messages} / {expected_messages} expected")
    print(f"  - STATUS:      {status_messages} / {expected_status} expected")
    print(f"  - DONE:        {done_messages} / {expected_done} expected")
    print(f"Deliverables:    {total_deliverables} / {expected_deliverables} expected")
    print(f"Complete agents: {complete_agents} / {expected_complete} expected")
    print()

    # Calculate loss
    message_loss = expected_messages - total_messages
    deliverable_loss = expected_deliverables - total_deliverables
    status_loss = expected_complete - complete_agents

    total_ops = expected_messages + expected_deliverables + expected_complete
    total_loss = message_loss + deliverable_loss + status_loss
    loss_pct = (total_loss / total_ops * 100) if total_ops > 0 else 0

    # Check success
    success = (
        total_messages == expected_messages and
        total_deliverables == expected_deliverables and
        complete_agents == expected_complete
    )

    if success:
        print("=" * 80)
        print("TEST PASSED: ZERO DATA LOSS")
        print("=" * 80)
        print("\nThe concurrency fixes work perfectly!")
        print("All 10 agents wrote simultaneously with no conflicts.")
    else:
        print("=" * 80)
        print(f"TEST FAILED: {loss_pct:.1f}% DATA LOSS")
        print("=" * 80)
        print(f"\nLost operations:")
        print(f"  - Messages: {message_loss}")
        print(f"  - Deliverables: {deliverable_loss}")
        print(f"  - Status updates: {status_loss}")
        print(f"  - Total: {total_loss} / {total_ops}")

    return success


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
