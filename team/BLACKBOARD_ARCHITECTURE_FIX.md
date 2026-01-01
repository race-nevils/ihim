# Blackboard Architecture Fix - Scribe Pattern

**Problem**: the agent scouts are READ-ONLY by design but need to share findings during swarm coordination.

**Root Cause**: Current blackboard requires write access (POST endpoints or file writes), which violates tier constraints in GUARDRAILS.md.

---

## Proposed Solution: Scribe Pattern

### Architecture

```
[the agent Scout 1] --write--> [result-1.json]
[the agent Scout 2] --write--> [result-2.json]        READ
[the agent Scout N] --write--> [result-N.json]         |
                                                    v
                                              [the agent Scribe]
                                                    |
                                                   WRITE
                                                    v
                                             [blackboard.json]
                                                    |
                                                   READ
                                                    v
                                    [All agents monitor for updates]
```

### How It Works

1. **the agent scouts** remain READ-ONLY:
   - Write findings to individual result files (`C:/Users/<user>/workspace/IHIM/team/results/{agent}-result.json`)
   - Read the blackboard for context (allowed)
   - No POST operations, no blackboard writes

2. **the agent scribe** coordinates:
   - Polls result files from all the agent scouts
   - Aggregates findings and writes to blackboard
   - Posts synthesis, patterns, and coordination messages

3. **Blackboard** becomes the coordination layer:
   - All agents read for context
   - Only the agent+ agents write coordination messages
   - Maintains single source of truth for team state

### Implementation Changes

#### 1. New Scribe Agent Template

**File**: `IHIM/data/team_templates.json`

Add a new template for scribe-coordinated swarms:

```json
{
  "name": "scribe-coordinated-swarm",
  "description": "the agent swarm with the agent scribe for coordination",
  "size": 11,
  "composition": {
    "haiku-scout": 10,
    "sonnet-scribe": 1
  },
  "use_blackboard": true,
  "scribe_mode": true
}
```

#### 2. Scribe Behavior Instructions

**File**: `IHIM/team/scribe_instructions.md`

