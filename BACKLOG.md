# iHIM Backlog

Updated: 2026-02-20 (medium+low sweep complete)

## How to Use

- Items discovered during 5 brain robustness sessions + 9-scout deep audit
- Check off when fixed, note the commit/branch
- Prioritized by severity within each section
- Source tags: `(S1-S5)` = session handoff, `(Scout N)` = audit scout

---

## Critical (affects correctness / data loss risk)

- [x] `get_recent_entries()` defined twice in `data/database.py` (~line 241 and ~403) — Python shadows first definition silently. Two signatures (days vs minutes) create confusion about which is actually called. (S4) — **Fixed: `critical-fixes`**
- [x] UNIQUE index on `source_filename` silently fails if production DB already has existing duplicates — need to audit and deduplicate before relying on constraint. Query: `SELECT source_filename, COUNT(*) FROM entries WHERE source_filename IS NOT NULL GROUP BY source_filename HAVING COUNT(*) > 1` (S1) — **Audited: no duplicates found. `critical-fixes`**
- [x] Resource leak: `EmbeddingAdapter` in `/api/brain/status` endpoint not closed after use (Scout 3) — **Fixed: `critical-fixes`**
- [x] Blocking async: `backfill_embeddings` has sync httpx calls inside async handler — blocks event loop (Scout 3) — **Fixed: `critical-fixes`**
- [x] `AsyncOllamaAdapter` singleton never closed — potential socket exhaustion over time (Scout 6) — **Fixed: lifespan shutdown in `main.py`. `critical-fixes`**
- [x] `OllamaAdapter.generate()` uses unsafe dict access `["response"]` — KeyError if Ollama returns unexpected shape (Scout 6) — **Fixed: `.get()` with warning log. `critical-fixes`**
- [x] Singleton lock in `workers/inbox_watcher/runner.py` has 3 race conditions around file-based locking (Scout 5) — **Fixed: atomic O_CREAT|O_EXCL + stale age check. `critical-fixes`**
- [x] File move (`os.rename`) in watcher has no error handling — fails silently on cross-filesystem moves (Scout 5) — **Fixed: try/except with shutil.move fallback. `critical-fixes`**
- [x] SQLite missing `PRAGMA busy_timeout` / WAL mode — "database is locked" under concurrent access (watcher + API + rebuild) (Scout 5) — **Fixed: both `get_connection()` and `_get_conn()`. `critical-fixes`**
- [ ] ~~Deferred~~ Watcher and rebuild can race on same inbox files — no coordination mechanism (Scout 5) — **rebuild.py:748 already defers inbox deletion; full protocol needs design**
- [x] Blocking Google API calls in async calendar endpoints — should use `run_in_executor` (Scout 4) — **Fixed: all 4 endpoints wrapped. `critical-fixes`**
- [x] `result.get("id")` in `brain.py` calendar push can return None — persists NULL `gcal_event_id` to DB, breaking future cleanup (Scout 1) — **Fixed: null-guard with warning log at all 3 return sites. `critical-fixes`**

## High (affects reliability / resource management)

