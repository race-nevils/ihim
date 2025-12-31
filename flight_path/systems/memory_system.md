# Flight Path System Document: Memory System

**System ID:** `memory_system`
**Criticality:** CRITICAL
**Owner:** workspace Core Infrastructure
**Last Updated:** 2025-12-28
**Status:** OPERATIONAL

---

## 1. System Overview

### Purpose
The Memory System provides persistent, structured context across AI sessions using a dual-memory architecture optimized for both fast boot times and comprehensive audit trails. It serves as the "moat" that enables continuity and learning across all workspace operations.

### Why It Exists
- **Context Continuity**: AI sessions are stateless; memory provides persistent state
- **Dual Perspectives**: Human thought direction + AI execution context (the agent) = complete picture
- **Compliance**: Full audit trail for SEC/FINRA requirements in financial services projects
- **Fast Boot**: Lean active memory reduces token overhead and session start time
- **Learning Amplification**: Archive enables pattern extraction, trend analysis, and continuous improvement

### Architecture Pattern
**Lean + Archive**: Active memory stays constant size (<80 lines), archive grows linearly with full session details.

### Key Metrics
- **Boot Time**: <2 seconds to load active memory
- **Context Depth**: 15 recent items (expandable via archive)
- **Archive Coverage**: 100% session capture since 2025-12-17
- **Token Efficiency**: ~2K tokens for active memory vs ~30K+ for full archive

---

## 2. Components

### 2.1 Core Files

| File | Role | Size Target | Update Frequency | Owner |
|------|------|-------------|------------------|-------|
| `MEMORY.md` | the agent's active context | <80 lines | After major tasks | the agent |
| `NOTES.md` | Human thought direction | <80 lines | After major tasks | the operator |
| `MEMORY_ARCHIVE.md` | Full audit trail | Unlimited | After major tasks | Both |
| `MEMORY_SCHEMA.md` | Schema documentation | Static | On pattern changes | the agent |

### 2.2 File Relationships

```
Boot Sequence:
  MEMORY.md ──────┐
                  ├──> Active Context (loaded every session)
  NOTES.md ─┘

Update Sequence:
  Session Work ──> MEMORY.md (Recent + Last Session)
                   ├──> MEMORY_ARCHIVE.md (append full details)
                   └──> NOTES.md (prompts + ideas)

Reference Chain:
  MEMORY_SCHEMA.md ──> Defines structure
  CLAUDE.md ──> Enforces boot sequence
  GUARDRAILS.md ──> Defines boundaries
```

### 2.3 MEMORY.md Structure

**Sections (in order):**
1. **Header**: Updated timestamp
2. **Environment**: Tools, platforms, path conventions
3. **Patterns**: Design patterns, anti-patterns, conventions
4. **Active Projects**: Current work with paths and status
5. **Assets**: Key file locations (logos, configs, docs)
6. **the agent Skills**: Available skills registry
7. **Decisions (Active)**: Current architecture decisions
8. **Heuristics**: Decision rules extracted from debriefs
9. **Last Session**: Quick context for session continuity
10. **Recent (last 15)**: Reverse chronological task list

**Size Constraints:**
- Target: <80 lines
- Hard limit: None, but warns if >80 lines (MEMORY_SCHEMA.md specifies <50 lines originally, but MEMORY.md currently uses 15 items)

### 2.4 NOTES.md Structure

**Sections (in order):**
1. **Header**: Updated timestamp
2. **Last Session**: Project, vibe, status
3. **Recent Prompts (last 15)**: User's actual prompts, reverse chronological, condensed
4. **Ideas in Flight**: Active design patterns, architecture decisions, open explorations
5. **Open Questions**: Unanswered questions with strikethrough when resolved

**Purpose:**
- Captures human thought direction, not just AI execution
- Shows intent from prompt sequence (narrative flow)
- Identifies recurring themes and priorities

### 2.5 MEMORY_ARCHIVE.md Structure

