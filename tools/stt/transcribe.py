"""Whisper transcription for dictation.

Calls faster-whisper via transcribe_channel, then strips low-confidence
trailing segments that Whisper fabricates on silence/noise at the end
of recordings.
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

# Segments below this confidence are suspect. If they're at the END
# of the transcript, they're almost certainly hallucinated on silence.
_TAIL_CONFIDENCE_THRESHOLD = 0.70


def _strip_low_confidence_tail(segments: list[dict]) -> list[dict]:
    """Drop trailing segments whose confidence is below threshold.

    Whisper fabricates short phrases ("Aww.", "Strap.", "Let's get it off.")
    at the end of audio where only silence/noise remains. These segments
    have low confidence (high no_speech_prob). Strip them from the tail
    only — low-confidence segments in the MIDDLE might be real speech
    in a noisy environment.
    """
    while segments and segments[-1]["confidence"] < _TAIL_CONFIDENCE_THRESHOLD:
        dropped = segments.pop()
        logger.info(
            "Dropped low-confidence tail segment (%.2f): '%s'",
            dropped["confidence"], dropped["text"],
        )
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
    )

    # Diagnostic: log every segment so we can see what Whisper produces
    _diag_logger.info("--- TRANSCRIPTION: %s ---", wav_path.name)
    for i, seg in enumerate(segments):
        _diag_logger.info(
            "  SEG[%d] conf=%.4f  [%.2f-%.2f]  '%s'",
            i, seg["confidence"], seg["start"], seg["end"], seg["text"],
        )

    # Strip fabricated trailing segments
    before_count = len(segments)
    segments = _strip_low_confidence_tail(segments)
    if len(segments) < before_count:
        _diag_logger.info("  STRIPPED %d tail segments", before_count - len(segments))
    _diag_logger.info("  FINAL: '%s'", " ".join(seg["text"] for seg in segments))

    return " ".join(seg["text"] for seg in segments)
