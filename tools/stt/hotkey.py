"""Hold-to-record hotkey listener using pynput.

Reuses stale-key guard pattern from tools/capture_widget/widget.pyw.
Default hotkey: Left Ctrl + Windows key chord (hold both to record,
release either to process).

Lock mode (Sticky Keys pattern): while recording, press the lock key
to keep recording after releasing the chord. Press the stop key to
finish and trigger the pipeline.

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
        lock_key: Optional[str] = None,
        stop_key: Optional[str] = None,
        on_locked: Optional[Callable[[], None]] = None,
    ):
        self._on_start = on_start
        self._on_stop = on_stop
        self._on_locked = on_locked
        self._hotkey = hotkey
        self._is_chord = isinstance(hotkey, (tuple, list))
        self._lock_key_str = lock_key
        self._stop_key_str = stop_key
        self._listener: Optional[object] = None
        self._recording = False
        self._locked = False
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

        # Resolve lock/stop keys (None if not configured)
        lock_key = self._resolve_key(self._lock_key_str) if self._lock_key_str else None
        stop_key = self._resolve_key(self._stop_key_str) if self._stop_key_str else None

        def on_press(key):
            try:
                now = time.time()
                # Stale-key guard: clear if no activity for 2s or set suspiciously large
                if (now - self._last_key_time > 2.0) or len(self._current_keys) > 4:
                    self._current_keys.clear()
                    # Clear stuck recording state (e.g. system slept mid-recording)
                    with self._lock:
                        if self._recording and not self._locked:
                            logger.info("Stale-key guard: cleared stuck recording state")
                            self._recording = False
                self._last_key_time = now
                self._current_keys.add(key)

                with self._lock:
                    # Lock mode: stop_key pressed while locked → stop recording
                    if self._locked and stop_key is not None and key == stop_key:
                        self._locked = False
                        self._recording = False
                        self._on_stop()
                        return

                    # Lock mode: lock_key pressed while recording (not yet locked) → lock
                    if (self._recording and not self._locked
                            and lock_key is not None and key == lock_key):
                        self._locked = True
                        logger.info("Recording locked — release chord, press stop key to finish")
                        if self._on_locked:
                            self._on_locked()
                        return

                    # Normal: check if ALL target keys are currently held
                    if target_keys.issubset(self._current_keys):
                        if not self._recording:
                            self._recording = True
                            self._on_start()
            except Exception as e:
                logger.debug("Hotkey on_press error: %s", e)

        def on_release(key):
            try:
                self._current_keys.discard(key)
                # If locked, releasing chord keys does NOT stop recording
                if self._locked:
                    return
                # Normal: if recording and ANY target key released → stop
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
        lock_display = f", lock: {self._lock_key_str}, stop: {self._stop_key_str}" if lock_key else ""
        logger.info("Hotkey listener started: %s (hold to record%s)", hotkey_display, lock_display)

    def stop(self) -> None:
        """Stop the hotkey listener."""
        if self._listener is not None:
            self._listener.stop()
            self._listener = None
            self._recording = False
            self._locked = False
            logger.info("Hotkey listener stopped")

    @property
    def is_running(self) -> bool:
        return self._listener is not None and self._listener.is_alive()

    @property
    def is_recording(self) -> bool:
        return self._recording

    @property
    def is_locked(self) -> bool:
        return self._locked

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