**Pattern:**
```markdown
## YYYY-MM-DD

### Session: [Brief Title]
**the operator's focus:** [What user was trying to accomplish]

**Tasks completed:**
- Bulleted list of concrete deliverables

**Files created/modified:**
- Full file paths with descriptions

**Decisions made:**
| Decision | Rationale |
|----------|-----------|
| X | Y |

**Learnings captured:**
- Key insights, gotchas, patterns discovered

**[Optional sections]:**
- Bug Fixes table
- Architecture diagrams
- Key code snippets
- Scout domains (for team spawns)
```

**Size:** Unlimited, append-only, currently ~1200 lines

---

## 3. Data Flow

### 3.1 Boot Sequence (Session Start)

```
1. the agent harness starts session
2. CLAUDE.md loaded (auto-loaded by the agent harness)
3. Boot sequence triggered:
   ├─> Read MEMORY.md (the agent's context)
   ├─> Read NOTES.md
   └─> Read GUARDRAILS.md (boundaries)
4. Confirmation: "🧠 Memory loaded: [project] | the operator was: [context]"
5. Ready for work
```

**Failure Modes:**
- **Missing MEMORY.md**: Create from schema or flag for user (self-healing)
- **Missing NOTES.md**: Create from template
- **Corrupted JSON in memory**: Fall back to last known good state

### 3.2 Update Triggers

| Trigger | MEMORY.md | NOTES.md | MEMORY_ARCHIVE.md |
|---------|-----------|----------------|-------------------|
| Major task completed (3+ tool calls) | Update Recent, rotate if >15 | Update Recent Prompts | Append full session |
| New tool installed | Add to Environment | - | Log in session |
| Architecture decision | Add to Decisions | Add to Ideas in Flight | Log with rationale |
| New pattern established | Add to Patterns | - | Log in session |
| Heuristic extracted | Add to Heuristics | - | Log in session |
| Session end (/endsession) | Update Last Session | Update Last Session | Append complete session |
| Quick checkpoint (/save) | Update Recent | - | Optional |

### 3.3 Update Sequence (After Major Task)

```
1. Task completes (e.g., 5 bugs fixed, new feature built)
2. Update MEMORY.md:
   ├─> Prepend to Recent (newest first)
   ├─> Update Last Session
   ├─> Rotate out items >15
   └─> Update timestamp
3. Update NOTES.md (if user prompts captured):
   ├─> Add prompts to Recent Prompts
   ├─> Update Ideas in Flight
   └─> Update timestamp
4. Append to MEMORY_ARCHIVE.md:
   ├─> Add date header (if new day)
   ├─> Add session section
   ├─> Full task details, files, decisions, learnings
   └─> Never delete, only append
5. Verify file writes succeeded
```

### 3.4 Data Dependencies

**Inbound (Memory System reads from):**
- `/debrief` command output → Heuristics section
- Agent retrospectives → Learnings
- iHIM execution logs → Recent tasks
- Git commit history → Recent tasks (optional)

**Outbound (Other systems read from Memory):**
- Boot sequence → MEMORY.md, NOTES.md
- `/audit` command → MEMORY_ARCHIVE.md (full history)
- Agent spawner → Active Projects, Environment
- Flight Path scanner → MEMORY.md for system context

---

## 4. Health Metrics

### 4.1 Key Performance Indicators (KPIs)

| Metric | Threshold | Alert Level | Measurement |
|--------|-----------|-------------|-------------|
| **MEMORY.md Size** | <80 lines | WARN if >80 | Line count via `wc -l` |
| **MEMORY.md Freshness** | Updated within 7 days | WARN if >7 days | Parse `Updated:` timestamp |
| **Recent Items Count** | Exactly 15 | WARN if ≠15 | Count Recent list items |
| **Archive Append Frequency** | 1+ per session | ERROR if 0 in session | File modification time |
| **Dual Memory Sync** | Dates match ±1 day | WARN if >1 day apart | Compare `Updated:` fields |
| **Schema Compliance** | All sections present | ERROR if missing | Section header regex match |
| **Boot Success Rate** | 100% | ERROR if fail | Exception during boot |
| **Archive File Size** | Unlimited | INFO only | Track growth rate |

### 4.2 Health Check Implementation

**Location:** `IHIM/api/system/health.py` (if integrated into Flight Path)

**Proposed Health Check Logic:**

