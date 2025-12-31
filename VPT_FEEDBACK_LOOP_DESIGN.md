# VPT Feedback Loop Design

**Core Principle:** "If the test becomes better, everything becomes better."

VPT (Value Per Token) measures the efficiency of AI sessions: value delivered divided by tokens consumed. This design outlines how VPT data flows through the system to drive continuous improvement.

---

## System Overview

```
┌────────────────────────────────────────────────────────────────┐
│                    VPT FEEDBACK LOOP                            │
└────────────────────────────────────────────────────────────────┘

     ┌─────────────┐
     │  EXECUTION  │ Session happens (commands, tools, decisions)
     └──────┬──────┘
            │
            ▼
     ┌─────────────┐
     │ MEASUREMENT │ Capture metrics (commands, efficiency, signals)
     └──────┬──────┘
            │
            ▼
     ┌─────────────┐
     │   STORAGE   │ Store in structured formats (debriefs.jsonl, metrics)
     └──────┬──────┘
            │
            ▼
     ┌─────────────┐
     │  ANALYSIS   │ Extract patterns, calculate trends, identify learnings
     └──────┬──────┘
            │
            ▼
     ┌─────────────┐
     │ PROMOTION   │ High-VPT patterns → heuristics → skills → memory
     └──────┬──────┘
            │
            ▼
     ┌─────────────┐
     │   ACTION    │ Apply learnings in next session (boot-time context)
     └──────┬──────┘
            │
            └──────────┐
                       ▼
                  ┌─────────────┐
                  │ EXECUTION   │ Improved session (loop closes)
                  └─────────────┘
```

---

## 1. Measurement Layer

### What Gets Measured

**Per Session:**
- Total commands/tools used
- Effective commands (moved task forward)
- Wasted commands (dead ends, retries)
- Efficiency ratio: effective / total
- Dead ends encountered
- Pivots made
- Time-to-root-cause (early/mid/late)
- Signal-to-action latency (per signal)
- Token count (if available via API)
- Value delivered (scored 1-10 across 5 dimensions)

**Value Dimensions (1-10 scale):**
1. Problem Understanding - grasped before coding?
2. Diagnosis Speed - how fast to root cause?
3. Solution Efficiency - minimum path vs actual?
4. Tool Mastery - right tools, used well?
5. Communication - kept user informed?

**Calculated VPT:**
```python
vpt_score = (
    (problem_understanding * 0.2) +
    (diagnosis_speed * 0.25) +
    (solution_efficiency * 0.3) +
    (tool_mastery * 0.15) +
    (communication * 0.1)
) / (tokens_consumed / 1000)

# Result: value points per 1K tokens
# Target: >0.05 (5 value points per 1K tokens)
```

### Measurement Triggers

**Automatic:**
- After any task taking 10+ tool calls
- After 3+ same errors
- After user frustration signals ("fucking", "again", "still not working")
- After any /debrief or /save command

**Manual:**
- User invokes /debrief
- Before /endsession

### Measurement Interface

**Existing:** `/debrief` command (already structured)
**Enhancement:** Add VPT calculation to debrief output

```python
# Add to debriefs.jsonl schema
{
  "timestamp": "ISO-8601",
  "task": "brief description",
  "outcome": "success|partial|failed",
  "metrics": {
    "total_commands": 25,
    "effective_commands": 8,
    "efficiency_ratio": 0.32,
    "dead_ends": 4,
    "pivots": 2,
    "time_to_root_cause": "late",
    "signal_latency_total": 43,  # NEW
    "tokens_consumed": 15000      # NEW (estimate if API unavailable)
  },
  "scores": {
    "problem_understanding": 4,
    "diagnosis_speed": 2,
    "solution_efficiency": 3,
    "tool_mastery": 4,
    "communication": 5,
    "overall": 3
  },
  "vpt": {                        # NEW
    "raw_score": 3.6,
    "tokens_consumed": 15000,
    "vpt_value": 0.024,           # 2.4 value points per 1K tokens
    "target": 0.05,
    "performance": "below_target"
  },
  "root_cause": "...",
  "learning": "...",
  "pattern": "zombie_process"
}
```

---

## 2. Storage Layer

