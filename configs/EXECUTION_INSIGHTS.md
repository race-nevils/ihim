# Execution Insights

## Context

These are execution insights from the agent harness agent mode runs—operational learnings from our current development tooling. They inform how we use the agent effectively, not ARLM architecture itself.

---

Central learnings from agent mode executions. Updated after each significant run.

---

## Mode Comparison Matrix

| Mode | Agents | Structure | Best For | Weakness |
|------|--------|-----------|----------|----------|
| **Yellow Mode** | 2S + 4W + 4O | Flat parallel | Fast builds, known tasks | No false positive detection |
| **Red Mode** | 8S + 2H monitors | Dual-team | Discovery, audits, uncertain tasks | Higher token cost |
| **Green Mode** | 10H | Flat verify | Binary PASS/FAIL gates | No meta-analysis |
| **Blue Mode** | 10H | Flat recon | Information gathering | READ-ONLY, no fixes |

---

## Key Finding: Monitor Value

**Date:** 2025-12-27
**Run:** exec-2025-12-27-006

### Red Mode vs Flat the agent

| Metric | Red Mode (8S+2H) | Flat the agent (6S) |
|--------|------------------|------------------|
| False positives caught | 2 | 0 |
| Architectural insights | 2 | 0 |
| Unnecessary code added | 0 | Would be 2 |
| Meta-level analysis | Yes | No |

**Verdict:** Red Mode's monitors provide significant value when:
- Task list may contain false positives
- Architectural context matters
- Cross-validation is valuable

### When to Use Each

**Use Red Mode (8S + 2H) when:**
- Findings list came from automated scan (may have false positives)
- Need architectural/structural insights
- Task requires judgment calls (fix vs don't fix)
- Want cross-validation of work

**Use Flat the agent (6S) when:**
- Bug list is validated and certain
- Pure implementation, no judgment needed
- Speed over thoroughness
- Simple, isolated fixes

---

## Execution Log

All runs logged to: `IHIM/configs/execution-logs/executions.jsonl`

### Session 2025-12-27 Summary

| Wave | Mode | Task | Outcome |
|------|------|------|---------|
| 1 | yellow-mode | Mission Control audit | 17 bugs found |
| 2 | red-team-fix (4S) | Fix 4 CRITICALs | 4/4 fixed |
| 3 | green-mode-verify | Verify fixes | PASS + 9 new findings |
| 4 | red-team-fix (6S) | Fix 6 issues | 6/6 fixed |
| 5 | green-mode-verify | Verify fixes | PASS + 28 new findings |
| 6 | red-mode (8S+2H) | Fix 8 issues | 6 fixed, 2 false positives caught |

**Total bugs fixed:** 16
**False positives avoided:** 2
**Architectural insights gained:** 2

---

## Heuristics Extracted

### H-EXEC-001: False Positive Rate
When findings come from automated deep scans, expect 20-30% false positive rate. Use Red Mode monitors to catch them.

### H-EXEC-002: Monitor Placement
Place monitors to observe ACROSS teams, not within. Frontend monitor watching frontend-only provides less value than one watching the full picture.

### H-EXEC-003: Verify Finds More
Each Green Mode verify wave discovers ~2x more issues than the original finding. Plan for multiple cycles.

### H-EXEC-004: Closed Loop Requirement
Never end a workflow at FIX. Always run VERIFY. Open loops accumulate.

---

## Improvement Tracking

### To Measure (Future Runs)
- [ ] Token usage per mode (need to add tracking)
- [ ] Time to completion per agent
- [ ] Cost per bug fixed
- [ ] Rework rate (fixes that needed re-fixing)

### To Implement
- [ ] Unified CleanupManager (from Monitor B insight)
- [ ] Terminal WebSocket cleanup on unload (from Monitor A insight)
- [ ] Automatic execution logging (currently manual)

---

*This file is updated after significant mode executions. It drives continuous improvement of agent configurations.*
