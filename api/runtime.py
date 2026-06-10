"""Process-level runtime state shared across API modules.

One tiny module so main.py and server.py don't import each other.
"""

import time
import uuid
from pathlib import Path

IHIM_DIR = Path(__file__).resolve().parents[1]
UI_DIR = IHIM_DIR / "ui"
DATA_DIR = IHIM_DIR / "data"
PID_PATH = DATA_DIR / "server.pid"

# Regenerated on every server start — drives frontend cache busting.
BOOT_ID = uuid.uuid4().hex[:8]

_started_monotonic: float | None = None


def mark_started() -> None:
    global _started_monotonic
    _started_monotonic = time.monotonic()


def uptime_seconds() -> float | None:
    if _started_monotonic is None:
        return None
    return round(time.monotonic() - _started_monotonic, 1)
