# RED TEAM AUDIT: Mission Control UX Rigidity Analysis

**Date**: 2025-12-28
**Auditor**: the agent Savage (RED TEAM MODE)
**Target**: Mission Control (iHIM/ui/index.html + api/team_builder/routes.py)
**Scope**: Identify ALL rigidity points preventing fluid, exploratory UX

---

## Executive Summary

**Problem**: User typed "Search the team" and it immediately spawned 5 terminals. No thinking phase, no preview, no way to explore before committing. Everything is a button-does-exact-thing pattern with zero flexibility.

**Root Cause**: The entire UI is built on the **action-trigger paradigm** - user expresses intent, system immediately executes. There is NO dialogue layer, NO exploration mode, NO "what-if" sandbox.

**Impact**: Mental load on the operator - he must pre-compute the entire workflow in his head before touching any UI element. The system doesn't think WITH him, it just executes AT him.

---

## RIGIDITY POINT #1: Immediate Spawn on Submit

**Location**: `index.html:3655-3696` (`spawnFromMC()` function)

**Current behavior**:
- User types task description
- User selects template from dropdown
- User clicks "Spawn Team"
- **IMMEDIATELY** hits `/api/teams/spawn` endpoint
- Terminal windows open instantly

**Problem**:
- No preview of what prompts will be generated
- No chance to review team composition
- No way to see "what would this team actually do with this task?"
- **Zero exploration** - it's all-or-nothing commit

**Missing**:
- Preview mode: "Show me what you'll give each agent"
- Edit mode: "Let me tweak the frontend-dev prompt before spawning"
- Staged execution: "Spawn 2 agents first, see how it goes, then spawn the rest"

**Suggested fix**:
```javascript
// Add "Preview Prompts" button BEFORE "Spawn Team"
// Shows generated prompts in expandable cards
// User can edit individual prompts
// User can deselect agents they don't want
// "Spawn Team" becomes "Spawn Selected Agents"
```

---

## RIGIDITY POINT #2: Template Dropdown is Commitment Device

**Location**: `index.html:522-524` (template selector), `index.html:3611-3653` (`onTemplateSelect()`)

**Current behavior**:
- Dropdown has list of templates
- Selecting one shows preview (name, count, S/H icons)
- Preview is **minimal** - just counts, no detail
- Selecting = committing to that exact team structure

**Problem**:
- Can't see agent details until AFTER selecting template
- Can't compare two templates side-by-side
- Can't mix agents from different templates
- Preview only shows WHAT (5 agents, 2S + 3H) not WHO or WHY

**Missing**:
- Rich preview: Show agent names, roles, expertise BEFORE selecting
- Compare mode: "Show me Yellow Mode vs Red Team side-by-side"
- Custom composition: "I want frontend-dev from Software Team + security-reviewer from Red Team"
- Template builder: "Save this custom mix as a new template"

**Suggested fix**:
```javascript
// Replace dropdown with card grid
// Each card shows full agent list with roles
// Click card → detailed view (not spawn, just explore)
// Checkboxes per agent for custom selection
// "Create Custom Team" button for mixing agents
```

---

## RIGIDITY POINT #3: Task Input Has No Intelligence

**Location**: `index.html:516` (textarea input), `index.html:3656-3657` (reads value directly)

**Current behavior**:
- User types freeform text
- Text is sent AS-IS to backend
- Backend does prompt morphing, but user never sees it
- No feedback loop until AFTER spawn

**Problem**:
- User has no idea if their phrasing is good/bad
- No suggestions: "Did you mean to spawn a security audit team?"
- No auto-detection: "This sounds like a research task, try Research Team"
- No validation: Empty string checked, but nothing else

**Missing**:
- Smart suggestions: Analyze input, suggest templates
- Auto-complete: Common task patterns as templates
- Syntax hints: "Use @agent-name to target specific agents"
- Confidence indicator: "This task matches Security Audit (85%)"