### Data Files

| File | Format | Purpose | Retention |
|------|--------|---------|-----------|
| `debriefs.jsonl` | JSONL | Raw session data | Unlimited |
| `heuristics.json` | JSON | IF-THEN rules extracted | Unlimited |
| `MEMORY.md` | Markdown | Boot-time context (recent 15) | Pruned weekly |
| `MEMORY_ARCHIVE.md` | Markdown | Full audit trail | Unlimited |
| `metrics.json` | JSON | Aggregated trends | Unlimited |
| `vpt_trends.json` | JSON | VPT time-series data | Unlimited |

### New File: `vpt_trends.json`

```json
{
  "snapshots": [
    {
      "timestamp": "2025-12-29T12:00:00Z",
      "period": "week_52_2025",
      "sessions_count": 8,
      "avg_vpt": 0.042,
      "median_vpt": 0.038,
      "best_session_vpt": 0.089,
      "worst_session_vpt": 0.015,
      "trend_direction": "improving",
      "trend_slope": 0.008,
      "top_patterns": [
        {"pattern": "frontend_silent_failure", "avg_vpt": 0.065},
        {"pattern": "zombie_process", "avg_vpt": 0.055}
      ],
      "bottom_patterns": [
        {"pattern": "shell_escaping", "avg_vpt": 0.018}
      ]
    }
  ],
  "all_time": {
    "total_sessions": 47,
    "avg_vpt": 0.039,
    "improvement_rate": 0.012,  # VPT gain per week
    "best_session": {
      "id": "2025-12-28-mc-draggable",
      "vpt": 0.089,
      "why": "Applied h004 immediately, saved 2000 tokens"
    }
  }
}
```

---

## 3. Analysis Layer

### Pattern Extraction

**Trigger:** After every 5 debriefs, run analysis to find patterns.

**Process:**
1. Load last 20 debriefs from `debriefs.jsonl`
2. Group by `pattern` field
3. Calculate per-pattern metrics:
   - Frequency (how often seen)
   - Avg VPT when pattern occurs
   - Avg tokens wasted
   - Avg time-to-resolution
4. Identify:
   - **High-cost patterns** (frequent + low VPT) → prioritize for heuristics
   - **High-value patterns** (frequent + high VPT) → codify and promote
   - **Emerging patterns** (new, trend unclear) → watch

**Output:** Pattern report to terminal + update `metrics.json`

### Trend Calculation

**Weekly aggregate:**
```python
def calculate_vpt_trend(period_days=7):
    """
    Compare VPT this week vs last week.
    Returns: slope, direction, significance
    """
    debriefs = load_debriefs()
    now = datetime.now()

    # Split into periods
    this_week = [d for d in debriefs if (now - d.timestamp).days <= 7]
    last_week = [d for d in debriefs if 7 < (now - d.timestamp).days <= 14]

    # Calculate averages
    this_avg = mean([d.vpt.vpt_value for d in this_week])
    last_avg = mean([d.vpt.vpt_value for d in last_week])

    # Slope
    slope = this_avg - last_avg
    direction = "improving" if slope > 0 else "declining"

    # Statistical significance (t-test)
    significance = ttest_ind(
        [d.vpt.vpt_value for d in this_week],
        [d.vpt.vpt_value for d in last_week]
    )

    return {
        "slope": slope,
        "direction": direction,
        "significant": significance.pvalue < 0.05,
        "this_week_avg": this_avg,
        "last_week_avg": last_avg
    }
```

### Heuristic Quality Scoring

**Problem:** How do we know if a heuristic is actually helping?

**Solution:** Track application and outcome.

```json
{
  "id": "h004",
  "trigger_conditions": ["frontend loads but content empty"],
  "action": "Ask user for F12 console screenshot",
  "anti_action": "Do NOT debug backend or spawn swarms first",
  "applications": [
    {
      "session_id": "2025-12-28-mc-fix",
      "applied": true,
      "outcome": "success",
      "tokens_saved_estimate": 2000,
      "tokens_saved_actual": 1847,
      "vpt_with_heuristic": 0.065,
      "vpt_baseline": 0.022  # from similar sessions without heuristic
    }
  ],
  "effectiveness": {
    "times_applied": 3,
    "success_rate": 1.0,
    "avg_tokens_saved": 1823,
    "avg_vpt_boost": 0.041,
    "confidence": 0.98
  }
}
```