```python
def check_memory_system():
    checks = {
        "memory_file_exists": os.path.exists("C:/Users/<user>/workspace/MEMORY.md"),
        "notes_doc_exists": os.path.exists("C:/Users/<user>/workspace/NOTES.md"),
        "archive_exists": os.path.exists("C:/Users/<user>/workspace/MEMORY_ARCHIVE.md"),
        "schema_exists": os.path.exists("C:/Users/<user>/workspace/MEMORY_SCHEMA.md"),
    }

    # Size check
    if checks["memory_file_exists"]:
        line_count = count_lines("C:/Users/<user>/workspace/MEMORY.md")
        checks["memory_size_ok"] = line_count <= 80
        checks["memory_line_count"] = line_count

    # Freshness check
    if checks["memory_file_exists"]:
        updated = parse_updated_timestamp("C:/Users/<user>/workspace/MEMORY.md")
        days_stale = (datetime.now() - updated).days
        checks["memory_fresh"] = days_stale <= 7
        checks["memory_days_stale"] = days_stale

    # Dual memory sync
    if checks["memory_file_exists"] and checks["notes_doc_exists"]:
        memory_date = parse_updated_timestamp("C:/Users/<user>/workspace/MEMORY.md")
        owner_date = parse_updated_timestamp("C:/Users/<user>/workspace/NOTES.md")
        checks["dual_memory_synced"] = abs((memory_date - owner_date).days) <= 1

    # Recent items count
    if checks["memory_file_exists"]:
        recent_count = count_recent_items("C:/Users/<user>/workspace/MEMORY.md")
        checks["recent_count_ok"] = recent_count == 15
        checks["recent_count"] = recent_count

    # Overall status
    critical_checks = ["memory_file_exists", "notes_doc_exists", "archive_exists"]
    warning_checks = ["memory_size_ok", "memory_fresh", "dual_memory_synced"]

    if not all(checks[c] for c in critical_checks):
        return "error"
    elif not all(checks.get(c, True) for c in warning_checks):
        return "degraded"
    else:
        return "healthy"
```

### 4.3 Monitoring Dashboard (Flight Path Integration)

**Proposed Vitals Panel:**

```
┌─ Memory System ─────────────────────────────────┐
│ Status: ● HEALTHY                               │
│                                                  │
│ Active Memory:        77 / 80 lines   [████░]   │
│ Last Updated:         2 hours ago     ✓         │
│ Recent Items:         15 / 15         ✓         │
│ Dual Sync:            ✓ Synced (same day)       │
│ Archive Size:         1,230 lines     ↗ growing │
│                                                  │
│ Quick Actions:                                   │
│ [Compact Recent] [View Archive] [Run Sanity]    │
└──────────────────────────────────────────────────┘
```

---

## 5. Degradation Patterns

### 5.1 How It Fails

| Pattern | Warning Signs | Impact | MTTR |
|---------|---------------|--------|------|
| **Memory Bloat** | MEMORY.md >80 lines | Slow boot, high token cost | 5 min |
| **Staleness** | Not updated in 7+ days | Loss of recent context | 10 min |
| **Desync** | MEMORY.md and NOTES.md dates differ by >1 day | Incomplete context | 5 min |
| **Recent Overflow** | Recent items >15 | Bloat, rotation not happening | 2 min |
| **Recent Underflow** | Recent items <15 | Context loss, updates missing | 5 min |
| **Archive Corruption** | Malformed markdown, missing date headers | Audit trail broken | 15 min |
| **Missing Files** | Any core file deleted | Boot failure | 10 min |
| **Section Drift** | Sections out of order or missing | Schema non-compliance | 10 min |

### 5.2 Early Warning Indicators

**Leading Indicators (predict failure):**
1. **Gradual size increase** - MEMORY.md grows from 60→70→80 lines over sessions
2. **Update frequency drops** - No updates in 3+ days (precursor to staleness)
3. **Recent item accumulation** - Recent count creeps up to 16, 17, 18 (rotation broken)
4. **Archive growth rate change** - Sudden spike or flatline in archive size

