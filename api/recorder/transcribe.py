"""faster-whisper integration + transcript merging.

Lazy-loads the model on first use. Transcribes each channel independently
with a speaker label, then merges chronologically. Uses GPU (CUDA) when
available with automatic CPU fallback if VRAM is insufficient.
"""

import ctypes
import os
import subprocess
import sys
import threading
import time
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

# --- Sleep detection (Windows) -------------------------------------------
# CUDA contexts go stale after system sleep (faster-whisper #829).
# Detect sleep by comparing monotonic time (includes sleep on Python 3.7+)
# against QueryUnbiasedInterruptTime (excludes sleep).  If the gap exceeds
# a threshold, the system slept and cached GPU models must be discarded.
if sys.platform == "win32":
    def _unbiased_100ns() -> int:
        """System uptime in 100ns units, excluding sleep/hibernate."""
        t = ctypes.c_uint64()
        ctypes.windll.kernel32.QueryUnbiasedInterruptTime(ctypes.byref(t))
        return t.value
else:
    _unbiased_100ns = None  # type: ignore[assignment]

# System-level sleep baseline — survives model unload/eviction.
# Unlike per-model stamps, this always has a valid baseline.
_last_active_mono: float = time.monotonic()
_last_active_unbiased: int = _unbiased_100ns() if _unbiased_100ns is not None else 0


def _check_system_sleep(threshold_s: float = 30.0) -> bool:
    """True if system slept since last check. Updates baseline on every call.

    Compares monotonic time (includes sleep) against
    QueryUnbiasedInterruptTime (excludes sleep). The gap between them
    is how long the system was asleep.
    """
    global _last_active_mono, _last_active_unbiased
    if _unbiased_100ns is None:
        return False
    mono_now = time.monotonic()
    unbiased_now = _unbiased_100ns()
    mono_gap = mono_now - _last_active_mono
    unbiased_gap = (unbiased_now - _last_active_unbiased) / 10_000_000
    _last_active_mono = mono_now
    _last_active_unbiased = unbiased_now
    return (mono_gap - unbiased_gap) > threshold_s

# Cached VRAM query (nvidia-smi is slow; cache for 30s)
_vram_cache: dict = {"value": None, "expires": 0}

# VRAM required (MB) for float16 by model size.
# Measured empirically: model footprint + CUDA overhead.
_VRAM_FLOAT16 = {
    "tiny": 500, "tiny.en": 500,
    "base": 700, "base.en": 700,
    "small": 1500, "small.en": 1500,
    "medium": 3000, "medium.en": 3000,
    "large-v3": 4500,
    "large-v3-turbo": 2000,
}

# Absolute minimum VRAM for any GPU usage (tiny/base models).
_MIN_VRAM_MB = 1000


def _get_free_vram() -> int:
    """Query free VRAM in MB via nvidia-smi. Cached for 30 seconds."""
    now = time.monotonic()
    if _vram_cache["value"] is not None and now < _vram_cache["expires"]:
        return _vram_cache["value"]

    result = subprocess.run(
        ["nvidia-smi", "--query-gpu=memory.free",
         "--format=csv,noheader,nounits"],
        capture_output=True, text=True, timeout=5,
    )
    value = int(result.stdout.strip())
    _vram_cache["value"] = value
    _vram_cache["expires"] = now + 30
    return value


def _pick_device(model_size: str = "small") -> tuple[str, str]:
    """Choose device and compute type based on available VRAM and model size.

    Selection logic (highest quality first):
    1. float16 on CUDA — if enough VRAM for the specific model + 500MB headroom
    2. int8_float16 on CUDA — if >= 3000MB free (fits any model with quantization)
    3. float16 on CUDA — if >= MIN_VRAM for small models (fallback for tiny/base/small)
    4. CPU int8 — safe fallback when GPU unavailable or insufficient
    """
    try:
        free_mb = _get_free_vram()
        needed = _VRAM_FLOAT16.get(model_size, 4500)

        if free_mb >= needed + 500:  # full model fits with headroom
            return ("cuda", "float16")
        if free_mb >= 3000:  # enough for int8_float16 of any model
            return ("cuda", "int8_float16")
        if free_mb >= _MIN_VRAM_MB:  # enough for small models in float16
            return ("cuda", "float16")

        print(f"[recorder] Low VRAM ({free_mb}MB free, need {needed}+500MB), falling back to CPU")
    except Exception:
        print("[recorder] Could not query GPU, falling back to CPU")
    return ("cpu", "int8")


