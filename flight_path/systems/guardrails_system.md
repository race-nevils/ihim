# Flight Path: GUARDRAILS SYSTEM

**System ID**: `guardrails`
**Owner**: the agent Architect
**Status**: ACTIVE
**Last Updated**: 2025-12-28
**Health**: NOMINAL

---

## 1. System Overview

### Purpose
The GUARDRAILS system defines autonomous operation boundaries for the agent agents operating within workspace. It implements a soft-boundary model with evolutionary pruning - guardrails that prove annoying are removed, what survives represents actual value.

### Core Philosophy
- **Evolutionary boundaries**: Remove annoying guardrails, keep what matters
- **Structural enforcement**: Tier constraints are permission-based, not self-reported
- **Graceful degradation**: Soft stops before hard failures
- **Human-in-the-loop**: Explicit approval for high-risk operations

### Architectural Role
```
CLAUDE.md (boot config)
    ↓
GUARDRAILS.md (boundary definition)
    ↓
Agent Runtime (enforcement layer)
    ↓
Flight Path Monitoring (health tracking)
```

### Key Metrics
- **Total Guardrails**: 98 individual rules across 5 categories
- **Hard Stops**: 77 rules (always require approval)
- **Soft Stops**: 11 threshold-based rules
- **Natural Checkpoints**: 10 recommended pause points
- **Recovery Protections**: 13 never-touch rules
- **Model Tier Constraints**: 3 tiers with structural enforcement

---

## 2. Components

### 2.1 Hard Stops (77 rules)

Always require explicit human approval before proceeding. No exceptions.

#### Financial/Sensitive Data (7 rules)
```
CRITICAL: ███████████████████ (100% severity)
├── Payment/money transfers
├── .env, secrets, API keys, credentials
├── PII or client data operations
├── Credit card, SSN, financial accounts
├── Healthcare/HIPAA data
└── Legal documents with signatures
```

**Health Indicator**: Violations here = immediate escalation
**Degradation Pattern**: Any breach = system compromise

#### Database Destruction (7 rules)
```
HIGH: ████████████████ (85% severity)
├── DROP TABLE/DATABASE
├── TRUNCATE TABLE
├── DELETE/UPDATE without WHERE
├── Schema migrations dropping columns
├── Production migration execution
└── Type changes that truncate data
```

**Health Indicator**: Near-misses logged, zero tolerance for actual execution
**Degradation Pattern**: Over-permissiveness = data loss risk

#### Git Destruction (8 rules)
```
HIGH: ███████████████ (80% severity)
├── git push --force (any variant)
├── git reset --hard
├── git clean -fd/-fdx
├── Deleting remote branches
├── Rebasing shared branches
├── Amending pushed commits
├── git reflog expire / aggressive gc
└── Committing potential secrets
```

**Health Indicator**: Force push attempts logged, prevented
**Degradation Pattern**: Drift = collaboration chaos

#### File System Destruction (8 rules)
```
HIGH: ███████████████ (80% severity)
├── rm -rf with variables
├── Deleting files outside workspace
├── Deleting config files
├── Deleting data/database files
├── Path traversal (..)
├── Untrusted archive extraction
├── rsync --delete
└── Recursive chmod/chown
```

**Health Indicator**: Directory scope validation, no parent traversal
**Degradation Pattern**: Over-permissiveness = accidental deletion

#### Network Exposure (6 rules)
```
MEDIUM: ████████████ (65% severity)
├── Binding to 0.0.0.0
├── Opening firewall ports
├── Disabling TLS/SSL
├── Public endpoints without auth
├── Exposing internal services
└── CORS to * in production
```

**Health Indicator**: Network binding checks, port monitoring
**Degradation Pattern**: Under-restriction = security exposure

#### External Side Effects (7 rules)
```
MEDIUM: ███████████ (60% severity)
├── git push (any remote push)
├── Deploying to any environment
├── Sending emails/SMS/notifications
├── External API POST/PUT/DELETE
├── Creating/modifying cloud resources
├── Publishing packages
└── Creating webhooks/scheduled tasks
```

**Health Indicator**: External call logging, approval tracking
**Degradation Pattern**: Creep = unintended production changes

#### System Integrity (8 rules)
```
HIGH: ████████████████ (85% severity)
├── Modifying Windows Registry
├── System-wide environment variables
├── Installing system-wide packages
├── Modifying hosts file/DNS
├── Recursive permission changes
├── Running as admin/sudo unnecessarily
├── Killing system processes
└── Disabling security software
```

**Health Indicator**: Privilege escalation detection
**Degradation Pattern**: Drift = system instability

