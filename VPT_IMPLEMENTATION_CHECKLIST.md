# VPT System - Implementation Checklist

Track progress on building the VPT feedback loop system.

---

## Sprint 1: Foundation (Week 1)

### Core VPT Calculation
- [ ] Update `debriefs.jsonl` schema with VPT fields
  - [ ] Add `vpt` object: `raw_score`, `tokens_consumed`, `vpt_value`, `target`, `performance`
  - [ ] Add `signal_latency_total` to metrics
  - [ ] Test with sample data

- [ ] Implement VPT calculation in `/debrief`
  - [ ] Read `harness/commands/debrief.md`
  - [ ] Add VPT formula: `(weighted_scores) / (tokens / 1000)`
  - [ ] Add comparison to target (0.05)
  - [ ] Add comparison to baseline (same pattern, past sessions)
  - [ ] Update output format to show VPT

- [ ] Create `vpt_trends.json` storage
  - [ ] Define schema (snapshots array, all_time stats)
  - [ ] Create file in `IHIM/data/`
  - [ ] Implement append logic (add snapshot after each debrief)

- [ ] Test on real sessions
  - [ ] Run /debrief on 3 recent tasks
  - [ ] Verify VPT calculates correctly
  - [ ] Verify data saves to both debriefs.jsonl and vpt_trends.json

**Deliverable:** Working VPT calculation in /debrief command

---

## Sprint 2: Boot Integration (Week 2)

### Context Loading
- [ ] Create VPT boot summary generator
  - [ ] Script: `IHIM/scripts/generate_vpt_boot_summary.py`
  - [ ] Read vpt_trends.json (last 7 days)
  - [ ] Read heuristics.json (top 5 by impact)
  - [ ] Generate `IHIM/data/vpt_boot_summary.json`

- [ ] Update boot sequence in `CLAUDE.md`
  - [ ] Add step 5: Load VPT context summary
  - [ ] Format: Recent VPT avg, trend, top heuristics, focus areas
  - [ ] Test: Verify summary loads and displays

- [ ] Enhance heuristics tracking
  - [ ] Add `applications` array to heuristics.json
  - [ ] Track: session_id, applied (bool), outcome, tokens_saved, vpt_with, vpt_baseline
  - [ ] Add `effectiveness` object: times_applied, success_rate, avg_tokens_saved, avg_vpt_boost

- [ ] Test awareness
  - [ ] Start new session
  - [ ] Confirm VPT context visible at boot
  - [ ] Confirm top heuristics listed
  - [ ] Apply a heuristic, verify tracking works

**Deliverable:** the agent has VPT awareness at session start

---

## Sprint 3: Analysis Pipeline (Week 3)

### Pattern Analysis
- [ ] Create weekly analysis script
  - [ ] Script: `IHIM/scripts/weekly_vpt_analysis.py`
  - [ ] Load last 20 debriefs from debriefs.jsonl
  - [ ] Group by pattern field
  - [ ] Calculate per-pattern metrics (frequency, avg VPT, avg waste)

- [ ] Implement trend calculation
  - [ ] Compare this week vs last week VPT
  - [ ] Calculate slope (improvement rate)
  - [ ] Determine direction (improving/declining)
  - [ ] Statistical significance (t-test)

- [ ] Calculate heuristic effectiveness
  - [ ] For each heuristic, load all applications
  - [ ] Calculate success rate
  - [ ] Calculate avg tokens saved
  - [ ] Calculate avg VPT boost vs baseline

- [ ] Build promotion logic
  - [ ] Auto-promote: success >80%, VPT boost >0.02, applied 3+ times
  - [ ] Auto-archive: success <50%, applied 5+ times
  - [ ] Generate recommendations report

**Deliverable:** Automated weekly VPT report

---

## Sprint 4: Command Integration (Week 4)

### Command Enhancements
- [ ] Enhance `/save` command
  - [ ] Read `harness/commands/save.md`
  - [ ] Add quick VPT estimate (command count proxy)
  - [ ] If VPT < 0.03, prompt: "Run /debrief now? (y/n)"
  - [ ] Test: Verify prompt appears on low VPT sessions

- [ ] Enhance `/endsession` command
  - [ ] Read `harness/commands/endsession.md`
  - [ ] Calculate session VPT summary
  - [ ] Add VPT to blackboard entry schema
  - [ ] Update daily VPT snapshot
  - [ ] Test: Verify VPT saves to blackboard

- [ ] Implement circuit breaker
  - [ ] Add checkpoint after 10 commands
  - [ ] Calculate estimated VPT trajectory
  - [ ] If < 0.03, STOP and ask 3 questions
  - [ ] Test: Manually trigger on low VPT session

- [ ] End-to-end test
  - [ ] Run complete session with all integrations
  - [ ] Boot (VPT context loads)
  - [ ] Execution (circuit breaker at 10 commands)
  - [ ] /save (VPT check)
  - [ ] /debrief (full metrics)
  - [ ] /endsession (blackboard with VPT)

**Deliverable:** Complete feedback loop operational

---

## Sprint 5: Dashboard & Refinement (Week 5+)

### iHIM UI Components
- [ ] Create VPT gauge widget
  - [ ] File: `IHIM/ui/widgets/vpt_gauge.js`
  - [ ] Display: current VPT, target, progress bar, trend arrow
  - [ ] Style: Periodic table card format
  - [ ] Test: Verify updates in real-time

