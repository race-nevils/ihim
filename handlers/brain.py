"""Brain handler: classify and store notes in the Second Brain.

Dual storage architecture:
- SQLite database (IHIM/data/brain.db) for machine queries
- Obsidian vault (Obsidian Vault/iHIM/iHIM Memory/) for human browsing
"""
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
import re

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from adapters.ollama import OllamaAdapter
from orchestrator.state import OrchestratorState
from data.database import insert_entry

logger = logging.getLogger(__name__)

# Paths - machine layer (SQLite is handled by data.database module)
IHIM_ROOT = Path(__file__).parent.parent
WORKSPACE_ROOT = IHIM_ROOT.parent
DATA_DIR = IHIM_ROOT / "data" / "local" / "brain"  # Legacy, keep for logs
LOGS_DIR = DATA_DIR / "logs"

# Paths - human layer (Obsidian)
OBSIDIAN_MEMORY = WORKSPACE_ROOT / "Obsidian Vault" / "iHIM" / "iHIM Memory"
NEEDS_REVIEW_DIR = OBSIDIAN_MEMORY / "needs_review"

# Valid categories
CATEGORIES = ["People", "Projects", "Ideas", "Admin"]

# Confidence threshold
CONFIDENCE_THRESHOLD = 0.7


CLASSIFY_PROMPT = """Classify this note into ONE category: People, Projects, Ideas, or Admin.

Categories:
- People: notes about individuals, conversations, relationships
- Projects: work items, technical projects, goals with deliverables
- Ideas: thoughts, concepts, theories, brainstorming, creative content
- Admin: logistics, scheduling, finances, household, routine tasks

Return ONLY valid JSON with no extra text:
{{"category": "<People|Projects|Ideas|Admin>", "confidence": <0.0-1.0>, "summary": "<1 sentence summary>", "title": "<short title, 3-5 words>"}}

Note: {content}

JSON response:"""


def slugify(text: str) -> str:
    """Convert text to a filename-safe slug."""
    # Lowercase, replace spaces with hyphens, remove special chars
    text = text.lower().strip()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[\s_]+', '-', text)
    text = re.sub(r'-+', '-', text)
    return text[:50]  # Limit length


def yaml_escape(text: str) -> str:
    """Escape a string for safe use in YAML double-quoted values.

    Escapes backslashes and double quotes to prevent YAML parsing errors.
    """
    if not text:
        return ""
    # Escape backslashes first, then double quotes
    text = text.replace("\\", "\\\\")
    text = text.replace('"', '\\"')
    # Also escape newlines
    text = text.replace("\n", "\\n")
    return text


def write_to_brain(content: str, classification: dict, source_file: Optional[str] = None) -> Path:
    """Write a note to BOTH SQLite database and Obsidian Memory folder.

    Dual write ensures:
    - SQLite: Machine-readable for queries/automation
    - Obsidian: Human-readable for browsing/GUI

    Args:
        content: The note content
        classification: Dict with category, confidence, summary, title
        source_file: Optional source file path

    Returns:
        Path to the created Obsidian file
    """
    category = classification.get("category", "Ideas")
    title = classification.get("title", "untitled")
    summary = classification.get("summary", "")
    confidence = classification.get("confidence", 0.0)

    # Ensure category is valid
    if category not in CATEGORIES:
        category = "Ideas"

    # Generate timestamp and ID
    timestamp = datetime.now(timezone.utc)
    date_str = timestamp.strftime("%Y%m%d")
    slug = slugify(title)
    note_id = f"brain-{timestamp.strftime('%Y%m%d%H%M%S')}-{slug[:8]}"

    # === WRITE 1: SQLite Database ===
    try:
        insert_entry({
            "id": note_id,
            "title": title,
            "category": category,
            "content": content,
            "summary": summary,
            "confidence": confidence,
            "source_file": source_file or "direct",
            "classifier": OllamaAdapter.FAST_MODEL
        })
        logger.info(f"Written to SQLite: {note_id}")
    except Exception as e:
        logger.error(f"Failed to write to SQLite: {e}")
        # Continue to Obsidian write even if SQLite fails

    # === WRITE 2: Obsidian Memory ===
    target_dir = OBSIDIAN_MEMORY / category
    target_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{slug}-{date_str}.md"
    file_path = target_dir / filename

    # Handle collisions
    counter = 1
    while file_path.exists():
        filename = f"{slug}-{date_str}-{counter}.md"
        file_path = target_dir / filename
        counter += 1

    # Create note with frontmatter (escape values to prevent YAML breakage)
    frontmatter = f"""---
id: "{note_id}"
title: "{yaml_escape(title)}"
category: "{category}"
confidence: {confidence:.2f}
summary: "{yaml_escape(summary)}"
classified_at: "{timestamp.isoformat()}"
classifier: "{OllamaAdapter.FAST_MODEL}"
source_file: "{yaml_escape(source_file) if source_file else 'direct'}"
---

"""
    file_path.write_text(frontmatter + content, encoding="utf-8")
    logger.info(f"Written to Obsidian: {file_path}")
    return file_path


