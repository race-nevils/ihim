"""Whisper transcription — minimal baseline."""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


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
        initial_prompt=(
            "Hello, this is a clear dictation with proper punctuation. "
            "I'll use commas, periods, and question marks where appropriate. "
            "Technical terms like API, JSON, GitHub, and TypeScript appear naturally."
        ),
        repetition_penalty=1.1,
    )
    return " ".join(seg["text"] for seg in segments)