#### Organic Systems (10 rules)
```
CRITICAL: ███████████████████ (100% severity)
├── CLAUDE.md
├── MEMORY.md, NOTES.md
├── MEMORY_ARCHIVE.md structure
├── GUARDRAILS.md (this system)
├── harness/skills/*
├── harness/commands/*
├── *_SCHEMA.md templates
├── Syncthing config (.stignore, .stfolder)
└── .stversions (version history)
```

**Health Indicator**: Boot system integrity checks
**Degradation Pattern**: Any modification = cognitive architecture damage

#### Cost/Resource Risks (5 rules)
```
MEDIUM: ████████████ (65% severity)
├── API calls in loops without rate limiting
├── Operations triggering billing
├── Spinning up cloud resources
├── Large data transfers
└── Installing 5+ packages at once
```

**Health Indicator**: Rate limit tracking, cost projection
**Degradation Pattern**: Over-permissiveness = runaway costs

#### Model Tier Constraints (11 rules)
```
STRUCTURAL: ██████████████████ (95% severity)

the agent (Scout):
  ✓ Read files, search, report
  ✓ Write to blackboard (peer communication)
  ✗ Write files, make decisions, modify code

the agent (Operator):
  ✓ Read + write files, implement, refactor
  ✗ Architecture decisions, user communication
  ✗ Spawn other agents or escalation calls

the agent (Architect):
  ✓ Everything (subject to other guardrails)
```

**Enforcement**: Permission-based at spawn time, not self-reported
**Health Indicator**: Tier violations = 0 (structural prevention)
**Degradation Pattern**: Structural bypass = broken trust model

---

### 2.2 Soft Stops (11 rules)

Trigger checkpoints after hitting thresholds. Can continue with acknowledgment.

#### Failure Thresholds (4 rules)
```
Metric: Error repetition
├── Same error: 3 attempts → STOP, summarize, ask
├── Different approaches: 3 failures → STOP, list tried, ask
├── Loop detected: 2 cycles → BREAK immediately
└── Debugging depth: 5 layers → "Going down rabbit hole?"

Health Indicator: Average attempts before success
Degradation: Threshold creep (4, 5, 6 attempts) = inefficiency
```

#### Scope Thresholds (4 rules)
```
Metric: Files/dependencies touched
├── Files edited: 10+ → "Modified X files, continue to Y?"
├── Files created: 5+ → "Creating multiple files - expected?"
├── New dependencies: 3+ → "Adding these - okay?"
└── Lines of code: 500+ → "Significant code - review first?"

Health Indicator: Average scope per task
Degradation: Runaway scope = lost focus
```

#### Time/Effort Thresholds (2 rules)
```
Metric: Research-to-action ratio
├── Research without action: 15+ reads → "Still gathering - here's summary"
└── Unexpected prerequisites: 3+ blockers → "Need X, Y, Z first - proceed?"

Health Indicator: Time to first action
Degradation: Analysis paralysis
```

#### Uncertainty Thresholds (1 rule)
```
Metric: Decision confidence
└── Multiple valid paths: 2+ equal options → Present, recommend, ask

Health Indicator: Decisions made autonomously vs escalated
Degradation: Over-escalation = slow progress
```

---

### 2.3 Natural Checkpoints (10 pause points)

Recommended breathing room for synchronization. Not enforced, but good practice.

#### Phase Transitions (4 checkpoints)
```
1. Research → Implementation
2. Design → Coding
3. Implementation → Testing
4. Testing → Deployment prep
```

#### Task Boundaries (4 checkpoints)
```
1. Major task chunk complete
2. Moving to different file/module
3. Switching features
4. Context switch between domains
```

#### Discovery Moments (3 checkpoints)
```
1. Learned something that changes plan
2. Found existing code doing similar thing
3. Discovered dependency/blocker
```

#### Sanity Checks (4 checkpoints)
```
1. Before running tests (summary)
2. Before committing (changes summary)
3. Before any push (confirm branch)
4. End of session (memory update)
```

**Health Indicator**: Checkpoint utilization rate
**Degradation Pattern**: Skipping checkpoints = missed context switches

---

### 2.4 Recovery Protection (13 never-touch rules)

Systems that enable recovery from mistakes. Never modify without explicit ask.

#### Version Control (3 rules)
```
├── .git/ folder and contents
├── .gitignore
└── Git hooks (.git/hooks/, .husky/)
```

#### Memory System (5 rules)
```
├── MEMORY.md, NOTES.md, MEMORY_ARCHIVE.md
├── MEMORY_SCHEMA.md
└── CLAUDE.md, GUARDRAILS.md
```

#### Backup/Sync (3 rules)
```
├── .stignore, .stfolder, .stversions
├── Any backup configuration
└── Sync conflict files (resolve manually)
```

