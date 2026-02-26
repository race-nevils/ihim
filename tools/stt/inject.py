"""Text injection into the active window via pynput."""

import logging
import time

logger = logging.getLogger(__name__)

# Delay before typing to allow focus to return to the target window
FOCUS_DELAY_S = 0.15


def inject_text(text: str) -> None:
    """Type text into the currently focused window.

    Args:
        text: The text to inject.
    """
    if not text:
        return

    from pynput.keyboard import Controller

    time.sleep(FOCUS_DELAY_S)
    kb = Controller()
    kb.type(text)
    logger.info("Injected %d characters", len(text))
