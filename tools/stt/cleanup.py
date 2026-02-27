"""Deterministic transcript cleanup — no LLM, no VRAM, no hallucination.

Whisper's raw output is already high quality. This module applies fast
regex/rule-based cleanup: hallucination filtering, stutter detection,
verbal punctuation commands, filler removal, false start detection,
deduplication, capitalization, whitespace normalization.

The old LLM approach is preserved as cleanup_transcript_llm() in case
a better model warrants revisiting.
"""

import logging
import re

logger = logging.getLogger(__name__)

# ── Whisper hallucination patterns ────────────────────────────────────
# Known artifacts from YouTube training data that Whisper hallucinates
# on silence or low-confidence audio.
_HALLUCINATION_PATTERNS = [
    r"thanks?\s+for\s+watching",
    r"subscribe\s+to\s+my\s+channel",
    r"like\s+and\s+subscribe",
    r"please\s+subscribe",
    r"hit\s+the\s+(?:bell|notification)",
    r"subtitles?\s+by\b",
]

_HALLUCINATION_RE = re.compile(
    "|".join(_HALLUCINATION_PATTERNS),
    re.IGNORECASE,
)

# ── Stutter detection ─────────────────────────────────────────────────
# Matches single-char-hyphen sequences: "s-s-stuttering" → "stuttering"
# Does NOT match compound words like "self-contained" (multi-char before hyphen).
_STUTTER_RE = re.compile(r"\b(?:\w-)+(\w+)\b")

# ── Verbal punctuation commands ───────────────────────────────────────
# Processed longest-first to prevent partial matches.
_PUNCTUATION_COMMANDS = [
    ("new paragraph", "\n\n"),
    ("new line", "\n"),
    ("newline", "\n"),
    ("exclamation point", "!"),
    ("exclamation mark", "!"),
    ("question mark", "?"),
    ("open parenthesis", "("),
    ("close parenthesis", ")"),
    ("open paren", "("),
    ("close paren", ")"),
    ("semicolon", ";"),
    ("period", "."),
    ("comma", ","),
    ("colon", ":"),
    ("dash", "\u2014"),  # em dash
    ("hyphen", "-"),
]

# Build regex patterns — word-boundary safe, case-insensitive.
# Uses [^\S\n]* (horizontal whitespace) instead of \s* to avoid eating
# newlines inserted by earlier punctuation commands (e.g. "new paragraph").
_PUNCT_CMD_PATTERNS = [
    (re.compile(r"[^\S\n]*\b" + re.escape(cmd) + r"\b[^\S\n]*", re.IGNORECASE), repl)
    for cmd, repl in _PUNCTUATION_COMMANDS
]

# ── Filler patterns ──────────────────────────────────────────────────
# Word-boundary-safe filler removal. Order matters (longer phrases first).
_FILLER_PHRASES = [
    r"\blet me rephrase\b",
    r"\bwhat I meant was\b",
    r"\bwhat I meant is\b",
    r"\bno wait\b",
    r"\byou know\b",
    r"\bi mean\b",
    r"\bkind of\b",
    r"\bsort of\b",
]

# "sorry" only when followed by comma + restart pronoun
_SORRY_RE = re.compile(
    r"\bsorry\s*,\s*(?=I\b|we\b|the\b|it\b|that\b)",
    re.IGNORECASE,
)

_FILLER_WORDS = [
    r"\bum+\b",
    r"\buh+\b",
    r"\bhmm+\b",
    r"\bah+\b",
    r"\boh\b",
    r"\bbasically\b",
    r"\bactually\b",
    r"\bliterally\b",
    r"\bright\b(?=[,.]?\s)",   # "right" only when followed by pause/punctuation
    r"\blike\s*,",              # "like" as filler + trailing comma
]

_FILLER_RE = re.compile(
    "|".join(_FILLER_PHRASES + _FILLER_WORDS),
    re.IGNORECASE,
)

# Repeated words: "the the" → "the", "I I" → "I"
_REPEATED_WORD_RE = re.compile(r"\b(\w+)(\s+\1)+\b", re.IGNORECASE)

# Collapse multiple spaces
_MULTI_SPACE_RE = re.compile(r"  +")

# Collapse multiple commas / comma-space sequences left by filler removal
_MULTI_COMMA_RE = re.compile(r"(\s*,\s*){2,}")

# Space before punctuation: "word ." → "word."
_SPACE_BEFORE_PUNCT_RE = re.compile(r"\s+([.,!?;:])")

# Sentence boundary: end of sentence → capitalize next word
_SENTENCE_START_RE = re.compile(r"(?:^|[.!?]\s+)(\w)")


# ── New pipeline functions ────────────────────────────────────────────

def _remove_hallucinations(text: str) -> str:
    """Strip known Whisper hallucination artifacts.

    If the entire transcript is a hallucination, returns empty string.
    """
    cleaned = _HALLUCINATION_RE.sub("", text).strip()
    if not cleaned or not re.search(r"\w", cleaned):
        return ""
    return cleaned


def _fix_stutters(text: str) -> str:
    """Collapse stuttered repetitions: 's-s-stuttering' → 'stuttering'."""
    return _STUTTER_RE.sub(r"\1", text)


