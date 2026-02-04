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

logger = logging.getLogger(__name__)


def _push_single_event(event_data: dict, classification: dict, content: str, creds) -> bool:
    """Push a single calendar event. Returns True on success."""
    cls_title = classification.get("title", "")
    cal_title = event_data.get("title", "")
    title = cls_title if cls_title and cls_title != "Untitled" else (cal_title or "Untitled Event")
    date_str = event_data.get("date", "")
    time_str = event_data.get("time")
    all_day = event_data.get("all_day", True)

    if not date_str:
        logger.warning(f"Calendar event '{title}' has no date, skipping")
        return False

    from api.calendar.sync import push_event, save_event_jsonld

    if all_day or not time_str:
        from googleapiclient.discovery import build
        service = build("calendar", "v3", credentials=creds, cache_discovery=False)
        event_body = {
            "summary": title,
            "description": content or classification.get("summary", ""),
            "start": {"date": date_str},
            "end": {"date": date_str},
        }
        created = service.events().insert(calendarId="primary", body=event_body).execute()
    else:
        start_dt = f"{date_str}T{time_str}:00"
        end_time = event_data.get("end_time")
        if end_time:
            end_dt = f"{date_str}T{end_time}:00"
        else:
            start_obj = datetime.fromisoformat(start_dt)
            end_obj = start_obj + timedelta(hours=1)
            end_dt = end_obj.strftime("%Y-%m-%dT%H:%M:%S")
        created = push_event(creds, summary=title, start=start_dt, end=end_dt,
                             description=content or classification.get("summary", ""))

    save_event_jsonld(created)
    logger.info(f"Auto-pushed calendar event: {title} on {date_str}")
    return True


def _push_to_calendar(classification: dict, content: str = "") -> None:
    """Auto-push to Google Calendar if classification contains calendar event(s).

    Handles both single events (dict) and multi-event notes (list).
    Fails silently - calendar push is best-effort, never blocks the pipeline.
    """
    calendar_data = classification.get("calendar")
    if not calendar_data:
        return

    # Normalize to list of events
    if isinstance(calendar_data, list):
        events = [e for e in calendar_data if isinstance(e, dict) and e.get("is_event")]
    elif isinstance(calendar_data, dict) and calendar_data.get("is_event"):
        events = [calendar_data]
    else:
        return

    if not events:
        return

    try:
        from api.calendar.google_auth import get_credentials
        from api.calendar.sync import pull_events, save_to_cache

        creds = get_credentials()
        if not creds:
            logger.info("Calendar event(s) detected but Google Calendar not authenticated, skipping")
            return

        # For multi-event notes, use each event's own title instead of classification title
        pushed = 0
        for event_data in events:
            try:
                # For multi-event, prefer the event's own title
                event_cls = dict(classification)
                if len(events) > 1 and event_data.get("title"):
                    event_cls["title"] = event_data["title"]
                if _push_single_event(event_data, event_cls, content, creds):
                    pushed += 1
            except Exception as e:
                logger.error(f"Calendar push failed for event '{event_data.get('title', '?')}': {e}")

        if pushed:
            # Refresh cache once after all events pushed
            events_list = pull_events(creds)
            save_to_cache(events_list)
            logger.info(f"Pushed {pushed}/{len(events)} calendar event(s)")

    except Exception as e:
        logger.error(f"Calendar auto-push failed (non-blocking): {e}")


@observe(name="brain_handler")
def handle(state: OrchestratorState) -> OrchestratorState:
    """Handle brain intent: classify and store the note.

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

        # Auto-push to Google Calendar if event detected
        _push_to_calendar(classification, content)

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
