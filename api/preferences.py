"""Preferences API — server-side persistence for user settings.

Stores preferences as JSON on disk so they survive browser cache clears.
Device names (not indices) are stored since names are stable across reboots.
"""

import json
from pathlib import Path
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/api/preferences", tags=["preferences"])

PREFS_PATH = Path(__file__).parent.parent / "data" / "local" / "preferences.json"


def _read_prefs() -> dict:
    """Read preferences from disk, returning empty dict if missing/corrupt."""
    if not PREFS_PATH.exists():
        return {}
    try:
        return json.loads(PREFS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _write_prefs(data: dict) -> None:
    """Write preferences to disk."""
    PREFS_PATH.parent.mkdir(parents=True, exist_ok=True)
    PREFS_PATH.write_text(json.dumps(data, indent=4), encoding="utf-8")


def _deep_merge(base: dict, updates: dict) -> dict:
    """Recursively merge updates into base. Returns merged dict."""
    result = base.copy()
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


@router.get("")
async def get_preferences():
    """Return all stored preferences."""
    return _read_prefs()


@router.put("")
async def put_preferences(request: Request):
    """Deep-merge incoming JSON into existing preferences and persist."""
    body = await request.json()
    if not isinstance(body, dict):
        return JSONResponse(status_code=400, content={"detail": "Request body must be a JSON object"})
    existing = _read_prefs()
    merged = _deep_merge(existing, body)
    _write_prefs(merged)
    return merged