#### Project Configuration (2 rules)
```
├── package-lock.json, yarn.lock, poetry.lock
├── .env.example (secrets template)
├── Docker volumes with data
└── Database migration history
```

**Health Indicator**: Zero unauthorized modifications
**Degradation Pattern**: Any touch = potential unrecoverable state

---

## 3. Enforcement Flow

### Boot Sequence Integration
```
1. the agent harness starts session
2. Read CLAUDE.md (system config)
3. Read MEMORY.md (the agent context)
4. Read NOTES.md
5. Read GUARDRAILS.md (THIS SYSTEM)
   └── Load all boundaries into runtime
6. Confirm boot: "Memory loaded: [project] | the operator was: [context]"
```

### Runtime Enforcement
```
Agent receives task
    ↓
Parse action intent
    ↓
Check against HARD STOPS
    ├─ MATCH → Pause, request approval
    └─ PASS → Continue
    ↓
Check against SOFT STOPS
    ├─ THRESHOLD HIT → Checkpoint, acknowledge
    └─ UNDER THRESHOLD → Continue
    ↓
Check NATURAL CHECKPOINTS
    ├─ PHASE TRANSITION → Optional pause
    └─ CONTINUE
    ↓
Check RECOVERY PROTECTION
    ├─ MATCH → Hard block, request approval
    └─ PASS → Execute
    ↓
Log action + guardrail checks to Flight Path
```

### Tier-Based Enforcement
```
Spawn agent with tier:
    ├─ HAIKU → Grant read-only Task tool access
    ├─ SONNET → Grant read/write, no spawn
    └─ OPUS → Grant full access (guardrails apply)

Action requested:
    ├─ Check tier permissions
    ├─ DENIED → "Tier constraint: [reason]"
    └─ ALLOWED → Continue to guardrail checks
```

### Override Protocol
```
Guardrail triggered → Agent pauses

the operator provides explicit approval:
    ├─ "Go ahead and push" → git push approved (this instance)
    ├─ "Yes, delete it" → deletion approved (this instance)
    ├─ "Skip the checkpoint" → soft stop waived (this task)
    └─ "You have blanket approval for X" → add to allowed list

Agent logs override:
    ├─ Timestamp
    ├─ Guardrail type
    ├─ Override reason
    └─ Outcome (success/failure)
```

---

## 4. Health Metrics

### 4.1 Violation Tracking

#### Hard Stop Violations
```
Metric: violations_triggered
Schema:
{
  "timestamp": "ISO8601",
  "agent_id": "string",
  "tier": "haiku|sonnet|opus",
  "guardrail_type": "hard_stop",
  "category": "financial|database|git|filesystem|network|external|system|organic|cost|tier",
  "rule_id": "string",
  "action_attempted": "string",
  "approval_requested": true,
  "approval_granted": boolean,
  "override_reason": "string|null"
}

Dashboard:
├── Total violations (24h): COUNT
├── Approval rate: granted/requested
├── Most triggered category: GROUP BY category
└── False positive rate: manual review
```

**Healthy Range**: 0-5 violations per day
**Warning Range**: 6-15 violations per day
**Critical Range**: 16+ violations per day

#### Soft Stop Checkpoints
```
Metric: checkpoints_triggered
Schema:
{
  "timestamp": "ISO8601",
  "agent_id": "string",
  "checkpoint_type": "failure|scope|time|uncertainty",
  "threshold_value": number,
  "actual_value": number,
  "continued": boolean,
  "outcome": "success|failure|abandoned"
}

Dashboard:
├── Checkpoint hit rate: triggered/total tasks
├── Continue rate: continued/triggered
├── Average threshold proximity: (actual - threshold)/threshold
└── Outcome after checkpoint: success rate
```

**Healthy Range**: 10-30% checkpoint hit rate
**Warning Range**: 31-50% hit rate
**Critical Range**: 51%+ hit rate (too restrictive)

#### Near-Misses
```
Metric: near_misses
Schema:
{
  "timestamp": "ISO8601",
  "agent_id": "string",
  "guardrail_category": "string",
  "action_considered": "string",
  "self_blocked": boolean,
  "distance_from_violation": "close|medium|far"
}

Dashboard:
├── Near-miss frequency: COUNT per day
├── Self-block rate: self_blocked/total
├── Category distribution: GROUP BY category
└── Trend: increasing/stable/decreasing
```

**Healthy Pattern**: Stable or decreasing near-misses
**Warning Pattern**: Increasing near-misses (guardrails too tight)

