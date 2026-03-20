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
# Patterns that match WITHIN longer text (stripped but don't reject the whole transcript)
_HALLUCINATION_PATTERNS = [
    r"thanks?\s+for\s+watching",
    r"subscribe\s+to\s+my\s+channel",
    r"like\s+and\s+subscribe",
    r"please\s+subscribe",
    r"hit\s+the\s+(?:bell|notification)",
    r"subtitles?\s+by\b",
    r"sub[tт]i[tт]l",                     # "subtitles" in mixed Latin/Cyrillic
    r"[Сс]убтитры",                        # Russian "subtitles"
    r"DimaTorzok",                          # specific known hallucination
    r"Amara\.org",                          # subtitle service
    r"[Мм]узыка",                           # Russian "music"
    r"Продолжение\s+следует",               # Russian "to be continued"
    r"♪+",                                  # music note symbols
    r"🎵+",                                 # music emoji
]

# Full-transcript hallucinations — if the ENTIRE transcript matches one of these,
# it's almost certainly hallucinated (Whisper's podcast/interview training data).
# These are checked against the full normalized transcript, not stripped from it.
_FULL_TRANSCRIPT_HALLUCINATIONS = [
    # YouTube/podcast closings
    r"^thanks?\s+for\s+(watching|listening|having\s+me|joining).*$",
    r"^thank\s+you\s+for\s+(watching|listening|having\s+me|joining|tuning\s+in).*$",
    r"^thank\s+you\.?\s*$",
    r"^you\.?\s*$",
    r"^bye[\s-]*bye\.?\s*$",
    r"^goodbye\.?\s*$",
    r"^see\s+you\s+(next\s+time|in\s+the\s+next|later|soon).*$",
    r"^i'?ll\s+see\s+you\s+in\s+the\s+next.*$",
    r"^(and\s+)?that'?s\s+(it|all)\s+for\s+(today|now|this).*$",
    r"^(so\s+)?stay\s+tuned.*$",
    r"^(please\s+)?leave\s+a\s+(comment|like).*$",
    r"^don'?t\s+forget\s+to\s+subscribe.*$",
    # Interview/podcast intros
    r"^welcome\s+(back\s+)?(to\s+the\s+show|to\s+the\s+channel|everyone).*$",
    r"^hey\s+(guys|everyone),?\s+welcome\s+back.*$",
    r"^(and\s+)?we'?re\s+back.*$",
    r"^(so\s+)?without\s+further\s+ado.*$",
    # Single filler words (Whisper loves generating these on silence)
    r"^(um|uh|hmm|ah|oh|okay|ok|yes|no|yeah|right|so|well|and)\.?\s*$",
]

_FULL_HALLUCINATION_RE = re.compile(
    "|".join(_FULL_TRANSCRIPT_HALLUCINATIONS),
    re.IGNORECASE,
)

_HALLUCINATION_RE = re.compile(
    "|".join(_HALLUCINATION_PATTERNS),
    re.IGNORECASE,
)

# Non-Latin script detector — English dictation should not contain Cyrillic,
# CJK, Arabic, Hebrew, Thai, etc. If >30% of alpha chars are non-Latin,
# the entire transcript is almost certainly a hallucination.
_NON_LATIN_RE = re.compile(r"[^\u0000-\u024F\u1E00-\u1EFF]")

def _is_non_english_hallucination(text: str) -> bool:
    """Detect if text is predominantly non-Latin script (hallucination)."""
    alpha_chars = [c for c in text if c.isalpha()]
    if not alpha_chars:
        return False
    non_latin = sum(1 for c in alpha_chars if _NON_LATIN_RE.match(c))
    return non_latin / len(alpha_chars) > 0.3

# Repetitive word/phrase detector — catches "jaa jaa jaa jaa" and
# "IHIM, IHIM, IHIM, IHIM" by stripping punctuation before comparing.
def _is_repetitive_nonsense(text: str) -> bool:
    """Detect if text is just the same word/phrase repeated 3+ times."""
    # Strip punctuation, lowercase, split into words
    words = re.sub(r"[^\w\s]", "", text).lower().split()
    if len(words) < 3:
        return False
    # Check if one word dominates (>= 70% of all words)
    from collections import Counter
    counts = Counter(words)
    most_common_word, most_common_count = counts.most_common(1)[0]
    return most_common_count / len(words) >= 0.7

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
    r"\byou know\b",
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


