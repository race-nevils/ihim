# Technical Specification: Dry Run Preview

**Feature**: Mission Control - "Preview Impact" Button
**Pattern**: Figma-style dry run simulation before execution
**Goal**: Show users exactly what will happen before spawning a team
**Priority**: Phase 1 - Implement First

---

## User Story

**As a** Mission Control user
**I want to** see exactly what a team will do before I spawn it
**So that** I can deploy with confidence and adjust if needed

**Current Behavior:**
```
User: *selects template, types task*
User: *clicks "Spawn Team"*
System: *spawns immediately*
User: *crosses fingers, hopes for the best*
```

**Desired Behavior:**
```
User: *selects template, types task*
User: *clicks "Preview Impact"*
System: *shows detailed dry run modal*
User: *reviews agents, files, permissions, output*
User: *clicks "Looks Good - Deploy"*
System: *spawns with user's full understanding*
```

---

## UI Changes

### 1. Add "Preview Impact" Button

**Location**: `IHIM/ui/index.html` - Mission Control panel
**Position**: Next to "Spawn Team" button

**Current:**
```html
<div class="mc-section mc-actions">
    <button id="mc-spawn-btn" class="mc-spawn-btn" onclick="spawnFromMC()" disabled>
        Spawn Team
    </button>
</div>
```

**Modified:**
```html
<div class="mc-section mc-actions">
    <button id="mc-preview-btn" class="mc-preview-btn" onclick="previewTeamImpact()" disabled>
        Preview Impact
    </button>
    <button id="mc-spawn-btn" class="mc-spawn-btn" onclick="spawnFromMC()" disabled>
        Spawn Team
    </button>
</div>
```

**Styling** (`IHIM/ui/static/style.css`):
```css
.mc-preview-btn {
    flex: 1;
    padding: 12px 24px;
    background: linear-gradient(135deg, #2a2a2a 0%, #1a1a1a 100%);
    border: 1px solid var(--accent-gold-30);
    border-radius: var(--radius-md);
    color: var(--accent-gold);
    cursor: pointer;
    font-weight: 500;
    transition: all 0.2s ease;
}

.mc-preview-btn:hover {
    background: linear-gradient(135deg, #333333 0%, #222222 100%);
    border-color: var(--accent-gold);
    box-shadow: 0 2px 8px var(--accent-gold-30);
}

.mc-preview-btn:disabled {
    opacity: 0.4;
    cursor: not-allowed;
}
```

### 2. Create Preview Modal

**Location**: `IHIM/ui/index.html` - Add before closing `</body>`

```html
<!-- Preview Impact Modal -->
<div id="preview-modal" class="modal" style="display: none;">
    <div class="modal-overlay" onclick="closePreviewModal()"></div>
    <div class="preview-modal-content">
        <div class="preview-modal-header">
            <h2>Preview - What Will Happen</h2>
            <button class="modal-close" onclick="closePreviewModal()">&times;</button>
        </div>

        <div class="preview-modal-body">
            <!-- Agents Section -->
            <div class="preview-section">
                <h3>🤖 Agents</h3>
                <div id="preview-agents" class="preview-detail">
                    <!-- Populated dynamically -->
                </div>
            </div>

            <!-- Permissions Section -->
            <div class="preview-section">
                <h3>🔒 Permissions</h3>
                <div id="preview-permissions" class="preview-detail">
                    <!-- Populated dynamically -->
                </div>
            </div>

            <!-- Files Section -->
            <div class="preview-section">
                <h3>📁 Files Accessed</h3>
                <div id="preview-files" class="preview-detail">
                    <!-- Populated dynamically -->
                </div>
            </div>

            <!-- Output Section -->
            <div class="preview-section">
                <h3>📤 Output</h3>
                <div id="preview-output" class="preview-detail">
                    <!-- Populated dynamically -->
                </div>
            </div>

            <!-- Time & Risks -->
            <div class="preview-meta">
                <div class="preview-time">
                    <span class="preview-meta-label">⏱️ Estimated Time:</span>
                    <span id="preview-time-value">--</span>
                </div>
                <div class="preview-risks">
                    <span class="preview-meta-label">⚠️ Risks:</span>
                    <span id="preview-risks-value">--</span>
                </div>
            </div>
        </div>

        <div class="preview-modal-footer">
            <button class="preview-btn-adjust" onclick="closePreviewModal()">
                Adjust Team
            </button>
            <button class="preview-btn-save" onclick="savePreviewScenario()">
                Save as Scenario
            </button>
            <button class="preview-btn-deploy" onclick="deployFromPreview()">
                Looks Good - Deploy
            </button>
        </div>
    </div>
</div>
```

