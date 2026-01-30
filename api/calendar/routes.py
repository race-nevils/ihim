"""FastAPI routes for Google Calendar integration."""
import logging
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from api.calendar.google_auth import (
    get_credentials,
    start_auth_flow,
    is_authenticated,
    revoke_auth,
    CREDS_FILE,
)
from api.calendar.models import CreateEventRequest, PushBrainEntryRequest, SyncRequest
from api.calendar.sync import (
    load_from_cache,
    sync_and_store,
    push_event,
    delete_event,
    save_event_jsonld,
    save_to_cache,
    pull_events,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/calendar", tags=["Calendar"])


def _require_auth():
    """Get credentials or raise 401."""
    creds = get_credentials()
    if not creds:
        raise HTTPException(status_code=401, detail="Google Calendar not authenticated")
    return creds


# --- Auth endpoints ---


@router.get("/status")
async def calendar_status():
    """Check authentication status and last sync info."""
    cache = load_from_cache()
    return {
        "authenticated": is_authenticated(),
        "credentials_file_exists": CREDS_FILE.exists(),
        "last_sync": cache.get("cached_at"),
        "event_count": len(cache.get("events", [])),
    }


@router.post("/auth/start")
async def calendar_auth_start():
    """Initiate OAuth2 flow. Opens browser for Google sign-in."""
    try:
        start_auth_flow()
        return {"success": True, "message": "Google Calendar connected"}
    except FileNotFoundError as e:
        return JSONResponse(
            status_code=400,
            content={
                "success": False,
                "error": str(e),
                "message": "Place credentials.json in IHIM/data/ first",
            },
        )
    except Exception as e:
        logger.error(f"Auth flow failed: {e}")
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": str(e)},
        )


@router.post("/auth/revoke")
async def calendar_auth_revoke():
    """Delete stored OAuth2 token."""
    revoked = revoke_auth()
    return {
        "success": True,
        "message": "Token revoked" if revoked else "No token to revoke",
    }


# --- Event endpoints ---


@router.get("/events")
async def get_events(days_ahead: int = 14):
    """Get calendar events from local cache.

    The frontend should call /sync to refresh the cache when needed.
    """
    if not is_authenticated():
        return {"authenticated": False, "events": [], "cached_at": None}

    cache = load_from_cache()
    return {
        "authenticated": True,
        "events": cache.get("events", []),
        "cached_at": cache.get("cached_at"),
    }


@router.post("/sync")
async def sync_calendar(request: SyncRequest = SyncRequest()):
    """Force pull from Google Calendar and refresh local cache + JSON-LD."""
    creds = _require_auth()
    try:
        cache = sync_and_store(
            creds,
            days_ahead=request.days_ahead,
            days_behind=request.days_behind,
            calendar_id=request.calendar_id,
        )
        return {
            "success": True,
            "events": cache.get("events", []),
            "cached_at": cache.get("cached_at"),
            "count": len(cache.get("events", [])),
        }
    except Exception as e:
        logger.error(f"Sync failed: {e}")
        raise HTTPException(status_code=500, detail=f"Sync failed: {e}")


@router.post("/events")
async def create_event(request: CreateEventRequest):
    """Create a new event on Google Calendar."""
    creds = _require_auth()
    try:
        created = push_event(
            creds,
            summary=request.summary,
            start=request.start,
            end=request.end,
            description=request.description,
            calendar_id=request.calendar_id,
        )
        # Save locally as JSON-LD
        save_event_jsonld(created)
        # Refresh cache
        events = pull_events(creds, calendar_id=request.calendar_id)
        save_to_cache(events)

        return {
            "success": True,
            "event": created,
            "message": f"Created: {request.summary}",
        }
    except Exception as e:
        logger.error(f"Create event failed: {e}")
        raise HTTPException(status_code=500, detail=f"Create event failed: {e}")


@router.delete("/events/{event_id}")
async def remove_event(event_id: str, calendar_id: str = "primary"):
    """Delete an event from Google Calendar."""
    creds = _require_auth()
    try:
        delete_event(creds, event_id, calendar_id)
        # Refresh cache
        events = pull_events(creds, calendar_id=calendar_id)
        save_to_cache(events)

        return {"success": True, "message": f"Deleted event {event_id}"}
    except Exception as e:
        logger.error(f"Delete event failed: {e}")
        raise HTTPException(status_code=500, detail=f"Delete event failed: {e}")


@router.post("/push-entry")
async def push_brain_entry(request: PushBrainEntryRequest):
    """Push an existing brain entry as a Google Calendar event."""
    creds = _require_auth()

    # Look up the brain entry
    try:
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).parent.parent.parent))
        from data.database import get_entry

        entry = get_entry(request.entry_id)
        if not entry:
            raise HTTPException(status_code=404, detail=f"Brain entry not found: {request.entry_id}")

        created = push_event(
            creds,
            summary=entry.get("title", "Untitled"),
            start=request.start,
            end=request.end,
            description=entry.get("content", ""),
            calendar_id=request.calendar_id,
        )
        save_event_jsonld(created)

        return {
            "success": True,
            "event": created,
            "message": f"Pushed '{entry.get('title')}' to Google Calendar",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Push brain entry failed: {e}")
        raise HTTPException(status_code=500, detail=f"Push failed: {e}")
