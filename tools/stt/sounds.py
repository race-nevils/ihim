"""Sound feedback for dictation events via winsound.Beep().

All sounds run in daemon threads so they never block the pipeline.
Configurable via the "sounds" section in stt_bar.json.
"""

import logging
import threading

logger = logging.getLogger(__name__)


def _beep(frequency: int, duration_ms: int) -> None:
    """Play a beep in a daemon thread (non-blocking)."""
    def _play():
        try:
            import winsound
            winsound.Beep(frequency, duration_ms)
        except Exception as exc:
            logger.debug("Beep failed: %s", exc)

    threading.Thread(target=_play, daemon=True, name="stt-beep").start()


def _sounds_enabled(cfg: dict, key: str) -> bool:
    """Check if a specific sound type is enabled in config."""
    sounds = cfg.get("sounds", {})
    return sounds.get("enabled", True) and sounds.get(key, True)


def play_success(cfg: dict) -> None:
    """Pleasant ding after successful injection."""
    if _sounds_enabled(cfg, "success"):
        _beep(880, 80)


def play_error(cfg: dict) -> None:
    """Low tone on pipeline failure."""
    if _sounds_enabled(cfg, "error"):
        _beep(300, 200)


def play_locked(cfg: dict) -> None:
    """Two quick high beeps when lock mode engages."""
    if _sounds_enabled(cfg, "locked"):
        def _double_high():
            try:
                import winsound
                winsound.Beep(1200, 60)
                import time
                time.sleep(0.04)
                winsound.Beep(1500, 60)
            except Exception as exc:
                logger.debug("Lock beep failed: %s", exc)

        threading.Thread(target=_double_high, daemon=True, name="stt-lock").start()