**Suggested fix**:
```javascript
// Add debounced analysis on textarea input
// Show inline suggestions as user types
// "Looks like you want to audit code - try Red Team (10H)"
// Click suggestion → auto-fill template + refine task description
```

---

## RIGIDITY POINT #4: No Agent Subset Selection in UI

**Location**: `routes.py:276-289` (backend supports `agent_subset`), `index.html` (UI DOES NOT expose it)

**Current behavior**:
- Backend API has `agent_subset` parameter
- UI sends `null` (always spawns ALL agents in template)
- User has zero control over which agents spawn

**Problem**:
- Template says "10 agents" but user only wants 3
- User can't say "Just spawn the scouts, not the operators"
- No granular control - it's all-or-nothing

**Missing**:
- Checkbox list: Show all agents in template, let user pick
- Presets: "Quick (3 agents)", "Standard (5)", "Full (10)"
- Conditional spawning: "Spawn scouts first, if they find issues spawn operators"

**Suggested fix**:
```javascript
// After selecting template, show agent checklist
// All checked by default, user can uncheck
// Send checked agent IDs as agent_subset
```

---

## RIGIDITY POINT #5: No Iteration or Feedback Loop

**Location**: Entire Mission Control flow (one-shot execution)

**Current behavior**:
- User describes task once
- System spawns team once
- Done. No conversation, no refinement.

**Problem**:
- User can't iterate: "Actually, add a security reviewer"
- User can't refine: "Make the task more specific"
- User can't pivot: "Stop this, try a different approach"
- **No dialogue** - it's a vending machine, not a collaborator

**Missing**:
- Multi-turn conversation: "Tell me more about the audit" → refine → "Here's what I'll do"
- Staged execution: "Spawn 2 scouts → review findings → spawn 5 operators"
- Live feedback: "Scout #1 found 3 issues, spawn more scouts?"
- Cancellation: "Stop spawning, I changed my mind"

**Suggested fix**:
```javascript
// Add "Plan Team" mode BEFORE "Spawn Team"
// Plan mode: LLM generates execution plan, shows to user
// User reviews, edits, approves
// THEN spawn happens
```

---

## RIGIDITY POINT #6: Template is Immutable

**Location**: `routes.py:174-201` (create template requires full definition), UI has NO template editing

**Current behavior**:
- Templates are defined in JSON
- User can CREATE new template via API (complex)
- User CANNOT edit existing template
- User CANNOT tweak template on-the-fly

**Problem**:
- Template says "5 agents" but user wants 7 this time
- User can't say "Yellow Mode but with 1 extra the agent"
- Can't experiment: "What if I swap the agent #3 for a the agent?"

**Missing**:
- Inline editing: Click template → modify agents → spawn custom instance
- Template forking: "Clone Yellow Mode, add 2 agents, save as Yellow+"
- Ephemeral templates: One-off modifications that don't persist

**Suggested fix**:
```javascript
// "Edit Template" button in preview
// Opens modal with agent editor
// Add/remove agents, change tiers
// "Save as New Template" or "Spawn Once (Don't Save)"
```

---

## RIGIDITY POINT #7: No "What Would Happen?" Preview

**Location**: `routes.py:292-303` (prompt generation happens in spawn, not exposed)

**Current behavior**:
- Backend calls `route_to_team()` to generate tailored prompts
- This happens INSIDE the spawn endpoint
- User NEVER sees these prompts before agents spawn
- Prompts are fire-and-forget

**Problem**:
- User has no idea what instructions agents receive
- Can't verify: "Is frontend-dev getting the right context?"
- Can't debug: "Why did security-reviewer miss this?"
- **Black box execution** - input goes in, terminals come out

