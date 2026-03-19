# VPT System - Integration Summary

Quick reference for implementing the VPT feedback loop system.

---

## Flow Diagram (Text-Based)

```
┌──────────────────────────────────────────────────────────────────────┐
│                     VPT FEEDBACK LOOP CYCLE                          │
└──────────────────────────────────────────────────────────────────────┘


    ┌──────────────┐
    │   SESSION    │  the agent executes task
    │   EXECUTION  │  - Commands/tools used
    └──────┬───────┘  - Decisions made
           │          - Signals observed
           │
           ▼
    ┌──────────────┐
    │ MEASUREMENT  │  /debrief captures:
    │   (Debrief)  │  - 27 commands (8 effective, 19 wasted)
    └──────┬───────┘  - Score: Problem=4, Speed=2, Efficiency=3
           │          - VPT: 0.020 (60% below target)
           │
           ▼
    ┌──────────────┐
    │   STORAGE    │  Data saved to:
    │  (Data Files)│  - debriefs.jsonl (raw session)
    └──────┬───────┘  - vpt_trends.json (time series)
           │          - heuristics.json (rules extracted)
           │
           ▼
    ┌──────────────┐
    │   ANALYSIS   │  Weekly aggregate:
    │  (Patterns)  │  - Pattern "shell_escaping" = 0.018 VPT (LOW)
    └──────┬───────┘  - Frequency: 11 occurrences
           │          - Cost: ~2000 tokens/occurrence
           │
           ▼
    ┌──────────────┐
    │  PROMOTION   │  Decision tree:
    │ (Heuristics) │  - Low VPT + Frequent = EXTRACT HEURISTIC
    └──────┬───────┘  - h003: "Use cmd.exe wrapper, not bash escaping"
           │          - Test: Apply in next 3 sessions
           │
           ▼
    ┌──────────────┐
    │   ACTION     │  Boot sequence (next session):
    │ (Boot Load)  │  - Load h003 into context
    └──────┬───────┘  - VPT summary shows shell_escaping as risk
           │          - Heuristic: "Before PowerShell, check h003"
           │
           └──────────┐
                      ▼
                ┌──────────────┐
                │   SESSION    │  New session (improved):
                │  EXECUTION   │  - h003 applied immediately
                └──────────────┘  - 5 commands (was 27)
                      │          - VPT: 0.055 (10% above target)
                      │
                      └─────> LOOP CLOSES (system improved)


═══════════════════════════════════════════════════════════════════════

PROMOTION PATHWAY (High VPT → Skills → Memory)

    Low VPT Session (0.020)
            │
            ▼
    Extract Heuristic (h003)
            │
            ├─> Test (3 uses)
            │       │
            │       ├─> Success Rate: 85%
            │       ├─> Avg VPT Boost: +0.032
            │       └─> Tokens Saved: 1800/use
            │
            ▼
    High VPT Confirmed (0.052 avg)
            │
            ├─────────────┬──────────────┬────────────┐
            │             │              │            │
            ▼             ▼              ▼            ▼
       MEMORY.md      Skill Ref    Guardrail?    Dashboard
       (Top 5)        (10+ uses)   (Critical?)   (Visualize)
            │             │              │            │
            ▼             ▼              ▼            ▼
       Boot time    Capability    Prevent      Track trend
       context      package       disaster     in iHIM


═══════════════════════════════════════════════════════════════════════

META-FEEDBACK LOOP (System Measures Itself)

    VPT System Running
            │
            ▼
    Weekly Health Check
            │
            ├─> VPT trending up? (YES = healthy)
            ├─> Heuristics applied? (>70% = healthy)
            ├─> Heuristics effective? (>80% success = healthy)
            └─> Patterns covered? (>90% tagged = healthy)
            │
            ├─> IF UNHEALTHY:
            │       │
            │       ├─> VPT declining → Review debriefs
            │       ├─> Low application → Increase visibility
            │       ├─> Low effectiveness → Refine/archive
            │       └─> Low coverage → Manual pattern review
            │
            └─> Adjust system parameters
                    │
                    └─> Next week improves
```

---

## Integration Points

### 1. `/debrief` Command
**Current:** Captures metrics, scores, root cause → saves to debriefs.jsonl

**Add:**
- VPT calculation (scores ÷ tokens)
- Comparison to target (0.05)
- Comparison to baseline (same pattern, past sessions)
- Update vpt_trends.json

**Files Modified:**
- `harness/commands/debrief.md` (add VPT steps)
- `IHIM/data/debriefs.jsonl` (schema enhancement)
- New: `IHIM/data/vpt_trends.json`

