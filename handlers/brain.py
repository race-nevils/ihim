"""Brain handler: classify and store notes in the Second Brain.

Dual storage architecture:
- SQLite database (IHIM/data/brain.db) for machine queries
- Obsidian vault (Obsidian Vault/iHIM/iHIM Memory/) for human browsing

File tracking: Database tracks source_filename + content_hash for deduplication
and update-in-place (Living Editable Zone pattern).
"""
import hashlib
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
from data.database import (
    insert_entry,
    update_entry,
    get_entry_by_source_filename,
    check_file_changed,
    update_file_tracking
)
from data.jsonld import (
    create_brain_entry_jsonld,
    write_jsonld,
    update_jsonld,
    compute_jsonld_hash
)

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
CATEGORIES = ["People", "Projects", "Ideas", "Admin", "Tasks"]

# Confidence threshold
CONFIDENCE_THRESHOLD = 0.7


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
{{"category": "<People|Projects|Ideas|Admin|Tasks>", "confidence": <0.0-1.0>, "summary": "<1 sentence summary>", "title": "<short title, 3-5 words>"}}

Note: {content}

JSON response:"""


def slugify(text: str) -> str:
    """Convert text to a filename-safe slug (for JSON-LD layer)."""
    # Lowercase, replace spaces with hyphens, remove special chars
    text = text.lower().strip()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[\s_]+', '-', text)
    text = re.sub(r'-+', '-', text)
    return text[:50]  # Limit length


def sanitize_title(text: str) -> str:
    """Sanitize title for use as Obsidian filename (human-readable, title case).

    Removes characters not allowed in Windows filenames while preserving
    readability: \\ / : * ? \" < > |
    """
    text = text.strip()
    # Remove Windows-forbidden characters
    text = re.sub(r'[\\/:*?"<>|]', '', text)
    # Collapse multiple spaces
    text = re.sub(r'\s+', ' ', text)
    # Limit length (Obsidian handles long names poorly)
    return text[:60]


def compute_content_hash(content: str) -> str:
    """Compute SHA-256 hash of content for change detection.

    Returns first 16 chars of hex digest (enough for uniqueness).
    """
    return hashlib.sha256(content.encode('utf-8')).hexdigest()[:16]


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


def write_to_brain(content: str, classification: dict, source_file: Optional[str] = None,
                   source_filename: Optional[str] = None) -> tuple[Path, str]:
    """Write a note to JSON-LD (source), SQLite (index), and Obsidian (view).

    Triple write architecture:
    1. JSON-LD: Source of truth (can rebuild everything from these)
    2. SQLite: Query index for fast lookups
    3. Obsidian: Human-readable view for browsing

    Args:
        content: The note content
        classification: Dict with category, confidence, summary, title
        source_file: Optional source file path (full path)
        source_filename: Optional original inbox filename (for deduplication)

    Returns:
        Tuple of (Path to Obsidian file, note_id for database)
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

    # Compute content hash for file tracking
    content_hash = compute_content_hash(content)

    # === WRITE 1: JSON-LD (Source of Truth) ===
    jsonld_path = None
    try:
        jsonld_doc = create_brain_entry_jsonld(
            entry_id=note_id,
            title=title,
            category=category,
            content=content,
            summary=summary,
            confidence=confidence,
            source_file=source_file,
            classifier=OllamaAdapter.FAST_MODEL,
            slug=slug,
            date_str=date_str
        )
        jsonld_path = write_jsonld(jsonld_doc, category, slug, date_str)
        logger.info(f"Written to JSON-LD: {jsonld_path}")
    except Exception as e:
        logger.error(f"Failed to write JSON-LD: {e}")

    # === WRITE 2: SQLite Database (Query Index) ===
    try:
        insert_entry({
            "id": note_id,
            "title": title,
            "category": category,
            "content": content,
            "summary": summary,
            "confidence": confidence,
            "source_file": source_file or "direct",
            "classifier": OllamaAdapter.FAST_MODEL,
            "source_filename": source_filename,
            "content_hash": content_hash,
            "jsonld_path": str(jsonld_path) if jsonld_path else None
        })
        logger.info(f"Written to SQLite: {note_id}")
    except Exception as e:
        logger.error(f"Failed to write to SQLite: {e}")
        # Continue to Obsidian write even if SQLite fails

    # === WRITE 3: Obsidian Memory (Human View) ===
    # Obsidian uses Title-only naming (human-readable, GUI layer)
    target_dir = OBSIDIAN_MEMORY / category
    target_dir.mkdir(parents=True, exist_ok=True)

    display_title = sanitize_title(title)
    filename = f"{display_title}.md"
    file_path = target_dir / filename

    # Handle collisions (Obsidian-style numbering)
    counter = 1
    while file_path.exists():
        filename = f"{display_title} {counter}.md"
        file_path = target_dir / filename
        counter += 1

    # Content only - no frontmatter (metadata lives in JSON-LD, the source of truth)
    file_path.write_text(content, encoding="utf-8")
    logger.info(f"Written to Obsidian: {file_path}")
    return file_path, note_id