**Key insight:** Each heuristic becomes a mini A/B test. Compare VPT when applied vs baseline.

---

## 4. Promotion Layer

### Promotion Pathway

```
Low VPT Pattern → Extract Heuristic → Test (3+ uses) → High VPT?
                                                            │
                                                      ┌─────┴─────┐
                                                      │           │
                                                     YES          NO
                                                      │           │
                                                      ▼           ▼
                                              Promote to      Refine or
                                              MEMORY.md       Archive
                                                      │
                                                      │
                                              ┌───────┴───────┐
                                              │               │
                                         Frequent?        Critical?
                                              │               │
                                             YES             YES
                                              │               │
                                              ▼               ▼
                                         Add to Skill    Add to Guardrail
```

### Promotion Criteria

**Heuristic → MEMORY.md:**
- Applied 3+ times
- Success rate >80%
- Avg VPT boost >0.02
- OR: Critical (prevents catastrophic failure)

**Heuristic → Skill:**
- Applied 10+ times across multiple contexts
- Broad applicability (not task-specific)
- Can be described as a capability
- Example: "Fast frontend debugging" skill incorporating h004, h005, h006

**Heuristic → Guardrail:**
- Prevents destructive actions
- Applies system-wide
- Example: "Never spawn 10+ agents without F12 check first" (from h004 learnings)

**Low-performing heuristic → Archive:**
- Applied 5+ times
- Success rate <50%
- OR: No longer relevant (tool changed, workflow evolved)

### Skill Refinement

**VPT-driven skill evolution:**

```markdown
# Example: LP--ui-design skill
## VPT Performance
- Current: 0.09 (90% VPT - excellent)
- Baseline: 0.05
- Sessions: 12
- Trend: Stable

## What's Working (keep)
- Tight scope (visual design only)
- Clear defer pattern (coding → LP Lead)
- Specific examples in context

## What's Not Working (remove)
- None identified

## Learnings to Incorporate
- h008: Always show color in hex + preview
- h012: Reference existing components before suggesting new
```

**LP Lead skill (needs refinement):**

```markdown
# Example: LP skill
## VPT Performance
- Current: 0.05 (50% VPT - at target but improvable)
- Baseline: 0.05
- Sessions: 23
- Trend: Flat

## What's Working (keep)
- Coordination role
- Architecture decisions
- Mentoring approach

## What's Not Working (remove)
- Too much context about Next.js internals (rarely used)
- Boilerplate examples (agents can search)

## Learnings to Incorporate
- h015: Defer to specialists earlier (reduces token waste)
- h017: Ask for wireframe before coding (prevents rework)

## Action: TRIM
Reduce skill.md from 800 lines → 400 lines, keep principles, remove examples.
```

---

## 5. Action Layer

### Boot-Time Context Injection

**Current boot sequence:**
1. Read `MEMORY.md`
2. Read `NOTES.md`
3. Read `GUARDRAILS.md`
4. Load tier awareness

**Enhanced boot sequence:**
1. Read `MEMORY.md` (includes top heuristics)
2. Read `NOTES.md`
3. Read `GUARDRAILS.md`
4. Load tier awareness
5. **NEW:** Load VPT context summary

**VPT context summary (auto-generated):**

```markdown
## VPT Performance (Last 7 Days)
- Avg VPT: 0.042 (target: 0.05) - BELOW TARGET
- Trend: +0.008/week (improving)
- Best session: 0.089 (mc-draggable)
- Worst session: 0.015 (shell-escaping loop)

## Active Heuristics (Top 5 by Impact)
1. **h004** (frontend silent failure) - 2000 tokens/use, 98% success
2. **h001** (zombie process) - 500 tokens/use, 95% success
3. **h005** (z-index burial) - 1500 tokens/use, 90% success
4. **h006** (agent template corruption) - 1000 tokens/use, 85% success
5. **h002** (systemic issue signal) - 300 tokens/use, 90% success

## Focus Areas (Low VPT Patterns)
- shell_escaping (0.018 VPT) - consider wrapping PowerShell calls
- assumption_error (0.021 VPT) - verify before implementing
```