- [ ] Create heuristics dashboard
  - [ ] File: `IHIM/ui/widgets/heuristics_dashboard.js`
  - [ ] Display: Top 5 heuristics (ID, name, success%, tokens saved)
  - [ ] Style: Table format, sortable
  - [ ] Test: Click to see details

- [ ] Create pattern performance matrix
  - [ ] File: `IHIM/ui/widgets/pattern_matrix.js`
  - [ ] Display: Pattern name, VPT, frequency, status (good/ok/low)
  - [ ] Color code by status
  - [ ] Test: Verify sorting and filtering

- [ ] Create VPT trend graph
  - [ ] File: `IHIM/ui/widgets/vpt_trend_graph.js`
  - [ ] Display: Time series (30 days), target line, trend line
  - [ ] Use Chart.js or similar
  - [ ] Test: Zoom, pan, date range selection

### API Endpoints
- [ ] `GET /api/vpt/summary`
  - [ ] File: `IHIM/api/vpt/endpoints.py`
  - [ ] Return: current_vpt, target, performance_pct, trend, best/worst session
  - [ ] Test: curl endpoint, verify JSON

- [ ] `GET /api/vpt/heuristics`
  - [ ] Return: active_count, heuristics array (id, name, success_rate, tokens_saved)
  - [ ] Test: Verify top 5 sorted by impact

- [ ] `GET /api/vpt/trends?period=30d`
  - [ ] Return: snapshots array, trend_line (slope, intercept, r_squared)
  - [ ] Support query params: 7d, 30d, 90d
  - [ ] Test: Verify date filtering

- [ ] `GET /api/vpt/patterns`
  - [ ] Return: patterns array (name, avg_vpt, frequency, status)
  - [ ] Test: Verify pattern aggregation

- [ ] Wire up to iHIM dashboard
  - [ ] Add VPT tab to Mission Control
  - [ ] Load widgets on page load
  - [ ] Test: All widgets display correctly

### Meta-Feedback
- [ ] Implement system health check
  - [ ] Script: `IHIM/scripts/vpt_health_check.py`
  - [ ] Check 4 metrics: VPT trend, application rate, effectiveness, coverage
  - [ ] Output: health report with recommendations
  - [ ] Run: Weekly (manual or cron)

- [ ] Build auto-adjustment logic
  - [ ] If VPT declining → alert, recommend debrief review
  - [ ] If low application → increase visibility (add to boot summary)
  - [ ] If low effectiveness → recommend refine/archive
  - [ ] If low coverage → recommend manual pattern review

**Deliverable:** iHIM dashboard with VPT visibility, self-improving system

---

## Optional Enhancements (Future)

### Advanced Features
- [ ] Token counting API integration
  - [ ] Use Anthropic API for actual token counts (not estimates)
  - [ ] Fallback: Command count proxy

- [ ] A/B testing framework
  - [ ] Track sessions with/without specific heuristics
  - [ ] Calculate statistical significance of improvements
  - [ ] Auto-enable high-impact heuristics

- [ ] Skill VPT tracking
  - [ ] Tag sessions by active skill
  - [ ] Calculate per-skill VPT
  - [ ] Trim low-VPT skills (LP Lead example)

- [ ] Real-time VPT dashboard
  - [ ] Live updates during session (WebSocket)
  - [ ] Show current trajectory vs target
  - [ ] Warn before circuit breaker threshold

- [ ] Heuristic recommendation engine
  - [ ] Given task description, suggest applicable heuristics
  - [ ] "Before you start, consider h004, h001..."
  - [ ] Learn from successful applications

---

## Definition of Done (Per Sprint)

### Sprint Complete When:
- [ ] All checklist items marked complete
- [ ] Unit tests written (where applicable)
- [ ] Manual testing passed
- [ ] Documentation updated
- [ ] Demo to the operator
- [ ] Retrospective: What went well? What to improve?

---

## Risks and Blockers

| Risk | Mitigation | Owner |
|------|-----------|-------|
| Token API unavailable | Use command count proxy | Sprint 1 |
| Baseline VPT unknown | Bootstrap with first 10 sessions | Sprint 1 |
| Pattern taxonomy inconsistent | Create patterns.json reference | Sprint 3 |
| Dashboard performance issues | Lazy load, pagination, caching | Sprint 5 |

---

## Progress Tracking

| Sprint | Status | Start Date | End Date | Notes |
|--------|--------|------------|----------|-------|
| 1: Foundation | Not Started | TBD | TBD | |
| 2: Boot | Not Started | TBD | TBD | |
| 3: Analysis | Not Started | TBD | TBD | |
| 4: Commands | Not Started | TBD | TBD | |
| 5: Dashboard | Not Started | TBD | TBD | |

---

## Quick Links

- Design doc: `VPT_FEEDBACK_LOOP_DESIGN.md`
- Integration summary: `VPT_INTEGRATION_SUMMARY.md`
- Quick reference: `VPT_QUICK_REF.md`
- Heuristics data: `IHIM/data/heuristics.json`
- Debriefs data: `IHIM/data/debriefs.jsonl`

---

**Start with Sprint 1. Mark items complete as you go. Update progress tracking weekly.**
