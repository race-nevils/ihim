# Flight Path: Team/Agent System

**System ID**: `team-agent-system`
**Component**: Multi-Agent Spawning and Coordination
**Owner**: iHIM Core
**Status**: Active
**Last Updated**: 2025-12-28

---

## System Overview

The Team/Agent System is iHIM's multi-model orchestration layer. It spawns parallel the agent harness CLI sessions in Windows Terminal, each with role-specific context and tier-appropriate model selection (the agent/the agent/the agent). Agents coordinate via a shared blackboard (JSON-based message bus) and report deliverables to a central results directory.

**Core Function**: Spawn N agents → coordinate via blackboard → collect results → synthesize at the agent tier

**Parallelism**: 10-agent soft limit per the agent account (hardware/API constraint)

**Operating Modes**:
- **Blue Mode**: 10 the agent scouts, READ-ONLY, fast research/recon
- **Red Mode**: 8 the agent + 2 the agent monitors, dual-team exploration/audit
- **Yellow Mode**: 2 the agent + 4 Worker the agent + 4 Observer the agent, fast builder
- **Software Dev Team**: 5 agents (frontend, backend, devops, qa, security)

---

## Components

### 1. Spawner (`spawner.py`)

**Responsibility**: Create and track Windows Terminal windows with the agent harness CLI tabs

**Key Functions**:
- `spawn_agent_team(routed_prompts, feature_description)` - Main entry point
- `spawn_single_agent(agent, prompt, working_dir, is_first)` - Per-agent spawning
- `collapse_team()` - Close tracked agent window
- `get_team_status()` - Check pending/completed agents
- `collect_results()` - Gather all agent result files

**Platform Support**: Windows only (uses `ctypes` + Win32 API for window tracking)

**Window Tracking**:
- Captures HWND (window handle) at spawn time
- Uses `CASCADIA_HOSTING_WINDOW_CLASS` to identify Windows Terminal windows
- Stores global `_team_window_hwnd` for collapse operations
- Named window: `iHIM-AgentTeam` for reliable targeting

**Safety Limits**:
- Max 10 agents per spawn (enforced)
- Session ID generated per spawn: `spawn-YYYYMMDD-HHMMSS-{uuid8}`

### 2. Templates (`templates.py`)

**Responsibility**: Role-specific prompt templates with tier constraints and coordination instructions

**Template Structure**:
```python
{
  "agent-name": """
    # Task for {agent}
    Your profile: harness/agents/{category}/{agent}.md

    ## Your Task
    {prompt}

    ## Deliverables
    - {specific outputs}

    ## Constraints
    - {tier-specific limits}

    ## END SEQUENCE (REQUIRED)
    1. Write result.json
    2. Write retrospective.md
    3. Post DONE to blackboard
    4. Verify before closing
  """
}
```

**Agents Defined**:
- `frontend-dev`: React/Next.js, TypeScript, CSS (the agent tier)
- `backend-dev`: Python/FastAPI, APIs, databases (the agent tier)
- `devops`: Docker, CI/CD, integration lead (the agent tier)
- `qa-tester`: Testing, edge cases, bug hunting (the agent tier)
- `security-reviewer`: OWASP Top 10, READ-ONLY audit (the agent tier)

**END_SEQUENCE Protocol**:
- Step 1: Write `results/{agent}-result.json` (structured output)
- Step 2: Write `results/{agent}-retrospective.md` (self-critique for learning)
- Step 3: POST to blackboard with DONE status
- Step 4: Verify all files exist before session close

### 3. Team Templates (`team_templates.json`)

**Responsibility**: Pre-configured team compositions for common workflows

**Schema**:
```json
{
  "id": "team-id",
  "name": "Team Name",
  "description": "What this team does",
  "agents": [
    {
      "id": "agent-id",
      "name": "Agent Name",
      "expertise": ["Domain 1", "Domain 2"],
      "responsibilities": ["Task 1", "Task 2"],
      "constraints": ["Limit 1", "Limit 2"],
      "collaborates_with": ["other-agent-id"],
      "prompt_template": null
    }
  ],
  "min_agents": 3,
  "max_agents": 10,
  "tags": ["category", "use-case"],
  "use_count": 0,
  "learnings": {
    "tested": "YYYY-MM-DD",
    "observations": ["Finding 1", "Finding 2"],
    "vpt_notes": "Value-per-token insights"
  }
}
```

