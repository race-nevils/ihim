# iHIM API System - Flight Path Vitals

**System Type:** Backend API Server
**Primary Function:** Dashboard command center with REST API
**Port:** 7777
**Framework:** FastAPI (Python/Uvicorn)
**Health Status:** Active monitoring via `/api/system/health`

---

## 1. System Overview

The iHIM API System is the central nervous system of the iHIM Command Center. It provides:

- **RESTful API** for all dashboard operations (tasks, notes, teams, blackboard)
- **Static file serving** for the web dashboard UI (HTML/CSS/JS)
- **Real-time coordination** between spawned agent teams via blackboard endpoints
- **System health monitoring** with topology-aware component tracking
- **Auto-reload development mode** for rapid iteration

The API runs as a single FastAPI application with hot-reload enabled, serving both dynamic endpoints (`/api/*`) and static UI assets.

---

## 2. Components

### 2.1 Core API Server

**File:** `C:\Users\<user>\workspace\IHIM\api\main.py`
**Entry Point:** `C:\Users\<user>\workspace\IHIM\run.py`

**Responsibilities:**
- FastAPI application initialization
- Middleware (CORS, cache-control)
- Router registration (commands, team builder, terminal)
- Global exception handlers (validation errors)
- Static file mounting (`/static` and `/` for `index.html`)

**Key Middleware:**
- **CORS:** Allow-all origins (for Chrome extensions and localhost access)
- **Cache-Control:** No-cache headers for `/api/*` endpoints to prevent stale data
- **Validation Error Handler:** Standardized error responses for Pydantic validation failures

### 2.2 Endpoint Groups

| Route Group | Purpose | Implementation |
|-------------|---------|----------------|
| `/api/actions` | Execute iHIM actions | `actions.registry.ACTIONS` |
| `/api/team/*` | Agent team spawning/management | `team.spawner`, `team.router` |
| `/api/blackboard/*` | Agent coordination | `team.blackboard` |
| `/api/feedback/*` | Self-improvement feedback loop | `team.feedback.*` |
| `/api/system/*` | Health & topology monitoring | `api.system.health`, `api.system.topology` |
| `/api/slash-commands/*` | Slash command center | `api.commands.routes` |
| `/api/team-builder/*` | Team composition builder | `api.team_builder.routes` (optional module) |
| `/api/terminal/*` | Mission Control terminal | `api.terminal.routes` (optional module) |
| `/api/tasks` | Task list CRUD | Inline handlers |
| `/api/notes` | Quick notes CRUD | Inline handlers |
| `/api/stopwatches` | Multiple stopwatch management | Inline handlers |
| `/api/flightpath/*` | Project dependency visualizer | `api.flightpath.scanner` |
| `/api/sanity/*` | System validation checks | `sanity.check` |
| `/api/server/*` | Server control (restart/status) | Inline handlers |

### 2.3 Data Stores

All data persisted as JSON files in `C:\Users\<user>\workspace\IHIM\data\`:

- `tasks.json` - Task list with priority/completion status
- `notes.json` - Quick notes with timestamps
- `stopwatches.json` - Multiple stopwatch states
- `slash_commands.json` - Slash command definitions + brainstorm ideas
- `team_templates.json` - Reusable team compositions
- `team_instances.json` - Active team spawn sessions
- `debriefs.jsonl` - Append-only debrief log (self-improvement)
- `heuristics.json` - Extracted decision rules from debriefs

**Team System Data:**
- `team/blackboard.json` - Current agent coordination state
- `team/team_state.json` - Agent lifecycle tracking

### 2.4 Static UI Files

**Location:** `C:\Users\<user>\workspace\IHIM\ui\`

- `index.html` - Main dashboard SPA
- `static/style.css` - Dashboard styling
- Static assets mounted at `/static`, root serves `index.html`

---

## 3. Request Flow

### 3.1 HTTP Request Lifecycle

```
Client (Browser/Extension)
  |
  v
[CORS Middleware] - Allow all origins
  |
  v
