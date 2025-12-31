# Compliance Loader System

**Status:** Phase 1 Complete - Loader Operational
**Version:** 1.0.0
**Created:** 2025-12-29

---

## What Is This?

The Compliance Loader System enables AI agents to load and enforce regulatory compliance modules (HIPAA, SOC 2, GDPR, etc.) at runtime. It extends workspace's existing boot sequence with compliance-specific controls, evidence collection, and violation handling.

**Core Principle:** Compliance modules are guardrails with teeth - they don't just warn, they enforce AND prove it.

---

## Quick Start

### 1. Test the Loader

```bash
cd C:/Users/<user>/workspace/IHIM
python compliance/test_compliance_flow.py
```

### 2. Use in Code

```python
from compliance.loader import ComplianceLoader

# Initialize loader
loader = ComplianceLoader()

# Activate HIPAA compliance
loader.activate_module("hipaa-2024")

# Load active modules
active_modules = loader.load_active_modules()

# Enhance agent prompt with compliance context
base_prompt = "Build a patient management API"
enhanced_prompt = loader.enhance_prompt(base_prompt, active_modules)

# Result: enhanced_prompt includes HIPAA guardrails and instructions
```

### 3. Integrate with Spawner

```python
# In IHIM/team/spawner.py
from compliance.loader import ComplianceLoader

def spawn_agent_team(routed_prompts, feature_description=None):
    # ... existing setup ...

    # NEW: Add compliance enhancement
    compliance = ComplianceLoader()
    active_modules = compliance.load_active_modules()

    for agent, prompt in routed_prompts.items():
        # Apply optimizations (existing)
        optimized_prompt = apply_optimizations_to_prompt(agent, prompt)

        # NEW: Apply compliance
        compliance_enhanced = compliance.enhance_prompt(optimized_prompt, active_modules)

        # Build final prompt
        enhanced_prompt = f"""# Task for {agent}

{compliance_enhanced}

{BLACKBOARD_INSTRUCTIONS}
"""
        # ... rest of spawn logic ...
```

---

## File Structure

```
IHIM/
├── compliance/
│   ├── __init__.py                    # Module exports
│   ├── loader.py                      # Main loader (COMPLETE)
│   ├── test_compliance_flow.py        # Test suite (COMPLETE)
│   ├── INTEGRATION_EXAMPLE.md         # Integration guide (COMPLETE)
│   ├── README.md                      # This file
│   ├── modules/                       # Compliance module definitions
│   │   ├── hipaa-2024.json            # HIPAA compliance (COMPLETE)
│   │   └── soc2.json                  # SOC 2 compliance (COMPLETE)
│   ├── enforcer.py                    # Runtime hooks (TODO: Phase 2)
│   ├── evidence.py                    # Audit trail (TODO: Phase 2)
│   └── validator.py                   # Module validation (TODO: Phase 2)
├── data/
│   ├── compliance_state.json          # Active modules state (COMPLETE)
│   └── compliance_audit.jsonl         # Evidence trail (TODO: Phase 2)
└── COMPLIANCE_LOADER_DESIGN.md        # Full design doc (COMPLETE)
```

---

## Available Modules

### HIPAA (Healthcare)

**Module ID:** `hipaa-2024`
**Priority:** 100 (highest)
**Status:** Ready

**Controls:**
- Minimum Necessary Standard (BLOCK on SSN, MRN, diagnosis)
- Encryption Requirements (BLOCK on unencrypted PHI files)
- Access Logging (AUDIT all PHI access)

**Agent Instructions:**
> All Protected Health Information (PHI) must be redacted using [REDACTED-PHI] patterns. Never log, transmit, or store SSNs, MRNs, diagnoses, or other PHI in plain text. Always encrypt sensitive data at rest (AES-256) and in transit (TLS 1.3+).

**Activate:**
```python
loader.activate_module("hipaa-2024")
```

### SOC 2 (Security & Availability)

**Module ID:** `soc2`
**Priority:** 90
**Status:** Ready

**Controls:**
- Access Controls (BLOCK on hardcoded passwords, API keys)
- System Monitoring (AUDIT all config changes)
- Transmission Security (WARN on HTTP usage)
- Change Management (AUDIT all deployments)

