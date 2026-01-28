"""Shared utilities for brain handlers.

Extracted from the original brain.py for modularity.
"""
import hashlib
import re
from pathlib import Path
from typing import Optional

# Valid categories (Misc is catch-all for low-confidence items)
CATEGORIES = ["People", "Projects", "Ideas", "Admin", "Tasks", "Misc"]

# Confidence threshold for routing to specific category vs Misc
CONFIDENCE_THRESHOLD = 0.7

# LLM classification prompt
CLASSIFY_PROMPT = """Classify this note into ONE category: People, Projects, Ideas, Admin, or Tasks.

Categories (choose the BEST fit):
- People: individuals, relationships, conversations, contact info, "talked to...", "meeting with..."
- Projects: active initiatives with deliverables, technical work, goals, milestones, "working on..."
- Ideas: concepts, theories, brainstorming, explorations, creative thoughts, "what if...", "maybe we could..."
- Admin: reference info, logistics, finances, household management, documentation, static records
- Tasks: action items, todos, things to complete, "need to...", "should...", "don't forget...", reminders

Key distinctions:
- Tasks are ACTIONS to complete (has a done/not-done state)
- Admin is REFERENCE info or ongoing maintenance (no completion state)
- Projects are INITIATIVES with multiple steps over time
- Ideas are EXPLORATIONS without commitment

Return ONLY valid JSON with no extra text:
{{"category": "<People|Projects|Ideas|Admin|Tasks>", "confidence": <0.0-1.0>, "summary": "<1 sentence summary>"}}

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
    """Extract title from source filename - DO NOT generate or infer.

    Title = what the user typed as the filename. Period.
    No inference, no first-line detection, no smartness.

    Args:
        content: The note content (unused, kept for signature compatibility)
        source_filename: Original filename (e.g., "My Note.md")

    Returns:
        Filename stem as title, or "Untitled" if no filename
    """
    if source_filename:
        return Path(source_filename).stem
    return "Untitled"


def yaml_escape(text: str) -> str:
    """Escape a string for safe use in YAML double-quoted values."""
    if not text:
        return ""
    text = text.replace("\\", "\\\\")
    text = text.replace('"', '\\"')
    text = text.replace("\n", "\\n")
    return text