- [ ] ~~Deferred~~ `EmbeddingAdapter` uses sync httpx — blocks event loop in all async endpoints that call embeddings (S4) — **Already mitigated by `run_in_executor` wrapping in `critical-fixes`. Full async adapter is a larger refactor.**
- [x] `store_embedding()` creates its own DB connection — can't participate in rebuild's EXCLUSIVE transaction (S2) — **Fixed: optional `conn` param, rebuild passes its connection. `high-tier-fixes`**
- [ ] ~~Deferred~~ Phase 3 reclassification in rebuild not transactional — file moves + DB updates lack rollback on partial failure (S2) — **Rebuild self-heals on next run. Proper atomic file+DB needs architectural work.**
- [x] Multi-event notes store only last `gcal_id` — earlier events in same note lose their calendar link (S3) — **Fixed: only first successful push writes gcal_event_id. `high-tier-fixes`**
- [x] `last_rebuild.json` is fragile — should be a DB table for atomicity and queryability (S4) — **Fixed: `rebuild_log` table in SQLite. Atomic writes, queryable history. `debugging`**
- [ ] ~~Deferred~~ Inbox safety: rebuild + watcher need coordination protocol to avoid processing same files (S2) — **Same as deferred Critical item. Needs design protocol. `rebuild.py:748` workaround holds.**
- [x] Silent failure in `/api/brain/status` drift check — returns "clean" when check actually threw an exception (Scout 3) — **Fixed: reports `status: "error"` + logs warning. `high-tier-fixes`**
- [x] `FileTracker` memory leak — `files` dict grows unbounded as files are added but never removed on processing (Scout 5) — **Fixed: cleanup handles missing files + periodic purge of dead entries. `high-tier-fixes`**
- [x] DB verification in watcher silently catches ALL exceptions including `OperationalError` (locked DB) (Scout 5) — **Fixed: OperationalError logged at WARNING. `high-tier-fixes`**
- [x] Duplicate `CATEGORIES` definition in `classify.py` (~line 204) shadows the import from `utils` (Scout 1) — **Fixed: removed local def, added to import. `critical-fixes`**
- [x] Sync `OllamaAdapter` blocks up to 120s on cold Ollama start — no async alternative (Scout 6) — **Fixed: health_check() gets own 5s timeout. generate() 120s is correct for LLM inference. `medium-low-sweep`**
- [ ] ~~Deferred~~ New `EmbeddingAdapter` connection created per call — connection pool thrashing (Scout 6) — **Not a leak — context managers close properly. Singleton pattern is optimization, not reliability fix.**
- [x] Rebuild calendar push not idempotent — crash between push and DB write creates duplicate GCal events (Scout 4) — **Fixed: per-entry commit after each push+DB-write. `high-tier-fixes`**
- [x] `sqlite-vec` missing from `requirements.txt` (Scout 9) — **Fixed: added `sqlite-vec>=0.1.6`. `high-tier-fixes`**
- [x] ~~3 incomplete terminal test files need deletion~~ (Scout 8) — **Already cleaned — files don't exist. Resolved.**

## Medium (affects maintainability / observability)

