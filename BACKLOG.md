# iHIM Backlog

Updated: 2026-02-20

## How to Use

- Items discovered during 5 brain robustness sessions + 9-scout deep audit
- Check off when fixed, note the commit/branch
- Prioritized by severity within each section
- Source tags: `(S1-S5)` = session handoff, `(Scout N)` = audit scout

---

## Critical (affects correctness / data loss risk)

- [ ] `get_recent_entries()` defined twice in `data/database.py` (~line 241 and ~403) — Python shadows first definition silently. Two signatures (days vs minutes) create confusion about which is actually called. (S4)
- [ ] UNIQUE index on `source_filename` silently fails if production DB already has existing duplicates — need to audit and deduplicate before relying on constraint. Query: `SELECT source_filename, COUNT(*) FROM entries WHERE source_filename IS NOT NULL GROUP BY source_filename HAVING COUNT(*) > 1` (S1)
- [ ] Resource leak: `EmbeddingAdapter` in `/api/brain/status` endpoint not closed after use (Scout 3)
- [ ] Blocking async: `backfill_embeddings` has sync httpx calls inside async handler — blocks event loop (Scout 3)
- [ ] `AsyncOllamaAdapter` singleton never closed — potential socket exhaustion over time (Scout 6)
- [ ] `OllamaAdapter.generate()` uses unsafe dict access `["response"]` — KeyError if Ollama returns unexpected shape (Scout 6)
- [ ] Singleton lock in `workers/inbox_watcher/runner.py` has 3 race conditions around file-based locking (Scout 5)
- [ ] File move (`os.rename`) in watcher has no error handling — fails silently on cross-filesystem moves (Scout 5)
- [ ] SQLite missing `PRAGMA busy_timeout` / WAL mode — "database is locked" under concurrent access (watcher + API + rebuild) (Scout 5)
- [ ] Watcher and rebuild can race on same inbox files — no coordination mechanism (Scout 5)
- [ ] Blocking Google API calls in async calendar endpoints — should use `run_in_executor` (Scout 4)
- [ ] `result.get("id")` in `brain.py` calendar push can return None — persists NULL `gcal_event_id` to DB, breaking future cleanup (Scout 1)

## High (affects reliability / resource management)

- [ ] `EmbeddingAdapter` uses sync httpx — blocks event loop in all async endpoints that call embeddings (S4)
- [ ] `store_embedding()` creates its own DB connection — can't participate in rebuild's EXCLUSIVE transaction (S2)
- [ ] Phase 3 reclassification in rebuild not transactional — file moves + DB updates lack rollback on partial failure (S2)
- [ ] Multi-event notes store only last `gcal_id` — earlier events in same note lose their calendar link (S3)
- [ ] `last_rebuild.json` is fragile — should be a DB table for atomicity and queryability (S4)
- [ ] Inbox safety: rebuild + watcher need coordination protocol to avoid processing same files (S2)
- [ ] Silent failure in `/api/brain/status` drift check — returns "clean" when check actually threw an exception (Scout 3)
- [ ] `FileTracker` memory leak — `files` dict grows unbounded as files are added but never removed on processing (Scout 5)
- [ ] DB verification in watcher silently catches ALL exceptions including `OperationalError` (locked DB) (Scout 5)
- [ ] Duplicate `CATEGORIES` definition in `classify.py` (~line 204) shadows the import from `utils` (Scout 1)
- [ ] Sync `OllamaAdapter` blocks up to 120s on cold Ollama start — no async alternative (Scout 6)
- [ ] New `EmbeddingAdapter` connection created per call — connection pool thrashing (Scout 6)
- [ ] Rebuild calendar push not idempotent — crash between push and DB write creates duplicate GCal events (Scout 4)
- [ ] `pytest` and `sqlite-vec` missing from `requirements.txt` (Scout 9)
- [ ] 3 incomplete terminal test files need deletion: `test_terminal_integration.py`, `test_terminal_pty.py`, `test_terminal_websocket.py` (Scout 8)

## Medium (affects maintainability / observability)

