"""
Simple diagnostic test for blackboard concurrency.
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
    add_deliverable,
    load_blackboard,
    clear_blackboard,
)


def simple_worker(agent_name: str, count: int):
    """Just add deliverables."""
    try:
        for i in range(count):
            success = add_deliverable(agent_name, f"file_{i}.py")
            if not success:
                print(f"{agent_name}: Failed to add deliverable {i}")
        return True
    except Exception as e:
        print(f"{agent_name} failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_simple_deliverables():
    """Test just deliverables with 10 agents."""
    print("=" * 70)
    print("SIMPLE DELIVERABLES TEST")
    print("=" * 70)

    clear_blackboard()
    num_agents = 10
    deliverables_per_agent = 20
    agents = [f"agent-{i}" for i in range(num_agents)]

    init_blackboard("Simple Test", agents)

    print(f"\n{num_agents} agents, {deliverables_per_agent} deliverables each")
    print(f"Expected total: {num_agents * deliverables_per_agent}")

    start_time = time.time()
    with mp.Pool(processes=num_agents) as pool:
        results = pool.starmap(simple_worker, [(name, deliverables_per_agent) for name in agents])

    elapsed = time.time() - start_time

    # Check results
    board = load_blackboard()
    if not board:
        print("FAILED: Could not load blackboard")
        return False

    total_deliverables = sum(len(d) for d in board.deliverables.values())
    expected = num_agents * deliverables_per_agent

    print(f"\nCompleted in {elapsed:.2f} seconds")
    print(f"Throughput: {(num_agents * deliverables_per_agent) / elapsed:.1f} ops/sec")
    print(f"\nDeliverables: {total_deliverables} / {expected}")

    # Show per-agent breakdown
    print("\nPer-agent breakdown:")
    for agent in agents:
        count = len(board.deliverables.get(agent, []))
        status = "OK" if count == deliverables_per_agent else f"LOST {deliverables_per_agent - count}"
        print(f"  {agent}: {count}/{deliverables_per_agent} {status}")

    loss_pct = ((expected - total_deliverables) / expected * 100) if expected > 0 else 0

    if total_deliverables == expected:
        print(f"\nPASSED: Zero data loss")
        return True
    else:
        print(f"\nFAILED: Lost {expected - total_deliverables} deliverables ({loss_pct:.1f}%)")
        return False


if __name__ == "__main__":
    success = test_simple_deliverables()
    sys.exit(0 if success else 1)