This gives the agent immediate awareness of:
1. Current performance vs target
2. Which heuristics to prioritize
3. Which patterns to avoid

### In-Session Application

**Pre-action heuristic check:**

```python
# Pseudocode for the agent's decision process
def before_action(context):
    # Check if any heuristic triggers match
    matching_heuristics = check_heuristics(context)

    if matching_heuristics:
        for h in matching_heuristics:
            apply_action(h.action)
            avoid_action(h.anti_action)
            log_application(h.id, context)
    else:
        proceed_normally()
```

**Circuit breaker integration:**

```python
# After 10 commands, check VPT trajectory
if command_count == 10:
    estimated_vpt = calculate_current_vpt()

    if estimated_vpt < 0.03:  # Below acceptable threshold
        STOP()
        output("⚠️ VPT CIRCUIT BREAKER")
        output(f"Current trajectory: {estimated_vpt:.3f} (target: 0.05)")
        output("Questions:")
        output("1. Am I making progress? (Y/N)")
        output("2. Have I checked heuristics? (Y/N)")
        output("3. What signals have I ignored?")

        # Wait for user decision
        await_user_direction()
```

---

## 6. Dashboard Integration (iHIM)

### New UI Components

**1. VPT Widget (Periodic Table Style)**

```
┌─────────────────────────────┐
│         VPT GAUGE           │
│                             │
│   ┌─────────────────────┐   │
│   │                     │   │
│   │    0.042 / 0.05    │   │
│   │    ████████░░░░     │   │
│   │      84% TARGET     │   │
│   │                     │   │
│   └─────────────────────┘   │
│                             │
│  Trend: ↗ +0.008/week       │
│  Sessions: 8 this week      │
│  Best: 0.089 (mc-drag)      │
└─────────────────────────────┘
```

**2. Heuristics Dashboard**

```
┌─────────────────────────────────────────┐
│       ACTIVE HEURISTICS (Top 5)         │
├─────────────────────────────────────────┤
│ h004 │ Frontend Silent Fail │ 98% │ 2000t│
│ h001 │ Zombie Process      │ 95% │  500t│
│ h005 │ Z-Index Burial      │ 90% │ 1500t│
│ h006 │ Template Corruption │ 85% │ 1000t│
│ h002 │ Systemic Signal     │ 90% │  300t│
└─────────────────────────────────────────┘
```

**3. Pattern Performance Matrix**

```
┌─────────────────────────────────────────────┐
│         PATTERN PERFORMANCE                 │
├─────────────────────────────────────────────┤
│ Pattern              │ VPT  │ Freq │ Status │
├──────────────────────┼──────┼──────┼────────┤
│ frontend_debug       │ 0.065│  12  │ ✓ Good │
│ zombie_process       │ 0.055│   5  │ ✓ Good │
│ integration_gap      │ 0.032│   8  │ ~ OK   │
│ assumption_error     │ 0.021│   7  │ ⚠ Low  │
│ shell_escaping       │ 0.018│  11  │ ⚠ Low  │
└─────────────────────────────────────────────┘
```

**4. VPT Trend Graph (Time Series)**

```
VPT Over Time (Last 30 Days)

0.09 │                                    ▲
     │                                   ╱
0.07 │                              ╱▂▂▂
     │                         ▂▂▂▂╱
0.05 │ ─ ─ ─ ─ ─ ─ ─ TARGET ─ ─ ─ ─ ─ ─
     │           ╱▂▂▂▂
0.03 │      ▂▂▂▂╱
     │ ▂▂▂▂╱
0.01 │▂╱
     └──────────────────────────────────
      D1 ············· D15 ············ D30
```

### API Endpoints

**GET `/api/vpt/summary`**
```json
{
  "current_vpt": 0.042,
  "target_vpt": 0.05,
  "performance_pct": 84,
  "trend_direction": "improving",
  "trend_slope": 0.008,
  "sessions_this_week": 8,
  "best_session": {
    "id": "mc-draggable",
    "vpt": 0.089,
    "date": "2025-12-28"
  },
  "worst_session": {
    "id": "shell-escape-loop",
    "vpt": 0.015,
    "date": "2025-12-26"
  }
}
```