def write_to_needs_review(content: str, classification: dict, source_file: Optional[str] = None,
                          source_filename: Optional[str] = None) -> Path:
    """Write a low-confidence note to needs_review (JSON-LD, SQLite, and Obsidian).

    Args:
        content: The note content
        classification: Dict with category, confidence, summary, title
        source_file: Optional source file path
        source_filename: Optional original inbox filename (for deduplication)

    Returns:
        Path to the created Obsidian file
    """
    timestamp = datetime.now(timezone.utc)
    date_str = timestamp.strftime("%Y%m%d")
    title = classification.get('title', 'needs review')
    slug = slugify(title)
    note_id = f"review-{timestamp.strftime('%Y%m%d%H%M%S')}-{slug[:8]}"

    # Compute content hash for file tracking
    content_hash = compute_content_hash(content)

    # === WRITE 1: JSON-LD (Source of Truth) ===
    jsonld_path = None
    try:
        jsonld_doc = create_brain_entry_jsonld(
            entry_id=note_id,
            title=title,
            category="needs_review",
            content=content,
            summary=classification.get('summary', ''),
            confidence=classification.get('confidence', 0.0),
            source_file=source_file,
            classifier=OllamaAdapter.FAST_MODEL,
            slug=slug,
            date_str=date_str
        )
        # Add review-specific metadata
        jsonld_doc["ihim:suggestedCategory"] = classification.get('category', 'unknown')
        jsonld_doc["ihim:needsReview"] = True
        jsonld_path = write_jsonld(jsonld_doc, "needs_review", slug, date_str)
        logger.info(f"Written to JSON-LD (needs_review): {jsonld_path}")
    except Exception as e:
        logger.error(f"Failed to write needs_review JSON-LD: {e}")

    # === WRITE 2: SQLite Database (with needs_review category) ===
    try:
        insert_entry({
            "id": note_id,
            "title": title,
            "category": "needs_review",  # Special category for low confidence
            "content": content,
            "summary": classification.get('summary', ''),
            "confidence": classification.get('confidence', 0.0),
            "source_file": source_file or "direct",
            "classifier": OllamaAdapter.FAST_MODEL,
            "source_filename": source_filename,
            "content_hash": content_hash,
            "jsonld_path": str(jsonld_path) if jsonld_path else None
        })
        logger.info(f"Written to SQLite (needs_review): {note_id}")
    except Exception as e:
        logger.error(f"Failed to write needs_review to SQLite: {e}")

    # === WRITE 3: Obsidian Memory needs_review folder (Human View) ===
    # Title-only naming for consistency with main categories
    NEEDS_REVIEW_DIR.mkdir(parents=True, exist_ok=True)

    display_title = sanitize_title(title)
    filename = f"{display_title}.md"
    file_path = NEEDS_REVIEW_DIR / filename

    # Handle collisions
    counter = 1
    while file_path.exists():
        filename = f"{display_title} {counter}.md"
        file_path = NEEDS_REVIEW_DIR / filename
        counter += 1

    # Content only - no frontmatter (metadata lives in JSON-LD, the source of truth)
    file_path.write_text(content, encoding="utf-8")
    logger.info(f"Written to Obsidian (needs_review): {file_path}")
    return file_path