**Implementation Priority:** HIGH (foundation)

---

### 2. `/save` Command
**Current:** Self-audit → sanity check → update memory

**Add:**
- Quick VPT estimate (command count proxy)
- If VPT < 0.03, prompt for /debrief
- Include VPT awareness in learnings

**Files Modified:**
- `harness/commands/save.md` (add VPT check)

**Implementation Priority:** MEDIUM (improvement nudge)

---

### 3. `/endsession` Command
**Current:** Collect session → append to blackboard

**Add:**
- Calculate session VPT summary
- Include VPT in blackboard entry
- Update daily VPT snapshot

**Files Modified:**
- `harness/commands/endsession.md` (add VPT summary)
- `harness/blackboard/sessions.json` (schema enhancement)

**Implementation Priority:** MEDIUM (tracking)

---

### 4. Boot Sequence
**Current:** Load MEMORY.md, NOTES.md, GUARDRAILS.md, tier awareness

**Add:**
- Load VPT context summary (auto-generated)
- Top 5 heuristics by impact
- Recent VPT trend (last 7 days)
- Focus areas (low VPT patterns)

**Files Modified:**
- `CLAUDE.md` (add VPT boot step)
- New: `IHIM/data/vpt_boot_summary.json` (auto-generated)

**Implementation Priority:** HIGH (immediate value)

---

### 5. Heuristics System
**Current:** Extract IF-THEN rules → save to heuristics.json → add to MEMORY.md

**Add:**
- Track application (when used)
- Track outcome (success/failure)
- Calculate effectiveness (VPT boost)
- Auto-archive low performers
- Auto-promote high performers

**Files Modified:**
- `IHIM/data/heuristics.json` (add tracking fields)
- `MEMORY.md` (heuristic effectiveness scores)

**Implementation Priority:** HIGH (core loop)

---

### 6. iHIM Dashboard
**Current:** Quick Notes, Tasks, Stopwatches, Periodic Table

**Add:**
- VPT gauge widget (current vs target)
- Heuristics dashboard (top 5 by impact)
- Pattern performance matrix
- VPT trend graph (time series)

**New API Endpoints:**
- `GET /api/vpt/summary`
- `GET /api/vpt/heuristics`
- `GET /api/vpt/trends?period=30d`
- `GET /api/vpt/patterns`

**Files to Create:**
- `IHIM/api/vpt/endpoints.py`
- `IHIM/ui/widgets/vpt_gauge.js`
- `IHIM/ui/widgets/heuristics_dashboard.js`

**Implementation Priority:** LOW (visibility, not critical path)

---

### 7. Weekly Analysis Script
**Current:** None

**Add:**
- Automated weekly VPT report
- Pattern extraction across sessions
- Heuristic effectiveness calculation
- System health check
- Promotion recommendations

**Files to Create:**
- `IHIM/scripts/weekly_vpt_analysis.py`
- Run via cron or manual `/analyze-vpt`

**Implementation Priority:** MEDIUM (continuous improvement)

---

## Recommended Implementation Order

### Sprint 1 (Week 1): Foundation
1. **Update debrief schema** - Add VPT fields to debriefs.jsonl
2. **VPT calculation** - Implement scoring ÷ tokens formula
3. **Create vpt_trends.json** - Storage for time-series data
4. **Test on real sessions** - Run /debrief on 3 recent tasks

**Deliverable:** Working VPT calculation in /debrief command

---

### Sprint 2 (Week 2): Boot Integration
1. **VPT boot summary** - Auto-generate from vpt_trends.json
2. **Update boot sequence** - Load VPT context in CLAUDE.md
3. **Heuristic tracking** - Add application/outcome fields to heuristics.json
4. **Test awareness** - Verify the agent sees VPT context at boot

**Deliverable:** the agent has VPT awareness at session start

---

### Sprint 3 (Week 3): Analysis Pipeline
1. **Pattern extraction** - Group debriefs by pattern, calculate VPT
2. **Trend calculation** - Weekly slope, direction, significance
3. **Heuristic effectiveness** - Track success rate, tokens saved
4. **Promotion logic** - Auto-promote high VPT, archive low VPT

**Deliverable:** Automated weekly VPT report

---

### Sprint 4 (Week 4): Command Integration
1. **Enhance /save** - Add VPT check and debrief prompt
2. **Enhance /endsession** - Include VPT in blackboard
3. **Circuit breaker** - Add 10-command VPT checkpoint
4. **Test end-to-end** - Full session with all integrations

**Deliverable:** Complete feedback loop operational

---

