# VPT System - Quick Reference Card

---

## What is VPT?

**Value Per Token** = Efficiency metric measuring value delivered ÷ tokens consumed

```
VPT = (Quality Score) / (Tokens / 1000)

Target: 0.05 (5 value points per 1K tokens)
```

---

## The 6-Step Loop

```
1. EXECUTE  → Run session (commands, tools, decisions)
2. MEASURE  → /debrief captures metrics + VPT
3. STORE    → Save to debriefs.jsonl, vpt_trends.json
4. ANALYZE  → Extract patterns, calculate trends (weekly)
5. PROMOTE  → High VPT → heuristic → skill → memory
6. ACTION   → Apply learnings at boot (next session)
```

**Loop closes:** Improved session → higher VPT → better patterns → repeat

---

## 5 Value Dimensions

| Dimension | Weight | Question |
|-----------|--------|----------|
| Problem Understanding | 20% | Did I grasp it before coding? |
| Diagnosis Speed | 25% | How fast to root cause? |
| Solution Efficiency | 30% | Minimum path vs actual? |
| Tool Mastery | 15% | Right tools, used well? |
| Communication | 10% | Kept user informed? |

**Score each 1-10, weighted sum = raw score**

---

## Promotion Pathway

```
Low VPT (0.020)
    │
    ▼
Extract Heuristic
    │
    ├─> Test 3+ uses
    │       │
    │       └─> Success >80%? VPT boost >0.02?
    │
    ▼
High VPT Confirmed
    │
    ├─> MEMORY.md (boot context)
    ├─> Skill (10+ uses, broad applicability)
    ├─> Guardrail (critical, prevents disaster)
    └─> Archive (low performer, obsolete)
```

---

## Heuristic Structure

```
ID: h004
IF: frontend loads but content empty
THEN: Ask user for F12 console screenshot
BEFORE: Do NOT debug backend or spawn swarms

Effectiveness:
- Applied: 3 times
- Success: 100%
- Tokens saved: ~2000/use
- VPT boost: +0.041
```

---

## Data Files

| File | Format | Purpose |
|------|--------|---------|
| `debriefs.jsonl` | JSONL | Raw session data |
| `vpt_trends.json` | JSON | Time-series snapshots |
| `heuristics.json` | JSON | IF-THEN rules + tracking |
| `MEMORY.md` | Markdown | Boot context (top 5 heuristics) |

---

## VPT Performance Tiers

| VPT Range | Status | Meaning |
|-----------|--------|---------|
| >0.07 | Excellent | 40%+ above target |
| 0.05-0.07 | Good | At or above target |
| 0.03-0.05 | Acceptable | Below target, improvable |
| <0.03 | Poor | Requires debrief |

---

## Weekly Health Check

```python
✓ VPT trending up? (slope > 0)
✓ Heuristics applied? (>70% of sessions)
✓ Heuristics effective? (>80% success rate)
✓ Patterns covered? (>90% tagged)
```

**If ANY fail:** System needs adjustment

---

## Key Commands

- `/debrief` - Capture session metrics + calculate VPT
- `/save` - Quick VPT check, prompt if <0.03
- `/endsession` - Include VPT in blackboard
- `/analyze-vpt` (future) - Run weekly analysis

---

## iHIM Widgets (Future)

1. **VPT Gauge** - Current vs target, trend arrow
2. **Heuristics Dashboard** - Top 5 by impact
3. **Pattern Matrix** - VPT by pattern type
4. **Trend Graph** - Time series (30 days)

---

## Circuit Breaker

**Trigger:** After 10 commands in a session

**Check:** Estimated VPT < 0.03?

**Action:** STOP and ask:
1. Am I making progress?
2. Have I checked heuristics?
3. What signals have I ignored?

---

## Example: High VPT Session

```
Task: Make Mission Control draggable
Commands: 5 (all effective)
Tokens: ~3000

Scores: Understanding=9, Speed=10, Efficiency=9, Tools=8, Comm=9
Raw Score: 9.05
VPT: 9.05 / 3 = 0.089

Performance: EXCELLENT (79% above target)
```

---

## Example: Low VPT Session

```
Task: Kill zombie processes
Commands: 27 (8 effective, 19 wasted)
Tokens: ~15000

Scores: Understanding=4, Speed=2, Efficiency=3, Tools=4, Comm=5
Raw Score: 3.0
VPT: 3.0 / 15 = 0.020

Performance: POOR (60% below target)
Learning: Created h001 (check processes first)
```

---

## Meta-Principle

> "If the test becomes better, everything becomes better."

The VPT feedback loop measures itself. When measurement improves, execution improves, which generates better measurements, which...

**Self-improving system.**

---

## Implementation Priority

1. **Sprint 1:** VPT in /debrief (foundation)
2. **Sprint 2:** Boot sequence integration (awareness)
3. **Sprint 3:** Analysis pipeline (pattern extraction)
4. **Sprint 4:** Command enhancement (full loop)
5. **Sprint 5:** Dashboard (visibility)

---

**Print this card for quick reference during sessions.**