def write_to_needs_review(content: str, classification: dict, source_file: Optional[str] = None) -> Path:
    """Write a low-confidence note to needs_review (both SQLite and Obsidian).

    Args:
        content: The note content
        classification: Dict with category, confidence, summary, title
        source_file: Optional source file path

    Returns:
        Path to the created Obsidian file
    """
    timestamp = datetime.now(timezone.utc)
    title = classification.get('title', 'needs review')
    slug = slugify(title)
    note_id = f"review-{timestamp.strftime('%Y%m%d%H%M%S')}-{slug[:8]}"

    # === WRITE 1: SQLite Database (with needs_review category) ===
    try:
        insert_entry({
            "id": note_id,
            "title": title,
            "category": "needs_review",  # Special category for low confidence
            "content": content,
            "summary": classification.get('summary', ''),
            "confidence": classification.get('confidence', 0.0),
            "source_file": source_file or "direct",
            "classifier": OllamaAdapter.FAST_MODEL
        })
        logger.info(f"Written to SQLite (needs_review): {note_id}")
    except Exception as e:
        logger.error(f"Failed to write needs_review to SQLite: {e}")

    # === WRITE 2: Obsidian Memory needs_review folder ===
    NEEDS_REVIEW_DIR.mkdir(parents=True, exist_ok=True)

    filename = f"review-{timestamp.strftime('%Y%m%d-%H%M%S')}.md"
    file_path = NEEDS_REVIEW_DIR / filename

    # Create note with classification metadata for manual review (escape values)
    frontmatter = f"""---
id: "{note_id}"
suggested_category: "{classification.get('category', 'unknown')}"
confidence: {classification.get('confidence', 0.0):.2f}
suggested_title: "{yaml_escape(title)}"
suggested_summary: "{yaml_escape(classification.get('summary', ''))}"
classified_at: "{timestamp.isoformat()}"
classifier: "{OllamaAdapter.FAST_MODEL}"
source_file: "{yaml_escape(source_file) if source_file else 'direct'}"
needs_review: true
---

{content}
"""
    file_path.write_text(frontmatter, encoding="utf-8")
    logger.info(f"Written to Obsidian (needs_review): {file_path}")
    return file_path


def log_receipt(state: OrchestratorState, classification: dict, action: str, destination: Path) -> None:
    """Log a receipt entry for this processing action.

    Args:
        state: The orchestrator state
        classification: The classification result
        action: What was done (e.g., "classified", "needs_review")
        destination: Where the file was written
    """
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOGS_DIR / "receipt.jsonl"

    timestamp = datetime.now(timezone.utc)
    receipt = {
        "id": f"receipt-{timestamp.strftime('%Y%m%d%H%M%S')}",
        "timestamp": timestamp.isoformat(),
        "source_file": state.get("source_file", "direct"),
        "action": action,
        "category": classification.get("category"),
        "confidence": classification.get("confidence"),
        "destination": str(destination),
        "classifier": OllamaAdapter.FAST_MODEL
    }

    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(receipt) + "\n")


def handle(state: OrchestratorState) -> OrchestratorState:
    """Handle brain intent: classify and store the note.

    Args:
        state: Current orchestrator state

    Returns:
        Updated state with processing result
    """
    adapter = OllamaAdapter()
    content = state.get("input_text", "")
    source_file = state.get("source_file")

    if not content.strip():
        state["error"] = "Empty content, nothing to classify"
        state["result"] = {"action": "skipped", "reason": "empty_content"}
        return state

    try:
        # Classify the content
        classification = adapter.generate_json(
            CLASSIFY_PROMPT.format(content=content),
            model=OllamaAdapter.FAST_MODEL
        )

        confidence = float(classification.get("confidence", 0.0))

        # Apply bouncer (confidence gating)
        if confidence >= CONFIDENCE_THRESHOLD:
            # High confidence: store in brain
            dest_path = write_to_brain(content, classification, source_file)
            action = "classified"
        else:
            # Low confidence: needs review
            dest_path = write_to_needs_review(content, classification, source_file)
            action = "needs_review"

        # Log receipt
        log_receipt(state, classification, action, dest_path)

        # Update state with result
        state["result"] = {
            "action": action,
            "category": classification.get("category"),
            "confidence": confidence,
            "title": classification.get("title"),
            "summary": classification.get("summary"),
            "destination": str(dest_path)
        }

    except Exception as e:
        state["error"] = f"Brain handler error: {str(e)}"
        state["result"] = {"action": "error", "error": str(e)}

    return state