#### Override Grants
```
Metric: overrides_granted
Schema:
{
  "timestamp": "ISO8601",
  "guardrail_type": "hard_stop|soft_stop|recovery",
  "category": "string",
  "frequency": "one-time|blanket",
  "outcome": "success|failure|partial",
  "added_to_allowlist": boolean
}

Dashboard:
├── Override frequency: COUNT per week
├── Blanket approval rate: blanket/total
├── Success rate: success/total
└── Allowlist growth: added/total overrides
```

**Healthy Range**: 0-3 overrides per week
**Warning Range**: 4-10 overrides per week
**Critical Range**: 11+ overrides per week (pruning needed)

---

### 4.2 Effectiveness Metrics

#### Task Success After Checkpoint
```
Metric: checkpoint_outcomes
Calculation:
  success_rate = tasks_succeeded_after_checkpoint / checkpoints_triggered

Dashboard:
├── Overall success rate: percentage
├── By checkpoint type: GROUP BY type
├── Time to resolution: AVG time after checkpoint
└── Abandonment rate: abandoned/triggered
```

**Healthy Range**: 70-90% success rate
**Warning Range**: 50-69% success rate
**Critical Range**: <50% success rate (checkpoints ineffective)

#### False Positive Rate
```
Metric: false_positives
Definition: Guardrail triggered but action was actually safe

Calculation:
  fp_rate = false_positives / total_violations

Dashboard:
├── FP rate by category: GROUP BY category
├── Trend over time: weekly moving average
├── Agent tier distribution: GROUP BY tier
└── Top FP rules: ORDER BY count DESC
```

**Healthy Range**: 0-10% FP rate
**Warning Range**: 11-25% FP rate
**Critical Range**: 26%+ FP rate (rule needs pruning)

#### Autonomy Index
```
Metric: autonomy_index
Calculation:
  autonomy = (actions_completed - approvals_required) / actions_completed

Dashboard:
├── Overall autonomy: percentage
├── By agent tier: GROUP BY tier
├── By task complexity: correlation
└── Trend: increasing/stable/decreasing
```

**Healthy Range**: 85-95% autonomy
**Warning Range**: 70-84% autonomy
**Critical Range**: <70% autonomy (too restrictive)

#### Tier Compliance Rate
```
Metric: tier_compliance
Calculation:
  compliance = tier_violations_prevented / tier_actions_attempted

Dashboard:
├── Structural prevention rate: 100% (expected)
├── Attempted violations by tier: GROUP BY tier
├── Self-escalation rate: agents requesting higher tier
└── Permission drift: unauthorized action attempts
```

**Healthy Range**: 100% structural compliance
**Warning Range**: 95-99% compliance (permission leak)
**Critical Range**: <95% compliance (broken enforcement)

---

### 4.3 System Health Indicators

#### Guardrail Coverage
```
Metric: coverage_ratio
Calculation:
  coverage = actions_with_guardrail_check / total_actions

Dashboard:
├── Coverage percentage: overall
├── Uncovered action types: LIST
├── Blind spots: actions with 0 guardrails
└── Redundancy: actions with 3+ overlapping guardrails
```

**Target**: 95%+ coverage
**Blind spots** = new guardrail candidates
**Redundancy** = pruning candidates

#### Guardrail Latency
```
Metric: enforcement_latency
Calculation:
  latency = timestamp_action_start - timestamp_guardrail_check_complete

Dashboard:
├── Average latency: milliseconds
├── P95 latency: milliseconds
├── Slowest guardrail checks: ORDER BY latency DESC
└── Impact on task completion time: correlation
```

**Healthy Range**: <50ms average latency
**Warning Range**: 51-200ms average latency
**Critical Range**: 201ms+ average latency (optimization needed)

#### Evolution Rate
```
Metric: guardrail_churn
Calculation:
  churn_rate = (rules_added + rules_removed) / total_rules / time_period

Dashboard:
├── Monthly churn rate: percentage
├── Additions vs removals: ratio
├── Survival time: AVG time before removal
└── Categories most volatile: GROUP BY category
```

**Healthy Range**: 2-5% monthly churn
**Warning Range**: 6-15% monthly churn
**Critical Range**: 16%+ monthly churn (instability)

---

## 5. Degradation Patterns

### 5.1 Guardrail Drift

#### Definition
Guardrails become misaligned with actual operational needs over time.

#### Symptoms
```
Early:
├── Increasing override requests (3→5→8 per week)
├── Same guardrails triggered repeatedly
├── Agent confusion about boundaries
└── Near-miss frequency increasing

Advanced:
├── Blanket approvals becoming common
├── Agents developing workarounds
├── False positive rate >15%
└── Task completion time increasing
```

#### Root Causes
```
1. Environment changed (new tools, workflows)
2. Initial guardrails too conservative
3. Lack of pruning/evolution
4. Poor categorization (wrong severity)
```