- [x] `_push_single_event` has two parallel code paths for all-day vs timed events — should be unified (S3) — **Fixed: unified start/end string building, single update/insert path. `medium-low-sweep`**
- [x] Silent search degradation: hybrid search drops to keyword-only when Ollama down, no log or indicator (S4) — **Fixed: `search_mode_actual` + `warnings` fields in response. `medium-low-sweep`**
- [x] Fuzzy title matching is weakest link for Obsidian reconciliation — fails when frontmatter not backfilled (S4) — **Fixed: SequenceMatcher ratio > 0.8 replaces substring match. `medium-low-sweep`**
- [x] Legacy entries have NULL `content_hash` — drift detection counts them as "unchecked" not "drifted" (S4) — **Fixed: excluded from drift query, reported as `unhashed` count. `medium-low-sweep`**
- [x] `_move_to_failed` uses `os.rename` — same-filesystem only, fails on cross-mount moves (S5) — **Fixed: shutil.move fallback. `critical-fixes`**
- [x] Recovery timestamp prefix strip is position-dependent (char 16) — breaks if format changes from `YYYYMMDD-HHMMSS_` (S5) — **Fixed: regex `r'^\d{8}-\d{6}_(.*)$'` with fallback. `medium-low-sweep`**
- [x] Watcher hashes file WITH frontmatter, DB `content_hash` is from stripped content — values will never match (S4) — **Fixed: `_get_content_hash()` now uses `read_file_content()` to strip frontmatter. `medium-low-sweep`**
- [x] No `response_model` declarations on any brain API endpoint — responses unvalidated (Scout 3) — **Fixed: Pydantic models for all 7 endpoints. `medium-low-sweep`**
- [x] No RFC 9457 `problem()` usage in brain endpoints — inconsistent error format (Scout 3) — **Fixed: HTTPException → `problem()` in search + get_entry. `medium-low-sweep`**
- [x] Missing shutdown handler in `main.py` — no graceful cleanup on SIGTERM (Scout 7) — **Fixed: lifespan asynccontextmanager with shutdown. `critical-fixes`**
- [x] ~~Already OK~~ Unhandled exceptions not logged by catch-all middleware before returning 500 (Scout 7) — **Already implemented: `unhandled_exception_handler` in `api/errors.py`**
- [x] CSP WebSocket directive hardcoded to port 7777 — breaks on test ports (Scout 7) — **Fixed: reads `IHIM_PORT` env var. `medium-low-sweep`**
- [x] Confusing `needs_auth` logic in `token_health()` — double-negative makes intent unclear (Scout 4) — **Fixed: simplified to `not creds.valid and not has_refresh`. `medium-low-sweep`**
- [x] `health_check()` in Ollama adapter uses 120s timeout — should be <5s for health probes (Scout 6) — **Fixed: own `timeout` param defaulting to 5s. `medium-low-sweep`**
- [x] No retry logic for failed Ollama API calls — single failure = complete loss (Scout 6) — **Fixed: 3-attempt retry on TimeoutException/ConnectError with 1s/2s backoff. `medium-low-sweep`**
- [x] Calendar fields update after `store_new` can fail silently — entry saved but cal fields missing (Scout 1) — **Fixed: escalated to `logger.error` with note_id. `medium-low-sweep`**
- [x] `old_title` fallback uses "Ideas" category instead of "untitled" — misleading default (Scout 1) — **Fixed: `"Ideas"` → `"Misc"` at 4 sites in rebuild.py. `medium-low-sweep`**
- [x] No JSON error handling in `read_jsonld()` — corrupt file crashes caller (Scout 2) — **Fixed: try/except JSONDecodeError, returns None, logs warning. `medium-low-sweep`**
- [x] O(n²) dedup logic in hybrid search — linear scan for each result (Scout 3) — **Fixed: `seen[eid] = (entry, idx)` for O(1) index lookup. `medium-low-sweep`**
- [ ] ~~Deferred~~ Sanity check doesn't validate DB schema or brain directory structure (Scout 9) — **Medium effort, separate concern. Doesn't affect runtime.**
- [ ] ~~Deferred~~ S1 handoff server tests reference non-existent `/api/brain` POST endpoint — actual flow is inbox-based (validation finding)
- [ ] ~~Deferred~~ S3 live tests can't detect running server — health check path mismatch (validation finding)
- [ ] ~~Deferred~~ `drift_sample` in `/api/brain/status` is non-deterministic — random sampling gives different results per call (validation finding) — **By design (random sampling). Could seed but value unclear.**

## Low (cleanup / improvement / nice-to-have)