**Agent Instructions:**
> All system changes must be auditable. Maintain comprehensive logs of security-relevant actions. Never hardcode credentials - use environment variables or secrets managers. Encrypt data in transit (HTTPS/TLS only) and at rest.

**Activate:**
```python
loader.activate_module("soc2")
```

---

## How It Works

### Boot Sequence Integration

```
1. CLAUDE.md loaded (base workspace configuration)
2. MEMORY.md + NOTES.md loaded (project context)
3. GUARDRAILS.md loaded (operational boundaries)
4. [NEW] Compliance modules loaded
   ├── Load compliance_state.json
   ├── Load active modules from compliance/modules/*.json
   ├── Validate modules (patterns compile, no duplicates)
   └── Merge controls by priority
5. Agent spawns with enhanced prompt (includes compliance context)
```

### Prompt Enhancement

**Before:**
```markdown
Build a patient management API with authentication and validation.
```

**After (with HIPAA active):**
```markdown
Build a patient management API with authentication and validation.

---

## COMPLIANCE CONTEXT

**NOTICE:** You are operating under HIPAA compliance.

**Additional Guardrails:**
- NEVER log, display, or transmit SSNs, MRNs, or PHI without redaction
- ALWAYS use encryption for PHI at rest (AES-256-GCM) and in transit (TLS 1.3+)
- REQUIRE explicit approval before accessing patient medical records

**Active Compliance Modules:** HIPAA (1.0.0)
**Enforcement Active:** Runtime hooks enabled for 1 module(s)
**CRITICAL:** Compliance violations will trigger immediate escalation.
```

### Multi-Module Layering

When multiple modules are active (e.g., HIPAA + SOC 2):

1. **Priority-based ordering:** HIPAA (100) applies before SOC 2 (90)
2. **Enforcement escalation:** Most restrictive level wins (BLOCK > REDACT > WARN > AUDIT)
3. **Evidence union:** Collect evidence for ALL active modules
4. **Instruction concatenation:** All agent_instructions included

Example:
```python
loader.activate_module("hipaa-2024")
loader.activate_module("soc2")

# Both modules' guardrails and instructions will be in the prompt
# If both have a file_write control, BLOCK level wins over AUDIT
```

---

## Test Results

**All tests passing:**

✅ Module discovery (found HIPAA, SOC 2)
✅ Module loading (2 modules loaded successfully)
✅ Module activation/deactivation
✅ Prompt enhancement (compliance context injected)
✅ Multi-module layering (5 controls found for file_write)
✅ Control resolution (BLOCK enforcement merged correctly)
✅ Health check (system healthy)

**Run tests:**
```bash
python compliance/test_compliance_flow.py
```

---

## Integration Status

### Phase 1 (COMPLETE)

✅ Compliance loader implemented
✅ Module format defined (JSON schema)
✅ Sample modules created (HIPAA, SOC 2)
✅ State management (activate/deactivate modules)
✅ Prompt enhancement logic
✅ Multi-module layering with priority
✅ Control resolution and enforcement merging
✅ Health check system
✅ Full test suite

### Phase 2 (TODO)

⬜ Runtime enforcement hooks (enforcer.py)
⬜ Evidence collection (evidence.py, compliance_audit.jsonl)
⬜ Violation logging and escalation
⬜ Module validation (validator.py)
⬜ API endpoints (in api/main.py)
⬜ Spawner integration (3-line change in spawner.py)
⬜ Hot-reload mechanism
⬜ iHIM UI dashboard for compliance monitoring

### Phase 3 (FUTURE)

⬜ Additional modules (GDPR, CCPA, LGPD)
⬜ Digital signatures for modules
⬜ ML-based PII detection (beyond regex)
⬜ Real-time compliance dashboard
⬜ Automated compliance reports (audit-ready PDFs)
⬜ Incident response automation

---

## API Endpoints (Planned)

```
GET  /api/compliance/modules                    # List all modules
GET  /api/compliance/modules/{module_id}        # Get module details
POST /api/compliance/modules/{module_id}/enable # Activate module
POST /api/compliance/modules/{module_id}/disable# Deactivate module
GET  /api/compliance/status                     # Health check
GET  /api/compliance/audit                      # Query audit trail
GET  /api/compliance/violations                 # List violations
POST /api/compliance/violations/{id}/approve    # Approve violation
POST /api/compliance/validate                   # Pre-validate content
```