def update_brain_entry(
    entry_id: str,
    obsidian_path: str,
    content: str,
    classification: dict,
    source_file: Optional[str] = None
) -> tuple[Path, bool]:
    """Update an existing brain entry in-place (both SQLite and Obsidian).

    This is the core of the Living Editable Zone - instead of creating
    new files on each edit, we update the existing file.

    Args:
        entry_id: The existing brain database ID
        obsidian_path: Path to existing Obsidian file
        content: New/updated content
        classification: New classification (may have changed)
        source_file: Source file path for provenance

    Returns:
        Tuple of (obsidian_path, category_changed)
        - obsidian_path: Path where content was written (may be new if reclassified)
        - category_changed: True if file was moved to different category
    """
    new_category = classification.get("category", "Ideas")
    title = classification.get("title", "untitled")
    summary = classification.get("summary", "")
    confidence = classification.get("confidence", 0.0)

    # Ensure category is valid
    if new_category not in CATEGORIES:
        new_category = "Ideas"

    old_path = Path(obsidian_path)
    category_changed = False

    # Check if category changed (requires file move)
    if old_path.exists():
        # Extract old category from path
        old_category = old_path.parent.name
        if old_category != new_category and old_category in CATEGORIES:
            category_changed = True
            # Move to new category folder (preserve title-only naming)
            new_dir = OBSIDIAN_MEMORY / new_category
            new_dir.mkdir(parents=True, exist_ok=True)
            new_path = new_dir / old_path.name
            # Handle collision in new location (Obsidian-style numbering)
            counter = 1
            while new_path.exists():
                stem = old_path.stem
                new_path = new_dir / f"{stem} {counter}.md"
                counter += 1
            old_path.rename(new_path)
            old_path = new_path
            logger.info(f"Moved file from {old_category} to {new_category}")

    # === UPDATE 1: SQLite Database ===
    try:
        update_entry(entry_id, {
            "title": title,
            "category": new_category,
            "content": content,
            "summary": summary,
            "confidence": confidence
        })
        logger.info(f"Updated SQLite entry: {entry_id}")
    except Exception as e:
        logger.error(f"Failed to update SQLite: {e}")

    # === UPDATE 2: Obsidian File ===
    # Content only - no frontmatter (metadata lives in JSON-LD, the source of truth)
    old_path.write_text(content, encoding="utf-8")
    logger.info(f"Updated Obsidian file: {old_path}")

    return old_path, category_changed


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

    Supports Living Editable Zone pattern:
    - New files: Classify and create new entries
    - Existing files (detected via database): Update in-place

    File tracking uses database columns (source_filename, content_hash)
    instead of a separate staging registry.

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

    # Extract source filename for deduplication
    source_filename = None
    if source_file:
        source_filename = Path(source_file).name

    # Compute content hash for change detection
    content_hash = compute_content_hash(content)

    try:
        # Check if we've seen this file before (database lookup replaces staging)
        is_new, has_changed = check_file_changed(source_filename, content_hash) if source_filename else (True, False)

        # If unchanged, skip processing
        if not is_new and not has_changed:
            state["result"] = {"action": "skipped", "reason": "unchanged"}
            return state

        # Always reclassify to detect category changes
        classification = adapter.generate_json(
            CLASSIFY_PROMPT.format(content=content),
            model=OllamaAdapter.FAST_MODEL
        )

        confidence = float(classification.get("confidence", 0.0))

        # === LIVING EDITABLE ZONE: Update-in-place ===
        if not is_new and has_changed:
            # Existing file with changes - update instead of create new
            existing = get_entry_by_source_filename(source_filename)
            if existing:
                entry_id = existing.get("id", "")
                # Derive obsidian path from category and title
                old_category = existing.get("category", "Ideas")
                old_title = existing.get("title", "untitled")
                old_slug = slugify(old_title)
                # Find the file in the old category folder
                old_dir = OBSIDIAN_MEMORY / old_category
                possible_files = list(old_dir.glob(f"{old_slug}*.md")) if old_dir.exists() else []
                obsidian_path = str(possible_files[0]) if possible_files else ""

                if entry_id and obsidian_path:
                    dest_path, category_changed = update_brain_entry(
                        entry_id=entry_id,
                        obsidian_path=obsidian_path,
                        content=content,
                        classification=classification,
                        source_file=source_file
                    )
                    action = "updated"
                    if category_changed:
                        action = "updated_reclassified"

                    # Update content hash in database
                    update_file_tracking(entry_id, source_filename, content_hash)

                    # Log receipt for update
                    log_receipt(state, classification, action, dest_path)

                    state["result"] = {
                        "action": action,
                        "category": classification.get("category"),
                        "confidence": confidence,
                        "title": classification.get("title"),
                        "summary": classification.get("summary"),
                        "destination": str(dest_path),
                        "processed_id": entry_id
                    }
                    return state

        # === NEW FILE: Create new entry ===
        processed_id = None
        # Apply bouncer (confidence gating)
        if confidence >= CONFIDENCE_THRESHOLD:
            # High confidence: store in brain
            dest_path, processed_id = write_to_brain(
                content, classification, source_file, source_filename
            )
            action = "classified"
        else:
            # Low confidence: needs review
            dest_path = write_to_needs_review(
                content, classification, source_file, source_filename
            )
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
            "destination": str(dest_path),
            "processed_id": processed_id
        }

    except Exception as e:
        state["error"] = f"Brain handler error: {str(e)}"
        state["result"] = {"action": "error", "error": str(e)}

    return state
