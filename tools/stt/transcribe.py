"""Whisper transcription for dictation.

Calls faster-whisper via transcribe_channel with word-level timestamps,
then strips trailing hallucinations using multiple signals: word decoder
probability, speech rate, and segment-level probability analysis.
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Dedicated file log for segment diagnostics — guaranteed capture
# regardless of how the server routes stdout/stderr.
_DIAG_LOG = Path(__file__).parent / "data" / "transcribe_diag.log"
_DIAG_LOG.parent.mkdir(parents=True, exist_ok=True)
_diag_handler = logging.FileHandler(str(_DIAG_LOG), encoding="utf-8")
_diag_handler.setFormatter(logging.Formatter("%(asctime)s  %(message)s", datefmt="%H:%M:%S"))
_diag_logger = logging.getLogger("stt.transcribe.diag")
_diag_logger.addHandler(_diag_handler)
_diag_logger.setLevel(logging.DEBUG)

# Words below this decoder probability at the tail are stripped.
_WORD_PROB_THRESHOLD = 0.5

# Max plausible speech rate (words/sec).  Normal English is ~2.5 w/s;
# fast speech tops out around 6-8.  Above 15 is physically impossible
# and means Whisper fabricated text on near-zero audio.
_MAX_SPEECH_RATE = 15.0

# For short segments (< 1s), if ANY word has probability below this,
# the whole segment is suspect hallucination from silence/noise.
_MIN_WORD_PROB = 0.25


def _strip_hallucinated_tail(segments: list[dict]) -> list[dict]:
    """Remove trailing hallucinated segments and words.

    Three detection layers, applied to the last segment:
    1. Impossible speech rate  → drop entire segment
    2. Short segment with very low-prob word → drop entire segment
    3. Low-prob trailing words → strip individual words
    """
    if not segments:
        return segments

    last_seg = segments[-1]
    words = last_seg.get("words")
    if not words:
        return segments

    seg_duration = last_seg["end"] - last_seg["start"]

    # Layer 1: Impossible speech rate (e.g. 4 words in 0.06s)
    if seg_duration > 0 and len(words) / seg_duration > _MAX_SPEECH_RATE:
        _diag_logger.info(
            "  DROP segment (%.0f w/s, impossible): '%s'",
            len(words) / seg_duration, last_seg["text"],
        )
        segments.pop()
        return _strip_hallucinated_tail(segments)

    # Layer 2: Short segment with a very low-prob word
    # On short tail audio (< 1s), Whisper often hallucinates a phrase where
    # the first word has very low prob but subsequent words are confident
    # (it "locks in" after the hallucinated start).
    if seg_duration < 1.0 and words:
        min_prob = min(w["prob"] for w in words)
        if min_prob < _MIN_WORD_PROB:
            _diag_logger.info(
                "  DROP segment (min_prob=%.4f in %.2fs segment): '%s'",
                min_prob, seg_duration, last_seg["text"],
            )
            segments.pop()
            return _strip_hallucinated_tail(segments)

    # Layer 3: Strip low-prob trailing words
    while words and words[-1]["prob"] < _WORD_PROB_THRESHOLD:
        dropped = words.pop()
        _diag_logger.info(
            "  STRIPPED word (prob=%.4f): '%s'",
            dropped["prob"], dropped["word"],
        )

    if not words:
        segments.pop()
        return _strip_hallucinated_tail(segments)

    # Reconstruct segment text from remaining words
    last_seg["text"] = "".join(w["word"] for w in words).strip()
    last_seg["end"] = words[-1]["end"]
    return segments


def transcribe(wav_path: Path, model_size: str = "large-v3-turbo") -> str:
    """Transcribe a WAV file using Whisper.

    Returns the raw transcript as a single string.
    """
    from api.recorder.transcribe import transcribe_channel

    segments = transcribe_channel(
        wav_path,
        speaker_label="dictation",
        model_size=model_size,
        condition_on_previous_text=False,
        compression_ratio_threshold=1.8,
        hallucination_silence_threshold=1.0,
        no_speech_threshold=0.3,
        language="en",
        vad_filter=True,
        repetition_penalty=1.1,
        word_timestamps=True,
    )

    # Diagnostic: log every segment and word
    _diag_logger.info("--- TRANSCRIPTION: %s ---", wav_path.name)
    for i, seg in enumerate(segments):
        _diag_logger.info(
            "  SEG[%d] conf=%.4f  [%.2f-%.2f]  '%s'",
            i, seg["confidence"], seg["start"], seg["end"], seg["text"],
        )
        for w in seg.get("words", []):
            _diag_logger.info(
                "    WORD prob=%.4f  [%.2f-%.2f]  '%s'",
                w["prob"], w["start"], w["end"], w["word"],
            )

    # Strip trailing hallucinations
    before_text = " ".join(seg["text"] for seg in segments)
    segments = _strip_hallucinated_tail(segments)
    after_text = " ".join(seg["text"] for seg in segments)
    if before_text != after_text:
        _diag_logger.info("  STRIPPED: '%s' → '%s'", before_text, after_text)
    _diag_logger.info("  FINAL: '%s'", after_text)

    return after_text
