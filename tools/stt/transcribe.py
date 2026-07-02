"""Whisper transcription for dictation — vocabulary priming + context carry.

vocab.txt terms ride the ``hotwords`` prompt slot, which faster-whisper
injects into EVERY decode window (``initial_prompt`` only seeds the
first). The tail of already-committed text rides ``initial_prompt`` so
chunked dictation keeps wording, casing, and punctuation continuity
across chunk boundaries. Trailing segments with impossible speech rates
are dropped (Whisper fabricating text on near-zero audio).
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent / "data"
VOCAB_FILE = DATA_DIR / "vocab.txt"

# Max plausible speech rate.  Normal English ~2.5 w/s, fast ~6-8.
# Above 15 is physically impossible — Whisper fabricated on silence.
_MAX_SPEECH_RATE = 15.0

# How much committed-text tail to feed forward as decoder context.
_CONTEXT_CHARS = 200


def _load_vocab() -> str:
    """Load vocabulary terms from vocab.txt as a hotwords string."""
    if not VOCAB_FILE.exists():
        return ""
    terms = [t.strip() for t in VOCAB_FILE.read_text(encoding="utf-8").splitlines() if t.strip()]
    return ", ".join(terms)


def _context_tail(prev_text: str) -> str:
    """Last ~N chars of committed text, cut at a word boundary."""
    tail = prev_text[-_CONTEXT_CHARS:]
    if len(prev_text) > _CONTEXT_CHARS and " " in tail:
        tail = tail.split(" ", 1)[1]
    return tail


def transcribe_segments(
    wav_path: Path, model_size: str = "large-v3-turbo", prev_text: str = ""
) -> list[dict]:
    """Transcribe a WAV, returning Whisper segments with timestamps.

    Segment start/end are in the WAV's own timeline — faster-whisper
    restores them through the VAD filter (restore_speech_timestamps).
    """
    from api.recorder.transcribe import transcribe_channel

    vocab = _load_vocab()
    segments = transcribe_channel(
        wav_path,
        speaker_label="dictation",
        model_size=model_size,
        initial_prompt=_context_tail(prev_text) or None,
        hotwords=vocab or None,
        condition_on_previous_text=False,
        compression_ratio_threshold=1.8,
        hallucination_silence_threshold=1.0,
        no_speech_threshold=0.3,
        language="en",
        vad_filter=True,
        repetition_penalty=1.1,
    )

    # Drop trailing segments with impossible speech rate
    while segments:
        seg = segments[-1]
        duration = seg["end"] - seg["start"]
        words = len(seg["text"].split())
        if duration > 0 and words / duration > _MAX_SPEECH_RATE:
            logger.info(
                "Dropped fabricated segment (%.0f w/s): '%s'",
                words / duration, seg["text"],
            )
            segments.pop()
        else:
            break

    return segments


def transcribe(
    wav_path: Path, model_size: str = "large-v3-turbo", prev_text: str = ""
) -> str:
    """Transcribe a WAV file to a single raw-transcript string."""
    segments = transcribe_segments(wav_path, model_size=model_size, prev_text=prev_text)
    return " ".join(seg["text"] for seg in segments)
