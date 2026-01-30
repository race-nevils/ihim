"""Pull/push logic and local cache for Google Calendar sync."""
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from googleapiclient.discovery import build
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

DEFAULT_TIMEZONE = "America/Chicago"


def _build_service(creds: Credentials):
    """Build the Google Calendar API service."""
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def pull_events(
    creds: Credentials,
    days_ahead: int = 14,
    days_behind: int = 1,
    calendar_id: str = "primary",
) -> list[dict]:
    """Fetch events from Google Calendar API.

    Returns list of event dicts in GCal API format.
    """
    service = _build_service(creds)
    now = datetime.now(timezone.utc)
    time_min = (now - timedelta(days=days_behind)).isoformat()
    time_max = (now + timedelta(days=days_ahead)).isoformat()

    events_result = (
        service.events()
        .list(
            calendarId=calendar_id,
            timeMin=time_min,
            timeMax=time_max,
            maxResults=100,
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )

    return events_result.get("items", [])


def push_event(
    creds: Credentials,
    summary: str,
    start: str,
    end: str,
    description: str = "",
    calendar_id: str = "primary",
) -> dict:
    """Create an event on Google Calendar. Returns the created event."""
    service = _build_service(creds)
    event_body = {
        "summary": summary,
        "description": description,
        "start": {"dateTime": start, "timeZone": DEFAULT_TIMEZONE},
        "end": {"dateTime": end, "timeZone": DEFAULT_TIMEZONE},
    }
    created = (
        service.events()
        .insert(calendarId=calendar_id, body=event_body)
        .execute()
    )
    logger.info(f"Created GCal event: {created.get('id')} - {summary}")
    return created


def delete_event(
    creds: Credentials,
    event_id: str,
    calendar_id: str = "primary",
) -> bool:
    """Delete an event from Google Calendar."""
    service = _build_service(creds)
    service.events().delete(calendarId=calendar_id, eventId=event_id).execute()
    logger.info(f"Deleted GCal event: {event_id}")
    return True


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


def sync_and_store(
    creds: Credentials,
    days_ahead: int = 14,
    days_behind: int = 1,
    calendar_id: str = "primary",
) -> dict:
    """Full sync: pull from GCal, update cache, write JSON-LD files.

    Returns the cache dict with events and cached_at timestamp.
    """
    events = pull_events(creds, days_ahead, days_behind, calendar_id)
    save_to_cache(events)

    # Write JSON-LD for each event
    for event in events:
        save_event_jsonld(event)

    cache = load_from_cache()
    logger.info(f"Synced {len(events)} calendar events")
    return cache
