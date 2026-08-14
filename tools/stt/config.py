"""Dictation engine configuration.

Loads from stt_bar.json (filename is historical — it once configured a
floating Tk bar that no longer exists); creates the file with defaults on
first run so hotkeys/model/timeouts are easy to customize.
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).parent / "stt_bar.json"

DEFAULT_CONFIG = {
    "hotkey": ["Key.ctrl_l", "Key.cmd"],
    "lock_key": "Key.ctrl_r",
    "stop_key": "Key.ctrl_r",
    "model": "large-v3-turbo",
    "idle_timeout_s": 600,
    "mute_on_dictate": True,
    "injection": {
        "method": "auto",
    },
    "audio_retention": {
        "enabled": False,
        "format": "flac",
    },
    "sounds": {
        "enabled": True,
        "success": True,
        "error": True,
        "locked": True,
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge *override* into a copy of *base*."""
    merged = base.copy()
    for key, val in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(val, dict):
            merged[key] = _deep_merge(merged[key], val)
        else:
            merged[key] = val
    return merged


def load_config() -> dict:
    """Load config from stt_bar.json, falling back to defaults.

    Creates stt_bar.json with defaults on first run so hotkeys, timeouts
    and appearance are easy to customize.
    """
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                user_config = json.load(f)
            return _deep_merge(DEFAULT_CONFIG, user_config)
        except Exception:
            logger.warning("Failed to load %s, using defaults", CONFIG_PATH, exc_info=True)
    else:
        # First run — write defaults to disk for easy customization
        save_config(DEFAULT_CONFIG)
        logger.info("Created default config at %s", CONFIG_PATH)
    return DEFAULT_CONFIG.copy()


def save_config(config: dict) -> None:
    """Persist the current config to disk."""
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
    except Exception:
        logger.warning("Failed to save config to %s", CONFIG_PATH, exc_info=True)
