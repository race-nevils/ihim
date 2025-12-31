# Compliance Loader Integration Example

This document shows how the Compliance Loader integrates with workspace's existing spawner system.

---

## Integration with spawner.py

### Before (Current State)

```python
# IHIM/team/spawner.py
def spawn_agent_team(routed_prompts, feature_description=None):
    # ... setup code ...

    for agent, prompt in routed_prompts.items():
        # Apply optimizations from feedback history
        optimized_prompt = apply_optimizations_to_prompt(agent, prompt)

        # Add session ID, blackboard info, and coordination instructions
        enhanced_prompt = f"""# Task for {agent}

## Session Info
- Session ID: {session_id}
- Blackboard: C:/Users/<user>/workspace/IHIM/team/blackboard.json
- Results output: C:/Users/<user>/workspace/IHIM/team/results/{agent}-result.json

---

{optimized_prompt}

---

{BLACKBOARD_INSTRUCTIONS}
"""

        task_file = write_task_file(agent, enhanced_prompt)
        # ... spawn logic ...
```

### After (With Compliance Integration)

```python
# IHIM/team/spawner.py
from compliance.loader import ComplianceLoader

def spawn_agent_team(routed_prompts, feature_description=None):
    # ... setup code ...

    # NEW: Initialize compliance loader
    compliance = ComplianceLoader()
    active_modules = compliance.load_active_modules()

    for agent, prompt in routed_prompts.items():
        # Apply optimizations from feedback history
        optimized_prompt = apply_optimizations_to_prompt(agent, prompt)

        # NEW: Apply compliance enhancement
        compliance_enhanced = compliance.enhance_prompt(optimized_prompt, active_modules)

        # Add session ID, blackboard info, and coordination instructions
        enhanced_prompt = f"""# Task for {agent}

## Session Info
- Session ID: {session_id}
- Blackboard: C:/Users/<user>/workspace/IHIM/team/blackboard.json
- Results output: C:/Users/<user>/workspace/IHIM/team/results/{agent}-result.json

---

{compliance_enhanced}

---

{BLACKBOARD_INSTRUCTIONS}
"""

        task_file = write_task_file(agent, enhanced_prompt)
        # ... spawn logic ...
```

### Key Changes

1. **Import compliance loader at top of file:**
   ```python
   from compliance.loader import ComplianceLoader
   ```

2. **Initialize loader before agent loop:**
   ```python
   compliance = ComplianceLoader()
   active_modules = compliance.load_active_modules()
   ```

3. **Enhance prompt with compliance context:**
   ```python
   compliance_enhanced = compliance.enhance_prompt(optimized_prompt, active_modules)
   ```

---

## Example: Agent Prompt Before vs After

### Before Compliance (Original)

```markdown
# Task for backend-dev

## Session Info
- Session ID: spawn-20251229-143210-a1b2c3d4
- Blackboard: C:/Users/<user>/workspace/IHIM/team/blackboard.json
- Results output: C:/Users/<user>/workspace/IHIM/team/results/backend-dev-result.json

---

Build a user management API with the following endpoints:
- POST /api/users (create user)
- GET /api/users/:id (get user)
- PUT /api/users/:id (update user)
- DELETE /api/users/:id (delete user)

Include proper authentication and validation.

---

[Blackboard instructions...]
```

### After Compliance (With HIPAA + SOC 2 Active)

```markdown
# Task for backend-dev

## Session Info
- Session ID: spawn-20251229-143210-a1b2c3d4
- Blackboard: C:/Users/<user>/workspace/IHIM/team/blackboard.json
- Results output: C:/Users/<user>/workspace/IHIM/team/results/backend-dev-result.json

---

Build a user management API with the following endpoints:
- POST /api/users (create user)
- GET /api/users/:id (get user)
- PUT /api/users/:id (update user)
- DELETE /api/users/:id (delete user)

Include proper authentication and validation.

---

## COMPLIANCE CONTEXT

**NOTICE:** You are operating under the following regulatory compliance frameworks:

### HIPAA (Health Insurance Portability and Accountability Act)
You are operating under HIPAA compliance. All Protected Health Information (PHI) must be redacted using [REDACTED-PHI] patterns. Never log, transmit, or store SSNs, MRNs, diagnoses, or other PHI in plain text. Always encrypt sensitive data at rest (AES-256) and in transit (TLS 1.3+).

**Additional Guardrails:**
- NEVER log, display, or transmit SSNs, MRNs, or PHI without redaction
- ALWAYS use encryption for PHI at rest (AES-256-GCM minimum) and in transit (TLS 1.3+)
- REQUIRE explicit approval before accessing patient medical records
- LOG all access to PHI-containing files and databases
- REPORT any suspected PHI breach immediately to compliance officer

### SOC 2 Type II (Security & Availability)
You are operating under SOC 2 Type II compliance. All system changes must be auditable. Maintain comprehensive logs of security-relevant actions. Never hardcode credentials - use environment variables or secrets managers. Encrypt data in transit (HTTPS/TLS only) and at rest.

**Additional Guardrails:**
- LOG all authentication attempts and authorization decisions
- ENCRYPT all API keys, passwords, and credentials using workspace secrets manager or environment variables
- VALIDATE all inputs before processing (SQL injection, XSS, command injection prevention)
- USE HTTPS for all external API calls (never plain HTTP)
- DOCUMENT all system changes with change tickets or commit messages
- MONITOR for abnormal access patterns or security events

**Active Compliance Modules:** HIPAA (Health Insurance Portability and Accountability Act) (1.0.0), SOC 2 Type II (Security & Availability) (1.0.0)
**Enforcement Active:** Runtime hooks enabled for 2 module(s)

**CRITICAL:** Compliance violations will trigger immediate escalation. When in doubt, ask for approval.

---

[Blackboard instructions...]
```

