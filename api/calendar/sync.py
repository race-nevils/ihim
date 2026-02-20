"""Pull/push logic and local cache for Google Calendar sync."""
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.oauth2.credentials import Credentials

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent.parent / "data"
CACHE_FILE = DATA_DIR / "calendar_cache.json"
JSONLD_ROOT = DATA_DIR / "local" / "brain"
CALENDAR_DIR = JSONLD_ROOT / "Calendar"

# Reuse the standard iHIM JSON-LD context
IHIM_CONTEXT = {
    "@vocab": "https://schema.org/",
    "dc": "http://purl.org/dc/terms/",
    "as": "https://www.w3.org/ns/activitystreams#",
    "ihim": "https://ihim.local/schema#",
}

DEFAULT_TIMEZONE = os.environ.get("IHIM_TIMEZONE", "America/Chicago")


def _build_service(creds: Credentials):
    """Build the Google Calendar API service."""
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def _execute_with_retry(request, max_retries: int = 2):
    """Execute a Google API request with retry on transient errors.

    Retries on 429 (rate limit), 500, 503 with exponential backoff.
    401 (auth failure) bubbles up immediately — no retry.
    """
    for attempt in range(max_retries + 1):
        try:
            return request.execute()
        except HttpError as e:
            status = e.resp.status
            if status == 401:
                raise  # Auth failure — don't retry
            if status in (429, 500, 503) and attempt < max_retries:
                wait = (attempt + 1)  # 1s, 2s
                logger.warning(f"Google API {status}, retrying in {wait}s (attempt {attempt + 1}/{max_retries})")
                time.sleep(wait)
                continue
            raise  # Non-retryable or retries exhausted


def _with_auth_refresh(creds: Credentials, operation):
    """Execute operation; on 401, refresh credentials and retry once.

    Handles the case where credentials expire mid-session. The operation
    receives creds and should build its own service from them.
    """
    try:
        return operation(creds)
    except HttpError as e:
        if e.resp.status != 401:
            raise
        from api.calendar.google_auth import get_credentials
        fresh = get_credentials()
        if not fresh:
            raise  # Refresh failed — can't recover
        logger.info("Refreshed credentials after 401, retrying once")
        return operation(fresh)


def pull_events(
    creds: Credentials,
    days_ahead: int = 365,
    days_behind: int = 7,
    calendar_id: str = "primary",
) -> list[dict]:
    """Fetch events from Google Calendar API.

    Defaults to 365 days ahead / 7 days behind. Personal calendar scale
    makes narrow windows unnecessary, and wider coverage ensures all
    future events get JSON-LD files with linked metadata.

    Paginates automatically for large result sets.

    Returns list of event dicts in GCal API format.
    """
    def _do(c):
        service = _build_service(c)
        now = datetime.now(timezone.utc)
        time_min = (now - timedelta(days=days_behind)).isoformat()
        time_max = (now + timedelta(days=days_ahead)).isoformat()

        all_events = []
        page_token = None

        while True:
            events_result = _execute_with_retry(
                service.events()
                .list(
                    calendarId=calendar_id,
                    timeMin=time_min,
                    timeMax=time_max,
                    maxResults=250,
                    singleEvents=True,
                    orderBy="startTime",
                    pageToken=page_token,
                )
            )
            all_events.extend(events_result.get("items", []))
            page_token = events_result.get("nextPageToken")
            if not page_token:
                break

        return all_events
    return _with_auth_refresh(creds, _do)


def push_event(
    creds: Credentials,
    summary: str,
    start: str,
    end: str,
    description: str = "",
    all_day: bool = False,
    recurrence: list[str] | None = None,
    calendar_id: str = "primary",
) -> dict:
    """Create an event on Google Calendar. Returns the created event."""
    def _do(c):
        service = _build_service(c)
        if all_day:
            event_body = {
                "summary": summary,
                "description": description,
                "start": {"date": start},
                "end": {"date": end},
            }
        else:
            event_body = {
                "summary": summary,
                "description": description,
                "start": {"dateTime": start, "timeZone": DEFAULT_TIMEZONE},
                "end": {"dateTime": end, "timeZone": DEFAULT_TIMEZONE},
            }
        if recurrence:
            event_body["recurrence"] = recurrence
        created = _execute_with_retry(
            service.events()
            .insert(calendarId=calendar_id, body=event_body)
        )
        logger.info(f"Created GCal event: {created.get('id')} - {summary}")
        return created
    return _with_auth_refresh(creds, _do)


def update_event(
    creds: Credentials,
    event_id: str,
    summary: str,
    start: str,
    end: str,
    description: str = "",
    all_day: bool = False,
    recurrence: list[str] | None = None,
    calendar_id: str = "primary",
) -> dict:
    """Update an existing event on Google Calendar. Returns the updated event."""
    def _do(c):
        service = _build_service(c)
        if all_day:
            event_body = {
                "summary": summary,
                "description": description,
                "start": {"date": start},
                "end": {"date": end},
            }
        else:
            event_body = {
                "summary": summary,
                "description": description,
                "start": {"dateTime": start, "timeZone": DEFAULT_TIMEZONE},
                "end": {"dateTime": end, "timeZone": DEFAULT_TIMEZONE},
            }
        if recurrence:
            event_body["recurrence"] = recurrence
        updated = _execute_with_retry(
            service.events()
            .patch(calendarId=calendar_id, eventId=event_id, body=event_body)
        )
        logger.info(f"Updated GCal event: {updated.get('id')} - {summary}")
        return updated
    return _with_auth_refresh(creds, _do)


