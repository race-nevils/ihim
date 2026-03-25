"""Whisper transcription for dictation.

Calls faster-whisper via transcribe_channel with word-level timestamps,
then strips trailing hallucinations using speech rate analysis and
conservative word probability checks.
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

# Only strip trailing words with VERY low probability.  0.3 is conservative
# because tail audio (short clips with no context) produces low probs even
# on real speech — 0.5 was too aggressive and stripped real words.
_WORD_PROB_THRESHOLD = 0.3

# Max plausible speech rate (words/sec).  Normal English is ~2.5 w/s;
# fast speech tops out around 6-8.  Above 15 is physically impossible
# and means Whisper fabricated text on near-zero audio.
_MAX_SPEECH_RATE = 15.0


def _strip_hallucinated_tail(segments: list[dict]) -> list[dict]:
    """Remove trailing hallucinated segments and words.

    Two detection layers, applied to the last segment:
    1. Impossible speech rate (>15 w/s) → drop entire segment
    2. Very low-prob trailing words (prob < 0.3) → strip individual words

    Layer 2 is deliberately conservative (0.3 not 0.5) because tail audio
    clips lack context, making Whisper assign low probabilities even to
    real words.  Better to let some hallucinations through than drop speech.
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

    # Layer 2: Strip very low-prob trailing words
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


def transcribe(
    wav_path: Path,
    model_size: str = "large-v3-turbo",
    word_timestamps: bool = True,
) -> str:
    """Transcribe a WAV file using Whisper.

    Args:
        word_timestamps: Enable word-level timestamps for tail stripping.
            Set False for streaming preview runs (saves ~30% per call).

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
        word_timestamps=word_timestamps,
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
