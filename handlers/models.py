"""Pydantic models and exceptions for brain pipeline validation.

Type safety at the entry point: malformed data gets caught here
before it can reach JSON-LD (source of truth) or any derived store.
"""
import logging
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from handlers.category_registry import get_registry

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class CalendarEvent(BaseModel):
    """Structured calendar event extracted from classification."""
    is_event: bool = False
    title: Optional[str] = None
    date: Optional[str] = None       # YYYY-MM-DD
    time: Optional[str] = None       # HH:MM
    end_time: Optional[str] = None   # HH:MM
    all_day: Optional[bool] = None
    rrule: Optional[str] = None


class ClassificationResult(BaseModel):
    """Validated classification from the LLM.

    Coerces invalid/hallucinated categories to Misc (the uncertainty bucket).
    Rejects empty titles and out-of-range confidence values.
    """
    category: str
    title: str = Field(min_length=1)
    summary: str = ""
    confidence: float = Field(ge=0.0, le=1.0)
    calendar: Optional[CalendarEvent] = None

    @field_validator("category")
    @classmethod
    def coerce_invalid_category(cls, v: str) -> str:
        registry = get_registry()
        if not registry.is_valid(v):
            logger.warning(
                "Invalid category %r coerced to %s (not in registry)",
                v, registry.catch_all(),
            )
            return registry.catch_all()
        return v

    @model_validator(mode="before")
    @classmethod
    def normalize_calendar(cls, data: dict) -> dict:
        """Handle calendar being a list (multi-event) or dict with is_event=False."""
        if not isinstance(data, dict):
            return data
        cal = data.get("calendar")
        if isinstance(cal, list):
            # Extract first dict with is_event=True
            match = next(
                (c for c in cal if isinstance(c, dict) and c.get("is_event")),
                None,
            )
            data["calendar"] = match
        elif isinstance(cal, dict) and not cal.get("is_event"):
            data["calendar"] = None
        return data


class BrainEntry(BaseModel):
    """Validated brain entry input (content + optional source metadata)."""
    content: str = Field(min_length=1)
    source_file: Optional[str] = None
    source_filename: Optional[str] = None


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class StorageError(Exception):
    """JSON-LD write failed. Operation aborted — nothing was persisted."""


class PartialWriteError(Exception):
    """JSON-LD succeeded but SQLite failed.

    Source of truth is safe but entry is invisible to queries until rebuild.
    """
    def __init__(self, message: str, jsonld_path: str):
        super().__init__(message)
        self.jsonld_path = jsonld_path