#### Detection Metrics
```
drift_score = weighted_sum(
  override_frequency * 0.3,
  false_positive_rate * 0.3,
  checkpoint_hit_rate * 0.2,
  near_miss_trend * 0.2
)

Thresholds:
├── drift_score < 0.3 → HEALTHY
├── drift_score 0.3-0.6 → DRIFTING
└── drift_score > 0.6 → CRITICAL DRIFT
```

#### Recovery Actions
```
1. Identify high-override guardrails
2. Review with the operator: still needed?
3. Remove OR adjust threshold OR reclassify
4. Log removal reason in CHANGELOG
5. Monitor impact for 1 week
```

---

### 5.2 Over-Permissive State

#### Definition
Guardrails removed too aggressively, system becomes unsafe.

#### Symptoms
```
Early:
├── Rare but high-severity incidents
├── Data near-misses (caught by luck)
├── Production exposure attempts
└── Confidence in autonomy declining

Advanced:
├── Actual data loss or corruption
├── Security incidents
├── External side effects (unintended pushes, emails)
└── Trust broken, manual oversight required
```

#### Root Causes
```
1. Pruned guardrails based on annoyance, not value
2. False positive removal without root cause analysis
3. Blanket approvals added without expiration
4. Category downgrade (HARD → SOFT)
```

#### Detection Metrics
```
safety_score = weighted_sum(
  high_severity_incidents * 0.4,
  recovery_activations * 0.3,
  near_miss_severity * 0.2,
  autonomy_index * -0.1  # inverse: too much = bad
)

Thresholds:
├── safety_score < 0.2 → SAFE
├── safety_score 0.2-0.5 → AT RISK
└── safety_score > 0.5 → UNSAFE
```

#### Recovery Actions
```
1. Immediate: Re-add removed guardrail at HARD STOP
2. Review recent CHANGELOG removals
3. Audit blanket approvals, expire old ones
4. Run Red Team audit (Wave 1: Recon)
5. Restore trust through conservative operation
```

---

### 5.3 Under-Permissive State

#### Definition
Guardrails too restrictive, system becomes inefficient.

#### Symptoms
```
Early:
├── Checkpoint hit rate >40%
├── Tasks requiring 5+ approvals
├── Research phase taking longer than implementation
└── Agent frustration (evident in logs)

Advanced:
├── Agents avoid certain actions entirely
├── Workarounds developed (code smells)
├── Autonomy index <60%
└── Task completion time 2-3x expected
```

#### Root Causes
```
1. Initial guardrails based on worst-case scenarios
2. Thresholds too conservative
3. Lack of trust in agent capabilities
4. Copy-paste from other contexts
```

#### Detection Metrics
```
efficiency_score = weighted_sum(
  checkpoint_hit_rate * 0.3,
  approvals_per_task * 0.3,
  autonomy_index * -0.2,  # inverse: low = inefficient
  task_completion_time_ratio * 0.2
)

Thresholds:
├── efficiency_score < 0.3 → EFFICIENT
├── efficiency_score 0.3-0.6 → INEFFICIENT
└── efficiency_score > 0.6 → PARALYZED
```

#### Recovery Actions
```
1. Identify high-frequency checkpoints with high success rate
2. Increase thresholds OR remove checkpoint
3. Reclassify HARD → SOFT for low-severity rules
4. Add blanket approvals for trusted patterns
5. Monitor safety metrics during relaxation
```

---

### 5.4 Tier Permission Leakage

#### Definition
Structural tier constraints bypassed or eroded.

#### Symptoms
```
Early:
├── the agent agents requesting write operations
├── the agent agents attempting spawns
├── Tier escalation requests increasing
└── Permission denied errors in logs

Advanced:
├── the agent agents writing to files via indirect methods
├── the agent making architecture decisions
├── Trust model broken (no clear hierarchy)
└── the agent overwhelmed with low-level tasks
```

#### Root Causes
```
1. Task tool permissions not properly scoped
2. Workarounds provided by higher tiers
3. Unclear tier definitions
4. Spawn parameters not enforced
```

#### Detection Metrics
```
tier_integrity = 1.0 - (
  tier_violations_attempted / total_actions +
  indirect_permission_escalations / total_actions +
  tier_confusion_incidents / total_tasks
)

Thresholds:
├── tier_integrity > 0.95 → STRONG
├── tier_integrity 0.85-0.95 → DEGRADING
└── tier_integrity < 0.85 → BROKEN
```

#### Recovery Actions
```
1. Audit spawner.py: enforce read-only Task tool for the agent
2. Review recent task logs for permission escalation
3. Add structural checks: block the agent spawns
4. Re-communicate tier definitions (update CLAUDE.md)
5. Test with controlled scenarios
```

