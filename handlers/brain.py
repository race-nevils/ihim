"""Brain handler: classify and store notes in the Second Brain.

Thin orchestration layer. All logic delegated to:
- dedup.py: Find existing entries
- classify.py: LLM classification
- storage.py: Triple-write (JSON-LD → SQLite → Obsidian)
- calendar auto-push: Events with dates go to Google Calendar

All steps traced via Langfuse for observability.
"""
import logging
from pathlib import Path
from datetime import datetime, timedelta

from handlers.tracing import observe

from orchestrator.state import OrchestratorState
from handlers.utils import compute_content_hash
from handlers.dedup import find_existing, is_unchanged
from handlers.classify import classify_content
from handlers.storage import store_new, update_existing, log_receipt
from data.database import update_entry

logger = logging.getLogger(__name__)


def _push_single_event(event_data: dict, classification: dict, content: str, creds,
                       existing_gcal_id: str | None = None) -> str | None:
    """Push or update a single calendar event. Returns GCal event ID on success."""
    cls_title = classification.get("title", "")
    cal_title = event_data.get("title", "")
    title = cls_title if cls_title and cls_title != "Untitled" else (cal_title or "Untitled Event")
    date_str = event_data.get("date", "")
    time_str = event_data.get("time")
    all_day = event_data.get("all_day", True)
    rrule = event_data.get("rrule")

    if not date_str:
        logger.warning(f"Calendar event '{title}' has no date, skipping")
        return None

    from api.calendar.sync import push_event, update_event, save_event_jsonld

    description = content or classification.get("summary", "")
    recurrence = [rrule] if rrule else None

    if all_day or not time_str:
        if existing_gcal_id:
            try:
                result = update_event(creds, existing_gcal_id, summary=title,
                                      start=date_str, end=date_str, description=description,
                                      all_day=True, recurrence=recurrence)
                save_event_jsonld(result)
                gcal_id = result.get("id")
                if not gcal_id:
                    logger.warning(f"GCal update returned no event ID for '{title}' on {date_str}")
                else:
                    logger.info(f"Updated calendar event: {title} on {date_str}")
                return gcal_id
            except Exception as e:
                logger.warning(f"GCal update failed (404?), falling back to insert: {e}")
                # Fall through to insert

        result = push_event(creds, summary=title, start=date_str, end=date_str,
                            description=description, all_day=True, recurrence=recurrence)
    else:
        start_dt = f"{date_str}T{time_str}:00"
        end_time = event_data.get("end_time")
        if end_time:
            end_dt = f"{date_str}T{end_time}:00"
        else:
            start_obj = datetime.fromisoformat(start_dt)
            end_obj = start_obj + timedelta(hours=1)
            end_dt = end_obj.strftime("%Y-%m-%dT%H:%M:%S")

        if existing_gcal_id:
            try:
                result = update_event(creds, existing_gcal_id, summary=title,
                                      start=start_dt, end=end_dt, description=description,
                                      recurrence=recurrence)
                save_event_jsonld(result)
                gcal_id = result.get("id")
                if not gcal_id:
                    logger.warning(f"GCal update returned no event ID for '{title}' on {date_str}")
                else:
                    logger.info(f"Updated calendar event: {title} on {date_str}")
                return gcal_id
            except Exception as e:
                logger.warning(f"GCal update failed (404?), falling back to insert: {e}")

        result = push_event(creds, summary=title, start=start_dt, end=end_dt,
                            description=description)

    save_event_jsonld(result)
    gcal_id = result.get("id")
    if not gcal_id:
        logger.warning(f"GCal push returned no event ID for '{title}' on {date_str}")
    else:
        logger.info(f"Auto-pushed calendar event: {title} on {date_str}")
    return gcal_id