[Cache-Control Middleware] - No-cache for /api/*
  |
  v
[FastAPI Router] - Match endpoint
  |
  +---> Static Files (/static, /) --> Serve HTML/CSS/JS
  |
  +---> API Endpoints (/api/*)
         |
         v
      [Endpoint Handler]
         |
         +---> Data Layer (JSON file read/write)
         +---> Team System (spawn, route, blackboard)
         +---> Health Checks (topology + component status)
         +---> Feedback System (process results, optimize)
         |
         v
      [Pydantic Validation] - Request/Response models
         |
         v
      [JSONResponse] - Return result
```

### 3.2 Example: Spawn Team Request

```
POST /api/team/spawn
{
  "prompt": "Build a user dashboard",
  "project": "workspace",
  "agents": null
}

Flow:
1. Pydantic validates SpawnRequest
2. route_prompt() morphs prompt per agent (5 default agents)
3. spawn_agent_team() opens Windows Terminal with tabs
4. get_team_state().spawn() updates team_state.json
5. init_blackboard() creates blackboard.json for coordination
6. Return { "success": true, "agents": [...] }
```

### 3.3 Example: Health Check Request

```
GET /api/system/health

Flow:
1. check_all_health() runs all component health checks
2. For each component:
   - check_api_server() - always healthy (API is running)
   - check_blackboard() - JSON validity + staleness check
   - check_team_spawner() - module import test
   - check_data_tasks() - JSON parse + item count
3. Aggregate: overall_status = ERROR/DEGRADED/HEALTHY
4. Return SystemHealth with component statuses + metrics
```

---

## 4. Health Metrics

### 4.1 System-Level Metrics

**Endpoint:** `GET /api/system/stats`

| Metric | Source | Description |
|--------|--------|-------------|
| `cpu.percent` | `psutil.cpu_percent()` | Current CPU usage (%) |
| `cpu.cores` | `psutil.cpu_count(logical=False)` | Physical cores |
| `cpu.threads` | `psutil.cpu_count(logical=True)` | Logical threads |
| `memory.percent` | `psutil.virtual_memory().percent` | RAM usage (%) |
| `memory.used_gb` | `psutil.virtual_memory().used` | RAM used (GB) |
| `memory.total_gb` | `psutil.virtual_memory().total` | Total RAM (GB) |
| `memory.available_gb` | `psutil.virtual_memory().available` | Available RAM (GB) |

### 4.2 Component Health Metrics

**Endpoint:** `GET /api/system/health`

Each component returns:
- **status:** `healthy` | `degraded` | `error` | `inactive`
- **message:** Human-readable status description
- **last_check:** ISO timestamp of health check
- **metrics:** Component-specific data (e.g., file size, item count, error details)

**Component Types:**

| Component ID | Health Check Logic |
|--------------|-------------------|
| `api-server` | Always healthy (if API responds, it's running) |
| `actions-registry` | Count registered actions, validate imports |
| `team-spawner` | Module import test |
| `blackboard` | JSON validity, phase detection, message count |
| `data-tasks` | JSON validity, item count, staleness override |
| `data-notes` | JSON validity, item count, staleness override |
| `data-team-state` | JSON validity, active team detection |
| `feedback-system` | Directory exists, module imports |
| `ui-assets` | Directory exists, file count |
| `ui-dashboard` | `index.html` file exists, size |
| `sanity-check` | Module import test |

### 4.3 Health Status Levels

| Status | Indicator | Meaning |
|--------|-----------|---------|
| `HEALTHY` | Green | Operational, no errors |
| `DEGRADED` | Yellow | Operational but slow/stale (e.g., file >30min old) |
| `ERROR` | Red | Exception, missing file, validation failure |
| `INACTIVE` | Gray | Not initialized or dormant (e.g., no blackboard session) |

### 4.4 Topology Awareness

**Endpoint:** `GET /api/system/topology`

Returns full system graph:
- **Nodes:** All iHIM components with parent-child relationships
- **Edges:** Dependencies (`dependency`), data flows (`data-flow`), parent-child hierarchy
- **Metadata:** Component type, file path, description

Used for visualizing the Flight Path SCADA dashboard - shows which components depend on which, and how data flows through the system.

---

## 5. Degradation Patterns

### 5.1 Port Conflicts

**Symptom:**
```
OSError: [Errno 10048] address already in use
```

**Cause:**
- Previous server instance still running on port 7777
- Another application using port 7777

**Detection:**
- Server fails to start
- Health endpoint unreachable at `http://localhost:7777/api/health`

**Impact:**
- Dashboard inaccessible
- API requests timeout or connection refused

### 5.2 Stale Processes

**Symptom:**
```
Multiple python.exe processes running
Server won't restart cleanly
```

**Cause:**
- `run.py` spawned but not killed properly
- PowerShell restart script failed midway
- Manual Ctrl+C during reload cycle

**Detection:**
- Task Manager shows multiple `python.exe` processes
- Server logs show "Reloading..." but no response
- Dashboard shows old data despite code changes

**Impact:**
- Hot reload broken
- Server stuck in degraded state
- Memory leaks over time

### 5.3 Memory Leaks

**Symptom:**
```
RAM usage climbing over hours
psutil reports memory.percent > 80%
Server becomes sluggish
```

**Cause:**
- Long-running server without restarts
- Large JSON files loaded into memory
- Unclosed file handles in data stores

**Detection:**
- `GET /api/system/stats` shows `memory.percent` > 80%
- Server response times increase
- System becomes unresponsive

**Impact:**
- Slow API responses
- Dashboard lag
- Risk of server crash

### 5.4 Data Corruption

**Symptom:**
```
JSONDecodeError in component health check
{
  "status": "error",
  "message": "Invalid JSON: Expecting property name..."
}
```

**Cause:**
- Incomplete file write (server crash during save)
- Manual file editing with syntax errors
- Concurrent writes from multiple processes (rare)

**Detection:**
- `GET /api/system/health` shows ERROR status for data components
- API endpoints return 500 errors
- Dashboard fails to load data widgets

**Impact:**
- Data loss for affected component
- API endpoints fail
- Dashboard shows error state

### 5.5 Module Import Failures

**Symptom:**
```
ImportError: No module named 'team.feedback'
{
  "status": "error",
  "message": "Import failed: No module..."
}
```

**Cause:**
- Missing Python dependencies
- Virtual environment not activated
- File moved/deleted but imports not updated

**Detection:**
- `GET /api/system/health` shows ERROR for module components
- Server logs show `ImportError` on startup
- Optional module features unavailable (e.g., feedback system)

**Impact:**
- Feature unavailable (graceful degradation for optional modules)
- Server may fail to start (if core module missing)

---

## 6. Recovery Procedures

### 6.1 Port Conflict Resolution

**Method 1: Kill All Python Processes (Nuclear Option)**

```powershell
# Via PowerShell
Stop-Process -Name python -Force -ErrorAction SilentlyContinue
```

```bash
# Via Task Manager (manual)
1. Ctrl+Shift+Esc
2. Find all "python.exe"
3. End task for each
```

**Method 2: Find and Kill Specific Port (Surgical)**

```powershell
# Find process using port 7777
netstat -ano | findstr :7777

# Kill by PID (replace 12345 with actual PID)
taskkill /PID 12345 /F
```

**Method 3: API-Triggered Restart**

```bash
# POST to restart endpoint (if server is responsive)
curl -X POST http://localhost:7777/api/server/restart

# Server will:
# 1. Wait 1 second
# 2. Kill all python.exe
# 3. Start new run.py instance
# 4. Client should poll /api/health after 3 seconds
```

**Verification:**
```bash
# Check server is back
curl http://localhost:7777/api/health

# Expected response:
{"status":"ok","name":"iHIM"}
```

### 6.2 Stale Process Cleanup

**Step 1: Identify Stale Processes**

```powershell
# List all Python processes with command line
Get-Process python | Format-List *

# Look for multiple processes with "run.py" or "uvicorn"
```

**Step 2: Clean Kill**

```powershell
# Kill all Python processes
Stop-Process -Name python -Force

# Wait 2 seconds
Start-Sleep -Seconds 2
```

**Step 3: Restart Fresh**

```bash
# Navigate to IHIM directory
cd C:\Users\<user>\workspace\IHIM

# Start server (venv auto-activated by run.py)
python run.py
```

**Verification:**
- Browser opens to `http://localhost:7777`
- Dashboard loads cleanly
- `GET /api/system/health` returns healthy components

### 6.3 Memory Leak Mitigation

**Immediate Action: Restart Server**

```bash
# Use API restart (if responsive)
curl -X POST http://localhost:7777/api/server/restart

# OR manual restart
# 1. Ctrl+C in server terminal
# 2. python run.py
```

**Long-Term Mitigation:**

1. **Monitor Memory Usage:**
   ```bash
   # Add to cron/task scheduler
   curl http://localhost:7777/api/system/stats
   # Alert if memory.percent > 80%
   ```

2. **Scheduled Restarts:**
   ```powershell
   # Task Scheduler: Daily restart at 3 AM
   $action = New-ScheduledTaskAction -Execute 'curl' -Argument '-X POST http://localhost:7777/api/server/restart'
   $trigger = New-ScheduledTaskTrigger -Daily -At 3am
   Register-ScheduledTask -Action $action -Trigger $trigger -TaskName "iHIM Daily Restart"
   ```

3. **Reduce Data File Size:**
   - Archive old tasks/notes
   - Clear completed stopwatches
   - Truncate old debrief logs (keep last 100 entries)

### 6.4 Data Corruption Recovery

**Step 1: Identify Corrupted File**

```bash
# Check system health
curl http://localhost:7777/api/system/health | jq '.components[] | select(.status == "error")'

# Example output:
{
  "id": "data-tasks",
  "status": "error",
  "message": "Invalid JSON: Expecting property name..."
}
```

**Step 2: Restore from Backup (if available)**

```bash
# Manual backup restore (if you created one)
cp C:\Users\<user>\workspace\IHIM\data\tasks.json.bak C:\Users\<user>\workspace\IHIM\data\tasks.json
```

**Step 3: Reset to Empty State (last resort)**

```bash
# Backup corrupted file first
cp C:\Users\<user>\workspace\IHIM\data\tasks.json C:\Users\<user>\workspace\IHIM\data\tasks.json.corrupt

# Reset to empty valid JSON
echo '{"tasks":[]}' > C:\Users\<user>\workspace\IHIM\data\tasks.json
```

**Step 4: Verify Recovery**

```bash
# Check health again
curl http://localhost:7777/api/system/health | jq '.components[] | select(.id == "data-tasks")'

# Expected:
{
  "id": "data-tasks",
  "status": "healthy",
  "message": "0 tasks"
}
```

### 6.5 Module Import Failure Resolution

**Step 1: Check Virtual Environment**

```bash
# Verify venv is active
cd C:\Users\<user>\workspace\IHIM
.venv\Scripts\python.exe --version

# Should show Python 3.x
```

**Step 2: Reinstall Dependencies**

```bash
# Activate venv
.venv\Scripts\activate

# Reinstall from requirements.txt
pip install -r requirements.txt

# Verify critical modules
python -c "import fastapi, uvicorn, psutil, pydantic; print('OK')"
```

**Step 3: Check for Missing Files**

```bash
# List all Python modules in team system
ls -R C:\Users\<user>\workspace\IHIM\team\*.py

# Verify expected files exist:
# - spawner.py
# - router.py
# - state.py
# - blackboard.py
# - feedback/*.py
```

**Step 4: Restart Server**

```bash
python run.py

# Check logs for import errors
# If successful, health endpoint should show healthy modules
```

### 6.6 Full System Reset (Nuclear Option)

**When to Use:**
- Multiple components showing ERROR
- Server won't start at all
- Unknown failure state

**Procedure:**

```powershell
# 1. Kill all Python processes
Stop-Process -Name python -Force

# 2. Clear all data files (WARNING: Data loss!)
Remove-Item C:\Users\<user>\workspace\IHIM\data\*.json
Remove-Item C:\Users\<user>\workspace\IHIM\team\*.json

# 3. Reinitialize data stores
New-Item -Path C:\Users\<user>\workspace\IHIM\data\tasks.json -Value '{"tasks":[]}'
New-Item -Path C:\Users\<user>\workspace\IHIM\data\notes.json -Value '{"notes":[]}'
New-Item -Path C:\Users\<user>\workspace\IHIM\data\stopwatches.json -Value '{"stopwatches":[]}'

# 4. Restart server
cd C:\Users\<user>\workspace\IHIM
python run.py
```

**Post-Reset Verification:**

```bash
# All components should be healthy or inactive
curl http://localhost:7777/api/system/health | jq '.overall_status'
# Expected: "healthy" or "degraded" (not "error")

# Dashboard should load
curl http://localhost:7777/
# Should return HTML
```

---

## 7. Flight Path Integration

### 7.1 SCADA Dashboard Requirements

**Real-Time Metrics Display:**
- CPU/RAM usage (update every 5 seconds)
- Component health status (color-coded: green/yellow/red/gray)
- Topology graph (nodes + edges, interactive)

**Alerts and Thresholds:**
- Memory > 80% → Yellow warning
- Memory > 90% → Red critical
- Any component ERROR → Red alert
- Port conflict → Red critical + recovery button

**Recovery Actions:**
- "Restart Server" button → `POST /api/server/restart`
- "Clear Stale Data" button → Delete old stopwatches/completed tasks
- "Reset Component" button → Reset specific data file to empty state

### 7.2 Recommended Polling Intervals

| Endpoint | Interval | Purpose |
|----------|----------|---------|
| `/api/system/stats` | 5 seconds | CPU/RAM monitoring |
| `/api/system/health` | 30 seconds | Component health checks |
| `/api/system/topology` | On page load | System graph (static) |
| `/api/team/status` | 10 seconds | Active team monitoring |
| `/api/blackboard` | 15 seconds | Agent coordination state |

### 7.3 Vitals Visualization

**Component Health Grid:**
```
┌─────────────────┬─────────┬──────────┐
│ Component       │ Status  │ Metrics  │
├─────────────────┼─────────┼──────────┤
│ API Server      │ ●       │ Port 7777│
│ Actions         │ ●       │ 12 acts  │
│ Blackboard      │ ○       │ Inactive │
│ Data: Tasks     │ ●       │ 5 tasks  │
│ Feedback System │ ●       │ Loaded   │
└─────────────────┴─────────┴──────────┘

Legend: ● Healthy  ◐ Degraded  ◯ Error  ○ Inactive
```

**System Resource Graph:**
```
CPU: [████████░░] 80%
RAM: [██████░░░░] 60%  (4.8 / 8.0 GB)

Trend (last 5 minutes):
CPU: ▂▃▅▆█ (climbing)
RAM: ▃▃▄▄▄ (stable)
```

**Topology Diagram (D3.js/Cytoscape.js):**
```
       [iHIM Root]
            |
    +-------+-------+
    |       |       |
 [API]  [Team]  [Data]
    |       |       |
  /api/* spawner  tasks.json
         |
    [Blackboard]
```

### 7.4 Health Check API Contract

**Request:**
```http
GET /api/system/health
Accept: application/json
```

**Response (Healthy):**
```json
{
  "success": true,
  "overall_status": "healthy",
  "timestamp": "2025-12-28T14:23:45.123456",
  "components": [
    {
      "id": "api-server",
      "status": "healthy",
      "message": "Running",
      "last_check": "2025-12-28T14:23:45.123456",
      "metrics": {"port": 7777}
    },
    {
      "id": "data-tasks",
      "status": "healthy",
      "message": "5 tasks",
      "last_check": "2025-12-28T14:23:45.123456",
      "metrics": {
        "item_count": 5,
        "file_size": 512,
        "last_modified": "2025-12-28T14:20:00.000000"
      }
    }
  ]
}
```

**Response (Degraded):**
```json
{
  "success": true,
  "overall_status": "degraded",
  "timestamp": "2025-12-28T14:23:45.123456",
  "components": [
    {
      "id": "blackboard",
      "status": "degraded",
      "message": "File is stale (>30min old)",
      "last_check": "2025-12-28T14:23:45.123456",
      "metrics": {
        "file_size": 2048,
        "last_modified": "2025-12-28T13:00:00.000000",
        "phase": "complete",
        "message_count": 12
      }
    }
  ]
}
```

**Response (Error):**
```json
{
  "success": true,
  "overall_status": "error",
  "timestamp": "2025-12-28T14:23:45.123456",
  "components": [
    {
      "id": "data-tasks",
      "status": "error",
      "message": "Invalid JSON: Expecting property name...",
      "last_check": "2025-12-28T14:23:45.123456",
      "metrics": {}
    }
  ]
}
```

---

## 8. Operational Notes

### 8.1 Development vs Production

**Current State:** Development mode (auto-reload enabled)

- `uvicorn.run(..., reload=True)` in `run.py`
- Server restarts on file changes
- Not suitable for production load

**Production Deployment (Future):**
```bash
# Disable reload, add workers
uvicorn api.main:app --host 0.0.0.0 --port 7777 --workers 4 --log-level info
```

### 8.2 Logging

**Current Logging Level:** `warning`

```python
# In run.py
uvicorn.run(..., log_level="warning")
```

**Change to Debug:**
```python
uvicorn.run(..., log_level="debug")
```

**Structured Logging (Future):**
- Implement JSON logging for all API requests
- Add request IDs for tracing
- Log to file + stdout

### 8.3 Security Considerations

**Current State:**
- CORS allow-all (for localhost/extension access)
- No authentication/authorization
- No rate limiting

**Suitable for:** Local development, single-user command center

**NOT suitable for:** Public-facing deployment, multi-user environment

**Future Hardening:**
- API key authentication for external access
- Rate limiting per IP
- CORS restrict to specific origins

### 8.4 Performance Baseline

**Typical Latency (localhost):**
- `GET /api/health`: <5ms
- `GET /api/system/health`: 10-50ms (depends on file I/O)
- `POST /api/team/spawn`: 500-1000ms (Windows Terminal spawn)
- `GET /api/tasks`: <10ms

**Throughput:**
- Handles 100+ req/sec on localhost (single worker)
- No load testing performed for concurrent users

**Bottlenecks:**
- JSON file I/O (synchronous reads/writes)
- Windows Terminal spawning (subprocess overhead)

---

## 9. Future Enhancements

### 9.1 Health Check Improvements

- [ ] Add uptime tracking (server start time → current time)
- [ ] Add response time metrics per endpoint (P50/P95/P99)
- [ ] Add error rate tracking (errors per minute)
- [ ] Port availability check (before server start)
- [ ] Disk space monitoring (prevent out-of-space errors)

### 9.2 Recovery Automation

- [ ] Auto-restart on repeated health check failures
- [ ] Automatic backup before data file writes
- [ ] Circuit breaker for failing components
- [ ] Graceful degradation (disable failing optional modules)

### 9.3 Flight Path Integration

- [ ] WebSocket endpoint for real-time health updates
- [ ] Historical metrics storage (SQLite or JSONL)
- [ ] Trend analysis (CPU/RAM over time)
- [ ] Predictive alerts (memory leak detection)

---

## 10. Quick Reference

### Essential Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/health` | GET | Simple health check |
| `/api/system/health` | GET | Full component health |
| `/api/system/stats` | GET | CPU/RAM metrics |
| `/api/system/topology` | GET | System graph |
| `/api/server/restart` | POST | Restart server |
| `/api/server/status` | GET | Server PID/port info |

### Essential Files

| File | Purpose |
|------|---------|
| `run.py` | Server entry point |
| `api/main.py` | FastAPI app definition |
| `api/system/health.py` | Health check logic |
| `api/system/topology.py` | System graph builder |
| `api/system/models.py` | Health/topology data models |

### Common Commands

```bash
# Start server
cd C:\Users\<user>\workspace\IHIM && python run.py

# Check health
curl http://localhost:7777/api/health

# Kill all Python
Stop-Process -Name python -Force

# Restart via API
curl -X POST http://localhost:7777/api/server/restart
```

---

**Document Version:** 1.0
**Last Updated:** 2025-12-28
**Maintainer:** the agent Sentinel (workspace Agent)
**Status:** Production-ready for Flight Path integration