```markdown
# Scribe Agent - Swarm Coordination

You are a **Scribe** agent. Your role is to coordinate READ-ONLY the agent scouts.

## Your Responsibilities

1. **Monitor Scout Results**
   - Poll `C:/Users/<user>/workspace/IHIM/team/results/` for new findings
   - Track which scouts have reported
   - Identify patterns across findings

2. **Aggregate to Blackboard**
   - POST aggregated findings to blackboard
   - Coordinate scout activities
   - Update phase transitions

3. **Synthesis**
   - Identify cross-cutting patterns
   - Flag blockers or questions
   - Post DONE when all scouts complete

## Operations

**Check for new scout results:**
```bash
ls C:/Users/<user>/workspace/IHIM/team/results/*-result.json
```

**Read scout findings:**
```bash
cat C:/Users/<user>/workspace/IHIM/team/results/scout-1-result.json
```

**Post to blackboard:**
```bash
curl -X POST http://localhost:7777/api/blackboard \
  -H "Content-Type: application/json" \
  -d '{"agent": "scribe", "message": "10/10 scouts reported. Common pattern: ...", "msg_type": "SYNTHESIS"}'
```

**Mark phase complete:**
```bash
curl -X POST http://localhost:7777/api/blackboard/done \
  -H "Content-Type: application/json" \
  -d '{"agent": "scribe", "summary": "All scouts complete. Key findings: ..."}'
```

## Workflow

1. Wait for scout result files to appear
2. Read and aggregate findings every 10 seconds
3. Post synthesis to blackboard when patterns emerge
4. Mark DONE when all scouts have reported
5. Write final synthesis to `scribe-synthesis.json`
```

#### 3. Enhanced Spawner Logic

**File**: `IHIM/team/spawner.py` (modifications)

Add scribe detection and instructions:

```python
def spawn_agent_team(routed_prompts: dict, feature_description: str = None, use_scribe: bool = False) -> dict:
    """
    Spawn agent team with optional scribe coordination.

    Args:
        routed_prompts: Agent prompts
        feature_description: What we're building
        use_scribe: If True, adds scribe instructions for the agent agents
    """
    # ... existing code ...

    # Detect scribe pattern (any agent named "scribe" or contains "scribe")
    has_scribe = any("scribe" in agent.lower() for agent in routed_prompts.keys())

    for agent, prompt in routed_prompts.items():
        enhanced_prompt = f"""# Task for {agent}

## Session Info
- Session ID: {session_id}
- Blackboard: C:/Users/<user>/workspace/IHIM/team/blackboard.json
- Results output: C:/Users/<user>/workspace/IHIM/team/results/{agent}-result.json

---

{optimized_prompt}

---

"""
        # Add appropriate instructions based on agent type
        if "scribe" in agent.lower():
            # Scribe gets coordination instructions
            scribe_instructions = Path("C:/Users/<user>/workspace/IHIM/team/scribe_instructions.md").read_text()
            enhanced_prompt += scribe_instructions
        elif has_scribe and "scout" in agent.lower():
            # Scouts in scribe mode get READ-ONLY reminder
            enhanced_prompt += """
## Coordination Mode: Scribe Pattern

You are a READ-ONLY scout. Do NOT write to the blackboard directly.

1. Write your findings to your result file: `{result_file}`
2. Read the blackboard for context: `curl http://localhost:7777/api/blackboard`
3. The scribe agent will aggregate your findings

Stay focused on gathering information. The scribe handles coordination.
"""
        else:
            # Standard agents get full blackboard instructions
            enhanced_prompt += BLACKBOARD_INSTRUCTIONS
```

#### 4. API Enhancement - Scout Results Endpoint

**File**: `IHIM/api/main.py`

Add endpoint for scribe to poll scout results:

```python
@app.get("/api/team/scout-results")
async def get_scout_results():
    """Get all scout result files for scribe aggregation."""
    results_dir = Path("C:/Users/<user>/workspace/IHIM/team/results")
    scout_results = []

    for result_file in results_dir.glob("*scout*-result.json"):
        try:
            with open(result_file, "r") as f:
                data = json.load(f)
                scout_results.append({
                    "agent": result_file.stem.replace("-result", ""),
                    "file": str(result_file),
                    "data": data,
                    "modified": result_file.stat().st_mtime
                })
        except Exception as e:
            scout_results.append({
                "agent": result_file.stem,
                "error": str(e)
            })

    return {
        "count": len(scout_results),
        "results": scout_results,
        "timestamp": datetime.now().isoformat()
    }
```

---

## Migration Path

### Phase 1: Implement Scribe Pattern (Immediate)
1. Create `scribe_instructions.md`
2. Add scribe template to `team_templates.json`
3. Enhance spawner with scribe detection
4. Add scout results API endpoint

### Phase 2: Update Existing Swarms (Next)
1. Convert Red Team pattern to use scribe
2. Update Blue-Red-Yellow waves to include scribe in Blue wave
3. Document scribe pattern in CLAUDE.md

### Phase 3: Deprecate Direct Blackboard Writes for the agent (Future)
1. Add guardrail check: the agent agents cannot POST to blackboard
2. Enforce at API level (reject the agent POST attempts)
3. Update all templates to use scribe pattern

---

## Benefits

1. **Respects Tier Constraints**: the agent = read-only, the agent = coordination
2. **Structural Enforcement**: Pattern is architectural, not self-reported
3. **Backward Compatible**: Existing non-scribe swarms still work
4. **Scalable**: Works for 10, 50, or 100 the agent scouts
5. **Clear Separation**: Gather (the agent) vs. Coordinate (the agent) vs. Decide (the agent)

---

## Trade-offs

| Aspect | Trade-off |
|--------|-----------|
| Token Cost | +1 the agent agent per swarm (minimal cost vs. benefit) |
| Latency | Scribe polling adds 5-10s delay (acceptable for swarm coordination) |
| Complexity | +1 agent type to manage (well-defined role, worth it) |
| Real-time | Not truly real-time (good enough for swarm patterns) |

---

## Alternative Considered: Read-Only Blackboard View

**Rejected because**: the agent scouts would still be isolated. The scribe pattern provides better coordination without violating constraints.

---

## Next Steps

1. Implement scribe instructions and template
2. Test with a small 3-scout + 1-scribe swarm
3. Validate coordination works end-to-end
4. Update CLAUDE.md with scribe pattern
5. Migrate existing swarm templates

---

**Status**: Proposed
**Author**: the agent Savage (Operator 1)
**Date**: 2025-12-31