def _push_to_calendar(classification: dict, content: str = "",
                      existing_gcal_id: str | None = None,
                      note_id: str | None = None) -> str | None:
    """Auto-push to Google Calendar if classification contains calendar event(s).

    Handles both single events (dict) and multi-event notes (list).
    Fails silently - calendar push is best-effort, never blocks the pipeline.

    When note_id is provided, gcal_event_id is persisted to the DB atomically
    after each successful push — the caller does not need a separate update_entry.

    Returns the GCal event ID of the first successfully pushed event, or None.
    """
    calendar_data = classification.get("calendar")
    if not calendar_data:
        return None

    # Normalize to list of events
    if isinstance(calendar_data, list):
        events = [e for e in calendar_data if isinstance(e, dict) and e.get("is_event")]
    elif isinstance(calendar_data, dict) and calendar_data.get("is_event"):
        events = [calendar_data]
    else:
        return None

    if not events:
        return None

    try:
        from api.calendar.google_auth import get_credentials
        from api.calendar.sync import pull_events, save_to_cache

        creds = get_credentials()
        if not creds:
            logger.info("Calendar event(s) detected but Google Calendar not authenticated, skipping")
            return None

        pushed = 0
        first_gcal_id = None
        for event_data in events:
            try:
                event_cls = dict(classification)
                if len(events) > 1 and event_data.get("title"):
                    event_cls["title"] = event_data["title"]
                # Only pass existing_gcal_id for the first event (dedup applies to single-event notes)
                gcal_id = _push_single_event(
                    event_data, event_cls, content, creds,
                    existing_gcal_id=existing_gcal_id if pushed == 0 else None
                )
                if gcal_id:
                    if note_id and first_gcal_id is None:
                        try:
                            update_entry(note_id, {"gcal_event_id": gcal_id})
                        except Exception as db_err:
                            logger.error(f"DB write failed for gcal_event_id={gcal_id} on note={note_id}: {db_err}")
                    pushed += 1
                    if first_gcal_id is None:
                        first_gcal_id = gcal_id
            except Exception as e:
                logger.error(f"Calendar push failed for event '{event_data.get('title', '?')}': {e}")

        if pushed:
            try:
                events_list = pull_events(creds)
                save_to_cache(events_list)
            except Exception as e:
                logger.warning(f"Post-push cache refresh failed (non-blocking): {e}")
            logger.info(f"Pushed {pushed}/{len(events)} calendar event(s)")

        return first_gcal_id

    except Exception as e:
        logger.error(f"Calendar auto-push failed (non-blocking): {e}")
        return None


@observe(name="brain_handler")
def handle(state: OrchestratorState) -> OrchestratorState:
    """Classify and store the note.

    Flow:
    1. Check for existing entry (dedup)
    2. If unchanged → skip
    3. If changed → update existing
    4. If new → classify and store

    Args:
        state: Current orchestrator state

    Returns:
        Updated state with processing result
    """
    content = state.get("input_text", "")
    source_file = state.get("source_file")

    # Empty content check
    if not content.strip():
        state["error"] = "Empty content, nothing to classify"
        state["result"] = {"action": "skipped", "reason": "empty_content"}
        return state

    source_filename = Path(source_file).name if source_file else None
    content_hash = compute_content_hash(content)

    try:
        # Step 1: Check for existing entry
        existing = find_existing(source_file, content)

        if existing:
            # Step 2: Check if unchanged
            if is_unchanged(existing, content_hash):
                state["result"] = {"action": "skipped", "reason": "unchanged"}
                return state

            # Step 3: Content changed - check if file is still live (in inbox)
            # Live files get reclassified, archived files just update content
            source_path = Path(source_file) if source_file else None
            is_live = source_path and source_path.exists() and "processed" not in str(source_path)

            if is_live:
                # Reclassify live files when content changes
                classification = classify_content(content, source_filename)
                new_category = classification.get("category")
                old_category = existing.get("category")

                from handlers.storage import update_with_reclassify
                obsidian_path, note_id = update_with_reclassify(
                    existing, content, content_hash, classification
                )

                # Calendar push on update (atomic — DB write inside _push_to_calendar)
                existing_gcal_id = existing.get("gcal_event_id")
                _push_to_calendar(classification, content,
                                  existing_gcal_id=existing_gcal_id, note_id=note_id)

                action = "updated_reclassified" if new_category != old_category else "updated"
                log_receipt(source_file, classification, action, obsidian_path)

                state["result"] = {
                    "action": action,
                    "category": new_category,
                    "old_category": old_category if new_category != old_category else None,
                    "confidence": classification.get("confidence"),
                    "title": classification.get("title"),
                    "destination": str(obsidian_path),
                    "processed_id": note_id
                }
            else:
                # Archived/stale files just update content, keep category
                obsidian_path, note_id = update_existing(existing, content, content_hash)

                log_receipt(source_file, {
                    "category": existing.get("category"),
                    "title": existing.get("title"),
                    "confidence": existing.get("confidence", 0.0)
                }, "updated", obsidian_path)

                state["result"] = {
                    "action": "updated",
                    "category": existing.get("category"),
                    "title": existing.get("title"),
                    "destination": str(obsidian_path),
                    "processed_id": note_id
                }
            return state

        # Step 4: Classify and store new entry
        classification = classify_content(content, source_filename)
        obsidian_path, note_id = store_new(
            content, classification, source_file, source_filename
        )

        # Auto-push to Google Calendar if event detected (atomic — DB write inside)
        _push_to_calendar(classification, content, note_id=note_id)

        action = "misc" if classification.get("confidence", 0) < 0.7 else "classified"
        log_receipt(source_file, classification, action, obsidian_path)

        state["result"] = {
            "action": action,
            "category": classification.get("category"),
            "confidence": classification.get("confidence"),
            "title": classification.get("title"),
            "summary": classification.get("summary"),
            "destination": str(obsidian_path),
            "processed_id": note_id
        }

    except Exception as e:
        logger.error(f"Brain handler error: {e}", exc_info=True)
        state["error"] = f"Brain handler error: {str(e)}"
        state["result"] = {"action": "error", "error": str(e)}

    return state