def _get_model(model_size: str = "small"):
    """Lazy-load and cache a faster-whisper model.

    Cache key is (model_size, device, compute_type) so the same model
    at different compute types are cached separately.  If the model was
    previously unloaded from GPU via ``unload_model()``, it is reloaded
    transparently using CTranslate2's ``load_model()`` API.

    The WhisperModel constructor runs OUTSIDE _model_lock so a hung
    constructor (stale CUDA context after sleep) cannot deadlock
    unload_model() or other callers.
    """
    device, compute_type = _pick_device(model_size)
    cache_key = (model_size, device, compute_type)

    # Flush stale CUDA context after system sleep (faster-whisper #829).
    # System-level detection works even after idle-unload evicts the cache.
    if _check_system_sleep():
        with _model_lock:
            _model_cache.clear()
        print("[recorder] Sleep detected — flushed all cached models")

    # Fast path: cache hit (lock protects read + potential CTranslate2 reload)
    with _model_lock:
        if cache_key in _model_cache:
            cached = _model_cache[cache_key]
            if not cached.model.model_is_loaded:
                print(f"[recorder] Reloading '{model_size}' on {device} ({compute_type})...")
                cached.model.load_model()
                print(f"[recorder] Model '{model_size}' reloaded on {device}.")
            return cached

    # Slow path: construct new model OUTSIDE _model_lock.
    # If two threads race here, one model is discarded — harmless for
    # a single-user app, and far better than holding the lock during a
    # constructor that can hang on post-sleep CUDA state.
    from faster_whisper import WhisperModel

    print(f"[recorder] Loading faster-whisper '{model_size}' on {device} ({compute_type})...")
    model = WhisperModel(model_size, device=device, compute_type=compute_type)

    with _model_lock:
        if cache_key not in _model_cache:
            _model_cache[cache_key] = model
        else:
            model = _model_cache[cache_key]

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


def is_model_loaded(model_size: str = "small") -> bool:
    """Check if a Whisper model is loaded on the compute device.

    Returns True only if the model is cached AND its weights are resident
    on the GPU/CPU (i.e. not unloaded via ``unload_model()``).
    """
    for key, cached in _model_cache.items():
        if (isinstance(key, tuple) and key[0] == model_size) or key == model_size:
            return cached.model.model_is_loaded
    return False


def unload_model(model_size: str = "small") -> bool:
    """Unload a cached Whisper model to free VRAM.

    Uses CTranslate2's explicit ``unload_model()`` API to release GPU
    memory without destroying the Python object.  The model stays in
    cache and can be cheaply reloaded via ``load_model()`` on next use.

    This avoids ``del`` + ``gc.collect()`` which triggers the C++
    destructor — known to hang on Windows when the CUDA driver stalls
    during idle/sleep transitions (faster-whisper #829).
    """
    with _model_lock:
        unloaded = False
        for key, cached in _model_cache.items():
            if (isinstance(key, tuple) and key[0] == model_size) or key == model_size:
                if cached.model.model_is_loaded:
                    cached.model.unload_model()
                    unloaded = True
    if unloaded:
        print(f"[recorder] Unloaded model '{model_size}' — VRAM freed.")
    return unloaded


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
    language: Optional[str] = None,
    vad_filter: bool = True,
    repetition_penalty: float = 1.0,
    word_timestamps: bool = False,
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
        vad_filter=vad_filter,
    )
    if vad_filter:
        transcribe_kwargs["vad_parameters"] = dict(
            min_silence_duration_ms=500,
            speech_pad_ms=200,
        )
    transcribe_kwargs.update(
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
    if language is not None:
        transcribe_kwargs["language"] = language
    if repetition_penalty != 1.0:
        transcribe_kwargs["repetition_penalty"] = repetition_penalty
    if word_timestamps:
        transcribe_kwargs["word_timestamps"] = True

    segments_iter, info = model.transcribe(
        str(wav_path),
        **transcribe_kwargs,
    )

    results = []
    for seg in segments_iter:
        text = _deloop_text(seg.text.strip())
        if not text:
            continue
        entry = {
            "speaker": speaker_label,
            "start": round(seg.start, 2),
            "end": round(seg.end, 2),
            "text": text,
            "confidence": round(1.0 - seg.no_speech_prob, 4),
        }
        if word_timestamps and seg.words:
            entry["words"] = [
                {
                    "word": w.word,
                    "start": round(w.start, 2),
                    "end": round(w.end, 2),
                    "prob": round(w.probability, 4),
                }
                for w in seg.words
            ]
        results.append(entry)

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
