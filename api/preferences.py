"""Preferences API — server-side persistence for user settings.

Stored as JSON on disk so settings survive browser cache clears. Device
NAMES (not indices) are what widgets store — names are stable across
reboots, indices are not.
"""

import json

from fastapi import APIRouter, Request

from api.errors import problem
from api.runtime import DATA_DIR

router = APIRouter(prefix="/api/preferences", tags=["preferences"])

PREFS_PATH = DATA_DIR / "local" / "preferences.json"


def _read_prefs() -> dict:
    if not PREFS_PATH.exists():
        return {}
    try:
        return json.loads(PREFS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _write_prefs(data: dict) -> None:
    PREFS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = PREFS_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=4), encoding="utf-8")
    tmp.replace(PREFS_PATH)


def _deep_merge(base: dict, updates: dict) -> dict:
    result = base.copy()
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


@router.get("")
async def get_preferences():
    """All stored preferences."""
    return _read_prefs()


@router.put("")
async def put_preferences(request: Request):
    """Deep-merge the JSON body into stored preferences; returns the result."""
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return problem(400, "Request body must be valid JSON", instance=request.url.path)
    if not isinstance(body, dict):
        return problem(400, "Request body must be a JSON object", instance=request.url.path)
    merged = _deep_merge(_read_prefs(), body)
    _write_prefs(merged)
    return merged


# Who the microphone belongs to. The recorder used to hardcode one person's
# name as the mic speaker, which meant every transcript on every machine was
# labelled with it. It is the symmetric twin of recorder.participant_name (the
# person on the other end), and it reads from the same preferences file, so the
# name lives in local data instead of the source.
OWNER_FALLBACK = "Me"


def owner_name() -> str:
    """Display name for the mic channel, from recorder.owner_name."""
    recorder = _read_prefs().get("recorder") or {}
    name = recorder.get("owner_name")
    return name.strip() if isinstance(name, str) and name.strip() else OWNER_FALLBACK