**Styling** (`IHIM/ui/static/style.css`):
```css
/* Preview Modal */
.preview-modal-content {
    background: var(--bg-secondary);
    border: 1px solid var(--border-bright);
    border-radius: var(--radius-lg);
    max-width: 700px;
    max-height: 85vh;
    overflow-y: auto;
    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.6);
}

.preview-modal-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: var(--space-5);
    border-bottom: 1px solid var(--border-dim);
}

.preview-modal-header h2 {
    font-size: 1.2rem;
    color: var(--text-primary);
    font-weight: 500;
}

.preview-modal-body {
    padding: var(--space-5);
}

.preview-section {
    margin-bottom: var(--space-5);
}

.preview-section h3 {
    font-size: 0.9rem;
    color: var(--accent-gold);
    margin-bottom: var(--space-3);
    font-weight: 500;
}

.preview-detail {
    background: var(--bg-tertiary);
    border: 1px solid var(--border-dim);
    border-radius: var(--radius-md);
    padding: var(--space-4);
    color: var(--text-secondary);
    font-size: 0.9rem;
    line-height: 1.6;
}

.preview-detail ul {
    list-style: none;
    padding-left: var(--space-4);
}

.preview-detail li {
    margin-bottom: var(--space-2);
}

.preview-detail li::before {
    content: '•';
    color: var(--accent-red-50);
    font-weight: bold;
    margin-right: var(--space-2);
}

.preview-meta {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: var(--space-4);
    padding: var(--space-4);
    background: var(--bg-tertiary);
    border: 1px solid var(--border-dim);
    border-radius: var(--radius-md);
}

.preview-meta-label {
    color: var(--text-tertiary);
    font-size: 0.85rem;
    margin-right: var(--space-2);
}

.preview-modal-footer {
    display: flex;
    gap: var(--space-3);
    padding: var(--space-5);
    border-top: 1px solid var(--border-dim);
}

.preview-btn-adjust,
.preview-btn-save,
.preview-btn-deploy {
    flex: 1;
    padding: 12px 20px;
    border-radius: var(--radius-md);
    font-weight: 500;
    cursor: pointer;
    transition: all 0.2s ease;
}

.preview-btn-adjust {
    background: var(--bg-elevated);
    border: 1px solid var(--border-bright);
    color: var(--text-secondary);
}

.preview-btn-save {
    background: var(--bg-elevated);
    border: 1px solid var(--accent-gold-30);
    color: var(--accent-gold);
}

.preview-btn-deploy {
    background: linear-gradient(135deg, var(--accent-red) 0%, #b11030 100%);
    border: 1px solid var(--accent-red);
    color: white;
}

.preview-btn-deploy:hover {
    box-shadow: 0 4px 12px var(--accent-red-50);
    transform: translateY(-2px);
}
```

---

## Frontend JavaScript

**Location**: `IHIM/ui/index.html` - Add to existing `<script>` block

