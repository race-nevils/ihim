"""Pydantic models for Google Calendar integration."""
from pydantic import BaseModel, Field
from typing import Optional


class CalendarEvent(BaseModel):
    """A calendar event (from GCal or local)."""
    id: str
    summary: str
    start: str  # ISO 8601 datetime or date
    end: str
    description: str = ""
    location: str = ""
    status: str = "confirmed"
    all_day: bool = False
    gcal_link: Optional[str] = None


class CreateEventRequest(BaseModel):
    """Request to create a new event on Google Calendar."""
    summary: str = Field(..., min_length=1, max_length=500)
    start: str = Field(..., description="ISO 8601 datetime (e.g. 2026-02-04T10:00:00)")
    end: str = Field(..., description="ISO 8601 datetime")
    description: str = Field("", max_length=5000)
    calendar_id: str = Field("primary")


class PushBrainEntryRequest(BaseModel):
    """Request to push an existing brain entry as a calendar event."""
    entry_id: str
    start: str = Field(..., description="ISO 8601 datetime")
    end: str = Field(..., description="ISO 8601 datetime")
    calendar_id: str = Field("primary")


class SyncRequest(BaseModel):
    """Request to sync events from Google Calendar."""
    days_ahead: int = Field(365, ge=1, le=730)
    days_behind: int = Field(7, ge=0, le=365)
    calendar_id: str = Field("primary")
