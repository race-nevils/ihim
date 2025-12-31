# BLACKBOARD SYSTEM

Agent coordination substrate for multi-agent team collaboration via shared memory.

Updated: 2025-12-28

---

## Quick Reference

| Component | Location | Type |
|-----------|----------|------|
| Core module | `IHIM/team/blackboard.py` | Python library |
| Data file | `IHIM/team/blackboard.json` | JSON shared state |
| API endpoints | `IHIM/api/main.py` | REST API (port 7777) |
| Lock mechanism | portalocker | Cross-platform file locking |
| Default poll interval | 8-12 seconds | Staggered by agent |

---

## 1. SYSTEM OVERVIEW

### Purpose

The Blackboard System is a shared communication layer enabling multi-agent coordination through message passing and status synchronization. Agents write status updates, deliverables, questions, and blockers to a central JSON file, which other agents poll to coordinate work.

### Design Principles

1. **Simple JSON format** - Easy for any agent to read/write
2. **Minimal schema** - 3 core fields (agent, timestamp, message), 2 optional (type, to)
3. **Natural adaptation** - Agents write naturally, system handles schema flexibility
4. **File-based persistence** - No database dependency, works offline
5. **Lock-based atomicity** - Cross-platform file locking prevents corruption

### Execution Model

```
Agent spawned
    ↓
Initialize with blackboard awareness
    ↓
Poll blackboard every ~8-12s (staggered)
    ↓
Read new messages since last poll
    ↓
Filter to relevant messages (broadcast or targeted)
    ↓
Execute callback with updates
    ↓
Post status/questions/deliverables
    ↓
Mark DONE when complete
    ↓
Wait for phase transition
```

### Communication Patterns

- **Broadcast**: `to=None` - visible to all agents
- **Directed**: `to="agent-name"` - targeted at specific agent
- **Status Updates**: Regular progress messages
- **Questions**: Async Q&A between agents
- **Blockers**: Escalation signals
- **Deliverables**: File/endpoint tracking
- **Phase Coordination**: Synchronized workflow progression

---

## 2. COMPONENTS

### 2.1 Core Module (`blackboard.py`)

**Path**: `C:\Users\<user>\workspace\IHIM\team\blackboard.py`

**Key Classes**:
- `Message`: Individual message record
  - Fields: agent, timestamp, message, type (optional), to (optional)
  - Serialization: Uses `from` key for agent (JSON), `agent` in Python
- `Blackboard`: Shared state container
  - Fields: feature, phase, started_at, messages, agent_status, deliverables
  - Methods: to_dict(), from_dict()
- `Phase`: Enum for workflow phases
  - PHASE_1_BUILD → PHASE_2_SYNC → PHASE_3_INTEGRATE → PHASE_4_VERIFY → COMPLETE

**Key Functions**:

| Function | Purpose | Thread-Safe |
|----------|---------|-------------|
| `init_blackboard()` | Create fresh board | Yes (atomic write) |
| `load_blackboard()` | Read current state | Yes (shared lock) |
| `save_blackboard()` | Write state | Yes (exclusive lock) |
| `atomic_update()` | Read-modify-write | Yes (exclusive lock) |
| `post_message()` | Add message | Yes (uses atomic_update) |
| `update_status()` | Change agent status | Yes (uses atomic_update) |
| `add_deliverable()` | Record file created | Yes (uses atomic_update) |
| `check_phase_ready()` | All agents done? | Yes (read-only) |
| `advance_phase()` | Move to next phase | Yes (atomic update) |

**Convenience Functions** (agent-friendly API):
- `agent_post()` - Post general message
- `agent_done()` - Mark complete + summary
- `agent_ask()` - Ask another agent
- `agent_deliver()` - Record deliverable
- `agent_blocked()` - Report blocker

### 2.2 Data File (`blackboard.json`)

**Path**: `C:\Users\<user>\workspace\IHIM\team\blackboard.json`

**Schema**:
```json
{
  "feature": "What we're building",
  "phase": "build|sync|integrate|verify|complete",
  "started_at": "2025-12-27T22:29:42.181819",
  "messages": [
    {
      "from": "agent-name",
      "timestamp": "2025-12-27T22:29:42.780172",
      "message": "Status update text",
      "type": "STATUS|DONE|QUESTION|DELIVERABLE|BLOCKER",
      "to": "target-agent-name or null"
    }
  ],
  "agent_status": {
    "agent-1": "starting|working|complete|blocked"
  },
  "deliverables": {
    "agent-1": ["file1.py", "file2.py"]
  }
}
```

