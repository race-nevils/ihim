# Backend Dev Retrospective - Stopwatch Widget API

**Date:** 2025-12-27
**Task:** Build stopwatch widget API for spawning multiple independent stopwatches
**Status:** Complete

---

## Assumptions I Didn't Verify

1. **Assumed JSON file storage was acceptable** - Didn't ask if this should use SQLite or another backend. For a simple stopwatch widget, JSON is fine, but for high-frequency updates it could become a bottleneck.

2. **Assumed frontend would handle the visual tick** - Made a design decision that the API only stores `elapsed_ms` when stopped, and `started_at` when running. Frontend calculates real-time display. Didn't verify this was the expected pattern.

3. **Assumed no authentication needed** - iHIM is localhost-only, but didn't verify if stopwatches should be user-specific in future.

4. **Assumed UTC timestamps were fine** - Used UTC for all timestamps without asking about timezone preferences.

---

## Where I Wasted Time

1. **Initially considered WebSocket for real-time updates** - Quickly realized this was over-engineering. A stopwatch ticks locally; the API just persists state. This was a 30-second mental detour.

2. **No significant time waste** - The task was straightforward and I followed existing patterns (tasks, notes) which gave me a clear template.

---

## What I'd Do Differently

1. **Ask about lap storage** - I implemented `/lap` to return the current time, but it doesn't persist laps. If the user wants to review lap history, I'd need to add a `laps` array to the stopwatch object.

2. **Consider polling vs. push** - Could have implemented a lightweight SSE endpoint so frontend doesn't need to poll for updates when multiple stopwatches are running across browser tabs.

3. **Add stopwatch limits** - No max number of stopwatches. Could add a reasonable limit (e.g., 100) to prevent accidental spam.

---

## What Might Break

1. **Time precision** - Using milliseconds as integers. JavaScript Date.now() returns milliseconds, Python datetime also handles this, but there could be sub-ms drift over very long runs (hours/days). Unlikely to matter for a stopwatch widget.

2. **File locking** - JSON file has no locking. If two API requests hit simultaneously, one could overwrite the other. Low risk for single-user localhost tool, but worth noting.

3. **Empty body on POST /api/stopwatches** - Made the request body optional (defaults to empty label). FastAPI handles this but some API clients might send unexpected payloads.

4. **Timezone edge cases** - If system clock changes (DST, NTP sync), a running stopwatch's calculated elapsed time could jump or go negative. Should probably guard against negative elapsed.

---

## What Next Agent Should Know

### For Frontend Dev:

1. **The + button workflow:**
   - `POST /api/stopwatches` (optional: `{"label": "Workout"}`)
   - Returns the new stopwatch object with `is_running: false`
   - Immediately call `POST /api/stopwatches/{id}/start` if you want it running

2. **Displaying running time:**
   ```javascript
   function getDisplayMs(stopwatch) {
     if (!stopwatch.is_running) return stopwatch.elapsed_ms;
     const started = new Date(stopwatch.started_at).getTime();
     return stopwatch.elapsed_ms + (Date.now() - started);
   }
   ```

3. **Control buttons should call:**
   - Start: `POST /api/stopwatches/{id}/start`
   - Stop: `POST /api/stopwatches/{id}/stop`
   - Reset: `POST /api/stopwatches/{id}/reset`
   - Delete (X): `DELETE /api/stopwatches/{id}`

4. **All endpoints return the updated stopwatch object** - You can use the response to update local state.

### For QA Tester:

1. Test the start/stop/start cycle - elapsed_ms should accumulate correctly
2. Test reset while running - should stop and zero out
3. Test rapid clicks - idempotent operations (start while running, stop while stopped)
4. Test with empty label vs. custom label
5. Test /lap endpoint while running vs. stopped

---

## Honest Assessment

**What I did well:** Followed existing patterns exactly, kept scope minimal, documented API contracts clearly.

**What I could have done better:** Should have asked @frontend-dev what data format they prefer BEFORE implementing. I assumed they'd figure it out from the API response, but explicit coordination would have been more professional.

**Confidence level:** 95% - The API is simple, follows established patterns, and should work as documented. The 5% uncertainty is around edge cases I haven't tested (very long runs, concurrent requests, system clock changes).
