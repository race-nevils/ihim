# Flight Path Systems

System documentation for SCADA-like monitoring. Each system has health metrics, degradation patterns, and recovery procedures.

Updated: 2025-12-28

---

## Systems Index

| System | File | Description | Health Endpoints |
|--------|------|-------------|------------------|
| **the agent harness Foundation** | `claude_code_foundation.md` | API rate limits, context windows, agent spawning constraints | `/api/health/rate-limits`, `/api/health/context` |
| **Memory System** | `memory_system.md` | MEMORY.md, NOTES.md, archive management | `/api/system/memory/health` |
| **Blackboard System** | `blackboard_system.md` | Agent coordination, message passing, file locking | `/api/blackboard/health` |
| **Guardrails System** | `guardrails_system.md` | Autonomous operation boundaries, enforcement flow | `/api/system/guardrails/health` |
| **Team/Agent System** | `team_agent_system.md` | Agent spawning, tiering, wave execution | `/api/metrics/spawn`, `/api/team/status` |
| **iHIM API System** | `ihim_api_system.md` | FastAPI backend, dashboard, port 7777 | `/api/system/health`, `/api/system/topology` |
| **Syncthing System** | `syncthing_system.md` | File sync, versioning, conflict resolution | `/api/health/syncthing` |

---

## System Hierarchy

```
the agent harness Foundation (substrate)
    │
    ├── Memory System (context persistence)
    │   └── MEMORY.md, NOTES.md, MEMORY_ARCHIVE.md
    │
    ├── Guardrails System (operational boundaries)
    │   └── GUARDRAILS.md
    │
    ├── Team/Agent System (agent coordination)
    │   ├── spawner.py, templates.py
    │   └── Blackboard System (message bus)
    │       └── blackboard.py, blackboard.json
    │
    ├── iHIM API System (dashboard backend)
    │   └── main.py, run.py
    │
    └── Syncthing System (file sync)
        └── .stignore, .stversions
```

---

## Adding New Systems

When documenting a new system:

1. Create `{system_name}_system.md` in this folder
2. Follow the standard structure:
   - System Overview
   - Components
   - Data Flow
   - Health Metrics (with thresholds)
   - Degradation Patterns (with detection)
   - Recovery Procedures (with runbooks)
3. Update this README index
4. Wire health endpoints into Flight Path dashboard

---

## Health Monitoring Principles

**Three-tier alerting**:
- GREEN: All metrics within normal range
- YELLOW: Approaching thresholds, investigation needed
- RED: Critical, immediate action required

**Metrics categories**:
- Availability (is it running?)
- Performance (how fast?)
- Correctness (is data valid?)
- Capacity (how much headroom?)

**Recovery automation levels**:
- LOW: Requires human judgment
- MEDIUM: Can be scripted with confirmation
- HIGH: Fully automatable

---

*This folder is part of Flight Path. Each system feeds into the SCADA-like dashboard.*
