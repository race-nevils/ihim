"""Hold-to-record hotkey listener using pynput.

Reuses stale-key guard pattern from tools/capture_widget/widget.pyw.
Default hotkey: Left Ctrl + Windows key chord (hold both to record,
release either to process).

Supports single-key mode (str) and chord mode (tuple of str).
"""

import logging
import threading
import time
from typing import Callable, Optional, Tuple, Union

logger = logging.getLogger(__name__)

# Default: Left Ctrl + Windows key chord (matches Whisper Flow)
DEFAULT_HOTKEY: Tuple[str, ...] = ("Key.ctrl_l", "Key.cmd")


class HotkeyListener:
    """Hold-to-record listener using pynput.

    Single-key mode: press target key → start, release → stop.
    Chord mode: hold ALL chord keys → start, release ANY → stop.
    """

    def __init__(
        self,
        on_start: Callable[[], None],
        on_stop: Callable[[], None],
        hotkey: Union[str, Tuple[str, ...]] = DEFAULT_HOTKEY,
    ):
        self._on_start = on_start
        self._on_stop = on_stop
        self._hotkey = hotkey
        self._is_chord = isinstance(hotkey, (tuple, list))
        self._listener: Optional[object] = None
        self._recording = False
        self._lock = threading.Lock()

        # Stale-key guard state
        self._current_keys: set = set()
        self._last_key_time: float = 0.0

    def start(self) -> None:
        """Start the hotkey listener as a daemon thread."""
        if self._listener is not None:
            logger.warning("HotkeyListener already running")
            return

        from pynput import keyboard as pynput_keyboard

        # Resolve target keys
        if self._is_chord:
            target_keys = frozenset(
                self._resolve_key(k) for k in self._hotkey
            )
        else:
            target_keys = frozenset([self._resolve_key(self._hotkey)])

        def on_press(key):
            try:
                now = time.time()
                # Stale-key guard: clear if no activity for 2s or set suspiciously large
                if (now - self._last_key_time > 2.0) or len(self._current_keys) > 4:
                    self._current_keys.clear()
                self._last_key_time = now
                self._current_keys.add(key)

                # Check if ALL target keys are currently held
                if target_keys.issubset(self._current_keys):
                    with self._lock:
                        if not self._recording:
                            self._recording = True
                            self._on_start()
            except Exception as e:
                logger.debug("Hotkey on_press error: %s", e)

        def on_release(key):
            try:
                self._current_keys.discard(key)
                # If recording and ANY target key released → stop
                if key in target_keys:
                    with self._lock:
                        if self._recording:
                            self._recording = False
                            self._on_stop()
            except Exception as e:
                logger.debug("Hotkey on_release error: %s", e)

        self._listener = pynput_keyboard.Listener(
            on_press=on_press,
            on_release=on_release,
            suppress=False,
        )
        self._listener.daemon = True
        self._listener.start()
        hotkey_display = " + ".join(self._hotkey) if self._is_chord else self._hotkey
        logger.info("Hotkey listener started: %s (hold to record)", hotkey_display)

    def stop(self) -> None:
        """Stop the hotkey listener."""
        if self._listener is not None:
            self._listener.stop()
            self._listener = None
            self._recording = False
            logger.info("Hotkey listener stopped")

    @property
    def is_running(self) -> bool:
        return self._listener is not None and self._listener.is_alive()

    @property
    def is_recording(self) -> bool:
        return self._recording

    @staticmethod
    def _resolve_key(hotkey_str: str):
        """Resolve a hotkey string to a pynput Key object."""
        from pynput import keyboard as pynput_keyboard

        # Handle pynput Key enum values like "Key.ctrl_r"
        if hotkey_str.startswith("Key."):
            attr = hotkey_str[4:]
            return getattr(pynput_keyboard.Key, attr)

        # Handle single character keys
        if len(hotkey_str) == 1:
            return pynput_keyboard.KeyCode.from_char(hotkey_str)

        # Fallback: try as Key attribute directly
        return getattr(pynput_keyboard.Key, hotkey_str, None)