# ── Backtrack detection ──────────────────────────────────────────────
# Trigger phrases that indicate the speaker wants to redo the last sentence.
# Processed BEFORE filler removal so triggers aren't stripped first.
_BACKTRACK_TRIGGERS = [
    "scratch that",
    "wait no",
    "no wait",
    "i mean",
    "actually",
]

# Build a single regex: match from the last sentence boundary through the trigger
_BACKTRACK_RE = re.compile(
    r"(?:^|(?<=[.!?]\s))"          # sentence start or after sentence-ending punct
    r"[^.!?]*?"                     # content before the trigger (non-greedy)
    r"\b(?:" + "|".join(re.escape(t) for t in _BACKTRACK_TRIGGERS) + r")\b"
    r"\s*[,:]?\s*",                 # optional comma/colon after trigger
    re.IGNORECASE,
)


def _apply_backtrack(text: str) -> str:
    """Drop everything from the last sentence boundary through a backtrack trigger.

    Example: "Send the email to John, scratch that, send it to Sarah"
           → "Send it to Sarah"
    """
    # Process iteratively — multiple backtracks possible
    changed = True
    while changed:
        new_text = _BACKTRACK_RE.sub("", text, count=1)
        changed = new_text != text
        text = new_text
    return text.strip()


# ── Smart formatting ────────────────────────────────────────────────

# Numbered list: "one [text] two [text] three [text]"
# Only triggers when ordinals appear at start of text or after sentence-ending punct.
_ORDINAL_WORDS = {
    "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
    "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10",
    "first": "1", "second": "2", "third": "3", "fourth": "4", "fifth": "5",
    "sixth": "6", "seventh": "7", "eighth": "8", "ninth": "9", "tenth": "10",
}

# Match sequences like "one buy groceries two clean house three do laundry"
_NUMBERED_LIST_RE = re.compile(
    r"\b(" + "|".join(re.escape(w) for w in _ORDINAL_WORDS) + r")\b",
    re.IGNORECASE,
)

# Bullet list: "bullet [text] bullet [text]" or "dash [text] dash [text]"
_BULLET_TRIGGER_RE = re.compile(
    r"\b(bullet|dash)\b",
    re.IGNORECASE,
)


def _apply_smart_formatting(text: str) -> str:
    """Detect numbered and bullet list patterns, format them.

    Numbered lists: "one buy groceries two clean house" → "1. Buy groceries\\n2. Clean house"
    Bullet lists: "bullet buy groceries bullet clean house" → "- Buy groceries\\n- Clean house"
    """
    # --- Bullet lists ---
    bullet_parts = _BULLET_TRIGGER_RE.split(text)
    if len(bullet_parts) >= 5:  # At least 2 bullets (split produces: [before, trigger, text, trigger, text, ...])
        items = []
        for i in range(2, len(bullet_parts), 2):
            item = bullet_parts[i].strip().rstrip(".,;")
            if item:
                items.append(item)
        if len(items) >= 2:
            prefix = bullet_parts[0].strip()
            formatted = "\n".join(f"- {it[0].upper() + it[1:]}" for it in items if it)
            return (prefix + "\n" + formatted).strip() if prefix else formatted

    # --- Numbered lists ---
    # Find all ordinal word positions
    matches = list(_NUMBERED_LIST_RE.finditer(text))
    if len(matches) >= 3:
        # Check if ordinals form a sequence (1, 2, 3, ...)
        nums = []
        for m in matches:
            word = m.group(1).lower()
            if word in _ORDINAL_WORDS:
                nums.append((int(_ORDINAL_WORDS[word]), m))

        # Must be consecutive starting from 1 or have at least 3 in sequence
        if len(nums) >= 3:
            # Sort by number value
            nums.sort(key=lambda x: x[0])
            # Check for consecutive sequence
            is_sequence = all(nums[i][0] == nums[i-1][0] + 1 for i in range(1, len(nums)))

            if is_sequence:
                items = []
                for i, (num, match) in enumerate(nums):
                    start = match.end()
                    end = nums[i + 1][1].start() if i + 1 < len(nums) else len(text)
                    item = text[start:end].strip().rstrip(".,;")
                    if item:
                        items.append(f"{num}. {item[0].upper() + item[1:]}")

                if len(items) >= 3:
                    prefix = text[:nums[0][1].start()].strip()
                    formatted = "\n".join(items)
                    return (prefix + "\n" + formatted).strip() if prefix else formatted

    return text


