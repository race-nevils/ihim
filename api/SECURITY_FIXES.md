# Security Fixes - Input Validation (2025-12-27)

## Summary
Fixed CRITICAL input validation vulnerabilities in `IHIM/api/main.py` blackboard routes and request models.

## Vulnerabilities Fixed

### 1. DoS via Unbounded String Fields
**Before:** No max_length constraints on string fields
**After:** All string fields have appropriate max_length constraints

| Field | Max Length | Rationale |
|-------|-----------|-----------|
| `agent` | 50 chars | Agent IDs are short identifiers |
| `message` | 5000 chars | Reasonable message size |
| `msg_type` | 50 chars | Message type identifiers |
| `status` | 50 chars | Status strings |
| `deliverable` | 500 chars | File paths/descriptions |
| `summary` | 2000 chars | Work summaries |
| `blocker` | 1000 chars | Blocker descriptions |
| `feature` | 500 chars | Feature descriptions |
| `prompt` | 5000 chars | Task prompts |
| `team_name` | 100 chars | Team names |
| `project` | 100 chars | Project names |

### 2. Untyped Agent Lists (Type Confusion)
**Before:** `agents: Optional[list] = None` (accepts ANY type)
**After:** `agents: List[str] = Field(..., min_items=1, max_items=20)`

- Enforces type safety (only strings)
- Prevents empty lists
- Caps at 20 agents to prevent resource exhaustion

### 3. Agent Name Injection Attacks
**Before:** No validation on agent names (path traversal, XSS, injection possible)
**After:** Regex validation enforced via pattern and @field_validator

**Pattern:** `^[a-zA-Z0-9_-]+$` (alphanumeric, dash, underscore only)

**Applied to:**
- `SpawnRequest.agents` (with custom validator)
- `BlackboardMessageRequest.agent`
- `BlackboardMessageRequest.to`
- `BlackboardStatusRequest.agent`
- `BlackboardDeliverableRequest.agent`
- `BlackboardDoneRequest.agent`
- `BlackboardBlockedRequest.agent`
- `BlackboardInitRequest.agents` (with custom validator)

**Custom validator** checks:
- Pattern match (prevents `../`, `<script>`, SQL injection)
- Max length per agent (50 chars)
- Raises ValueError with clear message on violation

### 4. Message Type Validation
**Before:** No constraints on `msg_type`
**After:** `pattern=r'^[A-Z_]+$'` (uppercase letters and underscores only)

Prevents injection while allowing standard types: DONE, QUESTION, DELIVERABLE, BLOCKER

### 5. Standardized Error Responses
**Before:** Inconsistent error formats across endpoints
**After:** Centralized error_response() helper function

**New error response structure:**
```json
{
  "success": false,
  "error": {
    "type": "ValidationError",
    "message": "Clear error description"
  }
}
```

**Error types defined:**
- `ValidationError` (422) - Invalid input data
- `ServiceUnavailable` (503) - Blackboard system not loaded
- `BlackboardNotInitialized` (400) - Blackboard not initialized
- `InternalError` (500) - Server-side errors

**Global exception handler** added for Pydantic ValidationError:
- Catches validation failures
- Returns standardized error response
- Prevents internal structure leakage

### 6. Added Validation to Other Models

**TaskCreate / TaskUpdate:**
- `text`: 1-500 chars
- `priority`: 1-20 chars, lowercase only (`^[a-z]+$`)
- `description`: max 2000 chars

**CustomSpawnRequest:**
- `team_type`: 1-50 chars, alphanumeric/dash/underscore (`^[a-zA-Z0-9_-]+$`)
- `team_size`: 1-20 (ge=1, le=20)

**ProcessFeedbackRequest:**
- `session_id`: 1-100 chars, alphanumeric/dash/underscore (`^[a-zA-Z0-9_-]+$`)

**NoteCreate / NoteUpdate:**
- `content`: 1-10000 chars
- `title`: max 200 chars

**StopwatchCreate / StopwatchUpdate:**
- `label`: max 100 chars

## Security Benefits

1. **DoS Prevention**: Cannot send gigabyte-sized strings to exhaust memory
2. **Injection Prevention**: Agent names cannot contain path traversal (`../`), XSS (`<script>`), or SQL injection
3. **Type Safety**: Lists are properly typed, preventing type confusion attacks
4. **Resource Limits**: Agent count capped at 20, preventing resource exhaustion
5. **Clear Error Messages**: Attackers cannot probe for internal structure
6. **Consistent Security**: All endpoints follow same validation patterns

## Testing Recommendations

**Valid requests should still work:**
```bash
curl -X POST http://localhost:7777/api/blackboard \
  -H "Content-Type: application/json" \
  -d '{"agent":"frontend-dev","message":"Test","msg_type":"STATUS"}'
```

**Invalid requests should be rejected:**
```bash
# Path traversal attempt
curl -X POST http://localhost:7777/api/blackboard \
  -H "Content-Type: application/json" \
  -d '{"agent":"../../etc/passwd","message":"Test"}'
# Expected: 422 ValidationError

# XSS attempt
curl -X POST http://localhost:7777/api/blackboard \
  -H "Content-Type: application/json" \
  -d '{"agent":"<script>alert(1)</script>","message":"Test"}'
# Expected: 422 ValidationError

# DoS attempt (huge message)
curl -X POST http://localhost:7777/api/blackboard \
  -H "Content-Type: application/json" \
  -d '{"agent":"test","message":"'$(python -c 'print("A"*10000)')'"}'
# Expected: 422 ValidationError

# Empty agent list
curl -X POST http://localhost:7777/api/blackboard/init \
  -H "Content-Type: application/json" \
  -d '{"feature":"Test","agents":[]}'
# Expected: 422 ValidationError

# Too many agents
curl -X POST http://localhost:7777/api/blackboard/init \
  -H "Content-Type: application/json" \
  -d '{"feature":"Test","agents":["a1","a2",...,"a25"]}'
# Expected: 422 ValidationError
```

## Files Modified

- `C:\Users\<user>\workspace\IHIM\api\main.py`
  - Lines 6-14: Added imports (re, List, field_validator, ValidationError, HTTPException, JSONResponse)
  - Lines 98-144: Added error_response() helper and global ValidationError handler
  - Lines 182-206: Updated SpawnRequest model with validation
  - Lines 209-256: Updated all Blackboard*Request models with validation
  - Lines 438-444: Updated CustomSpawnRequest with validation
  - Lines 549-552: Updated ProcessFeedbackRequest with validation
  - Lines 1229-1239: Updated TaskCreate/TaskUpdate with validation
  - Lines 683-1000: Updated all blackboard endpoints to use error_response()

## Impact Assessment

**Breaking Changes:** NONE (tightens validation but doesn't change API contract)

**Performance Impact:** Minimal (regex validation is fast, happens once per request)

**Backward Compatibility:** Maintained (valid requests still work identically)

## Next Steps (Recommended)

1. Add rate limiting middleware to prevent brute force attacks
2. Add request size limits at FastAPI level (currently relying on field-level limits)
3. Add CSRF protection if deploying with authentication
4. Add security headers (X-Content-Type-Options, X-Frame-Options, etc.)
5. Consider adding request ID logging for audit trail