**Active Templates**:
1. `software-dev` - Full-stack feature development (5 agents)
2. `red-team-recon` - 10 the agent scouts for adversarial audit
3. `red-mode` - 8 the agent + 2 the agent monitors (dual-team exploration)
4. `blue-mode` - 10 the agent swarm (fast research)
5. `red-team-fix` - 6 the agent operators (implement fixes from recon)

**Execution History**: Tracked in `execution_history` array for mode comparison

### 4. Tiering Protocol (CLAUDE.md)

**Three-Tier Model**:

| Tier | Model | Permission | Use For |
|------|-------|------------|---------|
| Scout | the agent | READ-ONLY | File search, pattern matching, data gathering |
| Operator | the agent | Read/Write | Implementation, synthesis, refactoring |
| Architect | the agent | Full | Design, planning, user communication |

**HARD CONSTRAINT**: the agent = READ-ONLY to codebase (structural enforcement, not self-reported)

**Dispatch Rules**:
1. Information gathering → 3-5 the agent scouts (parallel)
2. Code writing → the agent operators
3. Architecture decisions → the agent (main session)
4. User communication → Always the agent

**Structural Trust Model**:
- the agent scouts spawned with read-only tool access
- the agent agents cannot spawn other agents
- Only the agent handles user-facing communication
- the agent CAN write to blackboard (peer communication only)

### 5. Blackboard (`blackboard.py`)

**Responsibility**: Shared JSON file for agent coordination (message bus pattern)

**Core Schema**:
```json
{
  "feature": "What we're building",
  "phase": "build|sync|integrate|verify|complete",
  "started_at": "ISO timestamp",
  "messages": [
    {
      "from": "agent-name",
      "timestamp": "ISO timestamp",
      "message": "Message content",
      "type": "STATUS|DONE|QUESTION|DELIVERABLE|BLOCKER",
      "to": "target-agent (optional)"
    }
  ],
  "agent_status": {
    "agent-name": "starting|working|blocked|complete"
  },
  "deliverables": {
    "agent-name": ["file1.py", "file2.js"]
  }
}
```

**Concurrency Control**:
- Uses `portalocker` for cross-platform file locking
- Exclusive lock (LOCK_EX) for writes
- Shared lock (LOCK_SH) for reads
- `atomic_update()` for read-modify-write operations
- Exponential backoff retry (max 10 attempts, 30s timeout)

**API Endpoints** (preferred over direct file writes):
- `POST /api/blackboard` - Post message
- `POST /api/blackboard/done` - Mark agent complete
- `POST /api/blackboard/blocked` - Report blocker
- `POST /api/blackboard/deliverable` - Record file created
- `GET /api/blackboard` - Read full state
- `GET /api/blackboard/messages` - Get messages
- `GET /api/blackboard/blockers` - Get blockers only

**Phase Progression**:
1. BUILD - Parallel work, agents post deliverables
2. SYNC - Share what was built, post to blackboard
3. INTEGRATE - DevOps wires things together
4. VERIFY - End-to-end testing
5. COMPLETE - All done

**Poll Interval**: Staggered 8-12 seconds (deterministic offset per agent to avoid thundering herd)

---

## Execution Flow

### 1. Spawn Phase

```
User/the agent → spawn_agent_team(routed_prompts)
  ├─ Generate session_id: spawn-{timestamp}-{uuid8}
  ├─ init_blackboard(feature, agents)
  ├─ For each agent:
  │   ├─ apply_optimizations_to_prompt(agent, prompt)  [feedback loop]
  │   ├─ Add session ID + blackboard path + BLACKBOARD_INSTRUCTIONS
  │   ├─ write_task_file(agent, enhanced_prompt)
  │   └─ spawn_single_agent(agent, prompt, WORKSPACE_PATH, is_first)
  │       ├─ Write prompt to {agent}-prompt.txt (avoids escaping hell)
  │       ├─ If first: wt --window iHIM-AgentTeam --title "[iHIM] {agent}"
  │       └─ Else: wt --window iHIM-AgentTeam nt --title "[iHIM] {agent}"
  ├─ Sleep 0.5s between spawns (let Windows Terminal catch up)
  ├─ Capture window handle (_team_window_hwnd)
  └─ Return spawn status
```

