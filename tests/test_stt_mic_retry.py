"""Mic-start retry — the heal for a stale PortAudio device snapshot.

A server started before Windows' audio endpoints were ready (boot race
after an update reboot, post-sleep self-restart before the wireless
dongle re-enumerated) sees a frozen device list — default input resolves
to -1 and every record press fails until manual restart (2026-07-22).
MicCapture.start() must refresh PortAudio and retry once, at press time.
"""

import pytest

import api.recorder.capture as capture_mod
from tools.stt.audio import MicCapture


class FakeCapture:
    """Stands in for DualStreamCapture; behavior driven by the plan list."""

    plan: list = []  # each entry: "resolve-fail" | "open-fail" | "ok"

    def __init__(self, mic_device_index=None, sys_device_index=None):
        self.mode = FakeCapture.plan.pop(0)
        self.stopped = False
        if self.mode == "resolve-fail":
            raise Exception("Error querying device -1")
        self.mic_sample_rate = 16000

    def start(self):
        pass

    def wait_mic_ready(self, timeout=1.5):
        return self.mode == "ok"

    def stop_mic_and_drain(self, timeout=1.5):
        self.stopped = True
        return True

    def mic_blocks(self):
        return []

    @property
    def errors(self):
        return ["mic: stream open failed"] if self.mode == "open-fail" else []

    @property
    def mic_device_name(self):
        return "fake mic"


@pytest.fixture
def fake_capture(monkeypatch):
    refreshes = []
    monkeypatch.setattr(capture_mod, "DualStreamCapture", FakeCapture)
    monkeypatch.setattr(
        capture_mod, "refresh_portaudio", lambda: refreshes.append(1)
    )
    return refreshes


class TestMicStartRetry:
    def test_healthy_start_never_refreshes(self, fake_capture):
        FakeCapture.plan = ["ok"]
        mic = MicCapture()
        mic.start()
        assert mic.is_recording
        assert fake_capture == []
        mic.discard_inflight()

    def test_resolution_failure_refreshes_and_retries(self, fake_capture):
        FakeCapture.plan = ["resolve-fail", "ok"]
        mic = MicCapture()
        mic.start()
        assert mic.is_recording
        assert fake_capture == [1]
        mic.discard_inflight()

    def test_dead_stream_refreshes_and_retries(self, fake_capture):
        # Device resolved but the stream never went live — dead-air trap.
        FakeCapture.plan = ["open-fail", "ok"]
        mic = MicCapture()
        mic.start()
        assert mic.is_recording
        assert fake_capture == [1]
        mic.discard_inflight()

    def test_second_failure_propagates(self, fake_capture):
        FakeCapture.plan = ["resolve-fail", "resolve-fail"]
        mic = MicCapture()
        with pytest.raises(Exception, match="device -1"):
            mic.start()
        assert not mic.is_recording
        assert fake_capture == [1]