**Validation Rules**:
- Agent list cannot be empty (raises ValueError on init)
- Empty strings preserved (not treated as None)
- Phase must match Phase enum values
- Timestamps in ISO 8601 format

### 2.3 API Endpoints (`main.py`)

**Base URL**: `http://localhost:7777`

| Endpoint | Method | Purpose | Request Body |
|----------|--------|---------|--------------|
| `/api/blackboard` | GET | Get current state summary | - |
| `/api/blackboard/messages` | GET | Get messages (filtered) | Query: type, for_agent |
| `/api/blackboard/blockers` | GET | Get blocker messages | - |
| `/api/blackboard` | POST | Post message | agent, message, msg_type, to |
| `/api/blackboard/status` | POST | Update agent status | agent, status |
| `/api/blackboard/deliverable` | POST | Record deliverable | agent, deliverable |
| `/api/blackboard/done` | POST | Mark agent complete | agent, summary |
| `/api/blackboard/blocked` | POST | Report blocker | agent, blocker |
| `/api/blackboard/init` | POST | Initialize new board | feature, agents[] |
| `/api/blackboard` | DELETE | Clear/reset board | - |

**Response Format**:
```json
{
  "success": true,
  "data": { ... },
  "message": "Human-readable status"
}
```

**Error Responses**:
- 400 - BlackboardNotInitialized, InvalidRequest
- 500 - InternalError, FileOperationFailed

### 2.4 File Locking (`portalocker`)

**Library**: `portalocker` (cross-platform)

**Lock Types**:
- `LOCK_SH` - Shared lock (multiple readers)
- `LOCK_EX` - Exclusive lock (single writer)

**Lock Strategy**:
- **Read** (load_blackboard): Shared lock, 30s timeout
- **Write** (save_blackboard): Exclusive lock, 30s timeout
- **Update** (atomic_update): Exclusive lock for read-modify-write

**Retry Logic**:
- Max retries: 10 attempts
- Backoff: Exponential (0.1s * 2^attempt)
- Timeout: 30 seconds per lock attempt

---

## 3. DATA FLOW

### 3.1 Message Lifecycle

```
Agent posts message
    ↓
atomic_update() acquires exclusive lock
    ↓
Read current blackboard.json
    ↓
Append new message to messages[]
    ↓
Write back to blackboard.json
    ↓
Release lock
    ↓
Other agents poll (8-12s interval)
    ↓
Load blackboard with shared lock
    ↓
Check messages since last poll
    ↓
Filter relevant messages
    ↓
Execute callback with updates
```

### 3.2 Phase Transition Flow

```
All agents in Phase 1 (BUILD)
    ↓
Each agent posts DONE message
    ↓
check_phase_ready() polls agent_status
    ↓
All agents status = "complete" OR posted DONE?
    ↓ Yes
advance_phase() called
    ↓
atomic_update() changes phase to PHASE_2_SYNC
    ↓
Agents detect phase change on next poll
    ↓
Agents begin Phase 2 work
```

### 3.3 Agent Coordination Pattern

**Parallel Work (Phase 1: BUILD)**:
```
10 agents spawn simultaneously
    ↓
Each works on independent component
    ↓
Post STATUS updates periodically
    ↓
Ask QUESTIONS to other agents
    ↓
Record DELIVERABLES as files created
    ↓
Post DONE when complete
```

**Synchronization (Phase 2: SYNC)**:
```
All agents read each other's DELIVERABLE messages
    ↓
Understand what components exist
    ↓
Post integration points needed
    ↓
Mark DONE when sync complete
```

**Integration (Phase 3: INTEGRATE)**:
```
DevOps agent wires components together
    ↓
Other agents assist with config/imports
    ↓
Post blockers if integration issues found
    ↓
Mark DONE when integration complete
```

### 3.4 Polling Mechanism

**Staggered Intervals**:
- Base interval: 8 seconds
- Jitter: ±2 seconds (random)
- Agent offset: 0-4 seconds (hash-based)
- Result: 6-14 second range, spread across time

**Purpose**: Prevent all 10 agents hitting file simultaneously

**Implementation**:
```python
agent_hash = int(hashlib.md5(agent.encode()).hexdigest()[:4], 16)
offset = (agent_hash % 5)  # 0-4 second deterministic offset
jitter = random.uniform(-2.0, 2.0)  # ±2 seconds random
interval = 8.0 + offset + jitter
```

