"""Whisper transcription with vocabulary priming."""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent / "data"
VOCAB_FILE = DATA_DIR / "vocab.txt"


def load_vocab() -> str:
    """Load vocabulary terms from vocab.txt as a conversational prompt.

    Wrapping terms in a sentence gives Whisper's decoder better attention
    context than a bare comma-separated list (17-38% → marginal improvement).
    """
    if not VOCAB_FILE.exists():
        return ""
    terms = []
    for line in VOCAB_FILE.read_text(encoding="utf-8").splitlines():
        term = line.strip()
        if term:
            terms.append(term)
    if not terms:
        return ""
    return "The following terms may appear in this dictation: " + ", ".join(terms) + "."


def transcribe(wav_path: Path, model_size: str = "large-v3-turbo") -> str:
    """Transcribe a WAV file using Whisper with vocabulary priming.

    Returns the raw transcript as a single string.
    """
    from api.recorder.transcribe import transcribe_channel

    # Style prompt steers Whisper toward dictation output (not podcast/interview).
    # Vocab-specific terms removed — they caused the decoder to parrot them back.
    style_prompt = "Dictation of spoken text. Natural conversational English."
    segments = transcribe_channel(
        wav_path,
        speaker_label="dictation",
        model_size=model_size,
        initial_prompt=style_prompt,
        condition_on_previous_text=False,
        compression_ratio_threshold=1.8,
        hallucination_silence_threshold=1.0,
        language="en",
    )
    return " ".join(seg["text"] for seg in segments)
