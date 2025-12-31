# the agent harness Foundation

Substrate documentation for the agent harness CLI. Real constraints, tested behaviors, known edge cases.

Updated: 2025-12-28

---

## Quick Reference

| Constraint | Value | Source |
|------------|-------|--------|
| Max concurrent agents | 10 | Platform limit |
| Token overhead per agent | ~20K | Empirical |
| Context window (standard) | 200K tokens | All models |
| Context window (extended) | 1M tokens | the agent only, Tier 4+, beta |
| Max output tokens | 64K | Per request |
| Bash default timeout | 2 minutes | Configurable |
| WebFetch max content | 10 MB fetch / 100 KB return | Hard limit |
| WebFetch cache TTL | 15 minutes | Per URL |

---

## 1. MODEL TIERS & RATE LIMITS

### Tokens Per Minute by Tier

| Model | Tier 1 | Tier 2 | Tier 3 | Tier 4 |
|-------|--------|--------|--------|--------|
| **the agent** | 50K/10K | 450K/90K | 1M/200K | 4M/800K |
| **the agent** | 30K/8K | 450K/90K | 800K/160K | 2M/400K |
| **the agent** | 30K/8K | 450K/90K | 800K/160K | 2M/400K |

Format: ITPM/OTPM (Input/Output Tokens Per Minute)

### Requests Per Minute

| Tier | RPM |
|------|-----|
| 1 | 50 |
| 2 | 1,000 |
| 3 | 2,000 |
| 4 | 4,000 |

### Cache Advantage

**Critical insight**: Only uncached input tokens count toward ITPM limits.
- 80% cache hit rate = 5x effective throughput
- Prompt caching billed at 10% of input price
- System prompts cache across conversations

### Credit Thresholds for Tier Advancement

| Tier | Cumulative Spend |
|------|------------------|
| 1 | $5 |
| 2 | $40 |
| 3 | $200 |
| 4 | $400 |

---

## 2. CONTEXT WINDOWS

### Standard Limits

| Model | Context | Max Output |
|-------|---------|------------|
| the agent 4.5 | 200K | 64K |
| the agent 4.5 | 200K (1M beta) | 64K |
| the agent 4.5 | 200K | 64K |

### 1M Context (Beta)

- **Availability**: the agent only, Tier 4+ orgs
- **Header required**: `context-1m-2025-08-07`
- **Pricing**: 2x input, 1.5x output for >200K tokens
- **Separate rate limits**: 1M ITPM / 200K OTPM

### Context Degradation Pattern

1. Context fills during long session
2. Compaction triggers (~2 minutes)
3. Post-a context reset quality drops:
   - Loses file knowledge
   - Must re-read files
   - May repeat earlier mistakes
4. Mitigation: `/compact` or `/clear`

---

## 3. AGENT SPAWNING

### Hard Limits

| Constraint | Value |
|------------|-------|
| Max concurrent agents | 10 |
| Nesting depth | 0 (no nested subagents) |
| Token overhead per agent | ~20K |
| Token multiplication | 3-4x vs single-threaded |

### Execution Model

```
Batch of 10 agents spawned
    ↓
ALL 10 must complete
    ↓
Next batch pulled from queue
    ↓
(No dynamic worker reuse)
```

### Context Isolation

- Each agent starts with clean slate
- No shared memory between agents
- All communication routes through orchestrator
- ~20K token overhead before any work begins

### Wave Pattern (Validated)

```
WAVE 1: Recon (10 the agent, READ-ONLY)
    ↓ All complete
WAVE 2: Implementation (3-6 the agent)
    ↓ All complete
WAVE 3: Verification (optional)
```

- 10 is composition ceiling, not type requirement
- Valid: 10 the agent, 7 the agent + 3 the agent, 10 the agent, etc.

---

## 4. TOOLS REFERENCE

### File Operations

| Tool | Purpose | Notes |
|------|---------|-------|
| Read | Read file contents | Absolute paths only |
| Write | Create/overwrite file | Will fail if file not read first |
| Edit | Precise string replacement | Requires unique match |
| Glob | Pattern-based file search | `**/*.ts` syntax |
| Grep | Content search (ripgrep) | Full regex support |

### Execution

| Tool | Purpose | Notes |
|------|---------|-------|
| Bash | Shell commands | 2-min default timeout, configurable |
| Task | Spawn subagent | 10 max concurrent, no nesting |

### Web