---

## 4. HEALTH METRICS

### 4.1 Message Throughput

**Definition**: Messages written per minute across all agents

**Calculation**:
```python
messages_last_minute = [
    m for m in board.messages
    if parse_time(m.timestamp) > (now - 60s)
]
throughput = len(messages_last_minute)
```

**Normal Range**: 5-30 messages/minute for 10 agents

**Alerts**:
- **Low** (<2/min): Agents may be stalled
- **High** (>60/min): Possible polling storm or infinite loop

**Exposed Via**: `/api/blackboard/health/throughput`

### 4.2 Lock Contention

**Definition**: Failed lock acquisition attempts / total attempts

**Measurement Points**:
- save_blackboard() failures
- load_blackboard() timeouts
- atomic_update() retry count

**Calculation**:
```python
contention_rate = lock_failures / lock_attempts
avg_retry_count = sum(retries) / successful_locks
```

**Normal Range**:
- Contention rate: 0-5%
- Avg retries: 0-1

**Alerts**:
- **Warning** (>10% contention): High concurrent write load
- **Critical** (>30% contention): Lock timeout failures, data loss risk

**Exposed Via**: `/api/blackboard/health/locks`

### 4.3 Phase Timing

**Definition**: Time spent in each phase

**Tracking**:
```json
{
  "phase_transitions": [
    {"from": "build", "to": "sync", "timestamp": "...", "duration_seconds": 120},
    {"from": "sync", "to": "integrate", "timestamp": "...", "duration_seconds": 45}
  ]
}
```

**Normal Range** (10 agents):
- BUILD: 60-180 seconds
- SYNC: 20-60 seconds
- INTEGRATE: 30-90 seconds
- VERIFY: 20-60 seconds

**Alerts**:
- **Warning** (>300s in BUILD): Agents may be stuck
- **Critical** (>600s in any phase): Likely deadlock

**Exposed Via**: `/api/blackboard/health/phases`

### 4.4 Agent Participation

**Definition**: Active agents vs expected agents

**Calculation**:
```python
expected_agents = len(board.agent_status)
active_agents = len([
    a for a, s in board.agent_status.items()
    if s not in ["blocked", "failed"]
])
participation_rate = active_agents / expected_agents
```

**Normal**: 100% (all agents active)

**Alerts**:
- **Warning** (<90%): 1+ agents blocked/failed
- **Critical** (<70%): Multiple agents down

**Exposed Via**: `/api/blackboard/health/agents`

### 4.5 Message Type Distribution

**Definition**: Breakdown of message types

**Calculation**:
```python
type_counts = {
    "STATUS": 0,
    "DONE": 0,
    "QUESTION": 0,
    "DELIVERABLE": 0,
    "BLOCKER": 0,
    "null": 0
}
for msg in board.messages:
    type_counts[msg.type or "null"] += 1
```

**Normal Pattern** (10 agents, BUILD phase):
- STATUS: 50-70%
- DONE: 10-15% (near end)
- QUESTION: 5-10%
- DELIVERABLE: 10-20%
- BLOCKER: 0-5%

**Alerts**:
- **Warning** (>10% BLOCKER): Multiple blockers
- **Critical** (>20% QUESTION, <5% STATUS): Communication breakdown

**Exposed Via**: `/api/blackboard/health/message-types`

---

## 5. DEGRADATION PATTERNS

### 5.1 the operator Conditions

**Symptom**: Messages appear out of order, duplicate status updates, lost deliverables

**Root Cause**: Multiple agents writing simultaneously without proper locking

**Detection**:
```python
# Check for timestamp inversions
for i in range(1, len(messages)):
    if messages[i].timestamp < messages[i-1].timestamp:
        alert("race condition detected: timestamp inversion")

# Check for duplicate DONE messages from same agent
done_counts = {}
for msg in messages:
    if msg.type == "DONE":
        done_counts[msg.agent] = done_counts.get(msg.agent, 0) + 1
for agent, count in done_counts.items():
    if count > 1:
        alert(f"race condition: {agent} posted DONE {count} times")
```