def delete_event(
    creds: Credentials,
    event_id: str,
    calendar_id: str = "primary",
) -> bool:
    """Delete an event from Google Calendar."""
    def _do(c):
        service = _build_service(c)
        _execute_with_retry(
            service.events().delete(calendarId=calendar_id, eventId=event_id)
        )
        logger.info(f"Deleted GCal event: {event_id}")
        return True
    return _with_auth_refresh(creds, _do)


# --- Local cache ---


def save_to_cache(events: list[dict]) -> None:
    """Write events to local cache file for fast frontend reads."""
    cache = {
        "cached_at": datetime.now(timezone.utc).isoformat(),
        "events": events,
    }
    CACHE_FILE.write_text(json.dumps(cache, indent=2), encoding="utf-8")


def load_from_cache() -> dict:
    """Read from cache. Returns {"cached_at": ..., "events": [...]}."""
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Cache read failed: {e}")
    return {"cached_at": None, "events": []}


# --- JSON-LD sovereign storage ---


def _slugify(text: str) -> str:
    """Convert text to filename-safe slug."""
    import re

    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text[:50]


def _parse_event_time(event: dict, field: str) -> Optional[str]:
    """Extract datetime string from GCal event start/end dict."""
    time_info = event.get(field, {})
    return time_info.get("dateTime") or time_info.get("date")


def event_to_jsonld(event: dict) -> dict:
    """Convert a GCal API event dict to iHIM JSON-LD format."""
    start = _parse_event_time(event, "start") or ""
    end = _parse_event_time(event, "end") or ""
    summary = event.get("summary", "Untitled Event")
    now = datetime.now(timezone.utc).isoformat()

    # Determine if all-day event
    all_day = "date" in event.get("start", {})

    doc = {
        "@context": IHIM_CONTEXT,
        "@type": "Event",
        "@id": f"ihim:calendar/{event.get('id', 'unknown')}",
        "identifier": event.get("id", "unknown"),
        "name": summary,
        "description": event.get("description", ""),
        "startDate": start,
        "endDate": end,
        "location": event.get("location", ""),
        "dateCreated": now,
        "dateModified": now,
        "ihim:category": "Calendar",
        "ihim:gcalEventId": event.get("id", ""),
        "ihim:gcalCalendarId": event.get("organizer", {}).get("email", "primary"),
        "ihim:syncDirection": "pull",
        "ihim:allDay": all_day,
        "dc:source": "google-calendar",
    }
    return doc


def save_event_jsonld(event: dict) -> Optional[Path]:
    """Write a calendar event as JSON-LD file.

    Returns path to written file, or None on failure.
    """
    CALENDAR_DIR.mkdir(parents=True, exist_ok=True)

    summary = event.get("summary", "untitled-event")
    start = _parse_event_time(event, "start") or ""
    date_str = start[:10].replace("-", "") if start else datetime.now().strftime("%Y%m%d")
    slug = _slugify(summary)
    if not slug:
        slug = "event"

    filename = f"cal-{date_str}-{slug}.jsonld"
    file_path = CALENDAR_DIR / filename

    # Handle collisions
    counter = 1
    while file_path.exists():
        filename = f"cal-{date_str}-{slug}-{counter}.jsonld"
        file_path = CALENDAR_DIR / filename
        counter += 1

    doc = event_to_jsonld(event)
    try:
        file_path.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info(f"Written calendar JSON-LD: {file_path}")
        return file_path
    except OSError as e:
        logger.error(f"Failed to write calendar JSON-LD: {e}")
        return None


def _get_existing_gcal_ids() -> set[str]:
    """Get set of GCal event IDs that already have local JSON-LD files.

    Scans Calendar directory so sync_and_store can skip events that
    already have sovereign local storage (preserving any enrichments).
    """
    existing = set()
    if CALENDAR_DIR.exists():
        for f in CALENDAR_DIR.glob("cal-*.jsonld"):
            try:
                doc = json.loads(f.read_text(encoding="utf-8"))
                gcal_id = doc.get("ihim:gcalEventId") or doc.get("identifier")
                if gcal_id:
                    existing.add(gcal_id)
            except (json.JSONDecodeError, OSError):
                continue
    return existing


def sync_and_store(
    creds: Credentials,
    days_ahead: int = 365,
    days_behind: int = 7,
    calendar_id: str = "primary",
) -> dict:
    """Full sync: pull from GCal, update cache, write JSON-LD for NEW events only.

    Existing JSON-LD files are never overwritten or deleted. Only events
    that don't already have a local JSON-LD file get one created.

    Returns the cache dict with events and cached_at timestamp.
    """
    events = pull_events(creds, days_ahead, days_behind, calendar_id)
    save_to_cache(events)

    # Only create JSON-LD for events not already stored locally
    existing_ids = _get_existing_gcal_ids()
    new_count = 0
    for event in events:
        if event.get("id") not in existing_ids:
            save_event_jsonld(event)
            new_count += 1

    cache = load_from_cache()
    logger.info(f"Synced {len(events)} calendar events ({new_count} new JSON-LD files)")
    return cache
