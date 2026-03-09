"""Configuration for the floating dictation bar.

Loads from stt_bar.json on first run; creates the file with defaults
if it doesn't exist.  Mirrors the load pattern from capture_widget.
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).parent / "stt_bar.json"

DEFAULT_CONFIG = {
    "hotkey": ["Key.ctrl_r", "Key.shift_r"],
    "model": "large-v3-turbo",
    "idle_timeout_s": 600,
    "position": "bottom_center",
    "offset_y": 80,
    "recording": {
        "max_seconds": 360,
        "warning_seconds": 300,
    },
    "injection": {
        "method": "auto",
        "focus_delay_s": 0.15,
        "restore_delay_s": 0.05,
        "recall_hotkey": "alt+shift+z",
    },
    "audio_retention": {
        "enabled": False,
        "format": "flac",
    },
    "sounds": {
        "enabled": True,
        "success": True,
        "error": True,
        "warning": True,
    },
    "window": {
        "idle_width": 200,
        "idle_height": 36,
        "recording_width": 400,
        "recording_height": 52,
        "opacity": 0.92,
    },
    "appearance": {
        "bg_idle": "#1e1e2e",
        "bg_recording": "#313244",
        "accent": "#89b4fa",
        "accent_recording": "#f38ba8",
        "accent_warning": "#fab387",
        "accent_error": "#f38ba8",
        "accent_loading": "#f9e2af",
        "text_color": "#cdd6f4",
        "font_family": "Segoe UI",
        "font_size": 13,
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

    Creates stt_bar.json with defaults on first run so the operator can
    easily customize hotkeys/timeouts/appearance.
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