**Prevention**:
- Use atomic_update() for all writes
- Never bypass file locking
- Respect lock timeouts (don't force)

**Recovery**:
- Detect via timestamp analysis
- Manual deduplication of messages
- Reset affected agents to retry

### 5.2 Data Loss

**Symptom**: Messages posted but not appearing in blackboard.json, deliverables missing

**Root Cause**: Lock timeout, write failure, file corruption

**Detection**:
```python
# Agent posts message but doesn't see it on next poll
posted_at = "2025-12-27T22:30:00"
poll_result = load_blackboard()
if not any(m.timestamp >= posted_at for m in poll_result.messages):
    alert("Data loss: message not persisted")

# Deliverable count mismatch
api_deliverable_count = len(agent_deliverables_via_api)
file_deliverable_count = len(board.deliverables[agent])
if api_deliverable_count != file_deliverable_count:
    alert(f"Data loss: {api_deliverable_count - file_deliverable_count} deliverables missing")
```

**Prevention**:
- Monitor save_blackboard() return values (should be True)
- Log all failed lock acquisitions
- Increase lock timeout if consistent failures

**Recovery**:
- Check API logs for failed writes
- Reconstruct messages from agent result files
- Re-run affected agents if critical data lost

### 5.3 Stale Locks

**Symptom**: Lock acquisition always times out, blackboard frozen

**Root Cause**: Agent crash while holding lock, OS not releasing file lock

**Detection**:
```python
# All lock attempts failing for extended period
lock_failures_last_5min = count_failures(now - 300s, now)
if lock_failures_last_5min > 50:
    alert("Stale lock suspected: >50 failures in 5 minutes")

# File locked by process that no longer exists
lock_holder_pid = get_lock_holder(BLACKBOARD_FILE)
if not process_exists(lock_holder_pid):
    alert(f"Stale lock: PID {lock_holder_pid} not running")
```

**Prevention**:
- Use portalocker with timeout (prevents indefinite holds)
- Ensure agents have proper cleanup on exit
- Monitor agent health, kill hung processes

**Recovery**:
- Force unlock (OS-specific):
  - Windows: `handle -c <handle_id>` (Sysinternals)
  - Linux: `lsof IHIM/team/blackboard.json | kill <PID>`
- Restart iHIM server (releases all locks)
- Restore from backup if file corrupted

### 5.4 Polling Storm

**Symptom**: High CPU usage, blackboard.json locked constantly, slow performance

**Root Cause**: Polling interval too short, too many agents polling, synchronization failure

**Detection**:
```python
# File access frequency
file_access_rate = count_file_opens_last_minute() / 60
if file_access_rate > 60:  # >1 access/second
    alert(f"Polling storm: {file_access_rate} accesses/sec")

# Lock acquisition rate
lock_rate = lock_attempts_last_minute / 60
if lock_rate > 100:
    alert(f"Lock contention high: {lock_rate} attempts/sec")
```

**Prevention**:
- Use staggered polling (8-12s interval)
- Avoid synchronous polling (all agents at once)
- Implement exponential backoff on errors

**Recovery**:
- Increase poll interval temporarily
- Kill and restart agents in waves (not all at once)
- Check for infinite polling loops in agent code

### 5.5 Phase Deadlock

**Symptom**: All agents stuck in same phase, no progress, check_phase_ready() never returns True

**Root Cause**: Agent never marks DONE, agent crashed before DONE, logic error in phase_ready check

**Detection**:
```python
# Phase duration exceeded
phase_start = parse_time(board.started_at)
phase_duration = now - phase_start
if phase_duration > 600:  # 10 minutes
    alert(f"Phase deadlock: stuck in {board.phase} for {phase_duration}s")

# Incomplete agents
incomplete = [
    agent for agent, status in board.agent_status.items()
    if status != "complete"
]
done_agents = get_done_agents()
missing_done = [a for a in incomplete if a not in done_agents]
if len(missing_done) > 0 and phase_duration > 120:
    alert(f"Phase deadlock: agents {missing_done} never marked DONE")
```

**Prevention**:
- Set timeout on phase duration
- Force-fail agents that exceed time budget
- Validate check_phase_ready() logic (== not >=)

**Recovery**:
- Manual DONE injection for stuck agents
- Force phase advance (skip stuck agents)
- Restart stuck agents individually

---

## 6. RECOVERY PROCEDURES

### 6.1 Reset Blackboard

**When**: Fresh start needed, corruption detected, testing

**Procedure**:
```bash
# Via API
curl -X DELETE http://localhost:7777/api/blackboard

# Via file
rm C:/Users/<user>/workspace/IHIM/team/blackboard.json

# Via Python
from team.blackboard import clear_blackboard
clear_blackboard()
```

**Side Effects**:
- All message history lost
- All agent status reset
- Deliverables tracking cleared
- Phase reset to PHASE_1_BUILD

**Post-Reset**:
```bash
# Reinitialize with new agents
curl -X POST http://localhost:7777/api/blackboard/init \
  -H "Content-Type: application/json" \
  -d '{"feature": "New feature", "agents": ["agent-1", "agent-2"]}'
```

### 6.2 Corruption Recovery

**When**: blackboard.json is malformed, cannot be parsed

**Detection**:
```python
try:
    board = load_blackboard()
except json.JSONDecodeError as e:
    alert(f"Blackboard corrupted: {e}")
```

**Procedure**:
1. **Backup corrupted file**:
   ```bash
   cp blackboard.json blackboard.json.corrupt.$(date +%s)
   ```

2. **Attempt repair**:
   ```python
   # Load with lenient parser
   import json5  # Handles trailing commas, comments
   with open("blackboard.json") as f:
       data = json5.load(f)

   # Validate and fix schema
   if "messages" not in data:
       data["messages"] = []
   if "agent_status" not in data:
       data["agent_status"] = {}

   # Write repaired version
   with open("blackboard.json", "w") as f:
       json.dump(data, f, indent=2)
   ```

3. **If repair fails, reconstruct from agent results**:
   ```python
   # Gather agent result files
   result_files = glob("IHIM/team/results/*-result.json")

   # Extract messages and deliverables
   messages = []
   deliverables = {}
   for result_file in result_files:
       with open(result_file) as f:
           result = json.load(f)
           messages.extend(result.get("messages", []))
           agent = result["agent"]
           deliverables[agent] = result.get("deliverables", [])

   # Reconstruct blackboard
   board = Blackboard(
       feature="Reconstructed",
       phase=Phase.COMPLETE,
       started_at=min(m["timestamp"] for m in messages),
       messages=[Message.from_dict(m) for m in messages],
       agent_status={agent: "complete" for agent in deliverables.keys()},
       deliverables=deliverables
   )
   save_blackboard(board)
   ```

### 6.3 Deadlock Resolution

**When**: Agents stuck waiting for each other, no progress

**Detection**: See section 5.5 (Phase Deadlock)

**Procedure**:
1. **Identify stuck agents**:
   ```python
   board = load_blackboard()
   incomplete = [
       a for a, s in board.agent_status.items()
       if s != "complete"
   ]
   done_agents = get_done_agents()
   stuck = [a for a in incomplete if a not in done_agents]
   print(f"Stuck agents: {stuck}")
   ```

2. **Check agent logs**:
   ```bash
   # Find last activity from stuck agents
   for agent in stuck:
       grep "$agent" IHIM/configs/execution-logs/*.jsonl | tail -5
   ```

3. **Force DONE if agent completed but didn't mark**:
   ```bash
   curl -X POST http://localhost:7777/api/blackboard/done \
     -H "Content-Type: application/json" \
     -d '{"agent": "stuck-agent", "summary": "Force-completed by operator"}'
   ```

4. **Force phase advance if multiple agents stuck**:
   ```python
   def force_advance():
       def update(board):
           # Mark all incomplete as complete
           for agent in board.agent_status:
               if board.agent_status[agent] != "complete":
                   board.agent_status[agent] = "complete"
       atomic_update(update)
       advance_phase()
   ```

5. **Kill and restart stuck agents**:
   ```bash
   # Find agent processes
   ps aux | grep "stuck-agent"
   kill <PID>

   # Respawn via spawner
   python IHIM/team/spawner.py --agent stuck-agent --resume
   ```

### 6.4 Lock Force Release

**When**: Stale lock preventing all access

**Detection**: See section 5.3 (Stale Locks)

**Procedure**:

**Windows**:
```bash
# Find process holding lock
handle.exe C:\Users\<user>\workspace\IHIM\team\blackboard.json

# Output example:
# python.exe         pid: 12345   type: File
#   C:\Users\<user>\workspace\IHIM\team\blackboard.json

# Close handle (Sysinternals tool)
handle.exe -c <handle_id> -p 12345 -y

# Or kill process
taskkill /PID 12345 /F
```

**Linux/WSL**:
```bash
# Find process holding lock
lsof C:/Users/<user>/workspace/IHIM/team/blackboard.json

# Kill process
kill -9 <PID>
```

**Nuclear Option** (if file system lock persists):
```bash
# Restart iHIM server (releases all locks)
curl -X POST http://localhost:7777/api/system/restart

# If that fails, kill server
pkill -f "python.*IHIM/run.py"

# Then manually delete lock file if exists
rm C:/Users/<user>/workspace/IHIM/team/blackboard.json.lock
```

### 6.5 Message History Cleanup

**When**: blackboard.json growing too large (>10MB), slowing down reads

**Safe Procedure**:
```python
def archive_old_messages(keep_last_n=100):
    """Move old messages to archive, keep recent N."""
    board = load_blackboard()

    # Keep last N messages
    archived = board.messages[:-keep_last_n]
    board.messages = board.messages[-keep_last_n:]

    # Save archive
    archive_file = f"blackboard_archive_{datetime.now().isoformat()}.json"
    with open(f"IHIM/team/archives/{archive_file}", "w") as f:
        json.dump([m.to_dict() for m in archived], f, indent=2)

    # Save cleaned board
    save_blackboard(board)

    print(f"Archived {len(archived)} messages to {archive_file}")
```

**Triggered By**:
- File size check (>5MB = time to archive)
- Message count (>1000 = archive)
- Manual operator command

---

## 7. FLIGHT PATH INTEGRATION

### 7.1 Health Check Endpoints

Expose blackboard metrics via Flight Path monitoring:

| Endpoint | Metric | Update Frequency |
|----------|--------|------------------|
| `/api/blackboard/health/throughput` | Messages/minute | 10s |
| `/api/blackboard/health/locks` | Contention rate, retries | 10s |
| `/api/blackboard/health/phases` | Phase timing, transitions | 10s |
| `/api/blackboard/health/agents` | Participation rate, status | 10s |
| `/api/blackboard/health/message-types` | Type distribution | 10s |
| `/api/blackboard/health/file-size` | blackboard.json size | 60s |

### 7.2 Dashboard Visualization

**SCADA-Style Display**:

```
┌─ BLACKBOARD SYSTEM ─────────────────────────────────────┐
│ Phase: INTEGRATE (2/4) ━━━━━━━━━━░░░░░░░░ 50%          │
│ Started: 2m 34s ago                                      │
│                                                          │
│ AGENTS (8/10 active)                                     │
│ ✓ agent-1  ✓ agent-2  ✓ agent-3  ✓ agent-4             │
│ ✓ agent-5  ✓ agent-6  ⚠ agent-7  ✗ agent-8             │
│ ✓ agent-9  ✓ agent-10                                   │
│                                                          │
│ THROUGHPUT          LOCK CONTENTION      FILE SIZE      │
│ 24 msg/min ▂▃▅▇█    3.2% (low) ▁▁▂▁     1.2 MB ▁▂▂▃    │
│                                                          │
│ MESSAGE TYPES                                            │
│ STATUS      ████████████████████░░ 65%                  │
│ DELIVERABLE ████████░░░░░░░░░░░░░ 18%                  │
│ DONE        ████░░░░░░░░░░░░░░░░░ 12%                  │
│ QUESTION    ██░░░░░░░░░░░░░░░░░░░  4%                  │
│ BLOCKER     █░░░░░░░░░░░░░░░░░░░░  1%                  │
│                                                          │
│ ALERTS                                                   │
│ ⚠ agent-7 blocked: "Waiting for API endpoint spec"     │
│ ✗ agent-8 crashed: "Timeout after 300s"                │
└──────────────────────────────────────────────────────────┘
```

### 7.3 Alert Thresholds

| Metric | Warning | Critical | Action |
|--------|---------|----------|--------|
| Throughput | <2 msg/min | 0 msg/min for 60s | Check agent health |
| Throughput | >60 msg/min | >100 msg/min | Polling storm, kill agents |
| Lock contention | >10% | >30% | Increase timeout, stagger polling |
| Phase duration | >300s | >600s | Force advance or kill stuck agents |
| Participation | <90% | <70% | Restart blocked/failed agents |
| File size | >5MB | >10MB | Archive old messages |
| BLOCKER messages | >5% | >20% | Manual intervention needed |

### 7.4 Degradation Detection

**Automated Checks** (run every 30s):

```python
def check_blackboard_health():
    board = load_blackboard()
    alerts = []

    # Check phase timing
    phase_duration = (now - parse_time(board.started_at)).total_seconds()
    if phase_duration > 600:
        alerts.append({
            "severity": "critical",
            "type": "phase_deadlock",
            "message": f"Stuck in {board.phase} for {phase_duration}s"
        })

    # Check participation
    participation = len([s for s in board.agent_status.values() if s != "blocked"]) / len(board.agent_status)
    if participation < 0.7:
        alerts.append({
            "severity": "critical",
            "type": "low_participation",
            "message": f"Only {participation*100}% agents active"
        })

    # Check file size
    file_size = BLACKBOARD_FILE.stat().st_size
    if file_size > 10_000_000:  # 10MB
        alerts.append({
            "severity": "critical",
            "type": "file_too_large",
            "message": f"Blackboard file {file_size/1e6:.1f}MB, needs archival"
        })

    # Check for blockers
    blockers = get_blockers()
    if len(blockers) > len(board.agent_status) * 0.2:  # >20% agents blocked
        alerts.append({
            "severity": "critical",
            "type": "multiple_blockers",
            "message": f"{len(blockers)} agents blocked"
        })

    return alerts
```

### 7.5 Logging Integration

**Structured Event Log** (append to `blackboard_events.jsonl`):

```json
{
  "timestamp": "2025-12-28T01:23:45.123456",
  "event_type": "message_posted",
  "agent": "agent-3",
  "message_type": "DELIVERABLE",
  "phase": "build",
  "board_size_bytes": 1234567,
  "message_count": 42,
  "lock_acquisition_ms": 12
}

{
  "timestamp": "2025-12-28T01:24:10.654321",
  "event_type": "phase_transition",
  "from_phase": "build",
  "to_phase": "sync",
  "duration_seconds": 125,
  "agent_count": 10,
  "message_count": 56
}

{
  "timestamp": "2025-12-28T01:24:15.789012",
  "event_type": "lock_contention",
  "agent": "agent-5",
  "retry_count": 3,
  "total_wait_ms": 450,
  "acquired": true
}
```

**Log Analysis Queries**:
```bash
# Average lock acquisition time
jq -s '[.[] | select(.event_type=="message_posted") | .lock_acquisition_ms] | add/length' blackboard_events.jsonl

# Phase transition timeline
jq 'select(.event_type=="phase_transition") | {from: .from_phase, to: .to_phase, duration: .duration_seconds}' blackboard_events.jsonl

# Blocked agents over time
jq 'select(.message_type=="BLOCKER") | {timestamp, agent, phase}' blackboard_events.jsonl
```

---

## 8. KNOWN EDGE CASES

### 8.1 Empty Agent List

**Symptom**: Board initialized but immediately marked complete

**Root Cause**: `check_phase_ready()` returns True when agent_status is empty (0 >= 0)

**Fix Applied**: Validation in `init_blackboard()` raises ValueError if agents list empty

**Detection**:
```python
if not agents:
    raise ValueError("Cannot initialize blackboard with empty agent list")
```

### 8.2 Timestamp Inversions

**Symptom**: Messages appear out of chronological order

**Root Cause**: System clock skew between agent processes, race condition in file writes

**Workaround**: Messages indexed by insertion order (list index), not timestamp

**Detection**:
```python
for i in range(1, len(board.messages)):
    if board.messages[i].timestamp < board.messages[i-1].timestamp:
        log_warning(f"Timestamp inversion at index {i}")
```

### 8.3 Phase Value Corruption

**Symptom**: Phase becomes invalid string, crashes advance_phase()

**Root Cause**: Manual editing of blackboard.json, schema migration

**Fix Applied**: Try/except in `advance_phase()` catches ValueError from phase_order.index()

**Recovery**:
```python
try:
    current_idx = phase_order.index(board.phase)
except ValueError:
    print(f"Warning: Invalid phase '{board.phase}', cannot advance")
    return board.phase  # Stay in current phase
```

### 8.4 Empty String vs None

**Symptom**: Empty messages treated as missing, lost data

**Root Cause**: Falsy checks (`if data.get("message")`) treat empty string as None

**Fix Applied**: Explicit None checks (`if data.get("message") is not None`)

**Example**:
```python
# WRONG (treats "" as None)
message = data.get("message") or data.get("content", "")

# CORRECT (preserves empty strings)
message = data.get("message") if data.get("message") is not None else data.get("content", "")
```

### 8.5 File Lock Starvation

**Symptom**: Writers starved by continuous readers, writes never succeed

**Root Cause**: Shared locks held too long, exclusive lock can't acquire

**Mitigation**: portalocker uses blocking mode by default, queues lock requests

**Detection**:
```python
# Monitor average wait time for exclusive locks
exclusive_lock_waits = [e.total_wait_ms for e in events if e.lock_type == "LOCK_EX"]
avg_wait = sum(exclusive_lock_waits) / len(exclusive_lock_waits)
if avg_wait > 5000:  # >5 seconds
    alert("Lock starvation: exclusive locks waiting too long")
```

---

## 9. BUG FIXES APPLIED

| Line | Issue | Fix | Impact |
|------|-------|-----|--------|
| 75-79 | Empty strings treated as None | Explicit `is not None` checks | Prevents data loss |
| 137-140 | Empty agent list causes immediate completion | Raise ValueError on init | Prevents 0/0 edge case |
| 423-429 | Phase ready check uses >= instead of == | Changed to exact equality | Prevents premature phase advance |
| 434-437 | Check phase ready before advancing | Guard clause added | Prevents invalid state transitions |
| 450-457 | Uncaught ValueError in phase_order.index() | Try/except wrapper | Graceful degradation on corruption |

---

## 10. PERFORMANCE CHARACTERISTICS

### 10.1 File Size vs Performance

| File Size | Read Time | Write Time | Lock Contention Risk |
|-----------|-----------|------------|----------------------|
| <100KB | <10ms | <20ms | Low |
| 100KB-1MB | 10-50ms | 20-100ms | Medium |
| 1MB-5MB | 50-200ms | 100-500ms | High |
| >5MB | >200ms | >500ms | Very High |

**Recommendation**: Archive messages when file exceeds 1MB

### 10.2 Agent Count Scaling

| Agents | Messages/Min | Lock Attempts/Min | Recommended Poll Interval |
|--------|--------------|-------------------|---------------------------|
| 1-3 | 5-15 | 10-30 | 5s |
| 4-7 | 15-40 | 30-70 | 8s |
| 8-10 | 40-60 | 70-120 | 10s |
| >10 | >60 | >120 | 12s+ or batch polling |

### 10.3 Lock Timeout Tuning

**Current Setting**: 30 seconds

**Recommendations**:
- **Light load** (<5 agents): 10s timeout sufficient
- **Normal load** (5-10 agents): 30s timeout (current)
- **Heavy load** (>10 agents): 60s timeout or retry strategy

**Calculation**:
```
timeout = max(10s, agent_count * 3s)
```

---

## 11. FUTURE ENHANCEMENTS

### 11.1 Message Indexing

**Problem**: Linear scan through all messages to filter by type/agent

**Solution**: In-memory index for fast queries
```python
class IndexedBlackboard:
    def __init__(self):
        self.messages_by_type = defaultdict(list)
        self.messages_by_agent = defaultdict(list)
        self.messages_to_agent = defaultdict(list)

    def add_message(self, msg):
        self.messages_by_type[msg.type].append(msg)
        self.messages_by_agent[msg.agent].append(msg)
        if msg.to:
            self.messages_to_agent[msg.to].append(msg)
```

### 11.2 Incremental File Updates

**Problem**: Full file rewrite on every message (inefficient for large boards)

**Solution**: Append-only log with periodic a context reset
```python
# Append message to log file
with open("blackboard.log", "a") as f:
    f.write(json.dumps(msg.to_dict()) + "\n")

# Periodic a context reset (every 100 messages)
if message_count % 100 == 0:
    compact_log_to_json()
```

### 11.3 Multi-Board Support

**Problem**: Only one active blackboard at a time

**Solution**: Named blackboards for multiple concurrent teams
```python
blackboard_1 = load_blackboard("team-alpha")
blackboard_2 = load_blackboard("team-beta")
```

### 11.4 Event Webhooks

**Problem**: Polling wastes CPU, delayed updates

**Solution**: WebSocket or SSE for real-time push
```python
@app.websocket("/api/blackboard/stream")
async def blackboard_stream(websocket):
    last_msg_count = 0
    while True:
        board = load_blackboard()
        if len(board.messages) > last_msg_count:
            new_msgs = board.messages[last_msg_count:]
            await websocket.send_json({"messages": [m.to_dict() for m in new_msgs]})
            last_msg_count = len(board.messages)
        await asyncio.sleep(1)
```

---

*This document is part of the Flight Path monitoring system. Updated by the agent Sentinel instance.*