```javascript
// =====================
// Preview Impact System
// =====================

async function previewTeamImpact() {
    const taskInput = document.getElementById('mc-task-input');
    const task = taskInput.value.trim();

    if (!task) {
        showMCStatus('Please describe your task first', 'error');
        taskInput.focus();
        return;
    }

    if (!mcSelectedTemplate) {
        showMCStatus('Please select a team template', 'error');
        return;
    }

    try {
        showMCStatus('Generating preview...', 'info');

        // Call backend preview endpoint
        const res = await fetch(`${API}/api/teams/preview`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                template_id: mcSelectedTemplate.id,
                task: task
            })
        });

        if (!res.ok) {
            throw new Error(`Preview failed: ${res.statusText}`);
        }

        const preview = await res.json();

        // Clear status
        showMCStatus('', 'info');

        // Populate and show modal
        populatePreviewModal(preview);
        document.getElementById('preview-modal').style.display = 'flex';

    } catch (err) {
        console.error('Preview error:', err);
        showMCStatus(`Preview failed: ${err.message}`, 'error');
    }
}

function populatePreviewModal(preview) {
    // Agents
    const agentsHtml = `
        <ul>
            <li><strong>${preview.agent_count}</strong> ${preview.agent_tier} agents</li>
            <li>Model: ${preview.model_name}</li>
            <li>Execution: ${preview.execution_mode}</li>
        </ul>
    `;
    document.getElementById('preview-agents').innerHTML = agentsHtml;

    // Permissions
    const permissionsHtml = `
        <ul>
            ${preview.permissions.map(p => `<li>${p}</li>`).join('')}
        </ul>
    `;
    document.getElementById('preview-permissions').innerHTML = permissionsHtml;

    // Files
    const filesHtml = `
        <ul>
            ${preview.files_breakdown.map(f =>
                `<li>${f.count} ${f.type} files (${f.pattern})</li>`
            ).join('')}
        </ul>
        <div style="margin-top: 8px; color: var(--text-tertiary); font-size: 0.85rem;">
            Total: ${preview.total_files} files
        </div>
    `;
    document.getElementById('preview-files').innerHTML = filesHtml;

    // Output
    const outputHtml = `
        <ul>
            ${preview.outputs.map(o => `<li>${o}</li>`).join('')}
        </ul>
    `;
    document.getElementById('preview-output').innerHTML = outputHtml;

    // Time & Risks
    document.getElementById('preview-time-value').textContent = preview.estimated_time;
    document.getElementById('preview-risks-value').textContent = preview.risks;
    document.getElementById('preview-risks-value').style.color =
        preview.risks.toLowerCase().includes('none')
            ? 'var(--status-success)'
            : 'var(--status-warning)';

    // Store preview data for deployment
    window.currentPreview = preview;
}

function closePreviewModal() {
    document.getElementById('preview-modal').style.display = 'none';
}

function deployFromPreview() {
    // Close preview modal
    closePreviewModal();

    // Trigger actual spawn
    spawnFromMC();
}

function savePreviewScenario() {
    // TODO: Phase 3 feature - save to scenarios/*.json
    alert('Scenario saving coming in Phase 3!');
}

// Enable/disable preview button alongside spawn button
function onTemplateSelect() {
    const select = document.getElementById('mc-template-select');
    const templateId = select.value;

    if (!templateId) {
        mcSelectedTemplate = null;
        document.getElementById('mc-preview-section').style.display = 'none';
        document.getElementById('mc-spawn-btn').disabled = true;
        document.getElementById('mc-preview-btn').disabled = true;
        return;
    }

    // ... existing code ...

    // Enable both buttons
    document.getElementById('mc-spawn-btn').disabled = false;
    document.getElementById('mc-preview-btn').disabled = false;
}
```

---

## Backend API

### Endpoint: `POST /api/teams/preview`

