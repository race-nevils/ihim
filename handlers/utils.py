"""Shared utilities for brain handlers.

Extracted from the original brain.py for modularity.
"""
import hashlib
import re
from pathlib import Path
from typing import Optional

# Valid categories (Misc is catch-all for low-confidence items)
# Based on MECE principle: Mutually Exclusive, Collectively Exhaustive
CATEGORIES = ["Tasks", "Projects", "People", "Ideas", "Reference", "Misc"]

# Confidence threshold for routing to specific category vs Misc
# Higher = more strict, more goes to Misc when uncertain
CONFIDENCE_THRESHOLD = 0.8

# LLM classification prompt - Decision tree for mutual exclusivity
CLASSIFY_PROMPT = """Classify this note into exactly ONE category by following this decision tree IN ORDER:

STEP 1: Is there a specific ACTION to complete? (verb like: clean, call, buy, fix, remind, send, check)
  → YES: Category = "Tasks"
  → NO: Continue to Step 2

STEP 2: Is this about a PERSON (name mentioned, relationship, contact info, conversation)?
  → YES: Category = "People"
  → NO: Continue to Step 3

STEP 3: Is this a MULTI-STEP GOAL with a deadline or end state? (project, initiative, thing being built)
  → YES: Category = "Projects"
  → NO: Continue to Step 4

STEP 4: Is this EXPLORATION or BRAINSTORMING? (what if, maybe, wondering, idea, concept, no commitment)
  → YES: Category = "Ideas"
  → NO: Continue to Step 5

STEP 5: Is this STATIC INFORMATION to remember? (facts, addresses, how-to, reference, documentation)
  → YES: Category = "Reference"
  → NO: Category = "Ideas" (default for unclear content)

EXAMPLES:
- "Need to clean oil from prop" → Tasks (has action verb "clean")
- "Remind Sarah about the pipes" → Tasks (has action verb "remind")
- "Sarah's new phone number is 555-1234" → People (about a person)
- "Talked to Mike about the deal" → People (conversation with person)
- "Launch iHIM v2 by March" → Projects (multi-step goal with deadline)
- "Working on the rental renovation" → Projects (ongoing initiative)
- "What if we used Redis for caching?" → Ideas (exploration, "what if")
- "Maybe try a different approach" → Ideas (no commitment)
- "API key for Stripe: sk_live_xxx" → Reference (static fact)
- "How to reset the router" → Reference (how-to info)

Return ONLY valid JSON:
{{"category": "<Tasks|People|Projects|Ideas|Reference>", "confidence": <0.0-1.0>, "summary": "<1 sentence describing the note>"}}

Note: {content}

JSON response:"""


def slugify(text: str) -> str:
    """Convert text to a filename-safe slug (for JSON-LD layer)."""
    text = text.lower().strip()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[\s_]+', '-', text)
    text = re.sub(r'-+', '-', text)
    return text[:50]


def sanitize_title(text: str) -> str:
    """Sanitize title for use as Obsidian filename (human-readable).

    Removes characters not allowed in Windows filenames: \\ / : * ? " < > |
    """
    text = text.strip()
    text = re.sub(r'[\\/:*?"<>|]', '', text)
    text = re.sub(r'\s+', ' ', text)
    return text[:60]


def compute_content_hash(content: str) -> str:
    """Compute SHA-256 hash of content for change detection.

    Returns first 16 chars of hex digest (enough for uniqueness).
    """
    return hashlib.sha256(content.encode('utf-8')).hexdigest()[:16]


def extract_title(content: str, source_filename: Optional[str] = None) -> str:
    """Extract title from frontmatter or filename - DO NOT generate or infer.

    Title priority:
    1. Frontmatter 'title:' field (from capture widget)
    2. Source filename stem (what user saved as)
    3. "Untitled" fallback

    Args:
        content: The note content (checked for frontmatter title)
        source_filename: Original filename (e.g., "My Note.md")

    Returns:
        Title from frontmatter, filename stem, or "Untitled"
    """
    # Check frontmatter for title
    if content and content.startswith("---"):
        # Find end of frontmatter
        end_idx = content.find("---", 3)
        if end_idx > 0:
            frontmatter = content[3:end_idx]
            # Look for title: "..." or title: '...' or title: ...
            for line in frontmatter.split("\n"):
                line = line.strip()
                if line.startswith("title:"):
                    title_val = line[6:].strip()
                    # Remove quotes if present
                    if (title_val.startswith('"') and title_val.endswith('"')) or \
                       (title_val.startswith("'") and title_val.endswith("'")):
                        title_val = title_val[1:-1]
                    if title_val:
                        return title_val

    # Fallback to filename
    if source_filename:
        stem = Path(source_filename).stem
        # Ignore timestamp-only filenames (e.g., 20260129_042620_6d06ddad)
        if not re.match(r"^\d{8}_\d{6}_[a-f0-9]+$", stem):
            return stem

    return "Untitled"


def yaml_escape(text: str) -> str:
    """Escape a string for safe use in YAML double-quoted values."""
    if not text:
        return ""
    text = text.replace("\\", "\\\\")
    text = text.replace('"', '\\"')
    text = text.replace("\n", "\\n")
    return text
