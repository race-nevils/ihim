"""faster-whisper integration + transcript merging.

Lazy-loads the model on first use (~74MB for 'base'). Transcribes each
channel independently with a speaker label, then merges chronologically.
"""

import threading
from pathlib import Path
from typing import Optional

_model_cache: dict = {}
_model_lock = threading.Lock()


def _get_model(model_size: str = "base"):
    """Lazy-load and cache a faster-whisper model."""
    if model_size in _model_cache:
        return _model_cache[model_size]

    with _model_lock:
        if model_size in _model_cache:
            return _model_cache[model_size]

        from faster_whisper import WhisperModel

        print(f"[recorder] Loading faster-whisper model '{model_size}'...")
        model = WhisperModel(model_size, device="cpu", compute_type="int8")
        _model_cache[model_size] = model
        print(f"[recorder] Model '{model_size}' loaded.")
        return model


def transcribe_channel(
    wav_path: Path,
    speaker_label: str,
    model_size: str = "base",
) -> list[dict]:
    """Transcribe a single WAV file, returning labeled segments.

    Returns list of:
        {"speaker": str, "start": float, "end": float, "text": str, "confidence": float}
    """
    model = _get_model(model_size)

    segments_iter, info = model.transcribe(
        str(wav_path),
        beam_size=5,
        vad_filter=True,
        vad_parameters=dict(
            min_silence_duration_ms=500,
            speech_pad_ms=200,
        ),
    )

    results = []
    for seg in segments_iter:
        text = seg.text.strip()
        if not text:
            continue
        results.append({
            "speaker": speaker_label,
            "start": round(seg.start, 2),
            "end": round(seg.end, 2),
            "text": text,
            "confidence": round(1.0 - seg.no_speech_prob, 4),
        })

    return results


def merge_transcripts(
    mic_segments: list[dict],
    sys_segments: list[dict],
) -> list[dict]:
    """Merge two speaker channels chronologically by start time."""
    combined = mic_segments + sys_segments
    combined.sort(key=lambda s: s["start"])
    return combined


def format_transcript(segments: list[dict]) -> str:
    """Format merged segments into human-readable dialogue.

    Example: [the operator 0:00]: Hello there
             [Other 0:03]: Hey, how's it going?
    """
    lines = []
    for seg in segments:
        minutes = int(seg["start"] // 60)
        seconds = int(seg["start"] % 60)
        ts = f"{minutes}:{seconds:02d}"
        lines.append(f"[{seg['speaker']} {ts}]: {seg['text']}")
    return "\n".join(lines)


def transcribe_dual(
    mic_wav: Path,
    sys_wav: Path,
    mic_label: str = "the operator",
    sys_label: str = "Other",
    model_size: str = "base",
) -> dict:
    """Full transcription pipeline: both channels → merge → format.

    Returns:
        {
            "segments": [...],
            "transcript": "formatted text",
            "mic_segments_count": int,
            "sys_segments_count": int,
        }
    """
    mic_segments = transcribe_channel(mic_wav, mic_label, model_size)
    sys_segments = transcribe_channel(sys_wav, sys_label, model_size)

    merged = merge_transcripts(mic_segments, sys_segments)
    formatted = format_transcript(merged)

    return {
        "segments": merged,
        "transcript": formatted,
        "mic_segments_count": len(mic_segments),
        "sys_segments_count": len(sys_segments),
    }