- [x] Dead code: `yaml_escape()` in `utils.py` never called anywhere (Scout 1) — **Fixed: deleted. `medium-low-sweep`**
- [x] Chrome extension wildcard in CORS config — overly permissive (Scout 7) — **Fixed: removed `chrome-extension://*`. `medium-low-sweep`**
- [x] No static dir existence check before `StaticFiles` mount — fails if dir missing (Scout 7) — **Fixed: `if _static_dir.exists():` guard with warning log. `medium-low-sweep`**
- [x] Root handler reads file synchronously on every request (Scout 7) — **Fixed: `_INDEX_HTML` cached at module load. `medium-low-sweep`**
- [ ] ~~Deferred~~ Hardcoded "primary" calendar ID — no secondary calendar support (Scout 4) — **No secondary calendar in use. Future feature.**
- [x] Timezone defaults to `America/Chicago` if `IHIM_TIMEZONE` not set — should warn (Scout 4) — **Fixed: `logger.warning()` in both sync.py and dateparse.py. `medium-low-sweep`**
- [ ] ~~Deferred~~ Watcher poll interval has no adaptive backoff when inbox is consistently empty (Scout 5) — **Design needed. Current 2s poll is fine for single user.**
- [x] Exclude folders list is case-sensitive on Windows — may miss `.git` vs `.Git` (Scout 5) — **Fixed: case-insensitive comparison. `medium-low-sweep`**
- [x] Ollama model names hardcoded in watcher warm-up — not configurable (Scout 5) — **Fixed: reads from `OllamaAdapter.FAST_MODEL` and `EMBED_MODEL`. `medium-low-sweep`**
- [ ] ~~Deferred~~ Processor result validation missing in `runner.py` — trusts processor output blindly (Scout 5) — **Needs Pydantic model design for processor output. Separate task.**
- [x] ~~Already OK~~ Heartbeat file write not truly atomic on Windows — `os.replace` may fail (Scout 5) — **Already uses `os.replace()` (atomic on all platforms)**
- [ ] ~~Deferred~~ Loose version constraints in `requirements.txt` — `>=` without upper bounds (Scout 9) — **Intentional flexibility for dev environment.**
- [x] Empty `scripts/` directory — remove or populate (Scout 9) — **Fixed: deleted. `medium-low-sweep`**
- [ ] ~~Deferred~~ 3 TODO comments in `team/` code — resolve or convert to backlog items (Scout 9) — **Feature work (agent selection, file locking), not bugs.**
- [ ] ~~Deferred~~ No `.env` file committed (only `.env.example`) — expected but undocumented (Scout 9) — **Not a code fix.**

---

## Resolved

### `critical-fixes` branch (2026-02-20)

| # | Item | Fix |
|---|------|-----|
| 1 | Dead `get_recent_entries(days)` shadowing live definition | Deleted days-based definition |
| 2 | Unsafe `["response"]` in OllamaAdapter.generate | `.get()` + warning log |
| 3 | Duplicate CATEGORIES in classify.py | Removed local, added to import |
| 4 | Null gcal_event_id persisted to DB | Null-guard with warning at all 3 return sites |
| 5 | EmbeddingAdapter leak in /status | Wrapped in `with` context manager |
| 6 | File move error handling in watcher | try/except + shutil.move fallback |
| 7 | SQLite missing WAL + busy_timeout | Added PRAGMAs to both connection functions |
| 8 | Duplicate source_filename audit | No duplicates found — UNIQUE constraint safe |
| 9 | AsyncOllamaAdapter never closed | Lifespan shutdown handler in main.py |
| 10 | Blocking backfill_embeddings | `run_in_executor` for sync embedding calls |
| 11 | Blocking Google API in calendar endpoints | `run_in_executor` on all 4 endpoints |
| 12 | Singleton lock race conditions | Atomic O_CREAT\|O_EXCL + 24h stale age check |
| — | `_move_to_failed` cross-filesystem (Medium) | Fixed alongside #6 |
| — | Missing shutdown handler (Medium) | Fixed alongside #9 |
| — | Duplicate CATEGORIES (High) | Fixed alongside #3 |

### `high-tier-fixes` on main (2026-02-20)

| # | Item | Fix |
|---|------|-----|
| 1 | `store_embedding()` creates own DB connection | Optional `conn` param; rebuild passes existing conn |
| 2 | Rebuild calendar push not idempotent | Per-entry commit after each push+DB-write |
| 3 | Drift check lumps errors with real drift | Categorized: `missing`, `hash_mismatch`, `errors` |
| 4 | `/status` drift sample masks errors as "clean" | Reports `status: "error"` + logs warning |
| 5 | Multi-event notes overwrite gcal_id | Only first successful push writes to DB |
| 6 | FileTracker memory leak (deleted files stay in dict) | Cleanup handles missing files + periodic purge |
| 7 | DB verification swallows OperationalError silently | OperationalError logged at WARNING level |
| 8 | `sqlite-vec` missing from requirements.txt | Added `sqlite-vec>=0.1.6` |
| 9 | Terminal test files need deletion | Already cleaned — files don't exist |