**GET `/api/vpt/heuristics`**
```json
{
  "active_count": 6,
  "heuristics": [
    {
      "id": "h004",
      "name": "Frontend Silent Failure",
      "success_rate": 0.98,
      "avg_tokens_saved": 2000,
      "times_applied": 3
    },
    ...
  ]
}
```

**GET `/api/vpt/trends?period=30d`**
```json
{
  "snapshots": [
    {"date": "2025-12-01", "vpt": 0.032},
    {"date": "2025-12-02", "vpt": 0.035},
    ...
  ],
  "trend_line": {
    "slope": 0.008,
    "intercept": 0.028,
    "r_squared": 0.82
  }
}
```

**GET `/api/vpt/patterns`**
```json
{
  "patterns": [
    {
      "name": "frontend_debug",
      "avg_vpt": 0.065,
      "frequency": 12,
      "status": "good"
    },
    ...
  ]
}
```

---

## 7. Integration with Existing Commands

### `/debrief` Enhancement

**Current flow:**
1. Collect metrics
2. Score dimensions
3. Extract root cause
4. Save to debriefs.jsonl
5. Extract heuristic
6. Update MEMORY.md

**Enhanced flow (add VPT):**
1. Collect metrics
2. Score dimensions
3. **NEW: Calculate VPT**
4. **NEW: Compare to baseline and target**
5. Extract root cause
6. Save to debriefs.jsonl (with VPT data)
7. Extract heuristic
8. **NEW: Score heuristic based on VPT boost potential**
9. Update MEMORY.md
10. **NEW: Update vpt_trends.json**

**Implementation:**

```python
# Add to /debrief command logic
def enhanced_debrief(session_data):
    # Existing
    metrics = collect_metrics(session_data)
    scores = score_dimensions(metrics)

    # NEW
    vpt = calculate_vpt(scores, metrics.tokens_consumed)
    vpt_performance = compare_to_target(vpt, target=0.05)
    vpt_vs_baseline = compare_to_baseline(vpt, pattern=metrics.pattern)

    # Existing
    root_cause = extract_root_cause(session_data)
    save_debrief(metrics, scores, vpt)  # Enhanced with VPT

    # Existing
    heuristic = extract_heuristic(root_cause)

    # NEW
    heuristic.expected_vpt_boost = calculate_expected_boost(vpt_vs_baseline)

    # Existing
    update_memory(heuristic)

    # NEW
    update_vpt_trends(vpt, session_data.timestamp)

    # Output
    return format_debrief_output(metrics, scores, vpt, heuristic)
```

### `/save` Enhancement

**Current flow:**
1. Self-audit
2. Run sanity check
3. Update MEMORY.md
4. Update NOTES.md
5. Confirm

**Enhanced flow (add VPT awareness):**
1. Self-audit
2. **NEW: Quick VPT check** (was this session efficient?)
3. Run sanity check
4. Update MEMORY.md
5. Update NOTES.md
6. **NEW: If VPT < 0.03, prompt for debrief**
7. Confirm

**Implementation:**

```python
# Add to /save command logic
def enhanced_save():
    # Existing
    audit_results = self_audit()

    # NEW
    estimated_vpt = quick_vpt_estimate(current_session)

    if estimated_vpt < 0.03:
        output("⚠️ Low VPT detected ({estimated_vpt:.3f})")
        output("This session may benefit from a /debrief.")
        user_wants_debrief = prompt("Run /debrief now? (y/n)")

        if user_wants_debrief:
            run_debrief()

    # Existing
    sanity_results = run_sanity_check()
    update_memory()
    update_notes_doc()
    confirm()
```

### `/endsession` Enhancement

**Current flow:**
1. Run sanity check
2. Collect session data
3. Append to blackboard
4. Confirm

**Enhanced flow:**
1. Run sanity check
2. Collect session data
3. **NEW: Calculate session VPT summary**
4. Append to blackboard (with VPT)
5. **NEW: Update daily VPT snapshot**
6. Confirm

---

## 8. Feedback Loop Health Metrics