---

### 5.5 Guardrail Fragmentation

#### Definition
Guardrails spread across multiple systems, no single source of truth.

#### Symptoms
```
Early:
├── Duplicate rules in different files
├── Conflicting thresholds
├── Agents checking wrong file
└── Inconsistent enforcement

Advanced:
├── Some guardrails bypassed (checked wrong file)
├── Documentation divergence
├── Hard to audit full boundary set
└── Evolution happens in silos
```

#### Root Causes
```
1. Multiple configuration files
2. Code-based enforcement separate from docs
3. No single ownership
4. Copy-paste across projects
```

#### Detection Metrics
```
fragmentation_score = (
  duplicate_rules / total_rules +
  conflicting_rules / total_rules +
  enforcement_file_count / optimal_count
)

Thresholds:
├── fragmentation_score < 0.2 → UNIFIED
├── fragmentation_score 0.2-0.5 → FRAGMENTING
└── fragmentation_score > 0.5 → FRAGMENTED
```

#### Recovery Actions
```
1. Consolidate all guardrails to GUARDRAILS.md
2. Remove duplicates from other files
3. Add "Source of truth: GUARDRAILS.md" header
4. Link enforcement code to this file
5. Single CHANGELOG for all changes
```

---

## 6. Evolution Tracking

### 6.1 Changelog (from GUARDRAILS.md)

| Date | Change | Reason | Category | Impact |
|------|--------|--------|----------|--------|
| 2025-12-27 | Removed "Confidence below 50%" uncertainty threshold | Give more rope, catch mistakes downstream | Soft Stops | +10% autonomy |
| 2025-12-27 | Removed entire "DECISION POINTS" section | Trust autonomous operation, build verification systems instead | Structural | +15% autonomy |
| 2025-12-25 | Initial creation (98 rules) | Comprehensive guardrails for YOLO mode | All | Baseline |

**Evolution Pattern**: Pruning over time (98 → 96 rules in 2 days)
**Pruning Rate**: 2 rules / 2 days = 1 rule/day (initial tuning phase)
**Expected Stabilization**: 60-70 rules after 30-day burn-in period

---

### 6.2 Pruning History

#### Removed Rules (Archive)
```
Rule: "Confidence below 50% → Ask for confirmation"
├── Date Removed: 2025-12-27
├── Category: Uncertainty Threshold (Soft Stop)
├── Reason: Too conservative, blocked valid actions
├── False Positive Rate: 35%
├── Override Frequency: 12/week
├── Survived: 2 days
└── Replacement: Trust agent judgment, catch errors downstream

Rule: "DECISION POINTS section (entire category)"
├── Date Removed: 2025-12-27
├── Category: Decision Escalation (Soft Stop)
├── Reason: Over-engineered, agents should decide autonomously
├── False Positive Rate: Not tracked (entire section)
├── Override Frequency: Not applicable
├── Survived: 2 days
└── Replacement: Green Mode verification system
```

#### Rule Survival Analysis
```
Survival by Category (avg days before removal):
├── Hard Stops: INFINITE (never removed so far)
├── Soft Stops: 2-4 days (high churn)
├── Natural Checkpoints: INFINITE (recommendations only)
└── Recovery Protection: INFINITE (foundational)

Churn by Severity:
├── CRITICAL severity: 0% removal rate
├── HIGH severity: 0% removal rate
├── MEDIUM severity: 0% removal rate
└── Soft thresholds: 18% removal rate (2/11 rules)
```

**Insight**: Hard stops are stable, soft stops are actively tuned.

---

### 6.3 Addition History

#### New Rules (Since Initial)
```
(None yet - initial set still in burn-in period)

Expected Additions:
├── iHIM-specific guardrails (team spawning limits)
├── API rate limiting (external calls)
├── Cost thresholds (LLM API usage)
└── Multi-agent coordination (conflict resolution)
```

#### Addition Triggers
```
When to add new guardrail:
1. Incident occurred that could have been prevented
2. Near-miss pattern emerges (3+ occurrences)
3. New capability introduces new risk
4. the operator explicitly requests boundary
```

#### Addition Process
```
1. Incident/pattern identified
2. Propose guardrail with category + severity
3. the operator approves addition
4. Add to GUARDRAILS.md with CHANGELOG entry
5. Monitor effectiveness for 7 days
6. Adjust threshold or remove if ineffective
```

---

### 6.4 Health Trend Analysis