---

## Boot Sequence Flow

### workspace Boot Sequence (Extended)

```
Agent Spawn Request
    ↓
1. CLAUDE.md loaded (base workspace configuration)
    ↓
2. MEMORY.md + NOTES.md loaded (project context)
    ↓
3. GUARDRAILS.md loaded (operational boundaries)
    ↓
4. [NEW] Compliance modules loaded (regulatory controls)
   - Load compliance_state.json
   - Load active modules from compliance/modules/*.json
   - Validate modules (schema, patterns, dependencies)
   - Merge controls by priority
    ↓
5. Route prompt to agents (existing logic)
    ↓
6. [NEW] Enhance prompts with compliance context
   - Inject agent_instructions
   - Append guardrail_additions
   - Add active modules summary
    ↓
7. Spawn agents in Windows Terminal tabs (existing logic)
    ↓
8. [NEW] Start enforcement session
   - Initialize runtime hooks
   - Start evidence collection
   - Monitor for violations
    ↓
Agent running with full compliance awareness
```

---

## API Integration

### New Compliance Endpoints

Add to `IHIM/api/main.py`:

```python
from compliance.loader import ComplianceLoader

compliance_loader = ComplianceLoader()

@app.get("/api/compliance/modules")
async def list_compliance_modules():
    """List all available compliance modules."""
    compliance_loader.load_all_modules()
    modules = compliance_loader._available_modules

    return {
        "modules": [
            {
                "module_id": m.module_id,
                "name": m.name,
                "version": m.version,
                "category": m.category,
                "enabled": m.enabled,
                "priority": m.priority,
                "controls_count": len(m.controls)
            }
            for m in modules.values()
        ]
    }

@app.get("/api/compliance/modules/{module_id}")
async def get_compliance_module(module_id: str):
    """Get details of a specific compliance module."""
    compliance_loader.load_all_modules()

    if module_id not in compliance_loader._available_modules:
        return {"error": f"Module {module_id} not found"}

    module = compliance_loader._available_modules[module_id]

    return {
        "module_id": module.module_id,
        "name": module.name,
        "version": module.version,
        "category": module.category,
        "enabled": module.enabled,
        "priority": module.priority,
        "controls": [
            {
                "control_id": c.control_id,
                "name": c.name,
                "description": c.description,
                "enforcement_level": c.enforcement_level.value,
                "triggers": c.triggers,
                "rules_count": len(c.rules)
            }
            for c in module.controls
        ],
        "agent_instructions": module.agent_instructions,
        "guardrail_additions": module.guardrail_additions,
        "metadata": module.metadata
    }

@app.post("/api/compliance/modules/{module_id}/enable")
async def enable_compliance_module(module_id: str):
    """Activate a compliance module."""
    success = compliance_loader.activate_module(module_id)

    if success:
        return {
            "success": True,
            "message": f"Module {module_id} activated",
            "module_id": module_id
        }
    else:
        return {
            "success": False,
            "error": f"Failed to activate module {module_id}"
        }

@app.post("/api/compliance/modules/{module_id}/disable")
async def disable_compliance_module(module_id: str):
    """Deactivate a compliance module."""
    success = compliance_loader.deactivate_module(module_id)

    if success:
        return {
            "success": True,
            "message": f"Module {module_id} deactivated",
            "module_id": module_id
        }
    else:
        return {
            "success": False,
            "error": f"Failed to deactivate module {module_id}"
        }

@app.get("/api/compliance/status")
async def compliance_status():
    """Get compliance system status."""
    health = compliance_loader.health_check()
    active = compliance_loader.load_active_modules()

    return {
        "healthy": health["healthy"],
        "active_modules": [
            {
                "module_id": m.module_id,
                "name": m.name,
                "priority": m.priority
            }
            for m in active
        ],
        "active_count": len(active),
        "errors": health.get("errors", []),
        "warnings": health.get("warnings", [])
    }
```

