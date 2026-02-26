"""LLM cleanup of raw transcripts via Ollama."""

import logging

logger = logging.getLogger(__name__)

CLEANUP_MODEL = "llama3.2:3b"

SYSTEM_PROMPT = (
    "You are a transcript cleanup assistant. "
    "Clean up the following dictated text: "
    "remove filler words (um, uh, like, you know), "
    "fix grammar and punctuation, "
    "remove false starts and repeated words, "
    "but preserve the original meaning exactly. "
    "Return ONLY the cleaned text, nothing else."
)


def cleanup_transcript(raw_text: str, model: str = CLEANUP_MODEL) -> str:
    """Clean up a raw transcript using Ollama LLM.

    Args:
        raw_text: Raw transcript from Whisper.
        model: Ollama model name.

    Returns:
        Cleaned transcript text.
    """
    if not raw_text.strip():
        return ""

    try:
        from adapters.ollama import OllamaAdapter

        with OllamaAdapter() as adapter:
            cleaned = adapter.generate(
                prompt=raw_text,
                model=model,
                system=SYSTEM_PROMPT,
            )
        return cleaned.strip()
    except Exception as e:
        logger.error("LLM cleanup failed, returning raw transcript: %s", e)
        return raw_text