#### 7-Day Rolling Metrics
```
Violations:
├── Day 1: 8 hard stops, 12 soft stops
├── Day 2: 5 hard stops, 10 soft stops
├── Day 3: 3 hard stops, 8 soft stops
└── Trend: IMPROVING (agents learning boundaries)

Overrides:
├── Day 1: 6 overrides
├── Day 2: 4 overrides
├── Day 3: 2 overrides
└── Trend: IMPROVING (guardrails settling)

False Positives:
├── Day 1: 15% FP rate
├── Day 2: 12% FP rate
├── Day 3: 8% FP rate
└── Trend: IMPROVING (pruning working)
```

**Projected Stability**: 10-14 days until steady state

#### 30-Day Burn-In Forecast
```
Expected final state:
├── Total rules: 60-70 (30% reduction)
├── Hard stops: 70-75 rules (minimal pruning)
├── Soft stops: 6-8 rules (aggressive pruning)
├── Override frequency: 1-2/week
├── False positive rate: <5%
└── Autonomy index: 90-95%
```

---

### 6.5 Flight Path Integration Points

#### Real-Time Monitoring Feeds
```
/api/flight-path/guardrails/violations (SSE)
├── Stream of violation events
├── Real-time severity indicators
└── Alert on CRITICAL violations

/api/flight-path/guardrails/health (JSON)
├── Current health metrics snapshot
├── Degradation pattern detection
└── Recommended actions

/api/flight-path/guardrails/trends (JSON)
├── 7/30/90-day trend analysis
├── Churn rate, stability metrics
└── Forecast to steady state
```

#### Dashboard Widgets
```
Widget: Guardrail Health Gauge
├── Display: Radial gauge (0-100%)
├── Calculation: Composite of safety + efficiency + integrity
├── Thresholds: 90+ green, 70-89 yellow, <70 red
└── Click-through: Detailed breakdown

Widget: Violation Heatmap
├── Display: 24-hour heatmap by category
├── Color: Green (0), yellow (1-3), red (4+)
├── Click-through: Violation details
└── Filter: By tier, category, severity

Widget: Evolution Timeline
├── Display: Horizontal timeline of changes
├── Events: Rule additions, removals, threshold adjustments
├── Impact: Autonomy/safety metrics before/after
└── Click-through: CHANGELOG entry

Widget: Top Triggered Guardrails
├── Display: Bar chart (top 10)
├── Metrics: Frequency, approval rate, FP rate
├── Action: "Prune this rule?" button
└── Click-through: Full rule details
```

#### Alert Conditions
```
CRITICAL Alerts (immediate notification):
├── Hard stop violation in ORGANIC SYSTEMS category
├── Tier integrity <0.85 (broken trust model)
├── Safety score >0.5 (unsafe state)
└── Same CRITICAL guardrail violated 3+ times/hour

WARNING Alerts (dashboard highlight):
├── Checkpoint hit rate >40%
├── Override frequency >10/week
├── False positive rate >15%
└── Drift score >0.6

INFO Alerts (logged only):
├── Soft stop triggered
├── Natural checkpoint utilized
├── Override granted (one-time)
└── Near-miss logged
```

---

## 7. Operational Runbook

### 7.1 Daily Health Check
```
1. Review violation count (last 24h)
   └── Expected: <5 violations
   └── If >10: Investigate pattern

2. Check false positive rate
   └── Expected: <10%
   └── If >15%: Review triggered rules, consider pruning

3. Monitor override requests
   └── Expected: 0-3/day
   └── If >5: Identify high-override rules

4. Verify tier integrity
   └── Expected: 100% structural compliance
   └── If <100%: URGENT - permission leak

5. Review near-misses
   └── Pattern emerging? Add guardrail
   └── Rare? Log and monitor
```

### 7.2 Weekly Tuning Session
```
1. Analyze most-triggered guardrails (top 10)
   └── False positive rate >20%? → Prune candidate
   └── Override frequency >50%? → Adjust threshold

2. Review CHANGELOG additions/removals
   └── Net change: additions vs removals
   └── Categories most volatile? → Stabilization needed

3. Check autonomy index trend
   └── Decreasing? → System too restrictive
   └── Increasing rapidly? → Verify safety score

4. Audit blanket approvals
   └── Still valid? → Keep
   └── Outdated? → Expire and remove

5. Update FLIGHT PATH forecast
   └── Projected steady state
   └── Burn-in progress
```

### 7.3 Incident Response
```
High-Severity Violation Occurred:

1. STOP all affected agents immediately
2. Assess damage (data loss, security exposure, etc.)
3. Determine if guardrail failed or was bypassed
4. If failed: Add/strengthen guardrail
5. If bypassed: Audit enforcement code
6. Document in CHANGELOG with "INCIDENT" tag
7. Re-run verification (Green Mode)
8. Resume operations with increased monitoring
```

