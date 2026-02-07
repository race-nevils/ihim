"""Instruction extraction from note content.

Separates meta-instructions (commands to the system) from
actual content (facts to classify and store).

Layer 1 of the Content/Instruction Separation System.
"""
import json
import re
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

IHIM_ROOT = Path(__file__).parent.parent
LEXICON_PATH = IHIM_ROOT / "data" / "lexicon" / "instruction_lexicon_v1.0.json"


class InstructionLexicon:
    """Instruction pattern library for extracting meta-instructions."""

    def __init__(self, lexicon_path: Path):
        self._data = json.loads(lexicon_path.read_text(encoding="utf-8"))
        self._terms = self._data.get("instruction_terms", [])
        # Sort phrases longest-first to prevent partial matches
        self._phrases_sorted = sorted(
            [t["phrase"] for t in self._terms],
            key=len,
            reverse=True
        )
        logger.info(f"Loaded instruction lexicon: {len(self._terms)} instruction terms")

    def get_instruction_terms(self) -> list[dict]:
        """Get all instruction term definitions."""
        return self._terms

    def get_phrases_sorted(self) -> list[str]:
        """Get instruction phrases sorted longest-first."""
        return self._phrases_sorted


# Singleton
_lexicon: Optional[InstructionLexicon] = None


def get_instruction_lexicon() -> InstructionLexicon:
    """Get or create the singleton InstructionLexicon instance."""
    global _lexicon
    if _lexicon is None:
        _lexicon = InstructionLexicon(LEXICON_PATH)
    return _lexicon


def extract_instructions(content: str, title: str = "") -> dict:
    """Extract meta-instructions from content.

    Detects instruction phrases like "needs to be", "make this", etc.
    Removes them from content so classification sees clean facts.

    Args:
        content: Note content to process
        title: Optional title for context

    Returns:
        {
            "clean_content": str,      # Content with instructions removed
            "instructions": [          # Extracted instructions
                {"type": "action_request", "phrase": "needs to be", "context": "..."},
            ],
            "category_hints": [],      # Explicit category hints if found
            "original_content": str,   # Unchanged original
        }
    """
    lexicon = get_instruction_lexicon()
    instructions = []
    category_hints = []
    clean_content = content

    # Track what to strip from content
    strips = []

    for phrase in lexicon.get_phrases_sorted():
        # Case-insensitive search
        pattern = r"\b" + re.escape(phrase) + r"\b"
        matches = list(re.finditer(pattern, content, re.IGNORECASE))

        if matches:
            # Find the term definition
            term_def = next(
                (t for t in lexicon.get_instruction_terms() if t["phrase"] == phrase),
                None
            )
            if not term_def:
                continue

            for match in matches:
                instr_type = term_def["type"]
                semantics = term_def.get("semantics", {})

                # Extract context (text around the match)
                start = match.start()
                end = match.end()
                context_start = max(0, start - 20)
                context_end = min(len(content), end + 50)
                context = content[context_start:context_end].strip()

                instruction = {
                    "type": instr_type,
                    "phrase": match.group(0),
                    "context": context,
                    "position": start,
                }

                # Handle category hints
                if instr_type == "categorization" and semantics.get("extract_target"):
                    # Try to extract the category name after the phrase
                    remainder = content[end:].strip()
                    # Match next word(s) that could be a category
                    cat_match = re.match(r"^(\w+(?:\s+\w+)?)", remainder)
                    if cat_match:
                        hint = cat_match.group(1).strip()
                        category_hints.append(hint)
                        instruction["target_category"] = hint

                instructions.append(instruction)

                # Mark for stripping if configured
                if semantics.get("strip_from_classification"):
                    # Strip the phrase and some context to clean up grammar
                    # For "This needs to be X" -> strip "This needs to be"
                    # For sentence-ending instruction, strip the whole sentence fragment
                    strip_start = start
                    strip_end = end

                    # Extend to include common trailing words
                    remainder = content[end:].strip()
                    # Match things like "annually", "recurring", "urgent" after instruction
                    trail_match = re.match(
                        r"^(\s+(?:annually|recurring|urgent|ASAP|weekly|monthly|daily|yearly))+",
                        remainder,
                        re.IGNORECASE
                    )
                    if trail_match:
                        strip_end += len(trail_match.group(0))

                    strips.append((strip_start, strip_end))

    # Apply strips (in reverse order to preserve indices)
    if strips:
        # Merge overlapping strips
        strips.sort()
        merged = []
        for start, end in strips:
            if merged and start <= merged[-1][1]:
                # Overlapping, extend the previous strip
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                merged.append((start, end))

        # Build clean content by removing stripped ranges
        parts = []
        last_end = 0
        for start, end in merged:
            parts.append(content[last_end:start])
            last_end = end
        parts.append(content[last_end:])
        clean_content = "".join(parts)

        # Clean up extra whitespace
        clean_content = re.sub(r"\s+", " ", clean_content).strip()
        clean_content = re.sub(r"\.\s*\.", ".", clean_content)  # Remove double periods

    if instructions:
        logger.info(f"[instruction] Extracted {len(instructions)} instruction(s): "
                    f"{[i['phrase'] for i in instructions]}")

    return {
        "clean_content": clean_content,
        "instructions": instructions,
        "category_hints": category_hints,
        "original_content": content,
    }