**Missing**:
- Separate endpoint: `POST /api/teams/preview` (returns prompts, doesn't spawn)
- UI preview: Show each agent's prompt in expandable card
- Edit prompts: "Tweak the backend-dev instructions before spawning"
- Diff view: "What changed from last time I ran this?"

**Suggested fix**:
```python
# routes.py - add preview endpoint
@router.post("/preview")
async def preview_team(request: SpawnTeamRequest):
    template = get_template(request.template_id)
    routed_prompts = route_to_team(template, request.task_description, request.project)
    return {"prompts": routed_prompts, "template": template.name}
```

```javascript
// UI - add "Preview Team" button
// Fetches prompts, shows in modal
// Each agent card: name + role + full prompt text
// Edit button per prompt
// "Looks good, spawn" → proceed with edited prompts
```

---

## RIGIDITY POINT #8: Status is Ephemeral

**Location**: `index.html:3687-3692` (status message shows, then disappears)

**Current behavior**:
- Spawn succeeds → green status "Spawned 5 agents"
- Status fades after 3 seconds
- User left with open terminals, no record in UI

**Problem**:
- Can't review: "What did I just spawn?"
- Can't track: "Is this the 3rd or 4th time I ran this?"
- No history: "What task did I give them 10 minutes ago?"

**Missing**:
- Persistent spawn log: List of recent spawns with timestamps
- Active teams panel: "You have 2 active teams (Yellow Mode, Red Team)"
- Spawn history: Click to see task description + agents spawned
- Re-run: "Run this exact config again"

**Suggested fix**:
```javascript
// Add "Recent Spawns" section in MC footer
// List last 5 spawns: timestamp + template + agent count
// Click → expand to see full details
// "Spawn Again" button for easy re-runs
```

---

## RIGIDITY POINT #9: No Exploration Mode

**Location**: Entire UI (all actions are destructive/committing)

**Current behavior**:
- Every button DOES something
- No "browse mode" or "what-if sandbox"
- User must know what they want before clicking

**Problem**:
- Can't explore: "What teams are available?"
- Can't learn: "What does Red Team do vs Yellow Mode?"
- Can't experiment: "Show me what this would look like"
- **High cognitive load** - must plan entire flow in head first

**Missing**:
- Browse mode: Click template → see full details, NO spawn
- Playground: Build a team, see preview, discard without saving
- Help mode: Hover over template → tooltip with use cases
- Examples: "Try these sample tasks" with pre-filled inputs

**Suggested fix**:
```javascript
// Add "Browse Teams" view (no spawn, just exploration)
// Card grid with rich previews
// Click card → modal with full agent details + example tasks
// "Try This Template" → fills MC inputs, doesn't spawn yet
```

---

## RIGIDITY POINT #10: Button Labels Are Action-Oriented

**Location**: Throughout UI (`onclick="spawnTeam()"`, `onclick="spawnFromMC()"`)

**Current behavior**:
- Buttons say "Spawn Team", "Spawn Agents"
- Language is **imperative** - it WILL happen
- No "Plan", "Preview", "Explore" verbs

**Problem**:
- User mindset: "This will execute, so I better be sure"
- No invitation to explore
- No progressive disclosure
- **Commitment anxiety** - hesitation to click anything

**Missing**:
- Exploration verbs: "Preview", "Plan", "Explore", "What If?"
- Progressive buttons: "Preview" → "Refine" → "Confirm & Spawn"
- Undo language: "Spawn (can stop later)" vs "Spawn (irreversible)"

**Suggested fix**:
```html
<!-- Before: -->
<button onclick="spawnFromMC()">Spawn Team</button>

<!-- After: -->
<button onclick="previewTeam()">Preview Plan</button>
<!-- In preview modal: -->
<button onclick="spawnFromMC()">Looks Good, Spawn Team</button>
```

---

## RIGIDITY POINT #11: No Conversational Interface

**Location**: Entire UI (form-based, not conversational)

**Current behavior**:
- User fills form fields (task + template)
- Clicks button
- System executes
- **Zero back-and-forth**

**Problem**:
- User quote: "I typed 'Search the team' and it just spawned 5 terminals"
- User wanted to ASK a question, system EXECUTED an action
- No way to TALK to Mission Control, only COMMAND it

**Missing**:
- Chat mode: Type freeform, system asks clarifying questions
- Natural language: "I want to audit security" → "I found 3 audit teams, which one?"
- Ambiguity resolution: "Did you mean search FOR a team or search WITH a team?"
- Suggestions: "Based on your task, I recommend Red Team (10H)"

**Suggested fix**:
```javascript
// Add conversational mode toggle
// Instead of task textarea + dropdown:
// Single chat input: "What do you want to do?"
// LLM backend: Analyze intent, ask questions, build plan
// After 2-3 turns → "Here's the team I'll spawn, approve?"
```

---

## RIGIDITY POINT #12: Templates Are Static Definitions

**Location**: `routes.py:123-152` (templates loaded from JSON file)

**Current behavior**:
- Templates defined in `team_templates.json`
- Loaded once at startup
- User picks from fixed menu

**Problem**:
- Templates are prescriptive: "Use these exact 5 agents"
- No dynamic composition: "Build me a team for THIS specific task"
- No learning: "Last time I used Yellow, I needed 1 more the agent"

**Missing**:
- Dynamic templates: LLM generates team on-the-fly based on task
- Template suggestions: "For this task, I recommend 3S + 4H"
- Template evolution: "Yellow Mode usually needs +1S, update default?"
- Contextual templates: "You're in debug mode, try Debug Swarm (8H)"

**Suggested fix**:
```javascript
// Add "Auto-Build Team" button
// Sends task to LLM, gets back recommended team composition
// Shows preview: "I suggest 2S + 5H: Frontend, Backend, 5 Scouts"
// User approves or tweaks
```

---

## RIGIDITY POINT #13: No Feedback Collection

**Location**: No post-spawn feedback mechanism

**Current behavior**:
- Team spawns
- User works with agents
- Mission Control shows nothing
- **No learning loop**

**Problem**:
- System doesn't learn: "Was this team effective?"
- User can't rate: "Yellow Mode worked great for audits"
- No improvement: Template use_count increments, but no quality signal

**Missing**:
- Post-spawn survey: "Did this team solve your problem? (Y/N)"
- Agent rating: "Which agents were most helpful?"
- Task matching: "Was Yellow Mode the right choice? (Yes/No/Suggest better)"
- Improvement loop: Feed ratings back to template recommendations

**Suggested fix**:
```javascript
// After spawn, add notification bar
// "Team spawned! Rate this later?"
// Click → modal: "How did it go?" + thumbs up/down
// "Which agents helped most?" + checkboxes
// Store in spawn history, use for future recommendations
```

---

## RIGIDITY POINT #14: No Spawn Cancellation

**Location**: `routes.py:306-309` (spawn is synchronous, no cancellation)

**Current behavior**:
- User clicks "Spawn Team"
- Backend opens terminals
- No way to stop mid-spawn
- No way to cancel if user realizes mistake

**Problem**:
- User typo in task → spawns anyway
- User changes mind → too late
- Wrong template selected → terminals already opening
- **Irreversible action** with no safety net

**Missing**:
- Confirmation dialog: "About to spawn 10 terminals, proceed?"
- Cancel button: "Spawning... [Cancel]"
- Undo: "Spawned 5 agents [Undo - close all terminals]"

**Suggested fix**:
```javascript
// Add confirmation for >5 agents
if (agentCount > 5) {
  const confirmed = confirm(`About to spawn ${agentCount} terminal tabs. Proceed?`);
  if (!confirmed) return;
}

// Add progress indicator during spawn
// "Spawning 1/5... [Cancel]"
// If cancelled, don't spawn remaining agents
```

---

## RIGIDITY POINT #15: Task Input is Single-Shot

**Location**: `index.html:516` (single textarea, no history)

**Current behavior**:
- User types task
- Spawns team
- Task input clears (line 3689: `taskInput.value = ''`)
- **Task is lost** after spawn

**Problem**:
- Can't review: "What task did I give them?"
- Can't refine: "Spawn same team, slightly different task"
- Can't compare: "Try Red Team with same task as Yellow Mode"

**Missing**:
- Task history: Dropdown of recent tasks
- Task templates: Save common tasks as presets
- Task refinement: "Use last task but add XYZ"
- Task persistence: Don't clear input after spawn

**Suggested fix**:
```javascript
// Add task history dropdown
// "Recent tasks" with last 10
// Click → fills textarea
// "Save as template" button for common tasks
```

---

## RIGIDITY POINT #16: No Agent Status Visibility

**Location**: Mission Control shows spawn count, but no agent status

**Current behavior**:
- Spawn happens
- Terminals open
- Mission Control shows: "Spawned 5 agents from Yellow Mode"
- **Zero visibility** into what agents are doing

**Problem**:
- Can't monitor: "Is frontend-dev done yet?"
- Can't debug: "Why is backend-dev stuck?"
- Can't coordinate: "Who's waiting on who?"

**Missing**:
- Agent status panel: List of spawned agents with live status
- Progress indicators: "frontend-dev: writing code (60%)"
- Blackboard integration: Show agent communications
- Dependency graph: "backend-dev blocked on frontend-dev"

**Suggested fix**:
```javascript
// Add "Active Agents" panel in MC window
// Live WebSocket updates from blackboard
// Show agent name + current status + last action
// Click agent → open their terminal tab
```

---

## RIGIDITY POINT #17: Template Selection is Binary

**Location**: `index.html:522-524` (dropdown - single selection only)

**Current behavior**:
- User picks ONE template
- Can't combine templates
- Can't layer templates

**Problem**:
- User wants: "Yellow Mode + 2 extra security agents"
- User wants: "Red Team scouts + Software Dev operators"
- **Forced into pre-defined boxes**

**Missing**:
- Multi-select: "Combine Yellow Mode + Security Audit"
- Template layers: "Base: Yellow Mode, Add-on: +2 Security"
- Template math: "Software Dev - DevOps + Security"

**Suggested fix**:
```javascript
// Change dropdown to tag selector
// Multi-select templates
// Backend merges agent lists (deduplicates by role)
// Preview shows combined team
```

---

## RIGIDITY POINT #18: No Quick Actions

**Location**: Every action requires opening Mission Control window

**Current behavior**:
- User wants to spawn team
- Opens MC window
- Fills form
- Spawns
- **3-4 clicks minimum**

**Problem**:
- High friction for common tasks
- Can't quick-spawn: "Just give me Red Team, now"
- Can't repeat: "Run last team again"

**Missing**:
- Quick spawn buttons: Desktop icons for common teams
- Keyboard shortcuts: "Ctrl+Shift+R = Red Team"
- Last spawn: "Re-run last config" button
- Presets: "Audit", "Build Feature", "Research" one-click spawns

**Suggested fix**:
```javascript
// Add quick-spawn buttons to MC footer
// "Red Team" "Yellow Mode" "Software Dev"
// Click → skips form, spawns with default task
// Optional: Prompts for task if template requires it
```

---

## RIGIDITY POINT #19: No Prompt Customization in UI

**Location**: Backend generates prompts (`route_to_team()`), UI never shows them

**Current behavior**:
- Backend uses templates to generate prompts
- Prompts injected with task context
- Agents receive prompts
- **User has zero visibility or control**

**Problem**:
- Can't customize: "Tell frontend-dev to use React, not Vue"
- Can't debug: "Why did security-reviewer miss this pattern?"
- Can't learn: "What exact prompt did backend-dev get?"

**Missing**:
- Prompt editor: Show generated prompts, allow edits
- Prompt templates: Save custom prompt variations
- Prompt variables: "Add extra instructions: {user_input}"
- Prompt library: "Use Security Audit Prompt v2"

**Suggested fix**:
```javascript
// After selecting template, add "Customize Prompts" accordion
// Shows each agent's prompt
// Editable textarea per agent
// "Reset to Default" button
// Spawn with customized prompts
```

---

## RIGIDITY POINT #20: No Progressive Disclosure

**Location**: Entire UI (all options visible at once)

**Current behavior**:
- Mission Control shows all fields immediately
- No steps, no wizard, no guidance
- **Blank canvas anxiety**

**Problem**:
- User overwhelmed: "What do I fill in first?"
- No workflow: "Is this the right order?"
- No validation: "Did I miss something?"

**Missing**:
- Wizard flow: Step 1: Describe task → Step 2: Pick team → Step 3: Review → Step 4: Spawn
- Progressive fields: Show team selector AFTER task input
- Smart defaults: Pre-fill based on task analysis
- Guided mode: "First time? Follow this flow..."

**Suggested fix**:
```javascript
// Add wizard mode toggle
// Step 1: "What do you want to do?" (task input only)
// Step 2: "I recommend these teams" (template suggestions)
// Step 3: "Review plan" (preview prompts)
// Step 4: "Spawn team" (final confirmation)
```

---

## Summary: The Core Problem

**Current paradigm**: Mission Control is a **form that executes**.

**Needed paradigm**: Mission Control should be a **conversation that plans, then executes**.

### The Fundamental Shift

| Current (Rigid) | Needed (Fluid) |
|----------------|----------------|
| Fill form → Execute | Describe goal → Explore options → Refine → Execute |
| One-shot spawn | Multi-turn planning |
| Button = action | Button = next step in dialogue |
| Template = prescription | Template = suggestion |
| User pre-computes flow | System guides flow |
| No preview | Full preview + edit |
| Immediate execution | Staged execution |
| Zero visibility post-spawn | Live agent monitoring |

---

## Recommended Implementation Priority

### Phase 1: Add Preview Layer (CRITICAL)
- **RP #7**: Add `/api/teams/preview` endpoint + UI
- **RP #1**: Change "Spawn Team" to "Preview Team" → "Spawn"
- **RP #3**: Add task analysis + template suggestions

### Phase 2: Enable Exploration (HIGH)
- **RP #9**: Add "Browse Teams" mode (no spawn, just explore)
- **RP #4**: Add agent subset checkboxes in UI
- **RP #6**: Add inline template editing

### Phase 3: Add Feedback Loops (HIGH)
- **RP #5**: Add multi-turn conversation mode
- **RP #13**: Add post-spawn rating system
- **RP #16**: Add live agent status panel

### Phase 4: Reduce Friction (MEDIUM)
- **RP #18**: Add quick-spawn buttons
- **RP #15**: Add task history dropdown
- **RP #8**: Add persistent spawn log

### Phase 5: Advanced Features (LOW)
- **RP #11**: Add full conversational interface
- **RP #12**: Add dynamic team composition
- **RP #17**: Add multi-template combining

---

## Metrics to Track Improvement

1. **Clicks to Spawn**: Current: 4+ (open MC, fill task, select template, spawn)
   Target: 1-2 (quick spawn) or 6-8 (full preview flow)

2. **Preview Rate**: Current: 0% (no preview exists)
   Target: 80%+ (most users preview before spawn)

3. **Spawn Cancellation**: Current: 0% (can't cancel)
   Target: 10-15% (users realize mistake, cancel, refine)

4. **Template Editing**: Current: 0% (can't edit)
   Target: 30%+ (users customize before spawn)

5. **User Confidence**: "I know what will happen before I click Spawn"
   Current: Low (black box)
   Target: High (full transparency)

---

## Closing Thoughts

The current Mission Control is a **jukebox** - you punch in your selection, it plays a song.

the operator wants a **DJ booth** - fluid mixing, live preview, real-time adjustment, collaborative flow.

Every rigidity point above is a place where we forced the operator to think like a computer (precise, pre-planned, committed) instead of letting the computer think with him (exploratory, iterative, forgiving).

**The fix isn't just UI polish - it's a paradigm shift from EXECUTION MODE to EXPLORATION MODE.**

---

**END OF AUDIT**