### Meta-Feedback: Measuring the Measurement System

**The VPT feedback loop itself needs a feedback loop.**

| Metric | Target | Measurement |
|--------|--------|-------------|
| Heuristic application rate | >70% | % of sessions where at least 1 heuristic applied |
| Heuristic success rate | >80% | % of applied heuristics that improved outcome |
| VPT improvement rate | +0.005/week | Linear regression slope over 4 weeks |
| Pattern coverage | >90% | % of low-VPT sessions that get tagged with pattern |
| Time-to-heuristic | <3 sessions | Sessions between pattern discovery → heuristic creation |
| Heuristic lifespan | 10+ uses | How many times before obsolete/archived |

### Self-Improvement Triggers

**Automatic system adjustments:**

```python
# Weekly health check
def vpt_system_health_check():
    trends = load_vpt_trends()

    # Check 1: Are we improving?
    if trends.slope < 0:  # Declining
        alert("VPT DECLINING - System not learning")
        recommend("Review last 10 debriefs for missed patterns")

    # Check 2: Are heuristics being used?
    application_rate = calculate_heuristic_usage()
    if application_rate < 0.5:
        alert("HEURISTICS UNDERUTILIZED")
        recommend("Add heuristics to boot summary for visibility")

    # Check 3: Are heuristics effective?
    effectiveness = calculate_heuristic_effectiveness()
    low_performers = [h for h in heuristics if h.success_rate < 0.5]

    if low_performers:
        alert(f"LOW PERFORMING HEURISTICS: {len(low_performers)}")
        recommend(f"Archive or refine: {[h.id for h in low_performers]}")

    # Check 4: Pattern coverage
    untagged_sessions = get_untagged_low_vpt_sessions()
    if len(untagged_sessions) > 5:
        alert(f"{len(untagged_sessions)} sessions need pattern tags")
        recommend("Review and categorize")

    return health_report
```

---

## 9. Implementation Roadmap

### Phase 1: Foundation (Week 1)
- [ ] Add VPT calculation to /debrief command
- [ ] Create vpt_trends.json schema and storage
- [ ] Update debriefs.jsonl schema with VPT fields
- [ ] Add VPT summary to boot sequence
- [ ] Test on 3 real sessions

### Phase 2: Analysis (Week 2)
- [ ] Build pattern analysis scripts
- [ ] Implement trend calculation
- [ ] Add heuristic effectiveness tracking
- [ ] Create weekly VPT report generator
- [ ] Test aggregation across 10+ sessions

### Phase 3: Integration (Week 3)
- [ ] Enhance /save with VPT check
- [ ] Add VPT to /endsession blackboard
- [ ] Build promotion pipeline (heuristic → skill)
- [ ] Add circuit breaker to in-session logic
- [ ] Test end-to-end flow

### Phase 4: Dashboard (Week 4)
- [ ] Create VPT gauge widget
- [ ] Create heuristics dashboard
- [ ] Create pattern performance matrix
- [ ] Create trend graph visualization
- [ ] Build API endpoints
- [ ] Integrate into iHIM UI

### Phase 5: Meta-Feedback (Week 5)
- [ ] Implement VPT system health check
- [ ] Add auto-adjustment triggers
- [ ] Build system evolution dashboard
- [ ] Document learnings
- [ ] Refine based on usage

---

## 10. Success Metrics

**3-Month Goals:**

| Metric | Baseline (Now) | Target (3 Months) |
|--------|----------------|-------------------|
| Avg VPT | 0.039 | 0.055 |
| VPT improvement rate | Unknown | +0.005/week |
| Heuristic count | 6 | 15-20 |
| Heuristic application rate | 0% (not tracked) | 70% |
| Sessions requiring debrief | 60% | 30% |
| Avg commands per task | Unknown | -20% |
| User frustration events | ~2/week | <1/week |

**Long-term Vision (6 Months):**

- VPT becomes primary performance metric (replaces manual code review)
- Skills auto-evolve based on VPT performance
- New agents spawn with VPT-optimized context
- Flight Path shows VPT as primary health indicator
- the operator can see VPT trends at a glance in iHIM

---

## 11. Key Principles

