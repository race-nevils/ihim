"""faster-whisper integration + transcript merging.

Lazy-loads the model on first use. Transcribes each channel independently
with a speaker label, then merges chronologically. Uses GPU (CUDA) when
available with automatic CPU fallback if VRAM is insufficient.
"""

import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Optional, Union

# Register NVIDIA CUDA DLL directories so ctranslate2 can find cuBLAS/cuDNN.
# The nvidia-cublas-cu12 pip package installs DLLs into subdirectories that
# aren't on Windows' default DLL search path. We prepend to PATH because
# ctranslate2's C++ runtime uses LoadLibrary which only searches PATH,
# not directories added via os.add_dll_directory().
if sys.platform == "win32":
    _site_packages = Path(sys.prefix) / "Lib" / "site-packages" / "nvidia"
    if _site_packages.exists():
        _nvidia_bins = [str(d) for d in _site_packages.glob("*/bin")]
        if _nvidia_bins:
            os.environ["PATH"] = os.pathsep.join(_nvidia_bins) + os.pathsep + os.environ.get("PATH", "")

_model_cache: dict = {}
_model_lock = threading.Lock()

# Minimum free VRAM (MB) required to load Whisper on GPU.
# "small" model needs ~2GB; leave headroom for CUDA overhead.
_MIN_VRAM_MB = 2500


def _pick_device() -> tuple[str, str]:
    """Choose device and compute type based on available VRAM.

    Returns ("cuda", "float16") if enough VRAM is free,
    otherwise ("cpu", "int8") as a safe fallback.
    """
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.free",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        )
        free_mb = int(result.stdout.strip())
        if free_mb >= _MIN_VRAM_MB:
            return ("cuda", "float16")
        print(f"[recorder] Low VRAM ({free_mb}MB free), falling back to CPU")
    except Exception:
        print("[recorder] Could not query GPU, falling back to CPU")
    return ("cpu", "int8")


def _get_model(model_size: str = "small"):
    """Lazy-load and cache a faster-whisper model."""
    if model_size in _model_cache:
        return _model_cache[model_size]

    with _model_lock:
        if model_size in _model_cache:
            return _model_cache[model_size]

        from faster_whisper import WhisperModel

        device, compute_type = _pick_device()
        print(f"[recorder] Loading faster-whisper '{model_size}' on {device} ({compute_type})...")
        model = WhisperModel(model_size, device=device, compute_type=compute_type)
        _model_cache[model_size] = model
        print(f"[recorder] Model '{model_size}' loaded on {device}.")
        return model


def _deloop_text(text: str) -> str:
    """Remove consecutively repeated n-grams (3+ words) from text.

    Common Whisper failure: "Thank you. Thank you. Thank you. Thank you."
    becomes "Thank you." after delooping.
    """
    words = text.split()
    if len(words) < 6:
        return text

    # Try n-gram sizes from largest (half the text) down to 3 words
    max_n = len(words) // 2
    for n in range(max_n, 2, -1):
        i = 0
        result = []
        while i < len(words):
            # Check if the n-gram starting at i repeats immediately after
            gram = words[i:i + n]
            if len(gram) < n:
                result.extend(words[i:])
                break
            # Count consecutive repetitions
            reps = 1
            j = i + n
            while j + n <= len(words) and words[j:j + n] == gram:
                reps += 1
                j += n
            result.extend(gram)
            i = j if reps > 1 else i + 1
        if len(result) < len(words):
            words = result

    return " ".join(words)


def transcribe_channel(
    wav_path: Path,
    speaker_label: str,
    model_size: str = "small",
    initial_prompt: Optional[str] = None,
    condition_on_previous_text: bool = True,
    compression_ratio_threshold: float = 2.4,
    no_speech_threshold: float = 0.6,
    log_prob_threshold: float = -1.0,
    hallucination_silence_threshold: Optional[float] = 2.0,
    temperature: Union[float, tuple[float, ...]] = (0.0, 0.2, 0.4, 0.6, 0.8, 1.0),
) -> list[dict]:
    """Transcribe a single WAV file, returning labeled segments.

    Args:
        wav_path: Path to mono 16kHz WAV file.
        speaker_label: Label for the speaker in output segments.
        model_size: Whisper model size (tiny/base/small/medium).
        initial_prompt: Optional text to prime the decoder (vocabulary terms).
        condition_on_previous_text: Feed previous output as prompt for next window.
            Set False for short dictation to prevent hallucination loops.
        compression_ratio_threshold: Skip segments with compression ratio above
            this value (catches repetitive hallucinated text). Default 2.4.
        no_speech_threshold: Probability threshold for silence detection.
        log_prob_threshold: Reject segments below this avg log probability.
            Default -1.0 (explicit; matches faster-whisper default).
        hallucination_silence_threshold: faster-whisper exclusive — skip silent
            sections longer than this (seconds). Default 2.0 to suppress
            hallucinated text during silence gaps.
        temperature: Sampling temperature or tuple for fallback sequence.
            Default (0.0, 0.2, 0.4, 0.6, 0.8, 1.0) — greedy first, falls
            back to higher temperatures if quality checks fail on a segment.

    Returns list of:
        {"speaker": str, "start": float, "end": float, "text": str, "confidence": float}
    """
    model = _get_model(model_size)

    transcribe_kwargs = dict(
        beam_size=5,
        vad_filter=True,
        vad_parameters=dict(
            min_silence_duration_ms=500,
            speech_pad_ms=200,
        ),
        condition_on_previous_text=condition_on_previous_text,
        compression_ratio_threshold=compression_ratio_threshold,
        no_speech_threshold=no_speech_threshold,
        log_prob_threshold=log_prob_threshold,
        temperature=temperature,
    )
    if initial_prompt:
        transcribe_kwargs["initial_prompt"] = initial_prompt
    if hallucination_silence_threshold is not None:
        transcribe_kwargs["hallucination_silence_threshold"] = hallucination_silence_threshold

    segments_iter, info = model.transcribe(
        str(wav_path),
        **transcribe_kwargs,
    )

    results = []
    for seg in segments_iter:
        text = _deloop_text(seg.text.strip())
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
    model_size: str = "small",
    initial_prompt: Optional[str] = None,
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
    mic_segments = transcribe_channel(mic_wav, mic_label, model_size, initial_prompt=initial_prompt)
    sys_segments = transcribe_channel(sys_wav, sys_label, model_size, initial_prompt=initial_prompt)

    merged = merge_transcripts(mic_segments, sys_segments)
    formatted = format_transcript(merged)

    return {
        "segments": merged,
        "transcript": formatted,
        "mic_segments_count": len(mic_segments),
        "sys_segments_count": len(sys_segments),
    }
