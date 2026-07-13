"""Whisper transcription for dictation — vocabulary priming + context carry.

vocab.txt terms ride the ``hotwords`` prompt slot, which faster-whisper
injects into EVERY decode window (``initial_prompt`` only seeds the
first). The tail of already-committed text rides ``initial_prompt`` so
chunked dictation keeps wording, casing, and punctuation continuity
across chunk boundaries. Trailing segments with impossible speech rates
are dropped (Whisper fabricating text on near-zero audio).
"""

import logging
import re
import wave
from pathlib import Path

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent / "data"
VOCAB_FILE = DATA_DIR / "vocab.txt"

# Max plausible speech rate.  Normal English ~2.5 w/s, fast ~6-8.
# Above 15 is physically impossible — Whisper fabricated on silence.
_MAX_SPEECH_RATE = 15.0

# How much committed-text tail to feed forward as decoder context.
_CONTEXT_CHARS = 200

# Prompt-echo drop: fabricated segments that quote the hotwords wrapper
# need at least this many words to be dropped — short overlaps ("okay",
# "let me") are legitimate speech.
_ECHO_MIN_WORDS = 4

# Segment splitting: VAD speech-padding glues continuous speech into
# giant segments (a 43s monologue = one timestamp). Word timings let us
# re-cut them at natural boundaries.
_SPLIT_GAP = 1.0          # inter-word silence that always starts a new segment
_SPLIT_AT_SENTENCE = 5.0  # sentence end closes a segment once it's this long
_SPLIT_HARD = 15.0        # absolute cap — split at the next word boundary
_SENTENCE_ENDS = (".", "?", "!")


def _split_long_segments(segments: list[dict], deloop) -> list[dict]:
    """Re-cut long segments at pauses / sentence ends using word timings."""
    out = []
    for seg in segments:
        words = seg.get("words")
        if not words or (seg["end"] - seg["start"]) <= _SPLIT_AT_SENTENCE:
            out.append(seg)
            continue
        pieces = [[words[0]]]
        for prev, nxt in zip(words, words[1:]):
            piece = pieces[-1]
            length = prev["end"] - piece[0]["start"]
            gap = nxt["start"] - prev["end"]
            at_sentence = prev["word"].rstrip().endswith(_SENTENCE_ENDS)
            if gap > _SPLIT_GAP or (at_sentence and length >= _SPLIT_AT_SENTENCE) or length >= _SPLIT_HARD:
                pieces.append([nxt])
            else:
                piece.append(nxt)
        if len(pieces) == 1:
            out.append(seg)
            continue
        for piece in pieces:
            text = deloop("".join(w["word"] for w in piece).strip())
            if not text:
                continue
            out.append({
                "speaker": seg["speaker"],
                "start": piece[0]["start"],
                "end": piece[-1]["end"],
                "text": text,
                "confidence": seg["confidence"],
            })
    return out


def _load_vocab() -> str:
    """Load vocabulary terms from vocab.txt as a hotwords string.

    The terms are wrapped in a cased, punctuated sentence — Whisper
    mimics the STYLE of its prompt, and a bare comma-list in every
    window suppresses periods and capitalization in the output.
    """
    if not VOCAB_FILE.exists():
        return ""
    terms = [t.strip() for t in VOCAB_FILE.read_text(encoding="utf-8").splitlines() if t.strip()]
    if not terms:
        return ""
    return (
        "Okay, here's what I'm thinking. This dictation may mention "
        + ", ".join(terms)
        + ". Let me walk through it."
    )


def _normalize(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace — for echo matching."""
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", text.lower())).strip()


def _wav_duration(wav_path: Path) -> float | None:
    """Audio duration in seconds, or None for non-WAV/unreadable files."""
    try:
        with wave.open(str(wav_path)) as w:
            rate = w.getframerate()
            return w.getnframes() / rate if rate else None
    except Exception:
        return None


def _context_tail(prev_text: str) -> str:
    """Last ~N chars of committed text, cut at a word boundary."""
    tail = prev_text[-_CONTEXT_CHARS:]
    if len(prev_text) > _CONTEXT_CHARS and " " in tail:
        tail = tail.split(" ", 1)[1]
    return tail


def transcribe_segments(
    wav_path: Path, model_size: str = "large-v3-turbo", prev_text: str = "",
    speaker_label: str = "dictation",
) -> list[dict]:
    """Transcribe a WAV, returning Whisper segments with timestamps.

    Segment start/end are in the WAV's own timeline — faster-whisper
    restores them through the VAD filter (restore_speech_timestamps).

    This is the tuned dictation path (vocab priming, anti-hallucination
    thresholds, repetition penalty, fabricated-segment drop). The meeting
    recorder routes each channel through here too, passing its own
    speaker_label, so both features share one authoritative tuning.
    """
    from api.recorder.transcribe import _deloop_text, transcribe_channel

    vocab = _load_vocab()
    segments = transcribe_channel(
        wav_path,
        speaker_label=speaker_label,
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
        # hallucination_silence_threshold is INERT without word timestamps
        # (faster-whisper only runs the silence-skip inside its
        # word_timestamps branch). Without it, a hallucinated segment in a
        # silence gap advances seek by the full 30s window — swallowing any
        # real speech in that window (truncation, 2026-07-12).
        word_timestamps=True,
    )

    # Re-cut VAD-glued monologue blobs into pause/sentence-sized segments,
    # then drop the per-word arrays — callers consume segment level only.
    segments = _split_long_segments(segments, _deloop_text)
    for seg in segments:
        seg.pop("words", None)

    # Drop prompt echoes: Whisper quotes the hotwords wrapper on silence
    # ("Let me walk through it."). Match normalized segment text against
    # the wrapper; 4+ words so real short phrases survive.
    if vocab:
        vocab_norm = _normalize(vocab)
        kept = []
        for seg in segments:
            text_norm = _normalize(seg["text"])
            if len(text_norm.split()) >= _ECHO_MIN_WORDS and text_norm in vocab_norm:
                logger.info("Dropped hotwords echo: '%s'", seg["text"])
                continue
            kept.append(seg)
        segments = kept

    # Clamp to real audio length — fabricated segments run past EOF.
    duration = _wav_duration(wav_path)
    if duration is not None:
        segments = [s for s in segments if s["start"] < duration]
        for seg in segments:
            if seg["end"] > duration:
                seg["end"] = round(duration, 2)

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