def _apply_punctuation_commands(text: str) -> str:
    """Convert verbal punctuation to actual punctuation marks."""
    for pattern, replacement in _PUNCT_CMD_PATTERNS:
        text = pattern.sub(replacement, text)
    # Ensure space after sentence/separator punctuation before a word char
    text = re.sub(r"([.!?,:;)])(\w)", r"\1 \2", text)
    # Ensure space before opening paren after a word char
    text = re.sub(r"(\w)([(])", r"\1 \2", text)
    # Add period before newlines if sentence doesn't end with punctuation
    text = re.sub(r"(\w)\n", r"\1.\n", text)
    return text


def _remove_false_starts(text: str) -> str:
    """Remove false starts where speaker restarts a phrase.

    Splits on em dash or double dash, compares words before/after.
    If end of part A overlaps with start of part B, keeps only part B.
    If no overlap, keeps both (the dash was just a pause).
    """
    text = text.replace("--", "\u2014")

    if "\u2014" not in text:
        return text

    parts = text.split("\u2014")
    if len(parts) < 2:
        return text

    result = parts[0].strip()

    for part in parts[1:]:
        part = part.strip()
        if not part:
            continue

        result_words = result.lower().split()
        part_words = part.lower().split()

        if result_words and part_words:
            overlap = 0
            max_check = min(len(result_words), len(part_words))
            for length in range(1, max_check + 1):
                if result_words[-length:] == part_words[:length]:
                    overlap = length

            if overlap > 0:
                # False start — keep content before the overlapping phrase,
                # then use the restarted (more complete) version
                keep_words = result.split()[:-overlap]
                if keep_words:
                    result = " ".join(keep_words) + " " + part
                else:
                    result = part
                continue

        # No overlap — dash was just a pause, keep both
        result = result + " " + part if result else part

    return result


def cleanup_transcript(raw_text: str) -> str:
    """Clean up a raw Whisper transcript using deterministic rules.

    Pipeline:
     1. Strip Whisper hallucination artifacts
     2. Collapse stutters (s-s-stuttering → stuttering)
     3. Convert verbal punctuation (period → .)
     4. Remove filler words/phrases
     5. Remove false starts (I went to the— I went to the store)
     6. Collapse repeated words
     7. Clean punctuation artifacts
     8. Normalize whitespace
     9. Fix "i" → "I"
    10. Capitalize first character
    11. Capitalize after sentence-ending punctuation
    12. Ensure trailing punctuation
    """
    if not raw_text or not raw_text.strip():
        return ""

    text = raw_text.strip()

    # 1. Strip hallucinations
    text = _remove_hallucinations(text)
    if not text:
        return ""

    # 2. Fix stutters
    text = _fix_stutters(text)

    # 3. Apply verbal punctuation commands
    text = _apply_punctuation_commands(text)

    # 4. Remove fillers
    text = _FILLER_RE.sub("", text)
    text = _SORRY_RE.sub("", text)

    # 5. Remove false starts
    text = _remove_false_starts(text)

    # 6. Collapse repeated words
    text = _REPEATED_WORD_RE.sub(r"\1", text)

    # 7. Clean up punctuation artifacts from filler removal
    text = _MULTI_COMMA_RE.sub(", ", text)
    text = _SPACE_BEFORE_PUNCT_RE.sub(r"\1", text)

    # 8. Normalize whitespace (preserve newlines from punctuation commands)
    text = re.sub(r"[^\S\n]+", " ", text)
    text = text.strip()

    # 9. Fix standalone "i" → "I"
    text = re.sub(r"\bi\b", "I", text)

    # 10. Capitalize first character
    if text:
        text = text[0].upper() + text[1:]

    # 11. Capitalize after sentence-ending punctuation
    def _cap(m):
        return m.group(0)[:-1] + m.group(1).upper()
    text = _SENTENCE_START_RE.sub(_cap, text)

    # 12. Ensure trailing punctuation
    if text and text[-1] not in ".!?\n":
        text += "."

    return text


# ── Legacy LLM cleanup (preserved for future use) ───────────────────

_LLM_CLEANUP_MODEL = "llama3.2:3b"

_LLM_SYSTEM_PROMPT = (
    "You are a transcript cleanup assistant. "
    "Clean up the following dictated text: "
    "remove filler words (um, uh, like, you know), "
    "fix grammar and punctuation, "
    "remove false starts and repeated words, "
    "but preserve the original meaning exactly. "
    "Return ONLY the cleaned text, nothing else."
)


def cleanup_transcript_llm(raw_text: str, model: str = _LLM_CLEANUP_MODEL) -> str:
    """Clean up a raw transcript using Ollama LLM (legacy).

    Preserved in case a better model warrants re-enabling LLM cleanup.
    Not used in the default pipeline — see cleanup_transcript() instead.
    """
    if not raw_text.strip():
        return ""

    try:
        from adapters.ollama import OllamaAdapter

        with OllamaAdapter() as adapter:
            cleaned = adapter.generate(
                prompt=raw_text,
                model=model,
                system=_LLM_SYSTEM_PROMPT,
                keep_alive="0",
            )
        return cleaned.strip()
    except Exception as e:
        logger.error("LLM cleanup failed, returning raw transcript: %s", e)
        return raw_text
