"""Hold-to-record hotkey listener using pynput.

Default hotkey: Left Ctrl + Windows key chord (hold both to record,
release either to process). Supports single-key mode (str) and chord
mode (tuple of str).

Lock mode (Sticky Keys pattern): while recording, press the lock key to
keep recording after releasing the chord. Press the stop key to finish
and trigger the pipeline.

``on_start`` must return True only if recording actually began.
``_recording`` follows that ack — a chord press that gets swallowed
post-sleep or errors on mic start leaves the listener idle, so the
lock key can never lock a recording that doesn't exist (the "fast
lock after cold press" dead-hotkey ghost state).

``is_live`` is the reverse channel: the owner reports whether a
recording is genuinely capturing right now. The listener's own flag
can desync from reality (the stale-key guard clearing a live
dictation), and ground truth from the mic outranks event-timing
heuristics on both the guard and the release path.
"""

import logging
import threading
import time
from typing import Callable, Optional, Tuple, Union

logger = logging.getLogger(__name__)

# Default: Left Ctrl + Windows key chord (matches Whisper Flow)
DEFAULT_HOTKEY: Tuple[str, ...] = ("Key.ctrl_l", "Key.cmd")

# No key events for this long → treat held-key state as stale.
_STALE_AFTER_S = 2.0

# Ignore a lock/stop key event this soon after the previous lock/stop.
# With lock_key == stop_key the action is a toggle, so a phantom/duplicate
# press (the pynput hook emits these under heavy load — e.g. the GPU model
# load during a cold-start warm-up) double-toggles lock → stop and ends the
# dictation the instant it locks. the operator never toggles this fast on purpose.
_TOGGLE_DEBOUNCE_S = 0.4


