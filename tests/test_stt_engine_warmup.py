"""Unit tests for record-while-warming (cold-start hotkey smoothness).

A cold chord press used to warm the model and swallow itself — plus
every press after it until the load landed, with no feedback. Now the
mic starts immediately and the model loads in parallel; no press is
ever swallowed waiting for warm. No GPU, no mic, no pynput — engine
collaborators are stubbed.
"""

import sys
import threading
import time
import types

import pytest

import api.recorder.transcribe as transcribe
from tools.stt.engine import STTEngine

CONFIG = {"model": "test-model", "idle_timeout_s": 600}


class FakeMic:
    def __init__(self):
        self.started = 0

    def start(self):
        self.started += 1

    @property
    def is_recording(self):
        return self.started > 0


class FakeStreamer:
    def __init__(self, mic, model_name):
        pass

    def start(self):
        pass


class FakeListener:
    def __init__(self, recording=False, locked=False):
        self.is_recording = recording
        self.is_locked = locked


@pytest.fixture
def engine(monkeypatch):
    eng = STTEngine(config=dict(CONFIG))
    eng._mic = FakeMic()
    monkeypatch.setattr(
        "tools.stt.app_context.get_active_app_context", lambda: "prose"
    )
    monkeypatch.setattr("tools.stt.streaming.ChunkedTranscriber", FakeStreamer)
    monkeypatch.setattr(eng, "_mute_audio", lambda mute: None)
    # Fresh sleep baseline so _system_slept() never trips in tests
    import tools.stt.engine as engine_mod
    engine_mod._system_slept()
    return eng


class TestRecordWhileWarming:
    def test_cold_press_records_immediately(self, engine, monkeypatch):
        load_gate = threading.Event()
        loads = []

        def fake_get_model(name):
            load_gate.wait(timeout=5)
            loads.append(name)

        monkeypatch.setattr(transcribe, "is_model_loaded", lambda name: False)
        monkeypatch.setattr(transcribe, "_get_model", fake_get_model)

        assert engine._on_record_start() is True  # press is honored, not swallowed
        assert engine._mic.started == 1
        assert engine._warming_up is True

        load_gate.set()
        deadline = time.time() + 5
        while engine._warming_up and time.time() < deadline:
            time.sleep(0.01)
        assert loads == ["test-model"]

    def test_press_during_load_also_records_without_second_warmup(
        self, engine, monkeypatch
    ):
        load_gate = threading.Event()
        loads = []

        def fake_get_model(name):
            load_gate.wait(timeout=5)
            loads.append(name)

        monkeypatch.setattr(transcribe, "is_model_loaded", lambda name: False)
        monkeypatch.setattr(transcribe, "_get_model", fake_get_model)

        assert engine._on_record_start() is True
        # Model still loading — a second press (after release) must record
        # too, and must not spawn a second warm-up thread.
        assert engine._on_record_start() is True
        assert engine._mic.started == 2

        load_gate.set()
        deadline = time.time() + 5
        while engine._warming_up and time.time() < deadline:
            time.sleep(0.01)
        assert loads == ["test-model"]  # exactly one load

    def test_status_recording_outranks_loading(self, engine):
        engine._warming_up = True
        engine._listener = FakeListener(recording=True)
        assert engine.status == "recording"
        engine._listener = FakeListener(recording=False)
        assert engine.status == "loading"

    def test_warmup_completion_mid_recording_does_not_stomp_status(
        self, engine, monkeypatch
    ):
        monkeypatch.setattr(transcribe, "_get_model", lambda name: None)
        engine._listener = FakeListener(recording=True)
        broadcast = []
        engine.set_state_callback(broadcast.append)

        engine._warming_up = True
        engine._warm_up_model("test-model")

        assert "warm" not in broadcast  # SSE never saw warm mid-recording
        assert engine._status == "warm"  # internal state still advanced
        assert engine._warming_up is False


class TestSingleFlightModelLoad:
    """_get_model must not construct duplicates under a warm-up race."""

    @pytest.fixture(autouse=True)
    def isolate(self, monkeypatch):
        monkeypatch.setattr(transcribe, "_model_cache", {})
        monkeypatch.setattr(transcribe, "_loading_events", {})
        monkeypatch.setattr(transcribe, "_pick_device", lambda name: ("cpu", "int8"))
        monkeypatch.setattr(transcribe, "_check_system_sleep", lambda: False)

    def _install_fake_whisper(self, monkeypatch, constructions, delay_s=0.2,
                              fail_first=False):
        class FakeWhisperModel:
            def __init__(self, name, device=None, compute_type=None):
                n = len(constructions)
                constructions.append(name)
                time.sleep(delay_s)
                if fail_first and n == 0:
                    raise RuntimeError("constructor blew up")
                self.model = types.SimpleNamespace(model_is_loaded=True)

        monkeypatch.setitem(
            sys.modules, "faster_whisper",
            types.SimpleNamespace(WhisperModel=FakeWhisperModel),
        )

    def test_concurrent_callers_construct_once(self, monkeypatch):
        constructions = []
        self._install_fake_whisper(monkeypatch, constructions)

        results = []
        threads = [
            threading.Thread(target=lambda: results.append(transcribe._get_model("tiny")))
            for _ in range(3)
        ]
        for t in threads:
            t.start()
            time.sleep(0.02)  # leader wins the loading-event registration
        for t in threads:
            t.join(timeout=10)

        assert len(constructions) == 1
        assert len(results) == 3
        assert all(r is results[0] for r in results)

    def test_leader_failure_does_not_strand_followers(self, monkeypatch):
        constructions = []
        self._install_fake_whisper(monkeypatch, constructions, fail_first=True)

        results, errors = [], []

        def call():
            try:
                results.append(transcribe._get_model("tiny"))
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=call)
        t2 = threading.Thread(target=call)
        t1.start()
        time.sleep(0.02)
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        # Leader raised; follower woke up and loaded its own copy.
        assert len(errors) == 1
        assert len(results) == 1
        assert results[0] is not None