**Success Criteria**:
- All agents spawned successfully
- Window handle captured
- Task files written to `team/tasks/{agent}-task.md`

### 2. Agent Work Phase

```
Agent starts the agent harness CLI
  ├─ Read task file: team/tasks/{agent}-task.md
  ├─ Load role profile: harness/agents/{category}/{agent}.md
  ├─ Execute task with tier-appropriate permissions
  ├─ Poll blackboard every 8-12s (staggered)
  │   ├─ Read messages targeted at self or broadcast
  │   ├─ Check phase transitions
  │   └─ Respond to questions/blockers
  ├─ Post updates to blackboard via API
  │   ├─ STATUS updates
  │   ├─ DELIVERABLE records
  │   ├─ QUESTION to other agents
  │   └─ BLOCKER if stuck
  └─ When done: Execute END_SEQUENCE
```

**Coordination Patterns**:
- Frontend → Backend: "What's the API response format for X?"
- Backend → Frontend: "POST /api/endpoint returns {schema}"
- Any → DevOps: "Ready for integration"
- Any → All: "BLOCKER: Missing dependency Y"

### 3. Collection Phase

```
the agent (main session) → collect_results()
  ├─ Read all team/results/{agent}-result.json
  ├─ Read all team/results/{agent}-retrospective.md
  ├─ Synthesize findings
  ├─ Identify patterns from retrospectives (feed to optimizer)
  └─ Return aggregated results to user
```

**Result Schema**:
```json
{
  "agent": "agent-name",
  "status": "complete|blocked|error",
  "timestamp": "ISO timestamp",
  "summary": "1-2 sentence summary",
  "files_created": ["path1", "path2"],
  "files_modified": ["path3"],
  "blockers": ["blocker1"],
  "handoff_notes": "What next agent needs to know"
}
```

### 4. Cleanup Phase

```
collapse_team()
  ├─ Delete task files: team/tasks/{agent}-task.md
  ├─ Delete prompt files: team/tasks/{agent}-prompt.txt
  ├─ Check window handle exists
  ├─ Verify window still open (IsWindow)
  ├─ Send WM_CLOSE to _team_window_hwnd
  ├─ Reset _team_window_hwnd = None
  └─ Return success status
```

**Note**: Result files persist in `team/results/` for synthesis and learning

---

## Health Metrics

### Spawn Success Rate

**Metric**: `spawned_count / requested_count`

**Target**: ≥ 95%

**Measurement**:
```python
spawn_result = spawn_agent_team(prompts)
success_rate = len(spawn_result['agents']) / len(prompts)
```

**Degradation Indicators**:
- `< 90%` - Windows Terminal stability issue
- `< 80%` - Critical, investigate process limits
- `0%` - Complete failure, check Windows Terminal installation

**Collection**:
- Track in `team_state.json` at spawn time
- Log failures to `IHIM/logs/spawn_errors.jsonl`

### Agent Completion Time

**Metric**: `time_to_done = agent.completed_at - agent.started_at`

**Targets**:
- the agent scouts: < 2 minutes
- the agent operators: < 10 minutes
- Complex features: < 30 minutes

**Measurement**:
```python
# From result.json
started = team_state['agents'][agent]['started_at']
completed = result['timestamp']
duration = parse_iso(completed) - parse_iso(started)
```

**Degradation Indicators**:
- the agent > 5 min - Likely stuck, check blackboard for BLOCKER
- the agent > 30 min - Over-scoped task or infinite loop
- No completion after 60 min - Orphaned agent, manual intervention needed

**Collection**:
- Parse result.json timestamps
- Track per-agent-type averages
- Alert if 2x normal duration

### Tier Violations

**Metric**: Count of the agent agents modifying files (should be ZERO)

**Target**: 0 violations

**Detection**:
```python
# Check result.json for the agent agents
if agent.tier == "haiku" and len(result['files_modified']) > 0:
    log_tier_violation(agent, result['files_modified'])
```

**Degradation Indicators**:
- ANY violation = CRITICAL (breaks structural trust model)
- Indicates prompt injection or template misconfiguration

**Collection**:
- Automated check in `collect_results()`
- Log to `IHIM/logs/tier_violations.jsonl`
- Alert immediately (this is a safety boundary)