---

## Usage Examples

### Enable HIPAA Compliance

```bash
# Via API
curl -X POST http://localhost:7777/api/compliance/modules/hipaa-2024/enable

# Via Python (in spawner or script)
from compliance.loader import ComplianceLoader

loader = ComplianceLoader()
loader.activate_module("hipaa-2024")
```

### Enable Multiple Modules (HIPAA + SOC 2)

```python
loader = ComplianceLoader()
loader.activate_module("hipaa-2024")
loader.activate_module("soc2")

# Spawn agents - they'll get both compliance contexts
spawn_agent_team(routed_prompts, feature_description="Build HIPAA-compliant patient portal")
```

### Check Active Compliance

```bash
curl http://localhost:7777/api/compliance/status

# Response:
{
  "healthy": true,
  "active_modules": [
    {
      "module_id": "hipaa-2024",
      "name": "HIPAA (Health Insurance Portability and Accountability Act)",
      "priority": 100
    },
    {
      "module_id": "soc2",
      "name": "SOC 2 Type II (Security & Availability)",
      "priority": 90
    }
  ],
  "active_count": 2,
  "errors": [],
  "warnings": []
}
```

---

## Testing the Integration

### Test 1: Spawn Agent Without Compliance

```python
# No modules active
loader = ComplianceLoader()
active = loader.load_active_modules()  # Returns []

prompt = "Build a user API"
enhanced = loader.enhance_prompt(prompt, active)

# Result: enhanced == prompt (no changes)
```

### Test 2: Spawn Agent With HIPAA

```python
# Activate HIPAA
loader = ComplianceLoader()
loader.activate_module("hipaa-2024")
active = loader.load_active_modules()

prompt = "Build a patient management API"
enhanced = loader.enhance_prompt(prompt, active)

# Result: enhanced includes HIPAA context, guardrails, and instructions
assert "HIPAA" in enhanced
assert "[REDACTED-PHI]" in enhanced
assert "COMPLIANCE CONTEXT" in enhanced
```

### Test 3: Multi-Module Priority Resolution

```python
# Activate both (HIPAA priority 100, SOC2 priority 90)
loader = ComplianceLoader()
loader.activate_module("hipaa-2024")
loader.activate_module("soc2")

# Get controls for file_write trigger
controls = loader.get_controls_for_trigger("file_write")

# Verify HIPAA controls come first (higher priority)
assert controls[0][0].module_id == "hipaa-2024"
assert controls[0][0].priority == 100
```

---

## File Structure (After Integration)

```
workspace/
├── IHIM/
│   ├── compliance/
│   │   ├── __init__.py
│   │   ├── loader.py              # ✅ Created
│   │   ├── enforcer.py            # TODO: Phase 2
│   │   ├── evidence.py            # TODO: Phase 2
│   │   ├── validator.py           # TODO: Phase 2
│   │   ├── modules/
│   │   │   ├── hipaa-2024.json    # ✅ Created
│   │   │   ├── soc2.json          # ✅ Created
│   │   │   └── schema.json        # TODO
│   │   └── INTEGRATION_EXAMPLE.md # ✅ This file
│   ├── data/
│   │   ├── compliance_state.json  # ✅ Created
│   │   └── compliance_audit.jsonl # TODO: Created on first enforcement
│   ├── team/
│   │   └── spawner.py             # TODO: Add 3 lines of code
│   └── api/
│       └── main.py                # TODO: Add compliance endpoints
└── COMPLIANCE_LOADER_DESIGN.md   # ✅ Created
```

---

## Next Steps

1. **Test the loader standalone:**
   ```bash
   cd C:/Users/<user>/workspace/IHIM
   python -m compliance.loader
   ```

2. **Add API endpoints to main.py** (copy from above)

3. **Integrate with spawner.py** (3-line change)

4. **Spawn test agent with HIPAA active:**
   ```bash
   # Enable HIPAA via API
   curl -X POST http://localhost:7777/api/compliance/modules/hipaa-2024/enable

   # Spawn agent via Team Builder
   # Check task file - should include HIPAA context
   ```

5. **Build Phase 2 (Enforcement Hooks):**
   - `enforcer.py` - Runtime hooks for file_write, api_call, etc.
   - `evidence.py` - JSONL audit trail writer
   - `validator.py` - Module integrity checker

---

**Integration Status:** Design complete, loader implemented, ready for spawner integration