| Tool | Purpose | Notes |
|------|---------|-------|
| WebFetch | Fetch URL content | 10MB fetch, 100KB return, 15-min cache |
| WebSearch | Web search | Rate limited per API |

### Bash Timeout Configuration

```json
// the harness dir/settings.json
{
  "env": {
    "BASH_DEFAULT_TIMEOUT_MS": "1800000",
    "BASH_MAX_TIMEOUT_MS": "7200000"
  }
}
```

---

## 5. ERROR HANDLING

### HTTP Error Codes

| Code | Type | Meaning |
|------|------|---------|
| 429 | rate_limit | Exceeding RPM/ITPM/OTPM |
| 400 | invalid_request | Malformed request |
| 401 | authentication | Invalid API key |
| 403 | permission | Key lacks permission |
| 413 | request_too_large | >32MB message |
| 500 | api_error | Anthropic internal |
| 529 | overloaded | Temporary overload |

### 429 Recovery

1. Check `retry-after` header
2. Exponential backoff: 1s → 2s → 4s
3. Monitor `api-ratelimit-*-remaining` headers

### Request Size Limits

| Context | Limit |
|---------|-------|
| Messages API | 32 MB |
| Batch API | 256 MB |
| Files API | 500 MB |

---

## 6. KNOWN EDGE CASES

### Context Window Issues

- **Monorepo baseline**: ~20K tokens (10%) consumed at session start
- **Remaining**: 180K tokens for actual work
- **Compaction latency**: ~2 minutes when triggered
- **Post-a context reset**: Performance degradation, re-reading required

### Agent Coordination Issues

- **Concurrent writes**: 70-90% data loss without file locking
- **Solution**: portalocker with atomic read-modify-write
- **Batch blocking**: All 10 agents must finish before next batch

### Timeout Issues

- **Persistent connection drops**: Some users report ~10s timeout
- **API retry storms**: Up to 10 retry attempts on timeout
- **Mitigation**: Background execution mode for long tasks

### Extended Thinking Constraints

- `budget_tokens` must be < `max_tokens`
- Minimum budget: 1,024 tokens
- No temperature/top_k modifications with thinking
- Changing budget breaks message-level cache

---

## 7. COST OPTIMIZATION

### Pricing (Per Million Tokens)

| Model | Input | Output |
|-------|-------|--------|
| the agent | $1 | $5 |
| the agent | $3 | $15 |
| the agent | $5 | $25 |

### Multipliers

| Condition | Effect |
|-----------|--------|
| Long context (>200K) | +100% input, +50% output |
| Batch API | -50% all tokens |
| Prompt caching (read) | -90% input |
| Prompt caching (write) | +25% to +100% input |

### Token Economics Strategy

```
Push work to cheapest capable tier:
- Recon/search → the agent (~20x cheaper than the agent)
- Implementation → the agent
- Decisions/synthesis → the agent
```

---

## 8. CONFIGURATION FILES

### Settings Hierarchy

1. User: `the harness dir/settings.json` (all projects)
2. Project: `harness/settings.json` (team-shared, git tracked)
3. Local: `harness/settings.local.json` (personal, gitignored)

### Recommended Allowed Tools

```json
{
  "allowedTools": [
    "Read", "Glob", "Grep", "LS", "WebFetch"
  ]
}
```

### Use With Caution

- Write, Edit, MultiEdit (can modify codebase)
- Bash (especially `git:*` patterns)

---

## 9. UNDOCUMENTED / UNCONFIRMED

The following are NOT specified in official documentation:

- Per-second enforcement granularity within minute limits
- WebFetch concurrent request limits
- Subagent max execution timeout
- Max sequential agent chains
- Glob/Grep performance on very large codebases
- Task tool maximum queue depth
- Exact retry policy for 429 errors
- Whether prompt caching applies to the agent harness context

---

## 10. FLIGHT PATH INTEGRATION

This document feeds into the Flight Path monitoring system:

### Metrics to Surface

| Metric | Source | Alert Threshold |
|--------|--------|-----------------|
| ITPM usage | Rate limit headers | >80% of limit |
| OTPM usage | Rate limit headers | >80% of limit |
| Context fill | Token count | >160K tokens |
| Agent queue depth | Task tool | >20 queued |
| Cache hit rate | Token billing | <50% |

### Health Check Endpoints

```
/api/health/rate-limits   → Current RPM/ITPM/OTPM usage
/api/health/context       → Token count, a context reset status
/api/health/agents        → Active agents, queue depth
```

---

*This file is part of the organic system. Updated by Red Team the agent instance.*