class HotkeyListener:
    """Hold-to-record listener using pynput.

    Single-key mode: press target key → start, release → stop.
    Chord mode: hold ALL chord keys → start, release ANY → stop.
    """

    def __init__(
        self,
        on_start: Callable[[], bool],
        on_stop: Callable[[], None],
        hotkey: Union[str, Tuple[str, ...]] = DEFAULT_HOTKEY,
        lock_key: Optional[str] = None,
        stop_key: Optional[str] = None,
        on_locked: Optional[Callable[[], None]] = None,
        is_live: Optional[Callable[[], bool]] = None,
    ):
        self._on_start = on_start
        self._on_stop = on_stop
        self._on_locked = on_locked
        self._is_live = is_live
        self._hotkey = hotkey
        self._is_chord = isinstance(hotkey, (tuple, list))
        self._lock_key_str = lock_key
        self._stop_key_str = stop_key
        self._listener: Optional[object] = None
        self._recording = False
        self._locked = False
        self._lock = threading.Lock()

        # Resolved at start() — pynput key objects
        self._target_keys: frozenset = frozenset()
        self._lock_key = None
        self._stop_key = None

        # Stale-key guard state
        self._current_keys: set = set()
        self._last_key_time: float = 0.0
        # Toggle-debounce state (last time a lock/stop action fired)
        self._last_toggle_time: float = 0.0

    def start(self) -> None:
        """Resolve keys and start the pynput listener as a daemon thread."""
        if self._listener is not None:
            logger.warning("HotkeyListener already running")
            return

        from pynput import keyboard as pynput_keyboard

        self._resolve_keys()
        self._listener = pynput_keyboard.Listener(
            on_press=self._handle_press,
            on_release=self._handle_release,
            suppress=False,
        )
        self._listener.daemon = True
        self._listener.start()

        hotkey_display = " + ".join(self._hotkey) if self._is_chord else self._hotkey
        lock_display = (
            f", lock: {self._lock_key_str}, stop: {self._stop_key_str}"
            if self._lock_key else ""
        )
        logger.info("Hotkey listener started: %s (hold to record%s)",
                    hotkey_display, lock_display)

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

    # ------------------------------------------------------------------
    # Key event handlers (methods, not closures — unit-testable)
    # ------------------------------------------------------------------

    def _resolve_keys(self) -> None:
        if self._is_chord:
            self._target_keys = frozenset(self._resolve_key(k) for k in self._hotkey)
        else:
            self._target_keys = frozenset([self._resolve_key(self._hotkey)])
        self._lock_key = self._resolve_key(self._lock_key_str) if self._lock_key_str else None
        self._stop_key = self._resolve_key(self._stop_key_str) if self._stop_key_str else None

    def _handle_press(self, key) -> None:
        try:
            now = time.time()
            # Stale-key guard: clear if no activity or set suspiciously large.
            if (now - self._last_key_time > _STALE_AFTER_S) or len(self._current_keys) > 4:
                self._current_keys.clear()
                # Clear stuck recording state (e.g. system slept mid-recording).
                # Skip when the incoming key is the lock/stop key during active
                # recording — pynput doesn't repeat-fire while the chord is held,
                # so a >2s hold before tapping the lock key looks identical to
                # stale state. Action-key presses are proof of liveness.
                # (bug note 2026-05-01_stt-stale-key-guard-breaks-lock-during-long-hold)
                is_action_key = (
                    (self._lock_key is not None and key == self._lock_key)
                    or (self._stop_key is not None and key == self._stop_key)
                )
                with self._lock:
                    if self._recording and not self._locked and not is_action_key:
                        # A live mic outranks the timing heuristic: a cold-start
                        # model load blocks the hook thread for seconds inside
                        # on_start, so the queued duplicate press of a held
                        # chord key arrives >2s after the last event and looks
                        # exactly like stale state — clearing here killed the
                        # release (mute stuck, dictation never processed) until
                        # the next chord press re-acked (2026-07-31).
                        if self._is_live is not None and self._is_live():
                            logger.debug(
                                "Stale-key guard: mic is live — keeping recording state"
                            )
                        else:
                            logger.info("Stale-key guard: cleared stuck recording state")
                            self._recording = False
            self._last_key_time = now
            self._current_keys.add(key)

            with self._lock:
                # Debounce the lock/stop toggle: swallow a duplicate/phantom
                # action-key press that lands within the window of the last
                # toggle (would otherwise flip lock → stop the instant it locks).
                is_action_press = (
                    (self._lock_key is not None and key == self._lock_key)
                    or (self._stop_key is not None and key == self._stop_key)
                )
                if is_action_press and now - self._last_toggle_time <= _TOGGLE_DEBOUNCE_S:
                    return

                # Lock mode: stop_key pressed while locked → stop recording
                if self._locked and self._stop_key is not None and key == self._stop_key:
                    self._last_toggle_time = now
                    self._locked = False
                    self._recording = False
                    self._on_stop()
                    return

                # Lock mode: lock_key pressed while recording → lock
                if (self._recording and not self._locked
                        and self._lock_key is not None and key == self._lock_key):
                    self._last_toggle_time = now
                    self._locked = True
                    logger.info("Recording locked — release chord, press stop key to finish")
                    if self._on_locked:
                        self._on_locked()
                    return

                # Normal: ALL target keys held → start, gated on the ack.
                if self._target_keys.issubset(self._current_keys) and not self._recording:
                    self._recording = bool(self._on_start())
        except Exception as e:
            logger.debug("Hotkey on_press error: %s", e)

    def _handle_release(self, key) -> None:
        try:
            self._current_keys.discard(key)
            # If locked, releasing chord keys does NOT stop recording
            if self._locked:
                return
            # Normal: ANY target key released → stop if a recording is live.
            # is_live is the backstop for a desynced _recording flag: whatever
            # cleared it, releasing the chord over a live mic must still stop,
            # unmute, and process — the owner's stop path claims the mic
            # atomically, so a duplicate stop is a no-op there.
            if key in self._target_keys:
                with self._lock:
                    live = self._recording or (
                        self._is_live is not None and self._is_live()
                    )
                    self._recording = False
                    if live:
                        self._on_stop()
        except Exception as e:
            logger.debug("Hotkey on_release error: %s", e)

    @staticmethod
    def _resolve_key(hotkey_str: str):
        """Resolve a hotkey string to a pynput Key object."""
        from pynput import keyboard as pynput_keyboard

        # Handle pynput Key enum values like "Key.ctrl_r"
        if hotkey_str.startswith("Key."):
            return getattr(pynput_keyboard.Key, hotkey_str[4:])

        # Handle single character keys
        if len(hotkey_str) == 1:
            return pynput_keyboard.KeyCode.from_char(hotkey_str)

        # Fallback: try as Key attribute directly
        return getattr(pynput_keyboard.Key, hotkey_str, None)
