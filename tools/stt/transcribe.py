"""Whisper transcription for dictation with vocabulary priming.

Calls faster-whisper via transcribe_channel with an initial_prompt built
from vocab.txt, then drops trailing segments with impossible speech rates
(Whisper fabricating text on near-zero audio).
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent / "data"
VOCAB_FILE = DATA_DIR / "vocab.txt"

# Max plausible speech rate.  Normal English ~2.5 w/s, fast ~6-8.
# Above 15 is physically impossible — Whisper fabricated on silence.
_MAX_SPEECH_RATE = 15.0


def _load_vocab() -> str:
    """Load vocabulary terms from vocab.txt as an initial_prompt.

    Wrapping terms in a sentence gives Whisper's decoder better context
    than a bare comma-separated list.
    """
    if not VOCAB_FILE.exists():
        return ""
    terms = [t.strip() for t in VOCAB_FILE.read_text(encoding="utf-8").splitlines() if t.strip()]
    if not terms:
        return ""
    return "The following terms may appear: " + ", ".join(terms) + "."


def transcribe(wav_path: Path, model_size: str = "large-v3-turbo") -> str:
    """Transcribe a WAV file using Whisper with vocabulary priming.

    Returns the raw transcript as a single string.
    """
    from api.recorder.transcribe import transcribe_channel

    vocab_prompt = _load_vocab()

    segments = transcribe_channel(
        wav_path,
        speaker_label="dictation",
        model_size=model_size,
        initial_prompt=vocab_prompt or None,
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

    return " ".join(seg["text"] for seg in segments)
