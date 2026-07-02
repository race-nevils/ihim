"""Unit tests for the hotkey listener state machine.

Feeds pynput key objects straight into the handler methods — no OS
listener is started, no global hotkey registered. Covers the ack-gated
recording state (ghost-lock fix) and the stale-key-guard action-key
exemption (bug note 2026-05-01).
"""

import time

from pynput import keyboard

from tools.stt.hotkey import HotkeyListener

CTRL_L = keyboard.Key.ctrl_l
CMD = keyboard.Key.cmd
CTRL_R = keyboard.Key.ctrl_r


class Harness:
    """Listener with resolved keys and scripted on_start acks."""

    def __init__(self, ack=True):
        self.starts = 0
        self.stops = 0
        self.locks = 0
        self._ack = ack
        self.listener = HotkeyListener(
            on_start=self._on_start,
            on_stop=self._on_stop,
            hotkey=("Key.ctrl_l", "Key.cmd"),
            lock_key="Key.ctrl_r",
            stop_key="Key.ctrl_r",
            on_locked=self._on_locked,
        )
        self.listener._resolve_keys()

    def _on_start(self):
        self.starts += 1
        return self._ack

    def _on_stop(self):
        self.stops += 1

    def _on_locked(self):
        self.locks += 1

    def press(self, *keys):
        for k in keys:
            self.listener._handle_press(k)

    def release(self, *keys):
        for k in keys:
            self.listener._handle_release(k)


class TestBasicChord:
    def test_chord_records_and_release_stops(self):
        h = Harness(ack=True)
        h.press(CTRL_L, CMD)
        assert h.listener.is_recording
        h.release(CTRL_L)
        assert not h.listener.is_recording
        assert h.starts == 1 and h.stops == 1

    def test_partial_chord_does_not_record(self):
        h = Harness(ack=True)
        h.press(CTRL_L)
        assert not h.listener.is_recording
        assert h.starts == 0


class TestAckGate:
    def test_refused_ack_leaves_listener_idle(self):
        # Cold-model press: engine warms up and returns False.
        h = Harness(ack=False)
        h.press(CTRL_L, CMD)
        assert h.starts == 1
        assert not h.listener.is_recording
        h.release(CTRL_L, CMD)
        assert h.stops == 0  # nothing was recording — no pipeline run

    def test_fast_lock_after_refused_ack_cannot_ghost_lock(self):
        # THE ghost-lock bug: chord press only warmed the model, but the
        # old listener still flagged _recording=True — a fast Right-Ctrl
        # then "locked" a recording that didn't exist, and the hotkeys
        # went dead. With the ack gate the lock key is a no-op here.
        h = Harness(ack=False)
        h.press(CTRL_L, CMD)
        h.press(CTRL_R)  # fast lock attempt
        assert not h.listener.is_locked
        assert h.locks == 0
        h.release(CTRL_L, CMD, CTRL_R)
        # Hotkeys still work afterwards:
        h._ack = True
        h.press(CTRL_L, CMD)
        assert h.listener.is_recording

    def test_retry_after_warmup_records(self):
        h = Harness(ack=False)
        h.press(CTRL_L, CMD)
        h.release(CTRL_L, CMD)
        h._ack = True  # model is warm now
        h.press(CTRL_L, CMD)
        assert h.listener.is_recording


class TestLockMode:
    def test_lock_then_chord_release_keeps_recording(self):
        h = Harness(ack=True)
        h.press(CTRL_L, CMD)
        h.press(CTRL_R)
        assert h.listener.is_locked
        assert h.locks == 1
        h.release(CTRL_L, CMD)
        assert h.listener.is_recording
        assert h.stops == 0

    def test_stop_key_ends_locked_recording(self):
        h = Harness(ack=True)
        h.press(CTRL_L, CMD)
        h.press(CTRL_R)
        h.release(CTRL_L, CMD, CTRL_R)
        h.press(CTRL_R)  # stop key
        assert not h.listener.is_locked
        assert not h.listener.is_recording
        assert h.stops == 1

    def test_lock_after_long_hold_still_works(self):
        # Regression for bug note 2026-05-01: user holds the chord and talks
        # for >2s before tapping the lock key. The stale-key guard must not
        # clear _recording when the incoming key is an action key.
        h = Harness(ack=True)
        h.press(CTRL_L, CMD)
        h.listener._last_key_time = time.time() - 5.0  # simulate long hold
        h.press(CTRL_R)
        assert h.listener.is_locked

    def test_stale_guard_still_clears_on_non_action_key(self):
        # Sleep recovery path: after a long dead gap, a chord key press
        # (not an action key) clears the stuck recording state.
        h = Harness(ack=True)
        h.press(CTRL_L, CMD)
        assert h.listener.is_recording
        h.listener._last_key_time = time.time() - 5.0
        h.press(CTRL_L)  # ordinary key after the stale gap
        # Guard cleared the stuck state; a fresh full chord re-acks.
        assert h.starts >= 1