**Lagging Indicators (failure occurred):**
1. **Boot errors** - Exception during MEMORY.md read
2. **User confusion** - "Why doesn't the agent remember X?" (context loss)
3. **Duplicate entries** - Same task in Recent multiple times (update logic bug)

### 5.3 Cascade Failures

**Scenario 1: Memory Bloat → Slow Boot → Session Timeout**
```
MEMORY.md reaches 150 lines
  → Boot takes >10 seconds
  → User cancels, starts new session
  → MEMORY.md never updates
  → Bloat worsens
  → Boot time increases further
```

**Prevention:** Hard limit at 100 lines, auto-compact triggered

**Scenario 2: Staleness → Context Loss → Bad Decisions**
```
MEMORY.md not updated in 14 days
  → Recent items from 2 weeks ago
  → the agent suggests outdated approach
  → User corrects multiple times
  → User frustration increases
  → Trust in system decreases
```

**Prevention:** Freshness warnings at 7 days, error at 14 days

**Scenario 3: Archive Corruption → Audit Failure**
```
Bad append operation (race condition)
  → Malformed JSON in archive
  → /audit command fails to parse
  → Compliance audit blocked
  → Manual recovery required
```

**Prevention:** Atomic file writes, validation before append

---

## 6. Recovery Procedures

### 6.1 Memory Bloat (>80 lines)

**Symptoms:**
- MEMORY.md line count exceeds 80
- Boot time noticeably slower
- Sanity check warns about size

**Recovery Steps:**
1. **Identify bloat sources** - Which sections are oversized?
   ```bash
   # Count lines per section
   awk '/^## / {if (section) print section, count; section=$0; count=0; next} {count++} END {print section, count}' MEMORY.md
   ```

2. **Compact Recent items** - Keep only last 10, archive the rest
   ```markdown
   # Before (18 items):
   ## Recent (last 18)
   - Item 1
   - Item 2
   ...
   - Item 18

   # After (10 items):
   ## Recent (last 10)
   - Item 1
   ...
   - Item 10

   # Moved items 11-18 to MEMORY_ARCHIVE.md
   ```

3. **Prune Decisions** - Move inactive decisions to archive
   - Keep: Decisions actively influencing current work
   - Archive: Decisions from completed projects

4. **Compress Patterns** - Merge similar patterns, remove redundant ones

5. **Verify size** - Confirm <80 lines
   ```bash
   wc -l MEMORY.md
   ```

**MTTR:** 5 minutes

### 6.2 Staleness (Not Updated in 7+ Days)

**Symptoms:**
- `Updated:` timestamp older than 7 days
- Sanity check warns about freshness
- Recent items don't reflect current work

**Recovery Steps:**
1. **Review git history** - What work happened since last update?
   ```bash
   git log --since="7 days ago" --oneline --no-merges
   ```

2. **Update Recent items** - Add commits/tasks from git history
   ```markdown
   ## Recent (last 15)
   - [New task from today]
   - [Task from 2 days ago]
   - [Task from 5 days ago]
   ...
   ```

3. **Update Last Session** - Reflect current project focus

4. **Update timestamp** - Set to current date

5. **Append to archive** - Document the gap
   ```markdown
   ### Session: Memory Recovery (Staleness)
   **Recovery reason:** Memory not updated for 9 days due to [reason]

   **Backfilled Recent items:**
   - [reconstructed from git history]
   ```

**MTTR:** 10 minutes

### 6.3 Dual Memory Desync (Dates Differ by >1 Day)

**Symptoms:**
- MEMORY.md and NOTES.md timestamps >1 day apart
- Sanity check warns about desync

**Recovery Steps:**
1. **Identify newer file** - Which was updated more recently?
   ```bash
   ls -lt MEMORY.md NOTES.md
   ```

2. **Update stale file** - Sync to same session
   - If MEMORY.md is newer: Update NOTES.md with recent prompts
   - If NOTES.md is newer: Update MEMORY.md with recent tasks

3. **Verify dates match** - Both should be same date (±1 day acceptable)

**MTTR:** 5 minutes

### 6.4 Recent Item Overflow (>15 Items)

**Symptoms:**
- Recent section has >15 items
- Sanity check warns about overflow