### Blackboard Lock Contention

**Metric**: `lock_retry_count` and `lock_timeout_count`

**Targets**:
- Retries per write: < 3
- Timeouts: 0

**Measurement**:
```python
# Already logged in blackboard.py (lines 184, 224)
# Parse logs or instrument atomic_update()
```

**Degradation Indicators**:
- Retries > 5 - Too many agents writing simultaneously
- Timeouts > 0 - Deadlock or agent holding lock too long
- Persistent timeouts - File corruption or orphaned lock

**Collection**:
- Instrument `atomic_update()` with metrics
- Track per spawn session
- Alert on timeouts (immediate issue)

### Window Handle Tracking

**Metric**: `window_tracked = True/False` in spawn result

**Target**: 100% tracked

**Measurement**:
```python
spawn_result['window_tracked']
```

**Degradation Indicators**:
- `False` - Cannot reliably collapse team later
- Multiple False in sequence - Win32 API issue or WT update

**Collection**:
- Log in spawn_result
- Track trend over time
- Warn user if untracked (affects cleanup)

### Result File Completeness

**Metric**: `has_result_json AND has_retrospective_md`

**Target**: 100% for completed agents

**Measurement**:
```python
result_exists = (results_path / f"{agent}-result.json").exists()
retro_exists = (results_path / f"{agent}-retrospective.md").exists()
complete = result_exists and retro_exists
```

**Degradation Indicators**:
- Missing result.json - Agent crashed before END_SEQUENCE
- Missing retrospective.md - Agent skipped self-critique (learning gap)
- Both missing - Agent never reached completion

**Collection**:
- Check in `collect_results()`
- Log missing files with session_id
- Enables debugging stuck agents

---

## Degradation Patterns

### Pattern 1: Spawn Failures

**Symptoms**:
- `spawn_agent_team()` returns `success=False`
- Some agents in `failed` list
- Window handle not captured

**Root Causes**:
1. Windows Terminal not installed or outdated
2. Process spawn limit reached (OS-level)
3. Permission denied on `team/tasks/` directory
4. Command line escaping issues (Unicode in prompts)

**Detection**:
```python
if spawn_result['success'] == False:
    log_spawn_failure(spawn_result['message'])
```

**Impact**: HIGH - Cannot execute multi-agent workflows

### Pattern 2: Orphaned Agents

**Symptoms**:
- Agent task file exists but no result file after 60+ minutes
- `team_state.json` shows `status=working` but agent inactive
- Blackboard shows no recent messages from agent

**Root Causes**:
1. Agent crashed/closed window manually
2. Agent stuck in infinite loop
3. Agent waiting for user input (blocked on prompt)
4. Task file corrupted or unreadable

**Detection**:
```python
for agent, state in team_state['agents'].items():
    if state['status'] == 'working':
        elapsed = now() - parse_iso(state['started_at'])
        if elapsed > timedelta(minutes=60):
            flag_orphaned_agent(agent, elapsed)
```

**Impact**: MEDIUM - Blocks team completion, wastes resources

### Pattern 3: Window Handle Loss

**Symptoms**:
- `collapse_team()` returns `window_tracked=False`
- Cannot close agent window programmatically
- User must manually close Windows Terminal

**Root Causes**:
1. Spawn window detection failed (timing issue)
2. User closed and reopened Windows Terminal manually
3. Multiple Windows Terminal windows interfered
4. Windows Terminal update changed window class

**Detection**:
```python
if _team_window_hwnd is None:
    log_window_handle_loss()
```

**Impact**: LOW - Cleanup inconvenience, no functional loss

### Pattern 4: Blackboard Deadlock

**Symptoms**:
- Multiple agents report lock timeouts
- `atomic_update()` fails after 10 retries
- Blackboard file exists but unreadable

**Root Causes**:
1. Agent crashed while holding exclusive lock
2. File corruption (incomplete write)
3. Permissions changed on blackboard.json
4. Antivirus locked file for scanning

**Detection**:
```python
# In atomic_update() after max_retries
if attempts >= max_retries:
    log_blackboard_deadlock(BLACKBOARD_FILE)
```

**Impact**: CRITICAL - Halts all coordination

### Pattern 5: Tier Boundary Violation

