"""Google Calendar integration routes.

OAuth + cached-events model: /sync pulls from Google and refreshes the local
cache + Calendar JSON-LD; /events serves from cache only (the widget decides
when to sync). Errors raise HTTPException, which the global handler converts
to RFC 9457 Problem Details.

Removed in the 2026-06 refactor: /entries (brain-calendar join) and
/push-entry — no consumers.
"""

import asyncio
import logging

from fastapi import APIRouter, HTTPException
from googleapiclient.errors import HttpError

from api.calendar.google_auth import (
    CREDS_FILE,
    get_credentials,
    is_authenticated,
    revoke_auth,
    start_auth_flow,
    token_health,
)
from api.calendar.models import CreateEventRequest, SyncRequest
from api.calendar.sync import (
    delete_event,
    load_from_cache,
    pull_events,
    push_event,
    save_event_jsonld,
    save_to_cache,
    sync_and_store,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/calendar", tags=["Calendar"])


def _require_auth():
    creds = get_credentials()
    if not creds:
        raise HTTPException(status_code=401, detail="Google Calendar not authenticated")
    return creds


def _raise_google_error(action: str, e: HttpError):
    if e.resp.status == 401:
        logger.error("%s failed: auth expired", action)
        raise HTTPException(status_code=401, detail="Google auth expired — reconnect via Settings")
    logger.error("%s failed: Google API error %s: %s", action, e.resp.status, e)
    raise HTTPException(status_code=502, detail=f"Google API error: {e}")


@router.get("/status")
async def calendar_status():
    """Auth state + last sync info."""
    cache = load_from_cache()
    return {
        "authenticated": is_authenticated(),
        "credentials_file_exists": CREDS_FILE.exists(),
        "last_sync": cache.get("cached_at"),
        "event_count": len(cache.get("events", [])),
        "token_health": token_health(),
    }


@router.post("/auth/start")
async def calendar_auth_start():
    """Start the OAuth2 browser flow."""
    try:
        start_auth_flow()
        return {"success": True, "message": "Google Calendar connected"}
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=f"{e} — place credentials.json in IHIM/data/ first")
    except Exception as e:
        logger.error("Auth flow failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/auth/revoke")
async def calendar_auth_revoke():
    """Delete the stored OAuth2 token."""
    revoked = revoke_auth()
    return {"success": True, "message": "Token revoked" if revoked else "No token to revoke"}


@router.get("/events")
async def get_events():
    """Events from the local cache (call /sync to refresh)."""
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
    """Pull from Google Calendar; refresh cache + Calendar JSON-LD."""
    creds = _require_auth()
    try:
        loop = asyncio.get_event_loop()
        cache = await loop.run_in_executor(None, lambda: sync_and_store(
            creds,
            days_ahead=request.days_ahead,
            days_behind=request.days_behind,
            calendar_id=request.calendar_id,
        ))
        return {
            "success": True,
            "events": cache.get("events", []),
            "cached_at": cache.get("cached_at"),
            "count": len(cache.get("events", [])),
        }
    except HttpError as e:
        _raise_google_error("Sync", e)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Sync failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Sync failed: {e}")


@router.post("/events")
async def create_event(request: CreateEventRequest):
    """Create an event on Google Calendar (+ local JSON-LD + cache refresh)."""
    creds = _require_auth()
    try:
        loop = asyncio.get_event_loop()
        created = await loop.run_in_executor(None, lambda: push_event(
            creds,
            summary=request.summary,
            start=request.start,
            end=request.end,
            description=request.description,
            calendar_id=request.calendar_id,
        ))
        await loop.run_in_executor(None, save_event_jsonld, created)
        events = await loop.run_in_executor(None, lambda: pull_events(creds, calendar_id=request.calendar_id))
        save_to_cache(events)
        return {"success": True, "event": created, "message": f"Created: {request.summary}"}
    except HttpError as e:
        _raise_google_error("Create event", e)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Create event failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Create event failed: {e}")


@router.delete("/events/{event_id}")
async def remove_event(event_id: str, calendar_id: str = "primary"):
    """Delete an event from Google Calendar (+ cache refresh)."""
    creds = _require_auth()
    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: delete_event(creds, event_id, calendar_id))
        events = await loop.run_in_executor(None, lambda: pull_events(creds, calendar_id=calendar_id))
        save_to_cache(events)
        return {"success": True, "message": f"Deleted event {event_id}"}
    except HttpError as e:
        _raise_google_error("Delete event", e)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Delete event failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Delete event failed: {e}")
