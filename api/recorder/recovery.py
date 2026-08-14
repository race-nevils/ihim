"""Crash recovery for orphaned recordings.

On server startup, scans for .in-progress/ directories left behind by a crash.
Assembles raw PCM chunks into final WAV files and creates sidecar metadata
with status "recovered".
"""

import json
import logging
import os
import shutil
import wave
from pathlib import Path

from api.preferences import owner_name

logger = logging.getLogger(__name__)

TARGET_RATE = 16000


def _get_numpy():
    import numpy as np
    return np


def recover_orphaned_recordings(recordings_dir: Path) -> list[dict]:
    """Scan for orphaned .in-progress/ directories and recover them.

    Called during FastAPI lifespan startup.

    Returns:
        List of dicts describing each recovered recording.
    """
    in_progress_dir = recordings_dir / ".in-progress"
    if not in_progress_dir.exists():
        return []

    recovered = []
    for rec_dir in sorted(in_progress_dir.iterdir()):
        if not rec_dir.is_dir():
            continue
        manifest_path = rec_dir / "manifest.json"
        if not manifest_path.exists():
            logger.warning("No manifest in %s, skipping", rec_dir.name)
            continue

        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            result = _recover_recording(rec_dir, manifest, recordings_dir)
            if result:
                recovered.append(result)
        except Exception as e:
            logger.error("Failed to recover %s: %s", rec_dir.name, e)

    # Remove .in-progress parent if empty
    if in_progress_dir.exists() and not any(in_progress_dir.iterdir()):
        in_progress_dir.rmdir()

    return recovered


def _recover_recording(rec_dir: Path, manifest: dict, recordings_dir: Path) -> dict:
    """Assemble chunk files from a single orphaned recording into final WAVs."""
    np = _get_numpy()
    rec_id = manifest["rec_id"]
    sample_rate = manifest.get("sample_rate", TARGET_RATE)

    mic_chunks = _read_chunks(rec_dir, "mic", manifest.get("mic_chunks", 0))
    sys_chunks = _read_chunks(rec_dir, "sys", manifest.get("sys_chunks", 0))

    # Write recovered WAV files
    mic_path = recordings_dir / f"recording-{rec_id}-mic.wav"
    sys_path = recordings_dir / f"recording-{rec_id}-sys.wav"

    _write_recovered_wav(mic_path, mic_chunks, sample_rate)
    _write_recovered_wav(sys_path, sys_chunks, sample_rate)

    # Calculate duration from mic audio
    total_samples = sum(len(c) for c in mic_chunks)
    duration = total_samples / sample_rate if sample_rate > 0 else 0

    # Write sidecar with "recovered" status
    sidecar = {
        "recording_id": rec_id,
        "label": None,
        "started_at": manifest.get("started_at"),
        "ended_at": None,
        "duration_seconds": round(duration, 1),
        "config": {
            "model_size": "small",
            "sample_rate": sample_rate,
            "mic_device": manifest.get("mic_device", "unknown"),
            "sys_device": manifest.get("sys_device", "unknown"),
        },
        "speakers": {"mic": owner_name(), "system": "Other"},
        "segments": [],
        "transcript": "",
        "wav_mic": mic_path.name,
        "wav_sys": sys_path.name,
        "status": "pending_transcription",
    }

    sidecar_path = recordings_dir / f"recording-{rec_id}.json"
    tmp = sidecar_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(sidecar, indent=2), encoding="utf-8")
    os.replace(str(tmp), str(sidecar_path))

    # Clean up in-progress directory
    shutil.rmtree(rec_dir, ignore_errors=True)

    logger.info(
        "Recovered recording %s: %d mic chunks, %d sys chunks, %.1fs",
        rec_id, manifest.get("mic_chunks", 0),
        manifest.get("sys_chunks", 0), duration,
    )

    return {
        "recording_id": rec_id,
        "mic_chunks": manifest.get("mic_chunks", 0),
        "sys_chunks": manifest.get("sys_chunks", 0),
        "duration_seconds": round(duration, 1),
    }


def _read_chunks(rec_dir: Path, stream: str, count: int) -> list:
    """Read raw PCM chunk files and return as list of int16 numpy arrays."""
    np = _get_numpy()
    chunks = []
    for i in range(count):
        chunk_path = rec_dir / f"{stream}-chunk-{i:04d}.raw"
        if chunk_path.exists():
            raw = chunk_path.read_bytes()
            chunks.append(np.frombuffer(raw, dtype=np.int16))
    return chunks


def _write_recovered_wav(path: Path, chunks: list, sample_rate: int) -> None:
    """Concatenate int16 PCM chunks and write as WAV."""
    path.parent.mkdir(parents=True, exist_ok=True)

    if not chunks:
        with wave.open(str(path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(b"")
        return

    np = _get_numpy()
    final_pcm = np.concatenate(chunks)

    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(final_pcm.tobytes())