**Symptoms**:
- the agent agent reports `files_modified` in result.json
- the agent retrospective mentions "I wrote code to fix..."
- Result files show the agent agent created new files

**Root Causes**:
1. Prompt template missing tier constraints
2. Agent ignored constraints (prompt injection)
3. Feedback optimizer suggested code modifications
4. Template merge error (wrong tier template used)

**Detection**:
```python
if agent_tier(agent) == 'haiku':
    violations = result.get('files_modified', []) + result.get('files_created', [])
    if violations:
        alert_tier_violation(agent, violations)
```

**Impact**: CRITICAL - Breaks structural trust, potential bad code in codebase

---

## Recovery Procedures

### Recovery 1: Kill Stuck Agents

**When**: Agent orphaned (60+ min with no progress)

**Steps**:
1. Identify stuck agent: `get_team_status()` shows `working` > 60 min
2. Find Windows Terminal window: Manually or via Task Manager
3. Close specific tab (agent's CLI session) or entire window
4. Mark agent as failed in `team_state.json`:
   ```python
   team_state['agents'][agent]['status'] = 'failed'
   team_state['agents'][agent]['failed_at'] = datetime.now().isoformat()
   ```
5. Post BLOCKER to blackboard for record:
   ```python
   post_message("system", f"Agent {agent} orphaned, manual termination", "BLOCKER")
   ```
6. Continue with remaining agents or re-spawn single agent

**Automation Potential**: HIGH - Can detect and auto-kill based on timeout

### Recovery 2: Reset Team State

**When**: Team spawn completely failed or stuck in unrecoverable state

**Steps**:
1. Close all agent windows: `collapse_team()` or manual close
2. Delete task files:
   ```bash
   rm C:/Users/<user>/workspace/IHIM/team/tasks/*-task.md
   rm C:/Users/<user>/workspace/IHIM/team/tasks/*-prompt.txt
   ```
3. Clear blackboard:
   ```python
   from IHIM.team.blackboard import clear_blackboard
   clear_blackboard()
   ```
4. Reset team_state.json:
   ```python
   team_state = {"active": False, "agents": {}}
   (IHIM_PATH / "team/team_state.json").write_text(json.dumps(team_state))
   ```
5. Re-spawn team with fresh session_id

**Automation Potential**: MEDIUM - Can script, but requires confirmation

### Recovery 3: Unlock Blackboard

**When**: Blackboard deadlocked (lock timeouts persist)

**Steps**:
1. Check for orphaned processes:
   ```bash
   # Windows: check for the agent harness processes
   tasklist | findstr claude
   ```
2. Kill orphaned processes if found:
   ```bash
   taskkill /F /IM claude.exe
   ```
3. Verify file is not in use:
   ```bash
   # Try to read blackboard
   cat C:/Users/<user>/workspace/IHIM/team/blackboard.json
   ```
4. If corrupted, restore from last valid state:
   ```python
   # Load last known good state from logs
   # Or reinitialize fresh blackboard
   board = init_blackboard(feature, agents)
   ```
5. Resume agent operations

**Automation Potential**: LOW - Requires careful diagnosis

### Recovery 4: Handle Window Loss

**When**: `collapse_team()` reports window not tracked

**Steps**:
1. Find Windows Terminal window manually:
   - Look for window title containing "[iHIM]"
   - Or check Windows Terminal dropdown for tabs with agent names
2. Close window manually (click X or Ctrl+Shift+W)
3. Clean up task files (automated fallback in `collapse_team()`):
   ```python
   # Already done in collapse_team()
   for task_file in TASKS_PATH.glob("*-task.md"):
       task_file.unlink()
   ```
4. Log incident for tracking:
   ```python
   log_manual_cleanup(session_id, "window_handle_lost")
   ```

**Automation Potential**: MEDIUM - Can enumerate windows as fallback

### Recovery 5: Fix Tier Violation

**When**: the agent agent modified files (detected in result.json)

**Steps**:
1. **IMMEDIATE**: Review all files in `files_modified` list
2. **CRITICAL CHECK**: Is the code malicious or incorrect?
   - If yes: Revert immediately with `git checkout {files}`
   - If no but unintended: Mark for manual review
3. Update prompt template to reinforce READ-ONLY constraint:
   ```python
   # In templates.py, add to the agent template:
   """
   CRITICAL CONSTRAINT: You are READ-ONLY.
   You MUST NOT modify any files.
   You MUST NOT create new files.
   You MAY ONLY read and report.
   """
   ```
4. Add pre-spawn validation:
   ```python
   def validate_agent_tier(agent, template):
       if agent_tier(agent) == 'haiku':
           assert 'READ-ONLY' in template, f"the agent template missing READ-ONLY constraint"
   ```
5. Log violation for feedback loop:
   ```python
   log_tier_violation({
       'agent': agent,
       'files': violations,
       'session_id': session_id,
       'template_hash': hash(template)
   })
   ```
6. Alert user immediately (HIGH severity)

**Automation Potential**: HIGH - Detection is automated, remediation needs review

### Recovery 6: Restart Single Agent

**When**: One agent failed/stuck but others progressing normally

**Steps**:
1. Identify failed agent from `team_state.json`
2. Preserve existing blackboard and other agents
3. Generate new task file for failed agent:
   ```python
   enhanced_prompt = format_agent_prompt(agent, original_prompt, project, working_dir)
   write_task_file(agent, enhanced_prompt)
   ```
4. Spawn only this agent in existing `iHIM-AgentTeam` window:
   ```bash
   wt --window iHIM-AgentTeam nt --title "[iHIM] {agent}" -d {working_dir} cmd /k claude {instruction}
   ```
5. Update `team_state.json`:
   ```python
   team_state['agents'][agent] = {
       'status': 'working',
       'started_at': datetime.now().isoformat(),
       'retry_count': team_state['agents'][agent].get('retry_count', 0) + 1
   }
   ```
6. Monitor for completion

**Automation Potential**: HIGH - Can script with retry limit (max 2 retries)

---

## Flight Path Integration

### Dashboard Widgets

**Agent Team Status**:
- Active team indicator (green = active, gray = idle)
- Agent count badges (spawned/completed/failed)
- Current phase display (BUILD/SYNC/INTEGRATE/VERIFY/COMPLETE)
- Window tracking status (tracked/lost)

**Health Indicators**:
- Spawn success rate (last 10 spawns)
- Average completion time by tier (the agent/the agent)
- Blackboard lock contention gauge
- Tier violation count (should always be 0)

**Real-Time Monitoring**:
- Live agent status grid (starting/working/blocked/complete)
- Recent blackboard messages feed (last 10)
- Blocker alerts (red highlight)
- Question queue (unanswered questions)

### Alert Conditions

**CRITICAL**:
- Tier violation detected (the agent modified files)
- Blackboard deadlock (lock timeout)
- All spawns failed (spawn_success_rate = 0%)

**HIGH**:
- Agent orphaned (60+ min no progress)
- Spawn success rate < 80%
- Multiple blockers posted

**MEDIUM**:
- Agent completion time > 2x average
- Window handle lost
- Lock retries > 5

**LOW**:
- Single spawn failure in successful batch
- Agent self-reported blocker (with resolution path)

### SCADA-Style Metrics

**Spawn Throughput**:
- Agents spawned per hour
- Success rate trend (24h rolling)
- Failure reasons histogram

**Agent Performance**:
- Completion time distribution (box plot by tier)
- Work-to-completion ratio (messages posted / time elapsed)
- Retrospective quality score (has all sections = 100%)

**Blackboard Health**:
- Messages per minute (activity level)
- Lock contention events per hour
- Average lock acquisition time

**System Capacity**:
- Current agent count vs max (10)
- Available spawn slots
- Active sessions (can run multiple teams sequentially)

### Data Collection Endpoints

**Spawn Metrics**:
```python
GET /api/metrics/spawn
{
  "total_spawns": 42,
  "successful_spawns": 40,
  "success_rate": 0.952,
  "avg_agents_per_spawn": 7.2,
  "last_24h": {...}
}
```

**Agent Metrics**:
```python
GET /api/metrics/agents
{
  "haiku": {
    "avg_completion_time_sec": 87,
    "tier_violations": 0,
    "total_completed": 120
  },
  "sonnet": {
    "avg_completion_time_sec": 342,
    "total_completed": 89
  }
}
```

**Blackboard Metrics**:
```python
GET /api/metrics/blackboard
{
  "total_messages": 1523,
  "blockers": 3,
  "questions": 12,
  "lock_timeouts": 0,
  "avg_lock_wait_ms": 23
}
```

**Active Status**:
```python
GET /api/team/status
{
  "active": true,
  "session_id": "spawn-20251228-143420-a3f5d912",
  "phase": "integrate",
  "agents": {
    "frontend-dev": "complete",
    "backend-dev": "complete",
    "devops": "working",
    "qa-tester": "working",
    "security-reviewer": "complete"
  },
  "window_tracked": true,
  "elapsed_sec": 892
}
```

---

## Evolution and Learnings

### Execution History Tracking

Each team template includes `execution_history` array:
```json
{
  "run_id": "exec-2025-12-27-006",
  "task": "Fix Wave 3 findings",
  "results": {
    "fixes_attempted": 8,
    "fixes_applied": 6,
    "false_positives_caught": 2
  },
  "monitor_contributions": [
    "Monitor A verified XSS fixes",
    "Monitor B identified fragmented cleanup architecture"
  ],
  "comparison_vs_flat_sonnet": {
    "advantage": "Caught 2 false positives",
    "false_positive_rate": 0.25
  },
  "verdict": "Red Mode superior for meta-analysis tasks"
}
```

### VPT (Value Per Token) Notes

- **Blue Mode**: Fastest, 10 the agent = max parallelism, min cost
- **Red Mode**: High power, best for discovery + meta-analysis
- **Yellow Mode**: Velocity over safety, fast iteration
- **Software Dev Team**: Balanced, production-quality output

### Feedback Loop

Retrospective files feed back into prompt optimization:
```python
# In spawner.py (line 242)
optimized_prompt = apply_optimizations_to_prompt(agent, prompt)
```

Learnings are extracted from `{agent}-retrospective.md`:
- "Assumptions I Didn't Verify" → Add verification step to template
- "Where I Wasted Time" → Trim scope or add guardrails
- "What Might Break" → Add to test checklist
- Patterns → Update template constraints

---

## Technical Debt and Future Work

**Current Limitations**:
1. **Windows-only**: Spawner uses Win32 API, no Mac/Linux support yet
2. **Single window tracking**: Can only track one team at a time
3. **No agent restart**: Must manually re-spawn failed agents
4. **Blackboard polling**: No push notifications, agents poll every 8-12s
5. **No agent health checks**: Cannot detect stuck agents automatically

**Planned Improvements**:
1. **Cross-platform spawning**: Use tmux/screen for Mac/Linux
2. **Multi-session tracking**: Track multiple team windows simultaneously
3. **Auto-recovery**: Detect and restart stuck agents with timeout
4. **WebSocket blackboard**: Real-time push for faster coordination
5. **Agent lifecycle monitoring**: Heartbeat checks, auto-kill on timeout
6. **Result streaming**: Agents stream progress instead of final dump
7. **Tier enforcement in spawner**: Verify tool access before spawn
8. **Session replay**: Reconstruct execution from logs for debugging

**Flight Path Integration**:
- Real-time agent status dashboard (WebSocket feed)
- SCADA-style metrics visualization
- Historical trend analysis (spawn success over time)
- Capacity planning alerts (approaching 10-agent limit)
- Anomaly detection (completion time outliers)

---

## References

**Code**:
- `IHIM/team/spawner.py` - Agent spawning and window tracking
- `IHIM/team/templates.py` - Role-specific prompt templates
- `IHIM/team/blackboard.py` - Coordination message bus
- `IHIM/data/team_templates.json` - Pre-configured team compositions
- `CLAUDE.md` - Tiering protocol and dispatch rules

**Data**:
- `IHIM/team/tasks/{agent}-task.md` - Per-agent task files
- `IHIM/team/results/{agent}-result.json` - Structured output
- `IHIM/team/results/{agent}-retrospective.md` - Self-critique for learning
- `IHIM/team/blackboard.json` - Live coordination state
- `IHIM/team/team_state.json` - Current team status

**Logs** (proposed):
- `IHIM/logs/spawn_errors.jsonl` - Spawn failures
- `IHIM/logs/tier_violations.jsonl` - the agent write violations
- `IHIM/logs/blackboard_locks.jsonl` - Lock contention events

---

**Document Version**: 1.0
**Next Review**: After 100 total spawns or first major incident