**Deferred (4):**
- EmbeddingAdapter sync httpx — already mitigated by `run_in_executor`
- Phase 3 reclassification not transactional — rebuild self-heals
- Inbox safety: rebuild + watcher coordination — needs design protocol
- EmbeddingAdapter per-instance creation — not a leak, context managers close

### `medium-low-sweep` on main (2026-02-20)

| # | Tier | Item | Fix |
|---|------|------|-----|
| 1 | H | OllamaAdapter 120s cold-start blocking | `health_check()` gets 5s timeout; generate 120s is correct for LLM inference |
| 2 | M | `_push_single_event` duplicate code paths | Unified start/end building, single update/insert path |
| 3 | M | Silent search degradation | `search_mode_actual` + `warnings` fields in response |
| 4 | M | Fuzzy title matching too permissive | SequenceMatcher ratio > 0.8 replaces substring |
| 5 | M | NULL `content_hash` drift false positives | Excluded from query, reported as `unhashed` count |
| 6 | M | Recovery timestamp strip position-dependent | Regex `r'^\d{8}-\d{6}_(.*)$'` |
| 7 | M | Watcher content hash includes frontmatter | `_get_content_hash()` uses `read_file_content()` |
| 8 | M | No `response_model` on brain endpoints | Pydantic models for all 7 endpoints |
| 9 | M | No `problem()` in brain endpoints | HTTPException → `problem()` |
| 10 | M | CSP WebSocket hardcoded to 7777 | Reads `IHIM_PORT` env var |
| 11 | M | `needs_auth` double-negative logic | Simplified to `not creds.valid and not has_refresh` |
| 12 | M | Ollama health_check 120s timeout | Own `timeout` param defaulting to 5s |
| 13 | M | No Ollama retry logic | 3-attempt retry on transient errors (1s/2s backoff) |
| 14 | M | Calendar fields fail silently | Escalated to `logger.error` with note_id |
| 15 | M | Category fallback "Ideas" misleading | Changed to "Misc" at 4 sites in rebuild.py |
| 16 | M | `read_jsonld()` crashes on corrupt JSON | try/except JSONDecodeError, returns None |
| 17 | M | O(n²) hybrid search dedup | `seen[eid] = (entry, idx)` for O(1) lookup |
| 18 | L | Dead `yaml_escape()` | Deleted |
| 19 | L | Chrome extension CORS wildcard | Removed |
| 20 | L | StaticFiles no existence check | Guarded with `if exists():` |
| 21 | L | Root handler sync I/O per request | `_INDEX_HTML` cached at module load |
| 22 | L | Timezone default no warning | `logger.warning()` in sync.py + dateparse.py |
| 23 | L | Exclude folders case-sensitive | Case-insensitive comparison |
| 24 | L | Ollama model names hardcoded in warm-up | Reads from adapter constants |
| 25 | L | Empty `scripts/` directory | Deleted |

**Already resolved (2):**
- Unhandled exception middleware — properly implemented in `api/errors.py`
- Heartbeat atomicity — already uses `os.replace()`

**Deferred (11):**
- `last_rebuild.json` → DB table — architectural change
- Sanity check DB schema validation — medium effort, separate concern
- S1 handoff tests wrong endpoint — documentation finding
- S3 live tests health check mismatch — documentation finding
- `drift_sample` non-deterministic — by design (random sampling)
- Processor result validation — needs Pydantic model design
- Hardcoded "primary" calendar ID — no secondary calendar in use
- Watcher adaptive backoff — design needed, 2s poll is fine
- Loose version constraints — intentional for dev
- 3 TODO comments in team/ — feature work, not bugs
- No .env documented — not a code fix