---

## Architecture

### Data Flow

```
Agent Spawn
    ↓
Compliance Loader
    ├── Load active modules from compliance_state.json
    ├── Validate module integrity
    ├── Merge controls by priority
    └── Enhance agent prompt
    ↓
Enhanced Prompt (with compliance context)
    ↓
Agent Spawned
    ↓
[Phase 2] Runtime Hooks
    ├── file_write → Check controls → Redact/Block/Audit
    ├── api_call → Check controls → Validate/Log
    └── blackboard_post → Check controls → Redact PII
    ↓
[Phase 2] Evidence Collection
    └── Append to compliance_audit.jsonl
```

### Control Enforcement

When an agent performs an action (e.g., file_write):

1. **Lookup:** Get all controls with `file_write` trigger
2. **Apply rules:** Check content against each rule's pattern
3. **Enforce:** Based on enforcement_level
   - **BLOCK:** Prevent action, log violation, escalate
   - **REDACT:** Mask matches, allow action, log evidence
   - **WARN:** Allow action, log warning
   - **AUDIT:** Allow action, log for review
4. **Collect evidence:** Append to audit trail (JSONL)
5. **Escalate if needed:** Send violation to supervisor/human

---

## Design Decisions

### Why JSON modules?
- Human-readable and editable
- Easy to version control
- No code execution risks
- Can be validated against schema

### Why priority-based merging?
- Clear conflict resolution (HIPAA > SOC 2)
- Predictable enforcement behavior
- Easy to reason about

### Why append-only audit trail (JSONL)?
- Compliance requirement (immutable records)
- Tamper-evident (hash chaining)
- Easy to query and analyze
- No database overhead

### Why workspace boot sequence integration?
- Consistent with existing patterns (CLAUDE.md → MEMORY.md → GUARDRAILS.md)
- Natural extension point
- Agents get compliance context before first action
- No special case handling

---

## Next Steps

1. **Test standalone loader** (✅ DONE)
2. **Add API endpoints** to `api/main.py`
3. **Integrate with spawner** (3-line change in `team/spawner.py`)
4. **Build enforcer.py** (Phase 2 - runtime hooks)
5. **Build evidence.py** (Phase 2 - audit trail)
6. **Test with live agent spawn** (activate HIPAA, spawn backend-dev, verify prompt)

---

## Documentation

- **Design Doc:** `IHIM/data/COMPLIANCE_LOADER_DESIGN.md` (full architecture)
- **Integration Guide:** `IHIM/compliance/INTEGRATION_EXAMPLE.md` (how to use)
- **This README:** Quick start and overview

---

## Example Use Case

**Scenario:** Building a HIPAA-compliant patient portal

```python
from compliance.loader import ComplianceLoader
from team.spawner import spawn_agent_team
from team import route_prompt

# 1. Activate HIPAA compliance
loader = ComplianceLoader()
loader.activate_module("hipaa-2024")

# 2. Define task
task = "Build a patient portal with login, patient records, and appointment scheduling"

# 3. Route to agents
routed = route_prompt(task, project="PatientPortal")

# 4. Spawn agents (they'll get HIPAA context automatically)
result = spawn_agent_team(routed, feature_description="HIPAA-compliant patient portal")

# Result: All agents spawn with HIPAA guardrails and redaction rules
```

**Agent receives:**
- Base task prompt
- HIPAA instructions (redact SSN, MRN, diagnoses)
- HIPAA guardrails (encrypt PHI, log access, require approval)
- List of active modules and enforcement notice

**Agent behavior:**
- Won't hardcode SSNs or MRNs (BLOCK enforcement)
- Will use `[REDACTED-PHI]` patterns in logs
- Will flag unencrypted files containing PHI
- Will log all PHI access for audit trail

---

**Status:** Ready for Phase 2 (Enforcement Hooks) and API integration

**Contact:** workspace Compliance Team
**Version:** 1.0.0
**Last Updated:** 2025-12-29
