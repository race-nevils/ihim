"""Whisper transcription for dictation.

Calls faster-whisper via transcribe_channel with word-level timestamps,
then strips trailing words whose decoder probability is low — these are
typically hallucinated on silence/noise at the end of recordings.
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

# Words below this decoder probability at the END of the transcript are
# likely hallucinated.  Segment-level confidence (1 - no_speech_prob) is
# useless with VAD enabled (always ~1.0); word-level decoder probs are
# much more discriminating.
_WORD_PROB_THRESHOLD = 0.5


def _strip_low_prob_tail_words(segments: list[dict]) -> list[dict]:
    """Strip trailing words whose decoder probability is below threshold.

    Works on word-level data within segments.  If an entire segment's
    words are stripped, removes the segment and checks the previous one.
    """
    if not segments:
        return segments

    last_seg = segments[-1]
    words = last_seg.get("words")
    if not words:
        return segments

    # Strip low-prob words from the tail
    while words and words[-1]["prob"] < _WORD_PROB_THRESHOLD:
        dropped = words.pop()
        _diag_logger.info(
            "  STRIPPED word (prob=%.4f): '%s'",
            dropped["prob"], dropped["word"],
        )

    if not words:
        # Entire last segment was low-prob — remove and check previous
        segments.pop()
        return _strip_low_prob_tail_words(segments)

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

    # Strip trailing hallucinated words by decoder probability
    before_text = " ".join(seg["text"] for seg in segments)
    segments = _strip_low_prob_tail_words(segments)
    after_text = " ".join(seg["text"] for seg in segments)
    if before_text != after_text:
        _diag_logger.info("  STRIPPED: '%s' → '%s'", before_text, after_text)
    _diag_logger.info("  FINAL: '%s'", after_text)

    return after_text
