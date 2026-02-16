"""Stopwatch routes — multiple independent stopwatches."""

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from pathlib import Path
from typing import Optional
from datetime import datetime
import json
import uuid

from api.errors import problem

router = APIRouter(prefix="/api/stopwatches", tags=["stopwatch"])

STOPWATCHES_FILE = Path(__file__).parent.parent.parent / "data" / "stopwatches.json"


class StopwatchCreate(BaseModel):
    """Request model for creating a new stopwatch."""
    label: Optional[str] = Field(None, max_length=100, description="Optional name for the stopwatch")


class StopwatchUpdate(BaseModel):
    """Request model for updating a stopwatch."""
    label: Optional[str] = Field(None, max_length=100)


def load_stopwatches() -> list:
    """Load stopwatches from JSON file."""
    if STOPWATCHES_FILE.exists():
        try:
            data = json.loads(STOPWATCHES_FILE.read_text(encoding="utf-8"))
            return data.get("stopwatches", [])
        except Exception as e:
            print(f"Warning: Failed to load stopwatches: {e}")
    return []


def save_stopwatches(stopwatches: list):
    """Save stopwatches to JSON file."""
    STOPWATCHES_FILE.parent.mkdir(parents=True, exist_ok=True)
    STOPWATCHES_FILE.write_text(
        json.dumps({"stopwatches": stopwatches}, indent=2),
        encoding="utf-8"
    )


def _find_stopwatch(stopwatches: list, stopwatch_id: str):
    """Find a stopwatch by ID, return (index, stopwatch) or (None, None)."""
    for i, sw in enumerate(stopwatches):
        if sw["id"] == stopwatch_id:
            return i, sw
    return None, None


@router.get("")
async def get_stopwatches():
    """Get all stopwatches."""
    return {"stopwatches": load_stopwatches()}


@router.post("", status_code=201)
async def create_stopwatch(stopwatch: StopwatchCreate = None):
    """Create a new stopwatch in stopped state."""
    stopwatches = load_stopwatches()
    now = datetime.utcnow().isoformat() + "Z"

    new_stopwatch = {
        "id": str(uuid.uuid4())[:8],
        "label": (stopwatch.label if stopwatch else None) or "",
        "elapsed_ms": 0,
        "is_running": False,
        "started_at": None,
        "created_at": now
    }
    stopwatches.append(new_stopwatch)
    save_stopwatches(stopwatches)
    return {"success": True, "stopwatch": new_stopwatch}


@router.get("/{stopwatch_id}")
async def get_stopwatch(stopwatch_id: str, request: Request):
    """Get a single stopwatch by ID."""
    stopwatches = load_stopwatches()
    _, sw = _find_stopwatch(stopwatches, stopwatch_id)
    if sw is None:
        return problem(404, "Stopwatch not found", instance=request.url.path)
    return {"success": True, "stopwatch": sw}


@router.put("/{stopwatch_id}")
async def update_stopwatch(stopwatch_id: str, update: StopwatchUpdate, request: Request):
    """Update a stopwatch's label."""
    stopwatches = load_stopwatches()
    _, sw = _find_stopwatch(stopwatches, stopwatch_id)
    if sw is None:
        return problem(404, "Stopwatch not found", instance=request.url.path)
    if update.label is not None:
        sw["label"] = update.label
    save_stopwatches(stopwatches)
    return {"success": True, "stopwatch": sw}


@router.post("/{stopwatch_id}/start")
async def start_stopwatch(stopwatch_id: str, request: Request):
    """Start a stopwatch."""
    stopwatches = load_stopwatches()
    _, sw = _find_stopwatch(stopwatches, stopwatch_id)
    if sw is None:
        return problem(404, "Stopwatch not found", instance=request.url.path)
    if not sw["is_running"]:
        sw["is_running"] = True
        sw["started_at"] = datetime.utcnow().isoformat() + "Z"
        save_stopwatches(stopwatches)
    return {"success": True, "stopwatch": sw}


@router.post("/{stopwatch_id}/stop")
async def stop_stopwatch(stopwatch_id: str, request: Request):
    """Stop a stopwatch and accumulate elapsed time."""
    stopwatches = load_stopwatches()
    _, sw = _find_stopwatch(stopwatches, stopwatch_id)
    if sw is None:
        return problem(404, "Stopwatch not found", instance=request.url.path)
    if sw["is_running"] and sw["started_at"]:
        started = datetime.fromisoformat(sw["started_at"].rstrip("Z"))
        now = datetime.utcnow()
        additional_ms = int((now - started).total_seconds() * 1000)
        sw["elapsed_ms"] = sw.get("elapsed_ms", 0) + additional_ms
        sw["is_running"] = False
        sw["started_at"] = None
        save_stopwatches(stopwatches)
    return {"success": True, "stopwatch": sw}


@router.post("/{stopwatch_id}/reset")
async def reset_stopwatch(stopwatch_id: str, request: Request):
    """Reset a stopwatch to zero."""
    stopwatches = load_stopwatches()
    _, sw = _find_stopwatch(stopwatches, stopwatch_id)
    if sw is None:
        return problem(404, "Stopwatch not found", instance=request.url.path)
    sw["elapsed_ms"] = 0
    sw["is_running"] = False
    sw["started_at"] = None
    save_stopwatches(stopwatches)
    return {"success": True, "stopwatch": sw}


@router.post("/{stopwatch_id}/lap")
async def lap_stopwatch(stopwatch_id: str, request: Request):
    """Record a lap time without stopping."""
    stopwatches = load_stopwatches()
    _, sw = _find_stopwatch(stopwatches, stopwatch_id)
    if sw is None:
        return problem(404, "Stopwatch not found", instance=request.url.path)
    current_elapsed = sw.get("elapsed_ms", 0)
    if sw["is_running"] and sw["started_at"]:
        started = datetime.fromisoformat(sw["started_at"].rstrip("Z"))
        now = datetime.utcnow()
        current_elapsed += int((now - started).total_seconds() * 1000)
    return {
        "success": True,
        "lap_ms": current_elapsed,
        "timestamp": datetime.utcnow().isoformat() + "Z"
    }


@router.delete("/{stopwatch_id}")
async def delete_stopwatch(stopwatch_id: str, request: Request):
    """Delete a stopwatch."""
    stopwatches = load_stopwatches()
    original_count = len(stopwatches)
    stopwatches = [sw for sw in stopwatches if sw["id"] != stopwatch_id]

    if len(stopwatches) == original_count:
        return problem(404, "Stopwatch not found", instance=request.url.path)

    save_stopwatches(stopwatches)
    return {"success": True}


@router.delete("")
async def delete_all_stopwatches():
    """Delete all stopwatches."""
    save_stopwatches([])
    return {"success": True, "message": "All stopwatches deleted"}
