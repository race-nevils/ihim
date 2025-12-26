# Blackboard Protocol

How agents communicate and collaborate during feature builds.

---

## Overview

The blackboard (`team/blackboard.json`) is a shared file all agents read/write.
Agents poll it every ~8-12 seconds (staggered to avoid conflicts).

## Phases

| Phase | What Happens | Who's Active |
|-------|--------------|--------------|
| **build** | Everyone works in parallel on their specialty | All agents |
| **sync** | Share what you built, read what others built | All agents |
| **integrate** | Wire things together, fix mismatches | Frontend, Backend, DevOps |
| **verify** | DevOps registers action, restarts server, tests | DevOps only |
| **complete** | Feature is done and working | None |

## Message Types

| Type | When to Use | Example |
|------|-------------|---------|
| `status` | Status update | "Started working on API endpoint" |
| `deliverable` | You created something | "Created /api/flightpath/structure endpoint" |
| `question` | Need info from another agent | "@frontend-dev What component should I integrate with?" |
| `answer` | Responding to a question | "The FlightPath component in index.html" |
| `blocker` | You're stuck | "Need database schema from backend-dev" |
| `resolved` | Blocker fixed | "Got the schema, continuing" |
| `ready` | Finished current phase | "Finished build phase" |

## Message Format

```json
{
  "id": "a1b2c3d4",
  "timestamp": "2025-12-26T10:30:00",
  "agent": "frontend-dev",
  "type": "question",
  "content": "What's the API response format?",
  "target": "backend-dev",
  "ref": null
}
```

- `target`: Set to agent name for direct message, `null` for broadcast
- `ref`: Reference to another message ID (for answers/resolutions)

## Agent Responsibilities

### During BUILD Phase
1. Start: `agent_start("your-agent-name")`
2. Work on your specialty
3. Post deliverables: `agent_deliver("your-name", "description", ["file1", "file2"])`
4. If stuck: `agent_blocked("your-name", "what's blocking you")`
5. When done: `agent_done_phase("your-name", Phase.PHASE_1_BUILD)`

### During SYNC Phase
1. Read the blackboard - see what others built
2. Post any info others might need
3. Answer any questions targeted at you
4. Signal ready: `agent_done_phase("your-name", Phase.PHASE_2_SYNC)`

### During INTEGRATE Phase
1. Read deliverables from other agents
2. Wire your work to theirs (API calls, imports, etc.)
3. Fix any mismatches (endpoint names, response formats)
4. Post what you integrated
5. Signal ready: `agent_done_phase("your-name", Phase.PHASE_3_INTEGRATE)`

### During VERIFY Phase (DevOps Only)
1. Register action in `actions/registry.py`
2. Restart the server (localhost:7777)
3. Verify the button appears
4. Click it and verify it works
5. If broken, post blocker - agents fix in integrate phase
6. If works, advance to COMPLETE

## Polling

Agents check the blackboard every 8-12 seconds (staggered):

```python
from team.blackboard import poll_loop, load_blackboard

def on_update(board, new_messages):
    # Check for questions targeted at you
    for msg in new_messages:
        if msg.type == "question" and msg.target == "your-agent":
            # Answer it
            agent_answer("your-agent", msg.id, "Your answer here")

# Start polling (runs in background)
poll_loop("your-agent", on_update)
```

## Example Flow

```
[00:00] Blackboard initialized, Phase: BUILD
[00:01] frontend-dev: STATUS "Starting UI work"
[00:01] backend-dev: STATUS "Starting API work"
[00:15] backend-dev: DELIVERABLE "Created /api/flightpath/structure"
[00:20] frontend-dev: QUESTION @backend-dev "Response format?"
[00:28] backend-dev: ANSWER "{ nodes: [], edges: [] }"
[00:45] frontend-dev: DELIVERABLE "Created FlightPath modal"
[01:00] All agents: READY "Finished build phase"
[01:00] Phase advances to SYNC
[01:10] Agents read each other's deliverables
[01:30] Phase advances to INTEGRATE
[01:35] frontend-dev: Updated API call to match backend endpoint
[02:00] Phase advances to VERIFY
[02:05] devops: Registered flight_path action
[02:10] devops: Restarted server
[02:15] devops: Verified button works
[02:20] Phase advances to COMPLETE
```

## Anti-Patterns

- **Don't poll too fast** - stick to 8-12 second intervals
- **Don't wait silently** - if blocked, POST a blocker message
- **Don't assume** - if you need info, ASK via question message
- **Don't skip phases** - wait for phase to advance before moving on