### Sprint 5 (Week 5+): Dashboard & Refinement
1. **VPT gauge widget** - Visual performance indicator
2. **Heuristics dashboard** - Top 5 by impact
3. **API endpoints** - RESTful access to VPT data
4. **Meta-feedback** - System health check automation

**Deliverable:** iHIM dashboard with VPT visibility

---

## Quick Reference: Key Formulas

### VPT Calculation
```python
raw_score = (
    problem_understanding * 0.2 +
    diagnosis_speed * 0.25 +
    solution_efficiency * 0.3 +
    tool_mastery * 0.15 +
    communication * 0.1
)

vpt = raw_score / (tokens_consumed / 1000)

# Target: 0.05 (5 value points per 1K tokens)
```

### Trend Calculation
```python
this_week_avg = mean([session.vpt for session in last_7_days])
last_week_avg = mean([session.vpt for session in days_8_to_14])

slope = this_week_avg - last_week_avg
direction = "improving" if slope > 0 else "declining"
```

### Heuristic Effectiveness
```python
times_applied = len(heuristic.applications)
success_rate = sum(app.outcome == "success") / times_applied

avg_tokens_saved = mean([app.tokens_saved for app in applications])
avg_vpt_boost = mean([app.vpt_with - baseline for app in applications])

effective = success_rate > 0.8 and avg_vpt_boost > 0.02
```

### Pattern VPT
```python
pattern_sessions = [s for s in debriefs if s.pattern == "shell_escaping"]
pattern_vpt = mean([s.vpt.vpt_value for s in pattern_sessions])

status = (
    "good" if pattern_vpt >= 0.05 else
    "ok" if pattern_vpt >= 0.03 else
    "low"
)
```

---

## Data File Schemas

### vpt_trends.json
```json
{
  "snapshots": [
    {
      "timestamp": "ISO-8601",
      "period": "week_52_2025",
      "sessions_count": 8,
      "avg_vpt": 0.042,
      "trend_direction": "improving",
      "trend_slope": 0.008
    }
  ]
}
```

### debriefs.jsonl (enhanced)
```json
{
  "timestamp": "ISO-8601",
  "metrics": { "total_commands": 27, "effective_commands": 8 },
  "scores": { "problem_understanding": 4, "overall": 3 },
  "vpt": {
    "raw_score": 3.0,
    "tokens_consumed": 15000,
    "vpt_value": 0.020,
    "target": 0.05,
    "performance": "below_target"
  }
}
```

### heuristics.json (enhanced)
```json
{
  "id": "h004",
  "trigger_conditions": ["frontend loads but content empty"],
  "action": "Ask for F12 console screenshot",
  "applications": [
    {
      "session_id": "2025-12-28-mc-fix",
      "applied": true,
      "outcome": "success",
      "tokens_saved_actual": 1847,
      "vpt_with_heuristic": 0.065,
      "vpt_baseline": 0.022
    }
  ],
  "effectiveness": {
    "times_applied": 3,
    "success_rate": 1.0,
    "avg_tokens_saved": 1823,
    "avg_vpt_boost": 0.041
  }
}
```

---

## Success Indicators (3 Months)

| Metric | Current | Target | Status |
|--------|---------|--------|--------|
| Avg VPT | 0.039 | 0.055 | Track weekly |
| Heuristic count | 6 | 15-20 | Growing |
| Application rate | 0% | 70% | Measure in Sprint 2 |
| VPT trend slope | Unknown | +0.005/week | Track from Sprint 1 |
| Debrief rate | ~60% | ~30% | Fewer low-VPT sessions |

---

## Critical Dependencies

1. **Token counting** - Need accurate token consumption data
   - Fallback: Use command count as proxy (1 command ≈ 500-1000 tokens)
   - Long-term: Integrate with Anthropic API for actual token counts

2. **Pattern taxonomy** - Need consistent pattern naming
   - Start with existing: zombie_process, shell_escaping, frontend_silent_failure
   - Add as discovered, maintain in patterns.json

3. **Baseline VPT** - Need historical data for comparison
   - Bootstrap: First 10 sessions establish baseline
   - Refine: Update baseline monthly as system improves

---

## Document Cross-References

- Full design: `VPT_FEEDBACK_LOOP_DESIGN.md`
- Debrief command: `harness/commands/debrief.md`
- Save command: `harness/commands/save.md`
- Heuristics data: `IHIM/data/heuristics.json`
- Flight Path philosophy: `IHIM/FLIGHT_PATH.md`

---

**Version:** 1.0
**Created:** 2025-12-29
**Next Review:** After Sprint 1 completion