**Recovery Steps:**
1. **Rotate oldest items** - Keep newest 15, archive the rest
   ```markdown
   # Before (18 items):
   ## Recent (last 18)
   - Item 1 (newest)
   - Item 2
   ...
   - Item 16
   - Item 17
   - Item 18 (oldest)

   # After (15 items):
   ## Recent (last 15)
   - Item 1 (newest)
   ...
   - Item 15

   # Archive section updated with items 16-18
   ```

2. **Fix rotation logic** - If automated rotation failed, investigate why

**MTTR:** 2 minutes

### 6.5 Recent Item Underflow (<15 Items)

**Symptoms:**
- Recent section has <15 items
- Sanity check warns about underflow

**Recovery Steps:**
1. **Check archive** - Were items moved but not replaced?

2. **Backfill from git/archive** - Add recent work to reach 15
   - Review last 7 days of git commits
   - Review last 2 sessions in archive
   - Extract tasks and add to Recent

3. **Verify count** - Confirm exactly 15 items

**MTTR:** 5 minutes

### 6.6 Missing Files (Boot Failure)

**Symptoms:**
- Boot sequence fails with FileNotFoundError
- MEMORY.md, NOTES.md, or MEMORY_SCHEMA.md missing

**Recovery Steps:**
1. **Self-healing triggers** - CLAUDE.md specifies:
   - If files missing: Create from schema or flag for user

2. **Restore from git** - If file was committed previously
   ```bash
   git checkout HEAD -- MEMORY.md
   ```

3. **Create from template** - If never committed (new repo)
   - Use MEMORY_SCHEMA.md templates
   - Populate with minimal context

4. **Escalate to user** - If restore/create fails
   ```
   ERROR: Memory system boot failed
   Missing files: [list]
   Action required: Restore from backup or recreate
   ```

**MTTR:** 10 minutes

### 6.7 Archive Corruption (Malformed Markdown)

**Symptoms:**
- /audit command fails to parse archive
- Markdown linter errors in MEMORY_ARCHIVE.md

**Recovery Steps:**
1. **Identify corruption point** - Use git to find bad commit
   ```bash
   git log -p MEMORY_ARCHIVE.md | less
   ```