- [ ] `_push_single_event` has two parallel code paths for all-day vs timed events — should be unified (S3)
- [ ] Silent search degradation: hybrid search drops to keyword-only when Ollama down, no log or indicator (S4)
- [ ] Fuzzy title matching is weakest link for Obsidian reconciliation — fails when frontmatter not backfilled (S4)
- [ ] Legacy entries have NULL `content_hash` — drift detection counts them as "unchecked" not "drifted" (S4)
- [ ] `_move_to_failed` uses `os.rename` — same-filesystem only, fails on cross-mount moves (S5)
- [ ] Recovery timestamp prefix strip is position-dependent (char 16) — breaks if format changes from `YYYYMMDD-HHMMSS_` (S5)
- [ ] Watcher hashes file WITH frontmatter, DB `content_hash` is from stripped content — values will never match (S4)
- [ ] No `response_model` declarations on any brain API endpoint — responses unvalidated (Scout 3)
- [ ] No RFC 9457 `problem()` usage in brain endpoints — inconsistent error format (Scout 3)
- [ ] Missing shutdown handler in `main.py` — no graceful cleanup on SIGTERM (Scout 7)
- [ ] Unhandled exceptions not logged by catch-all middleware before returning 500 (Scout 7)
- [ ] CSP WebSocket directive hardcoded to port 7777 — breaks on test ports (Scout 7)
- [ ] Confusing `needs_auth` logic in `token_health()` — double-negative makes intent unclear (Scout 4)
- [ ] `health_check()` in Ollama adapter uses 120s timeout — should be <5s for health probes (Scout 6)
- [ ] No retry logic for failed Ollama API calls — single failure = complete loss (Scout 6)
- [ ] Calendar fields update after `store_new` can fail silently — entry saved but cal fields missing (Scout 1)
- [ ] `old_title` fallback uses "Ideas" category instead of "untitled" — misleading default (Scout 1)
- [ ] No JSON error handling in `read_jsonld()` — corrupt file crashes caller (Scout 2)
- [ ] O(n²) dedup logic in hybrid search — linear scan for each result (Scout 3)
- [ ] Sanity check doesn't validate DB schema or brain directory structure (Scout 9)
- [ ] S1 handoff server tests reference non-existent `/api/brain` POST endpoint — actual flow is inbox-based (validation finding)
- [ ] S3 live tests can't detect running server — health check path mismatch (validation finding)
- [ ] `drift_sample` in `/api/brain/status` is non-deterministic — random sampling gives different results per call (validation finding)

## Low (cleanup / improvement / nice-to-have)

- [ ] Dead code: `yaml_escape()` in `utils.py` never called anywhere (Scout 1)
- [ ] Chrome extension wildcard in CORS config — overly permissive (Scout 7)
- [ ] No static dir existence check before `StaticFiles` mount — fails if dir missing (Scout 7)
- [ ] Root handler reads file synchronously on every request (Scout 7)
- [ ] Hardcoded "primary" calendar ID — no secondary calendar support (Scout 4)
- [ ] Timezone defaults to `America/Chicago` if `IHIM_TIMEZONE` not set — should warn (Scout 4)
- [ ] Watcher poll interval has no adaptive backoff when inbox is consistently empty (Scout 5)
- [ ] Exclude folders list is case-sensitive on Windows — may miss `.git` vs `.Git` (Scout 5)
- [ ] Ollama model names hardcoded in watcher warm-up — not configurable (Scout 5)
- [ ] Processor result validation missing in `runner.py` — trusts processor output blindly (Scout 5)
- [ ] Heartbeat file write not truly atomic on Windows — `os.replace` may fail (Scout 5)
- [ ] Loose version constraints in `requirements.txt` — `>=` without upper bounds (Scout 9)
- [ ] Empty `scripts/` directory — remove or populate (Scout 9)
- [ ] 3 TODO comments in `team/` code — resolve or convert to backlog items (Scout 9)
- [ ] No `.env` file committed (only `.env.example`) — expected but undocumented (Scout 9)

---

## Resolved

_No items resolved yet. Check off items above and move here with commit reference._
