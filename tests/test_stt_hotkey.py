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
    """Listener with resolved keys, scripted on_start acks, scripted mic liveness."""

    def __init__(self, ack=True):
        self.starts = 0
        self.stops = 0
        self.locks = 0
        self.live = False  # what is_live reports (the engine's mic ground truth)
        self._ack = ack
        self.listener = HotkeyListener(
            on_start=self._on_start,
            on_stop=self._on_stop,
            hotkey=("Key.ctrl_l", "Key.cmd"),
            lock_key="Key.ctrl_r",
            stop_key="Key.ctrl_r",
            on_locked=self._on_locked,
            is_live=lambda: self.live,
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
        h.listener._last_toggle_time = time.time() - 1.0  # talked a beat while locked
        h.press(CTRL_R)  # stop key
        assert not h.listener.is_locked
        assert not h.listener.is_recording
        assert h.stops == 1

    def test_phantom_duplicate_lock_key_does_not_stop(self):
        # THE cold-start bug: lock_key == stop_key, so a duplicate/phantom
        # action-key press (the pynput hook emits these under the heavy GPU
        # load of a warm-up) toggled lock -> stop the instant it locked,
        # ending the dictation. The toggle debounce swallows the duplicate.
        h = Harness(ack=True)
        h.press(CTRL_L, CMD)
        h.listener._last_key_time = time.time() - 5.0  # long warm-up hold
        h.press(CTRL_R)  # intended lock
        assert h.listener.is_locked
        h.press(CTRL_R)  # phantom duplicate arriving milliseconds later
        assert h.listener.is_locked  # still locked, not stopped
        assert h.listener.is_recording
        assert h.stops == 0

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
        # (not an action key) clears the stuck recording state — but only
        # when the mic is NOT live (is_live False = genuinely stuck).
        h = Harness(ack=True)
        h.press(CTRL_L, CMD)
        assert h.listener.is_recording
        h.listener._last_key_time = time.time() - 5.0
        h.press(CTRL_L)  # ordinary key after the stale gap
        # Guard cleared the stuck state; a fresh full chord re-acks.
        assert h.starts >= 1


class TestColdStartGuardMisfire:
    """THE cold-start dead-release bug (2026-07-31).

    A cold press blocks the hook thread ~4s inside on_start (mic device
    open under model-load load); the queued duplicate press of a held
    chord key then lands >2s after the last key event and trips the
    stale-key guard, clearing _recording while the mic is live. The
    release then did nothing: mute stuck, dictation never processed,
    until the next chord press+release re-acked and swept everything.
    Same root kills lock mode — _recording cleared before the lock key
    processes, so the lock never engages and the stop key falls through.
    """

    def test_stale_guard_spares_live_recording(self):
        h = Harness(ack=True)
        h.press(CTRL_L, CMD)
        h.live = True  # mic capturing — the engine's ground truth
        h.listener._last_key_time = time.time() - 5.0  # hook thread starved
        h.press(CMD)  # queued duplicate of a held chord key
        assert h.listener.is_recording  # guard must NOT clear a live dictation
        h.release(CTRL_L)
        assert h.stops == 1  # release still processes

    def test_lock_still_engages_after_guard_window(self):
        # Lock-mode variant: duplicate chord press in the stale window,
        # then the real lock press — lock must engage, stop must work.
        h = Harness(ack=True)
        h.press(CTRL_L, CMD)
        h.live = True
        h.listener._last_key_time = time.time() - 5.0
        h.press(CMD)  # queued duplicate
        h.press(CTRL_R)  # lock
        assert h.listener.is_locked
        h.release(CTRL_L, CMD)
        h.listener._last_toggle_time = time.time() - 1.0
        h.press(CTRL_R)  # stop
        assert h.stops == 1

    def test_release_stops_live_mic_even_when_flag_desynced(self):
        # Backstop: whatever cleared _recording, releasing the chord over
        # a live mic must still stop (the engine claims the mic atomically,
        # so a duplicate stop is a no-op on its side).
        h = Harness(ack=True)
        h.press(CTRL_L, CMD)
        h.live = True
        h.listener._recording = False  # any desync path
        h.release(CTRL_L)
        assert h.stops == 1

    def test_release_with_idle_mic_stays_noop(self):
        # Normal typing: a bare ctrl release with nothing recording must
        # not invoke the stop path at all.
        h = Harness(ack=True)
        h.release(CTRL_L)
        assert h.stops == 0
