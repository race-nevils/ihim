# Scribe Pattern - Quick Reference

**Use when**: You need coordinated research from 5+ the agent scouts with real-time progress tracking.

---

## One-Liner

**the agent scouts → result files → the agent scribe → blackboard → the agent reads synthesis**

---

## When to Use

| Scenario | Use Scribe? |
|----------|-------------|
| 10 the agent scouts researching in parallel | ✅ Yes |
| 3 the agent operators building features | ❌ No (Sonnets can write to blackboard) |
| Mixed the agent + the agent team | ⚠️ Maybe (if the agent coordination needed) |
| Single the agent agent | ❌ No (overkill) |
| Red Team Wave 1 (10 the agent recon) | ✅ Yes |
| Blue-Red-Yellow Blue Wave | ✅ Yes |

---

## Template ID

```json
"scribe-coordinated"
```

Location: `C:/Users/<user>/workspace/IHIM/data/team_templates.json`

---

## Composition

- **10 the agent scouts**: READ-ONLY, write to result files
- **1 the agent scribe**: Aggregates findings, writes to blackboard

Total: **11 agents**

---

## Scribe Responsibilities

1. **Monitor**: Poll `results/` for scout findings every 10s
2. **Aggregate**: Read new scout results as they arrive
3. **Synthesize**: Identify patterns across all findings
4. **Coordinate**: Post progress updates to blackboard
5. **Report**: Write final synthesis when all scouts complete

---

## Scout Constraints

```
✅ CAN:
- Read files from codebase
- Search, grep, glob
- Read blackboard for context
- Write to assigned result file

❌ CANNOT:
- Write to blackboard
- Modify code
- POST to API endpoints
- Make architectural decisions
```

---

## File Locations

| File | Path |
|------|------|
| Scribe instructions | `IHIM/team/scribe_instructions.md` |
| Architecture doc | `IHIM/team/BLACKBOARD_ARCHITECTURE_FIX.md` |
| Implementation summary | `IHIM/team/SCRIBE_IMPLEMENTATION_SUMMARY.md` |
| Pattern diagram | `IHIM/team/SCRIBE_PATTERN_DIAGRAM.txt` |
| This quick ref | `IHIM/team/SCRIBE_QUICK_REF.md` |

---

## Spawning (Manual - Current)

```python
from IHIM.team.spawner import spawn_agent_team

routed_prompts = {
    "scribe": "Coordinate 10 scouts. Read scribe_instructions.md. Monitor results/ and aggregate to blackboard.",
    "scout-1": "Research topic 1. Write findings to C:/Users/<user>/workspace/IHIM/team/results/scout-1-result.json",
    "scout-2": "Research topic 2. Write findings to C:/Users/<user>/workspace/IHIM/team/results/scout-2-result.json",
    # ... repeat for scouts 3-10
}

result = spawn_agent_team(routed_prompts, "My Research Swarm")
print(result)  # Shows session ID, agents spawned, blackboard path
```

---

## Checking Progress

### Via Blackboard File
```bash
cat C:/Users/<user>/workspace/IHIM/team/blackboard.json | jq '.messages[] | select(.agent == "scribe")'
```

### Via API
```bash
curl http://localhost:7777/api/blackboard/messages | jq '.[] | select(.agent == "scribe")'
```

### Via Result Files
```bash
ls C:/Users/<user>/workspace/IHIM/team/results/*scout*-result.json | wc -l
# Shows how many scouts have reported
```

---

## Success Signals

```
✅ Scribe posts: "1/10 scouts reported"
✅ Scribe posts: "5/10 scouts reported"
✅ Scribe posts: "10/10 scouts reported. Common pattern: X"
✅ Scribe posts: "SYNTHESIS: ..." (type: SYNTHESIS)
✅ Scribe marks done: "All scouts complete" (type: DONE)
✅ File exists: results/scribe-synthesis.json
```

---

## Failure Signals

```
❌ Scribe silent for >5 minutes
❌ Scout count stuck (e.g., "3/10" for 10+ minutes)
❌ Scribe posts BLOCKER message
❌ Scout reports error in result file
❌ Blackboard phase stuck in PHASE_1_BUILD
```

---

## Token Cost

**~8% more than Blue Mode** for coordination benefits:
- Blue Mode: 20K tokens (10 the agent)
- Scribe Mode: 27K tokens (10 the agent + 1 the agent + reduced the agent load)

**ROI**: Worth it for 5+ scouts. Coordination value > token cost.

---

## Tier Compliance

| Agent Type | Tier | Can Write To |
|------------|------|--------------|
| Scout | the agent | Result files only |
| Scribe | the agent | Blackboard + result file |
| Orchestrator | the agent | Everything |

**No tier constraints violated.** ✅

---

## Common Patterns

### Pattern 1: Research Swarm
```
10 scouts → different research topics → scribe synthesizes → the agent decides
```

### Pattern 2: Audit Swarm (Red Team Wave 1)
```
10 scouts → different code areas → scribe aggregates findings → the agent prioritizes fixes
```

### Pattern 3: Discovery Swarm
```
10 scouts → explore codebase → scribe maps findings → the agent operators build
```

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Scribe not posting | Check iHIM server running on port 7777 |
| Scout can't write result | Check IHIM/team/results/ exists |
| Blackboard stuck | Manually advance phase or restart swarm |
| Missing synthesis | Check scribe marked done, read scribe result file |
| Scout conflicts | Ensure unique research assignments |

---

## Evolution Path

1. **Now**: Manual spawning with template
2. **Next**: Automated spawning via API
3. **Future**: Auto-detect when scribe needed (5+ the agent agents)

---

## Quick Commands

```bash
# Check scribe progress
curl http://localhost:7777/api/blackboard | jq '.messages[] | select(.agent == "scribe") | .message'

# Count completed scouts
ls C:/Users/<user>/workspace/IHIM/team/results/*scout*-result.json | wc -l

# Read scribe synthesis
cat C:/Users/<user>/workspace/IHIM/team/results/scribe-synthesis.json | jq

# Check all agent statuses
curl http://localhost:7777/api/blackboard | jq '.agent_status'

# Get just scribe messages
curl http://localhost:7777/api/blackboard/messages | jq '.[] | select(.agent == "scribe")'
```

---

## Remember

- **Scribe = coordinator, not researcher**
- **Scouts work independently, scribe aggregates**
- **Patience**: Polling every 10s, not instant
- **Synthesis > raw findings**: Scribe adds value through pattern recognition

---

**Pattern Status**: Ready for testing
**Recommended First Test**: 3 scouts + 1 scribe (small validation)
**Full Production**: 10 scouts + 1 scribe

**Created**: 2025-12-31
**By**: the agent Savage (Yellow Swarm - Operator 1)