**Location**: `IHIM/api/team_builder/routes.py` (create if doesn't exist)

**Request Body:**
```json
{
    "template_id": "red-team-recon",
    "task": "Audit iHIM for security issues"
}
```

**Response Body:**
```json
{
    "template_id": "red-team-recon",
    "template_name": "Red Team Recon",
    "task": "Audit iHIM for security issues",
    "agent_count": 10,
    "agent_tier": "the agent",
    "model_name": "claude-haiku-3.5",
    "execution_mode": "Parallel (10 concurrent)",
    "permissions": [
        "READ-ONLY (no file writes)",
        "No git operations",
        "No external API calls",
        "Blackboard write access (peer communication)"
    ],
    "files_breakdown": [
        { "type": "Python", "pattern": "IHIM/**/*.py", "count": 187 },
        { "type": "HTML", "pattern": "IHIM/**/*.html", "count": 34 },
        { "type": "JSON", "pattern": "IHIM/**/*.json", "count": 22 }
    ],
    "total_files": 243,
    "outputs": [
        "Findings → IHIM/team/blackboard.json",
        "Individual reports → IHIM/team/results/*-audit.json",
        "No code changes",
        "No git commits"
    ],
    "estimated_time": "3-5 minutes",
    "risks": "None (read-only operation)"
}
```

**Implementation:**

```python
# IHIM/api/team_builder/routes.py

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import json
import os
import glob

router = APIRouter(prefix="/api/teams", tags=["teams"])

class PreviewRequest(BaseModel):
    template_id: str
    task: str

class FileBreakdown(BaseModel):
    type: str
    pattern: str
    count: int

class PreviewResponse(BaseModel):
    template_id: str
    template_name: str
    task: str
    agent_count: int
    agent_tier: str
    model_name: str
    execution_mode: str
    permissions: list[str]
    files_breakdown: list[FileBreakdown]
    total_files: int
    outputs: list[str]
    estimated_time: str
    risks: str

@router.post("/preview", response_model=PreviewResponse)
async def preview_team(req: PreviewRequest):
    """Generate dry run preview for team spawn"""

    # Load template
    template_path = os.path.join("IHIM", "data", "team_templates.json")
    with open(template_path, "r") as f:
        data = json.load(f)
        templates = data.get("templates", [])

    template = next((t for t in templates if t["id"] == req.template_id), None)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    # Calculate file counts
    file_patterns = {
        "Python": "IHIM/**/*.py",
        "HTML": "IHIM/**/*.html",
        "JSON": "IHIM/**/*.json",
        "CSS": "IHIM/**/*.css",
        "JavaScript": "IHIM/**/*.js"
    }

    files_breakdown = []
    total_files = 0

    for file_type, pattern in file_patterns.items():
        files = glob.glob(pattern, recursive=True)
        count = len(files)
        if count > 0:
            files_breakdown.append(FileBreakdown(
                type=file_type,
                pattern=pattern,
                count=count
            ))
            total_files += count

    # Determine agent tier
    agent_count = template.get("agent_count", 1)
    agent_configs = template.get("agents", [])

    # Assume first agent's model defines tier
    first_agent = agent_configs[0] if agent_configs else {}
    model = first_agent.get("model", "claude-haiku-3.5")

    if "haiku" in model.lower():
        tier = "the agent"
        tier_name = "Scout"
        permissions = [
            "READ-ONLY (no file writes)",
            "No git operations",
            "No external API calls",
            "Blackboard write access (peer communication)"
        ]
        risks = "None (read-only operation)"
    elif "sonnet" in model.lower():
        tier = "the agent"
        tier_name = "Operator"
        permissions = [
            "READ and WRITE files",
            "Git operations (no push)",
            "Execute local commands",
            "Blackboard read/write access"
        ]
        risks = "Medium (can modify files locally)"
    else:  # the agent or unknown
        tier = "the agent"
        tier_name = "Architect"
        permissions = [
            "Full file system access",
            "Git operations (including push with approval)",
            "External API calls",
            "User communication"
        ]
        risks = "High (full system access)"

    # Estimate time (rough heuristic)
    time_per_agent = 30  # seconds
    if "parallel" in template.get("execution", "").lower():
        estimated_seconds = time_per_agent
    else:
        estimated_seconds = time_per_agent * agent_count

    if estimated_seconds < 60:
        estimated_time = f"{estimated_seconds} seconds"
    else:
        estimated_minutes = estimated_seconds // 60
        estimated_time = f"{estimated_minutes}-{estimated_minutes + 2} minutes"

    # Build outputs list
    outputs = [
        f"Findings → IHIM/team/blackboard.json",
        f"Individual reports → IHIM/team/results/*-audit.json"
    ]

    if tier == "the agent":
        outputs.extend([
            "No code changes",
            "No git commits"
        ])
    elif tier == "the agent":
        outputs.extend([
            "Possible code changes (check git status)",
            "No automatic commits"
        ])

    return PreviewResponse(
        template_id=req.template_id,
        template_name=template.get("name", "Unknown"),
        task=req.task,
        agent_count=agent_count,
        agent_tier=tier,
        model_name=model,
        execution_mode=f"Parallel ({agent_count} concurrent)" if "parallel" in template.get("execution", "").lower() else "Sequential",
        permissions=permissions,
        files_breakdown=files_breakdown,
        total_files=total_files,
        outputs=outputs,
        estimated_time=estimated_time,
        risks=risks
    )
```

**Register Router** (`IHIM/api/main.py`):

```python
# Add to imports
from api.team_builder.routes import router as team_builder_router

# Add to app
app.include_router(team_builder_router)
```

---

## File Structure

```
IHIM/
├── api/
│   ├── main.py                    # Register new router
│   └── team_builder/
│       ├── __init__.py
│       └── routes.py              # NEW: Preview endpoint
├── ui/
│   ├── index.html                 # Modified: Add preview button + modal
│   └── static/
│       └── style.css              # Modified: Add preview modal styles
└── data/
    └── team_templates.json        # Existing: Read by preview endpoint
```

---

## Testing Plan

### Manual Testing

1. **Happy Path:**
   - Open Mission Control
   - Enter task: "Audit iHIM for security"
   - Select template: "Red Team Recon"
   - Click "Preview Impact"
   - Verify modal shows:
     - 10 the agent agents
     - READ-ONLY permissions
     - File count (~243 files)
     - Output locations
     - Est. time: 3-5 min
     - Risks: None
   - Click "Looks Good - Deploy"
   - Verify team spawns correctly

2. **Edge Cases:**
   - Preview with empty task → Show error
   - Preview with no template selected → Show error
   - Preview with unknown template ID → Show 404 error
   - Preview with 0 files matching patterns → Show "0 files"

3. **UI/UX:**
   - Modal backdrop closes on click
   - "X" button closes modal
   - "Adjust Team" closes modal, returns to MC
   - "Deploy" closes modal and spawns
   - Modal is scrollable if content is long
   - Modal is responsive (mobile/tablet)

### Automated Testing

```python
# IHIM/tests/test_team_preview.py

import pytest
from fastapi.testclient import TestClient
from api.main import app

client = TestClient(app)

def test_preview_red_team():
    response = client.post("/api/teams/preview", json={
        "template_id": "red-team-recon",
        "task": "Audit iHIM"
    })
    assert response.status_code == 200
    data = response.json()
    assert data["agent_count"] == 10
    assert data["agent_tier"] == "the agent"
    assert "READ-ONLY" in data["permissions"][0]
    assert data["total_files"] > 0

def test_preview_unknown_template():
    response = client.post("/api/teams/preview", json={
        "template_id": "non-existent",
        "task": "Test"
    })
    assert response.status_code == 404

def test_preview_file_breakdown():
    response = client.post("/api/teams/preview", json={
        "template_id": "red-team-recon",
        "task": "Test"
    })
    data = response.json()
    assert len(data["files_breakdown"]) > 0
    assert data["files_breakdown"][0]["type"] in ["Python", "HTML", "JSON"]
```

---

## Success Criteria

- [ ] "Preview Impact" button appears next to "Spawn Team"
- [ ] Button is disabled until template is selected
- [ ] Clicking button opens preview modal
- [ ] Modal shows accurate file count (within 10% of actual)
- [ ] Modal shows correct tier (the agent/the agent/the agent)
- [ ] Modal shows correct permissions based on tier
- [ ] Modal shows estimated time
- [ ] Modal shows risks assessment
- [ ] "Deploy" button spawns team correctly
- [ ] "Adjust Team" returns to Mission Control
- [ ] Modal is keyboard accessible (Esc to close)
- [ ] Preview endpoint responds in <500ms

---

## Future Enhancements (Phase 2+)

### Phase 2: Enhanced Preview
- [ ] Show specific agent names (not just count)
- [ ] Preview agent prompts (what they'll be instructed to do)
- [ ] Show file access patterns (which directories each agent scans)
- [ ] Real-time file count (live glob, not cached)

### Phase 3: Scenario Management
- [ ] "Save as Scenario" saves to `team/scenarios/*.json`
- [ ] Scenario library (load saved configurations)
- [ ] Scenario comparison (side-by-side diff)
- [ ] Scenario versioning (track changes over time)

### Phase 4: Advanced Preview
- [ ] Dependency graph (agent A reads X, agent B uses A's output)
- [ ] Resource usage estimate (CPU, memory, API tokens)
- [ ] Historical data (past runs of this template took X minutes)
- [ ] Diff preview (compare two scenarios before deploying)

---

## Implementation Checklist

**Backend:**
- [ ] Create `IHIM/api/team_builder/routes.py`
- [ ] Implement `/api/teams/preview` endpoint
- [ ] Add file glob logic for accurate counts
- [ ] Add tier-based permission logic
- [ ] Add time estimation heuristics
- [ ] Register router in `main.py`
- [ ] Write unit tests

**Frontend:**
- [ ] Add "Preview Impact" button to Mission Control
- [ ] Create preview modal HTML structure
- [ ] Style preview modal (CSS)
- [ ] Implement `previewTeamImpact()` function
- [ ] Implement `populatePreviewModal()` function
- [ ] Wire up modal close handlers
- [ ] Wire up "Deploy" button
- [ ] Enable/disable preview button based on form state

**Testing:**
- [ ] Manual test: Happy path (preview → deploy)
- [ ] Manual test: Edge cases (empty task, no template)
- [ ] Manual test: UI responsiveness
- [ ] Automated test: Preview endpoint
- [ ] Automated test: File count accuracy
- [ ] Automated test: Permissions logic

**Documentation:**
- [ ] Update user guide (how to use preview)
- [ ] Add preview GIF/screenshot to README
- [ ] Document preview endpoint in API docs

---

## Estimated Effort

**Backend**: 4 hours
- Endpoint implementation: 2h
- File glob logic: 1h
- Testing: 1h

**Frontend**: 4 hours
- UI components: 2h
- JavaScript logic: 1h
- CSS styling: 1h

**Testing & Polish**: 2 hours
- Manual testing: 1h
- Bug fixes: 1h

**Total**: ~10 hours (1.5 days)

---

## Deployment Notes

**No Breaking Changes**: This feature is additive - existing Mission Control flow still works
**Feature Flag**: Could wrap in `if (window.PREVIEW_ENABLED)` for gradual rollout
**Rollback Plan**: Remove "Preview Impact" button, functionality degrades gracefully

**Backend Dependencies:**
- FastAPI (already installed)
- Pydantic (already installed)
- Python `glob` module (stdlib)

**Frontend Dependencies:**
- None (vanilla JavaScript)

**Database Changes**: None (stateless preview)

---

## Related Documents

- Main Analysis: `mission-control-competitive-analysis.md`
- Interaction Patterns: `mc-interaction-patterns.txt`
- Team Templates: `IHIM/data/team_templates.json`
- Mission Control UI: `IHIM/ui/index.html`