1. **Measure Everything** - Can't improve what you don't measure
2. **Close the Loop** - Data → Analysis → Action → Measurement
3. **Automate Promotion** - High-VPT patterns automatically promoted
4. **Prune Ruthlessly** - Low-VPT patterns archived
5. **Meta-Feedback** - The measurement system measures itself
6. **Visibility** - VPT visible at boot, in-session, and in dashboard
7. **Actionable** - Every metric leads to a decision or action
8. **Self-Improving** - System gets better at getting better

---

## 12. Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|----------|
| VPT gaming (optimize metric, not value) | High | Use multiple dimensions, user satisfaction override |
| Token count unavailable | Medium | Use command count proxy, refine when API available |
| Heuristic overload (too many rules) | Medium | Cap at 20 active, archive low-performers |
| Analysis paralysis (too much data) | Low | Focus on top 5 heuristics, weekly summaries only |
| Pattern misclassification | Medium | Allow pattern reclassification, track accuracy |
| Stale heuristics (world changes) | Medium | Lifespan tracking, auto-archive after 6 months unused |

---

## Appendix A: VPT Calculation Examples

### Example 1: High VPT Session (mc-draggable)

```
Task: Make Mission Control draggable
Commands: 5
Tokens: ~3000
Outcome: Success

Scores:
- Problem Understanding: 9 (read existing code first)
- Diagnosis Speed: 10 (knew exactly what to do)
- Solution Efficiency: 9 (minimal path)
- Tool Mastery: 8 (used right tools)
- Communication: 9 (kept user informed)

Raw Score: (9*0.2 + 10*0.25 + 9*0.3 + 8*0.15 + 9*0.1) = 9.05
VPT: 9.05 / (3000/1000) = 3.02 / 3 = 0.089

Performance: EXCELLENT (79% above target)
```

### Example 2: Low VPT Session (shell-escaping)

```
Task: Kill zombie Python processes
Commands: 27
Tokens: ~15000
Outcome: Success (eventually)

Scores:
- Problem Understanding: 4 (didn't check processes first)
- Diagnosis Speed: 2 (very slow to root cause)
- Solution Efficiency: 3 (many dead ends)
- Tool Mastery: 4 (fought with PowerShell escaping)
- Communication: 5 (kept user updated but wasted time)

Raw Score: (4*0.2 + 2*0.25 + 3*0.3 + 4*0.15 + 5*0.1) = 3.0
VPT: 3.0 / (15000/1000) = 3.0 / 15 = 0.020

Performance: POOR (60% below target)
Learning: Created h001 (check processes first)
```

---

## Appendix B: Data Flow Diagram (Detailed)

```
SESSION STARTS
    │
    ├─> Boot sequence loads VPT context
    │   ├─> MEMORY.md (heuristics summary)
    │   ├─> vpt_trends.json (recent performance)
    │   └─> Active heuristics (top 5)
    │
    ├─> During session:
    │   ├─> Commands executed
    │   ├─> Heuristics checked before actions
    │   ├─> Circuit breaker at 10 commands
    │   └─> Signals tracked
    │
    └─> Session ends:
        │
        ├─> /debrief triggered (manual or auto)
        │   ├─> Collect metrics
        │   ├─> Score dimensions
        │   ├─> Calculate VPT
        │   ├─> Compare to target/baseline
        │   ├─> Extract root cause
        │   └─> Generate heuristic
        │
        ├─> Save data
        │   ├─> debriefs.jsonl (append)
        │   ├─> vpt_trends.json (update)
        │   └─> heuristics.json (add/update)
        │
        ├─> Analysis (weekly)
        │   ├─> Pattern extraction
        │   ├─> Trend calculation
        │   ├─> Heuristic effectiveness
        │   └─> System health check
        │
        ├─> Promotion decisions
        │   ├─> High VPT → MEMORY.md
        │   ├─> Very high VPT → Skill
        │   ├─> Critical → Guardrail
        │   └─> Low VPT → Archive
        │
        └─> Next session starts (loop closes)
            └─> New VPT context loaded
```

---

**Document Version:** 1.0
**Created:** 2025-12-29
**Author:** the agent Sentinel
**Status:** Design Complete - Ready for Implementation