2. **Validate structure** - Check for:
   - Missing date headers (`## YYYY-MM-DD`)
   - Unclosed code blocks (```)
   - Malformed tables (uneven columns)

3. **Repair manually** - Fix markdown syntax errors

4. **Test parsing** - Verify /audit can read archive
   ```bash
   python -c "import markdown; markdown.markdown(open('MEMORY_ARCHIVE.md').read())"
   ```

5. **Prevent recurrence** - Add validation before append
   ```python
   def append_to_archive(content):
       # Validate markdown before writing
       try:
           markdown.markdown(content)
       except Exception as e:
           raise ValueError(f"Invalid markdown: {e}")

       # Atomic write
       with open("MEMORY_ARCHIVE.md", "a") as f:
           f.write(content)
   ```

**MTTR:** 15 minutes

### 6.8 Section Drift (Schema Non-Compliance)

**Symptoms:**
- Sections out of order (e.g., Recent before Decisions)
- Missing required sections (e.g., no Environment section)
- Sanity check fails schema validation

**Recovery Steps:**
1. **Compare against schema** - MEMORY_SCHEMA.md defines order

2. **Reorder sections** - Move to correct positions

3. **Add missing sections** - Create with placeholder content

4. **Verify compliance** - Run sanity check
   ```bash
   python harness/sanity/check.py
   ```

**MTTR:** 10 minutes

---

## 7. Integration Points

### 7.1 Boot Sequence (CLAUDE.md)

**Location:** `C:\Users\<user>\workspace\CLAUDE.md`

**Integration:**
```markdown
## Boot Sequence

1. Read context: `MEMORY.md`, `NOTES.md`, `GUARDRAILS.md`
2. Load tier awareness (this protocol)
3. Confirm: `🧠 Memory loaded: [project] | the operator was: [context]`

Self-healing: If files missing, create from schema or flag for user.
```

### 7.2 Slash Commands

**Location:** `harness/commands/`

**Commands that interact with Memory System:**

| Command | Memory Interaction |
|---------|-------------------|
| `/save` | Quick checkpoint - updates MEMORY.md Recent |
| `/endsession` | Full close-out - updates MEMORY.md + NOTES.md + MEMORY_ARCHIVE.md |
| `/audit` | Reads MEMORY_ARCHIVE.md for retrospective analysis |
| `/debrief` | Extracts heuristics → writes to MEMORY.md Heuristics section |

### 7.3 Sanity Check System

**Location:** `harness/sanity/check.py`

**Memory-related checks:**
1. Memory files exist (MEMORY.md, NOTES.md, archive, schema)
2. Required sections present
3. Freshness (warns if >7 days stale)
4. Size (warns if >80 lines)
5. Recent items count (warns if ≠15)
6. Dual memory sync (dates match within 1 day)

### 7.4 Flight Path Dashboard

**Location:** `IHIM/ui/index.html` (Flight Path modal)

**Proposed Integration:**
- Add "Memory System" node to topology
- Show health status (green/yellow/red ring)
- Display key metrics in node info panel:
  - File sizes
  - Last updated timestamp
  - Recent items count
  - Dual sync status

**API Endpoints (to be created):**
```
GET /api/system/memory/health
  → Returns: {status, metrics, warnings}

GET /api/system/memory/recent
  → Returns: {items: [...], count: 15}

POST /api/system/memory/compact
  → Triggers: Memory bloat recovery procedure
```

### 7.5 Agent Spawner

**Location:** `IHIM/team/spawner.py`

**Memory reads:**
- Active Projects → to determine context for agent prompts
- Environment → to include in agent system info
- Recent → to provide session context

**Memory writes:**
- After agent spawn completion → append to Recent
- Agent retrospectives → may inform future Heuristics

---

## 8. SCADA Dashboard Integration

### 8.1 Proposed Flight Path Panel

**Visual Layout:**

```
┌─ MEMORY SYSTEM ────────────────────────────────────────┐
│                                                         │
│  Status: ● HEALTHY                    Uptime: 100%     │
│                                                         │
│  ┌─ Active Memory ─────────────────────────────────┐   │
│  │ MEMORY.md              77 / 80 lines  [████░]   │   │
│  │ NOTES.md         65 / 80 lines  [███░░]   │   │
│  │ Last Sync:             2 hours ago    ✓         │   │
│  └─────────────────────────────────────────────────┘   │
│                                                         │
│  ┌─ Archive ────────────────────────────────────────┐   │
│  │ MEMORY_ARCHIVE.md      1,230 lines   ↗ +15/day  │   │
│  │ Sessions Logged:       47 sessions   since Dec17│   │
│  └─────────────────────────────────────────────────┘   │
│                                                         │
│  ┌─ Health Checks ──────────────────────────────────┐   │
│  │ ✓ Files exist          ✓ Schema compliance       │   │
│  │ ✓ Freshness (<7d)      ✓ Recent count (15)       │   │
│  │ ✓ Dual sync            ⚠ Size warning (77/80)    │   │
│  └─────────────────────────────────────────────────┘   │
│                                                         │
│  Actions: [Compact] [View Archive] [Run Sanity]        │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

### 8.2 Alert Thresholds

| Metric | Green | Yellow | Red |
|--------|-------|--------|-----|
| MEMORY.md size | <70 lines | 70-80 lines | >80 lines |
| Freshness | <3 days | 3-7 days | >7 days |
| Recent count | 15 | 13-14 or 16-17 | <13 or >17 |
| Dual sync | Same day | ±1 day | >1 day apart |
| Boot success | 100% | 95-99% | <95% |

### 8.3 Historical Trending

**Metrics to track over time:**
1. **Archive growth rate** - Lines per day/session
2. **Update frequency** - Updates per week
3. **Boot time** - Milliseconds to load memory
4. **Recent rotation rate** - How often items rotate out
5. **Heuristics accumulation** - New heuristics per week

**Visualization:**
- Line graph: Archive size over time (growth trend)
- Bar chart: Updates per week (update frequency)
- Gauge: Current MEMORY.md size vs 80-line target

---

## 9. Maintenance Procedures

### 9.1 Daily
- **Automated:** None (updates happen on-demand)
- **Manual:** None required

### 9.2 Weekly
- **Review MEMORY.md size** - If >70 lines, consider compacting
- **Review Recent items** - Ensure rotation is working (oldest item should be <7 days old)

### 9.3 Monthly
- **Archive audit** - Verify no corruption, check growth rate
- **Heuristics review** - Graduate learnings from archive to Heuristics section
- **Schema review** - Ensure templates still match actual usage

### 9.4 Quarterly
- **Full system audit** - Run all sanity checks, review all files
- **Performance review** - Boot time, token cost, context effectiveness
- **Schema evolution** - Update MEMORY_SCHEMA.md if patterns changed

---

## 10. Future Enhancements

### 10.1 Short-term (Next 30 days)
1. **Automated a context reset** - Trigger when >80 lines, auto-rotate Recent
2. **Flight Path integration** - Add Memory System node to topology
3. **Health API endpoints** - `/api/system/memory/health`, `/recent`, `/compact`
4. **Freshness alerts** - Email/Slack notification if stale >7 days

### 10.2 Medium-term (Next 90 days)
1. **Semantic search** - Query archive with natural language
2. **Auto-heuristic extraction** - ML model to identify patterns in archive
3. **Version control integration** - Auto-populate Recent from git commits
4. **Multi-project memory** - Separate memory per project with inheritance

### 10.3 Long-term (Next 180 days)
1. **Memory embeddings** - Vector database for semantic memory retrieval
2. **Predictive staleness** - ML model to predict when updates needed
3. **Cross-session learning** - Agents learn from archive, not just active memory
4. **Memory compression** - Auto-summarize old archive entries to reduce size

---

## 11. Runbook Summary

### Critical Procedures
1. **Boot Failure**: Restore from git or create from schema (10 min)
2. **Memory Bloat**: Compact Recent, prune Decisions (5 min)
3. **Staleness**: Backfill from git, update timestamp (10 min)
4. **Archive Corruption**: Find bad commit, repair markdown, add validation (15 min)

### Emergency Contacts
- **Owner**: workspace Core Infrastructure (automated)
- **Escalation**: the operator (manual intervention if self-healing fails)

### Related Systems
- **CLAUDE.md**: Boot sequence
- **GUARDRAILS.md**: Boundaries
- **Sanity Check System**: Validation
- **Flight Path**: Monitoring dashboard

---

## Appendix A: File Locations

```
C:\Users\<user>\workspace\
├── MEMORY.md                 # the agent's active context
├── NOTES.md            # the operator's thought direction
├── MEMORY_ARCHIVE.md         # Full audit trail
├── MEMORY_SCHEMA.md          # Schema documentation
├── CLAUDE.md                 # Boot sequence
├── GUARDRAILS.md             # Boundaries
└── harness dir\
    ├── sanity\
    │   └── check.py          # Sanity checks
    └── commands\
        ├── save.md           # Quick checkpoint
        ├── endsession.md     # Session close-out
        ├── audit.md          # Retrospective analysis
        └── debrief.md        # Heuristic extraction
```

---

## Appendix B: Metrics Collection Queries

**MEMORY.md line count:**
```bash
wc -l C:\Users\<user>\workspace\MEMORY.md | awk '{print $1}'
```

**Recent items count:**
```bash
awk '/^## Recent/,/^---/ {if (/^- /) count++} END {print count}' MEMORY.md
```

**Last updated timestamp:**
```bash
grep "^Updated:" MEMORY.md | awk '{print $2}'
```

**Archive session count:**
```bash
grep "^### Session:" MEMORY_ARCHIVE.md | wc -l
```

**Archive growth rate (lines per day):**
```bash
# Total lines / days since first entry
echo "scale=2; $(wc -l < MEMORY_ARCHIVE.md) / $((($(date +%s) - $(date -r MEMORY_ARCHIVE.md +%s)) / 86400))" | bc
```

---

## Document Changelog

| Date | Version | Changes |
|------|---------|---------|
| 2025-12-28 | 1.0 | Initial Flight Path system document created |

---

**End of Document**
