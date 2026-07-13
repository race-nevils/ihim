"""Recorder crash-recovery: checkpoint assembly, boot sweep, timeout scaling."""

import json
import wave
from datetime import datetime, timezone

import numpy as np
import pytest

from api.recorder import routes
from api.recorder.capture import recover_checkpoint


def _write_chunks(chunk_dir, stream, count, samples_per_chunk=8000):
    for i in range(count):
        pcm = (np.sin(np.linspace(0, 100, samples_per_chunk)) * 20000).astype(np.int16)
        (chunk_dir / f"{stream}-chunk-{i:04d}.raw").write_bytes(pcm.tobytes())


def _make_checkpoint(tmp_path, rec_id, mic_chunks=3, sys_chunks=2,
                     mic_rate=16000, sys_rate=48000, started_at=None):
    chunk_dir = tmp_path / ".inprogress" / rec_id
    chunk_dir.mkdir(parents=True)
    _write_chunks(chunk_dir, "mic", mic_chunks)
    _write_chunks(chunk_dir, "sys", sys_chunks)
    manifest = {
        "rec_id": rec_id,
        "started_at": started_at or datetime.now(timezone.utc).isoformat(),
        "mic_sample_rate": mic_rate,
        "sys_sample_rate": sys_rate,
        "mic_chunks": mic_chunks,
        "sys_chunks": sys_chunks,
        "mic_device": "Test Mic",
        "sys_device": "Test Loopback",
    }
    (chunk_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return chunk_dir


def test_recover_checkpoint_assembles_wavs(tmp_path):
    chunk_dir = _make_checkpoint(tmp_path, "20260101-120000")
    mic_path = tmp_path / "mic.wav"
    sys_path = tmp_path / "sys.wav"

    manifest = recover_checkpoint(chunk_dir, mic_path, sys_path)

    assert manifest is not None
    with wave.open(str(mic_path)) as wf:
        assert wf.getframerate() == 16000
        assert wf.getnframes() == 3 * 8000  # all mic chunks landed
    with wave.open(str(sys_path)) as wf:
        assert wf.getframerate() == 48000
        assert wf.getnframes() == 2 * 8000
    # duration = longest channel: mic 24000/16000 = 1.5s vs sys 16000/48000
    assert manifest["duration_seconds"] == 1.5


def test_recover_checkpoint_empty_dir_returns_none(tmp_path):
    chunk_dir = tmp_path / "empty"
    chunk_dir.mkdir()
    assert recover_checkpoint(chunk_dir, tmp_path / "m.wav", tmp_path / "s.wav") is None


@pytest.fixture
def recorder_dirs(tmp_path, monkeypatch):
    recordings = tmp_path / "recordings"
    recordings.mkdir()
    monkeypatch.setattr(routes, "RECORDINGS_DIR", recordings)
    monkeypatch.setattr(routes, "INPROGRESS_DIR", recordings / ".inprogress")
    return recordings


def test_boot_sweep_recovers_interrupted_recording(recorder_dirs, monkeypatch):
    rec_id = "20260101-120000"
    chunk_dir = _make_checkpoint(recorder_dirs, rec_id)
    # Age the manifest past the live-recording guard window
    import os, time
    old = time.time() - 300
    os.utime(chunk_dir / "manifest.json", (old, old))
    # State file from the crashed session
    (recorder_dirs / ".recorder-state.json").write_text(json.dumps({
        "recording_id": rec_id,
        "label": "Crashed call",
        "participant_name": "Mark",
        "model_size": "large-v3",
    }), encoding="utf-8")

    routes._recover_interrupted_recordings()

    sidecar = json.loads((recorder_dirs / f"recording-{rec_id}.json").read_text(encoding="utf-8"))
    assert sidecar["status"] == "pending_transcription"
    assert sidecar["recovered"] is True
    assert sidecar["label"] == "Crashed call"
    assert sidecar["speakers"]["system"] == "Mark"
    assert sidecar["config"]["model_size"] == "large-v3"
    assert (recorder_dirs / f"recording-{rec_id}-mic.wav").exists()
    assert (recorder_dirs / f"recording-{rec_id}-sys.wav").exists()
    assert not chunk_dir.exists()  # consumed
    assert not (recorder_dirs / ".recorder-state.json").exists()  # consumed


def test_boot_sweep_leaves_fresh_checkpoints_alone(recorder_dirs):
    # Fresh manifest = possibly a live recording in another instance
    rec_id = "20260101-130000"
    chunk_dir = _make_checkpoint(recorder_dirs, rec_id)

    routes._recover_interrupted_recordings()

    assert chunk_dir.exists()
    assert not (recorder_dirs / f"recording-{rec_id}.json").exists()


def test_boot_sweep_resets_stuck_transcribing(recorder_dirs):
    sidecar_path = recorder_dirs / "recording-20260101-140000.json"
    sidecar_path.write_text(json.dumps({
        "recording_id": "20260101-140000",
        "status": "transcribing",
        "transcription_stage": "transcribing_mic",
    }), encoding="utf-8")

    routes._reset_stuck_transcriptions()

    data = json.loads(sidecar_path.read_text(encoding="utf-8"))
    assert data["status"] == "pending_transcription"
    assert data["transcription_stage"] is None


def test_transcription_timeout_scales_with_duration():
    assert routes._transcription_timeout(0) == 600      # floor covers model load
    assert routes._transcription_timeout(60) == 600     # short clip stays at floor
    assert routes._transcription_timeout(10800) == 43200  # 3h meeting gets 12h cap