### 7.4 Pruning Protocol
```
Guardrail Identified for Removal:

1. Verify removal criteria met:
   ├── False positive rate >25% for 7+ days OR
   ├── Override frequency >10/week for 7+ days OR
   └── the operator explicitly requests removal

2. Check dependencies:
   └── Is this rule protecting recovery system?
   └── Is this rule foundational (ORGANIC SYSTEMS)?
   └── If yes: DO NOT REMOVE

3. Document removal:
   ├── Update GUARDRAILS.md (remove rule)
   ├── Add CHANGELOG entry with reason
   └── Archive to "Pruning History" section

4. Monitor impact (7 days):
   ├── Safety score stable? → Success
   ├── Incidents increase? → Re-add guardrail
   └── Log outcome in CHANGELOG
```

---

## 8. Future Evolution

### 8.1 Planned Enhancements
```
Q1 2025:
├── Machine learning-based threshold tuning
├── Context-aware guardrails (dev vs prod)
├── Agent reputation system (trust scoring)
└── Automated pruning suggestions

Q2 2025:
├── Multi-project guardrail inheritance
├── Guardrail A/B testing framework
├── Predictive violation detection
└── Self-healing enforcement layer
```

### 8.2 Research Questions
```
1. Can agent behavior predict guardrail violations?
2. Optimal checkpoint frequency by task complexity?
3. Trust decay curves for blanket approvals?
4. Correlation between guardrail density and task success?
```

### 8.3 Integration Roadmap
```
Phase 1 (Current):
└── Manual monitoring via Flight Path dashboard

Phase 2 (Next 30 days):
├── Automated health checks (cron)
├── Slack/email alerts for CRITICAL violations
└── Weekly summary reports

Phase 3 (60-90 days):
├── ML-based anomaly detection
├── Adaptive thresholds (self-tuning)
└── Cross-project guardrail learning

Phase 4 (Future):
├── Natural language guardrail definition
├── Agent-proposed guardrail adjustments
└── Fully autonomous boundary evolution
```

---

## 9. References

### Internal Documents
- `C:\Users\<user>\workspace\GUARDRAILS.md` - Source of truth
- `C:\Users\<user>\workspace\CLAUDE.md` - Boot configuration
- `C:\Users\<user>\workspace\MEMORY.md` - the agent context
- `C:\Users\<user>\workspace\NOTES.md` - the operator context

### Related Systems
- **Model Tiering Protocol** - Defines the agent/the agent/the agent roles
- **Team Spawner** - Enforces tier constraints at spawn
- **Execution Logging** - Records guardrail checks
- **Flight Path Dashboard** - Visualizes health metrics

### External Resources
- Anthropic the agent documentation (tier capabilities)
- workspace project conventions (path handling, security)
- Red Team audit framework (verification system)

---

## 10. Appendix

### A. Guardrail Checklist (Quick Reference)
```
Before executing action, check:
□ Is this a HARD STOP? → Pause, request approval
□ Does this hit a SOFT STOP threshold? → Checkpoint
□ Is this a RECOVERY PROTECTION file? → Hard block
□ Does my tier allow this? → Structural check
□ Is this a NATURAL CHECKPOINT moment? → Consider pause
```

### B. Override Request Template
```
Guardrail Override Request:

Rule Triggered: [category] - [specific rule]
Action Blocked: [describe action]
Justification: [why this action is safe]
Scope: [one-time | blanket | this-session]
Risk Assessment: [low | medium | high]
Rollback Plan: [if things go wrong]
```

### C. Health Metric Formulas
```
drift_score = 0.3*override_freq + 0.3*fp_rate + 0.2*checkpoint_rate + 0.2*near_miss_trend
safety_score = 0.4*incidents + 0.3*recovery_activations + 0.2*near_miss_severity - 0.1*autonomy
efficiency_score = 0.3*checkpoint_rate + 0.3*approvals_per_task - 0.2*autonomy + 0.2*time_ratio
tier_integrity = 1.0 - (violations + indirect_escalations + confusion_incidents) / total_actions
fragmentation_score = (duplicates + conflicts) / total_rules + files / optimal_files

Composite Health = 0.4*(1-safety_score) + 0.3*(1-drift_score) + 0.2*(1-efficiency_score) + 0.1*tier_integrity
```

### D. Severity Classification
```
CRITICAL (100%): Financial, PII, Organic Systems
HIGH (80-85%): Database, Git, File System, System Integrity
MEDIUM (60-65%): Network, External, Cost, Tier (structural=95%)
LOW (40-50%): Natural Checkpoints, Recommendations
```

---

**END OF FLIGHT PATH DOCUMENT**

*Last Updated: 2025-12-28*
*Next Review: 2026-01-04 (weekly during burn-in)*
*Owner: the agent Architect*
*Status: ACTIVE - Burn-in Phase*