# ── New pipeline functions ────────────────────────────────────────────

def _remove_hallucinations(text: str) -> str:
    """Strip known Whisper hallucination artifacts.

    If the entire transcript is a hallucination, returns empty string.
    Checks: full-transcript match, non-Latin script, repetitive nonsense, inline patterns.
    """
    normalized = text.strip()

    # Full-transcript hallucination check (podcast/interview phrases)
    if _FULL_HALLUCINATION_RE.match(normalized):
        logger.info("Hallucination filtered (full-transcript match): %s", normalized[:80])
        return ""

    # Non-Latin script dominance
    if _is_non_english_hallucination(normalized):
        logger.info("Hallucination filtered (non-English script): %s", normalized[:80])
        return ""

    # Repetitive nonsense
    if _is_repetitive_nonsense(normalized):
        logger.info("Hallucination filtered (repetitive): %s", normalized[:80])
        return ""

    # Inline pattern stripping (removes patterns but keeps surrounding text)
    cleaned = _HALLUCINATION_RE.sub("", normalized).strip()
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


def cleanup_transcript(raw_text: str, context: str = "prose") -> str:
    """Clean up a raw Whisper transcript using deterministic rules.

    Args:
        raw_text: Raw transcript from Whisper.
        context:  App context hint — "prose", "code", "terminal", or "chat".
                  Adjusts cleanup aggressiveness.

    Pipeline:
     1. Strip Whisper hallucination artifacts
     2. Collapse stutters (s-s-stuttering → stuttering)
     3. Convert verbal punctuation (period → .)
     4. Apply backtrack detection (scratch that, wait no, etc.)
     5. Remove filler words/phrases (skipped in "chat" context)
     6. Remove false starts (I went to the— I went to the store)
     7. Collapse repeated words
     8. Smart formatting (numbered/bullet lists)
     9. Clean punctuation artifacts
    10. Normalize whitespace
    11. Fix "i" → "I"
    12. Capitalize first character
    13. Capitalize after sentence-ending punctuation
    14. Ensure trailing punctuation (skipped in "terminal" context)
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

    # 4. Backtrack detection (before filler removal — triggers overlap with fillers)
    text = _apply_backtrack(text)

    # 5. Remove fillers (skip in chat context — casual tone OK)
    if context != "chat":
        text = _FILLER_RE.sub("", text)
        text = _SORRY_RE.sub("", text)

    # 6. Remove false starts
    text = _remove_false_starts(text)

    # 7. Collapse repeated words
    text = _REPEATED_WORD_RE.sub(r"\1", text)

    # 8. Smart formatting (numbered/bullet lists)
    text = _apply_smart_formatting(text)

    # 9. Clean up punctuation artifacts from filler removal
    text = _MULTI_COMMA_RE.sub(", ", text)
    text = _SPACE_BEFORE_PUNCT_RE.sub(r"\1", text)

    # 10. Normalize whitespace (preserve newlines from punctuation commands)
    text = re.sub(r"[^\S\n]+", " ", text)
    text = text.strip()

    # 11. Fix standalone "i" → "I"
    text = re.sub(r"\bi\b", "I", text)

    # 12. Capitalize first character
    if text:
        text = text[0].upper() + text[1:]

    # 13. Capitalize after sentence-ending punctuation
    def _cap(m):
        return m.group(0)[:-1] + m.group(1).upper()
    text = _SENTENCE_START_RE.sub(_cap, text)

    # 14. Ensure trailing punctuation (skip for terminal — commands don't end with .)
    if context != "terminal" and text and text[-1] not in ".!?\n":
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
