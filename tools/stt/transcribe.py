"""Whisper transcription with vocabulary priming."""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent / "data"
VOCAB_FILE = DATA_DIR / "vocab.txt"


def load_vocab() -> str:
    """Load vocabulary terms from vocab.txt, return as comma-separated string."""
    if not VOCAB_FILE.exists():
        return ""
    terms = []
    for line in VOCAB_FILE.read_text(encoding="utf-8").splitlines():
        term = line.strip()
        if term:
            terms.append(term)
    return ", ".join(terms)


def transcribe(wav_path: Path, model_size: str = "small") -> str:
    """Transcribe a WAV file using Whisper with vocabulary priming.

    Returns the raw transcript as a single string.
    """
    from api.recorder.transcribe import transcribe_channel

    vocab_prompt = load_vocab()
    segments = transcribe_channel(
        wav_path,
        speaker_label="dictation",
        model_size=model_size,
        initial_prompt=vocab_prompt or None,
    )
    return " ".join(seg["text"] for seg in segments)
