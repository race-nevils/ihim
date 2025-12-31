# Flight Path - Architecture & Philosophy

**What it is:** Personal SCADA system for workspace. A control system that monitors control systems.

**Mental model:** Industrial SCADA ensures field instrument readings match HMI display values. Flight Path ensures workspace system states match what the operator and the agent perceive.

---

## Core Purpose

1. **Awareness** - What exists in workspace?
2. **Monitoring** - Is it functioning?
3. **Feedback Health** - Is it learning/improving?
4. **Navigation** (future) - Point to areas needing attention

---

## Two Layers of Health

### Layer 1: Connected (Binary)
> "Is the router plugged in?"

- System exists
- Files present
- Services running
- Basic functionality confirmed

### Layer 2: Feedback Loop (Complex)
> "Is it learning and improving?"

- Data flowing through the loop
- Measurements being taken
- Adjustments being made
- Trends moving in right direction

**Not all systems have feedback loops.** Some are data stores (written to by other processes). Flight Path shows both:
- Connected? Yes/No
- Has feedback loop? Yes/No
- If yes, is loop healthy?

---

## The 10 Dimensions of Healthy

| # | Dimension | Question |
|---|-----------|----------|
| 1 | Functioning | Is it working at all? |
| 2 | Connected | Is it plugged in to the systems that need it? |
| 3 | Evolving | Is it changing over time? |
| 4 | Improving | Is the trend direction positive? |
| 5 | VPT Positive | Is it contributing value per token? |
| 6 | Responsive | When feedback comes in, does it get processed? |
| 7 | Stable | Not thrashing or oscillating? |
| 8 | Observable | Can we see what's happening? (Metrics exist) |
| 9 | Accurate | Are the measurements trustworthy? |
| 10 | Timely | Does the loop run at the right frequency? |

---

## Robustness Philosophy

```
No single feedback loop has to be perfect
         ↓
Each loop drilled as deep as practically possible
         ↓
Enough loops = redundant coverage
         ↓
One failure doesn't cascade
         ↓
Patterns emerge across loops
         ↓
Overarching feedback philosophy develops
         ↓
System gets more robust over time
```

**Defense in depth.** Not one perfect system - many imperfect systems watching each other.

---

## What Belongs in Flight Path

**Criteria:** Anything inside workspace that has (or should have) a feedback loop.

| System | Has Feedback Loop? | Notes |
|--------|-------------------|-------|
| Memory (MEMORY.md) | Needs one | Currently just updated, no quality feedback |
| Heuristics | Yes | Applied → catches issues → refined |
| Skills | Yes | Invoked → VPT measured → refined |
| Debriefs | Yes | Session reviewed → patterns extracted → applied |
| Projects | Partial | Build/test/fix cycle, but no meta-feedback |
| GUARDRAILS.md | Needs one | Boundaries adjusted based on outcomes |

---

## Feedback Loop Anatomy (Industrial Standard)

A real feedback loop has:

1. **Sensor** - What's measuring the thing?
2. **Setpoint** - What's the target value?
3. **Controller** - What decides how to adjust?
4. **Actuator** - What makes the adjustment?
5. **Process** - The actual thing being controlled

Each component has multiple data points. A single feedback loop can have 100+ metrics. This is complex work - we iterate toward completeness, not perfection on day one.

---

## Implementation Notes

- Start with "connected" checks (Layer 1) - these are simpler
- Add feedback loop monitoring (Layer 2) incrementally
- Each system gets its own feedback loop design
- Patterns across loops inform the overarching philosophy
- Document learnings as we go

---

*Created: 2025-12-28*
*This document captures the architectural foundation for Flight Path.*
