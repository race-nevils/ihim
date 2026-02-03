"""Triple-write storage for brain handler.

Architecture: JSON-LD (source) → SQLite (index) → Obsidian (view)

Single responsibility: write brain entries to all three layers.
All storage operations are traced via Langfuse.
"""
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from handlers.tracing import observe, langfuse_context, TracingSpan

from adapters.ollama import OllamaAdapter
from adapters.embeddings import EmbeddingAdapter
from data.database import insert_entry, update_entry, store_embedding
from data.jsonld import (
    create_brain_entry_jsonld,
    write_jsonld,
    update_jsonld_content
)
from handlers.utils import (
    CATEGORIES,
    CONFIDENCE_THRESHOLD,
    slugify,
    sanitize_title,
    compute_content_hash
)

logger = logging.getLogger(__name__)

# Paths
IHIM_ROOT = Path(__file__).parent.parent
WORKSPACE_ROOT = IHIM_ROOT.parent
OBSIDIAN_MEMORY = WORKSPACE_ROOT / "Obsidian Vault" / "iHIM" / "iHIM Memory"
LOGS_DIR = IHIM_ROOT / "data" / "local" / "brain" / "logs"


@observe(name="store_new")
def store_new(
    content: str,
    classification: dict,
    source_file: Optional[str] = None,
    source_filename: Optional[str] = None
) -> tuple[Path, str]:
    """Store a new brain entry (triple-write).

    Writes to:
    1. JSON-LD (source of truth)
    2. SQLite (query index)
    3. Obsidian (human view)

    Low-confidence entries are routed to Misc.

    Args:
        content: Note content
        classification: Dict with category, confidence, summary, title
        source_file: Full source file path
        source_filename: Original inbox filename

    Returns:
        Tuple of (Obsidian path, note_id)
    """
    # Extract classification fields
    category = classification.get("category", "Ideas")
    title = classification.get("title", "untitled")
    summary = classification.get("summary", "")
    confidence = float(classification.get("confidence", 0.0))

    # Validate category
    if category not in CATEGORIES:
        category = "Ideas"

    # Low confidence → route to Misc
    if confidence < CONFIDENCE_THRESHOLD:
        category = "Misc"

    # Generate identifiers
    timestamp = datetime.now(timezone.utc)
    date_str = timestamp.strftime("%Y%m%d")
    slug = slugify(title)
    prefix = "misc" if category == "Misc" else "brain"
    note_id = f"{prefix}-{timestamp.strftime('%Y%m%d%H%M%S')}-{slug[:8]}"
    content_hash = compute_content_hash(content)

    # === WRITE 1: JSON-LD (Source of Truth) ===
    jsonld_path = None
    with TracingSpan("write_jsonld"):
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
            # Store original suggested category if routed to Misc
            if category == "Misc" and classification.get("category") != "Misc":
                jsonld_doc["ihim:suggestedCategory"] = classification.get("category")

            jsonld_path = write_jsonld(jsonld_doc, category, slug, date_str)
            logger.info(f"Written to JSON-LD: {jsonld_path}")
        except Exception as e:
            logger.error(f"Failed to write JSON-LD: {e}")

    # === WRITE 2: SQLite Database (Query Index) ===
    with TracingSpan("write_sqlite"):
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
                "jsonld_path": str(jsonld_path) if jsonld_path else None,
                "first_seen_at": timestamp.isoformat()
            })
            logger.info(f"Written to SQLite: {note_id}")
        except Exception as e:
            logger.error(f"Failed to write to SQLite: {e}")

    # === WRITE 3: Obsidian Memory (Human View) ===
    obsidian_path = None
    with TracingSpan("write_obsidian"):
        try:
            target_dir = OBSIDIAN_MEMORY / category
            target_dir.mkdir(parents=True, exist_ok=True)

            display_title = sanitize_title(title)
            filename = f"{display_title}.md"
            obsidian_path = target_dir / filename

            # Handle collisions
            counter = 1
            while obsidian_path.exists():
                filename = f"{display_title} {counter}.md"
                obsidian_path = target_dir / filename
                counter += 1

            obsidian_path.write_text(content, encoding="utf-8")
            logger.info(f"Written to Obsidian: {obsidian_path}")
        except Exception as e:
            logger.error(f"Failed to write to Obsidian: {e}")

    # === WRITE 4: Embedding (Derived Vector Index) ===
    with TracingSpan("generate_embedding"):
        try:
            embed_text = f"{title}\n{content}"
            with EmbeddingAdapter() as adapter:
                embedding = adapter.generate_embedding(embed_text)
            if embedding:
                store_embedding(note_id, embedding)
                logger.info(f"Stored embedding for: {note_id}")
            else:
                logger.warning(f"Embedding generation returned None for: {note_id}")
        except Exception as e:
            logger.warning(f"Embedding step failed (non-blocking): {e}")

    # Log metadata to Langfuse
    langfuse_context.update_current_observation(
        metadata={
            "note_id": note_id,
            "category": category,
            "confidence": confidence,
            "routed_to_misc": category == "Misc" and classification.get("category") != "Misc"
        }
    )

    return obsidian_path, note_id


@observe(name="update_existing")
def update_existing(
    existing: dict,
    content: str,
    content_hash: str
) -> tuple[Path, str]:
    """Update an existing brain entry (triple-update).

    Updates:
    1. JSON-LD (if path exists)
    2. SQLite (content and hash)
    3. Obsidian (regenerate file)

    No reclassification - just content update.

    Args:
        existing: Existing entry dict from database
        content: New content
        content_hash: Hash of new content

    Returns:
        Tuple of (Obsidian path, note_id)
    """
    entry_id = existing["id"]
    category = existing.get("category", "Ideas")
    title = existing.get("title", "untitled")
    jsonld_path = existing.get("jsonld_path")

    # === UPDATE 1: JSON-LD (Source of Truth) ===
    with TracingSpan("update_jsonld"):
        if jsonld_path and Path(jsonld_path).exists():
            try:
                update_jsonld_content(Path(jsonld_path), content)
                logger.info(f"Updated JSON-LD: {jsonld_path}")
            except Exception as e:
                logger.error(f"Failed to update JSON-LD: {e}")

    # === UPDATE 2: SQLite Database ===
    with TracingSpan("update_sqlite"):
        try:
            update_entry(entry_id, {
                "content": content,
                "content_hash": content_hash
            })
            logger.info(f"Updated database entry: {entry_id}")
        except Exception as e:
            logger.error(f"Failed to update SQLite: {e}")

    # === UPDATE 3: Obsidian Memory (Regenerate) ===
    obsidian_path = None
    with TracingSpan("update_obsidian"):
        try:
            obsidian_path = OBSIDIAN_MEMORY / category / f"{sanitize_title(title)}.md"
            obsidian_path.parent.mkdir(parents=True, exist_ok=True)
            obsidian_path.write_text(content, encoding="utf-8")
            logger.info(f"Updated Obsidian: {obsidian_path}")
        except Exception as e:
            logger.error(f"Failed to update Obsidian: {e}")

    # === UPDATE 4: Re-embed with new content ===
    with TracingSpan("update_embedding"):
        try:
            embed_text = f"{title}\n{content}"
            with EmbeddingAdapter() as adapter:
                embedding = adapter.generate_embedding(embed_text)
            if embedding:
                store_embedding(entry_id, embedding)
                logger.info(f"Updated embedding for: {entry_id}")
            else:
                logger.warning(f"Embedding update returned None for: {entry_id}")
        except Exception as e:
            logger.warning(f"Embedding update failed (non-blocking): {e}")

    langfuse_context.update_current_observation(
        metadata={
            "note_id": entry_id,
            "category": category,
            "action": "update"
        }
    )

    return obsidian_path, entry_id


@observe(name="update_with_reclassify")
def update_with_reclassify(
    existing: dict,
    content: str,
    content_hash: str,
    classification: dict
) -> tuple[Path, str]:
    """Update an existing brain entry WITH reclassification.

    Used for live files (still in inbox) when content changes.
    May move file to different category folder if classification changes.

    Args:
        existing: Existing entry dict from database
        content: New content
        content_hash: Hash of new content
        classification: New classification result

    Returns:
        Tuple of (Obsidian path, note_id)
    """
    entry_id = existing["id"]
    old_category = existing.get("category", "Ideas")
    old_title = existing.get("title", "untitled")
    jsonld_path = existing.get("jsonld_path")

    # New classification
    new_category = classification.get("category", "Ideas")
    new_title = classification.get("title", old_title)
    new_summary = classification.get("summary", "")
    new_confidence = float(classification.get("confidence", 0.0))

    # Apply confidence threshold
    if new_confidence < CONFIDENCE_THRESHOLD:
        new_category = "Misc"

    category_changed = new_category != old_category

    # === UPDATE 1: JSON-LD ===
    with TracingSpan("update_jsonld_reclassify"):
        if jsonld_path and Path(jsonld_path).exists():
            try:
                old_jsonld = Path(jsonld_path)
                if category_changed:
                    # Move JSON-LD to new category folder
                    from data.jsonld import JSONLD_ROOT
                    new_jsonld_dir = JSONLD_ROOT / new_category
                    new_jsonld_dir.mkdir(parents=True, exist_ok=True)
                    new_jsonld_path = new_jsonld_dir / old_jsonld.name
                    old_jsonld.rename(new_jsonld_path)
                    jsonld_path = str(new_jsonld_path)
                    update_jsonld_content(new_jsonld_path, content)
                else:
                    update_jsonld_content(old_jsonld, content)
                logger.info(f"Updated JSON-LD: {jsonld_path}")
            except Exception as e:
                logger.error(f"Failed to update JSON-LD: {e}")

    # === UPDATE 2: SQLite Database ===
    with TracingSpan("update_sqlite_reclassify"):
        try:
            update_entry(entry_id, {
                "content": content,
                "content_hash": content_hash,
                "category": new_category,
                "summary": new_summary,
                "confidence": new_confidence,
                "jsonld_path": jsonld_path
            })
            logger.info(f"Updated database entry with reclassification: {entry_id}")
        except Exception as e:
            logger.error(f"Failed to update SQLite: {e}")

    # === UPDATE 3: Obsidian Memory ===
    obsidian_path = None
    with TracingSpan("update_obsidian_reclassify"):
        try:
            # Remove old file if category changed
            if category_changed:
                old_obsidian = OBSIDIAN_MEMORY / old_category / f"{sanitize_title(old_title)}.md"
                if old_obsidian.exists():
                    old_obsidian.unlink()
                    logger.info(f"Removed old Obsidian file: {old_obsidian}")

            # Write to new location
            target_dir = OBSIDIAN_MEMORY / new_category
            target_dir.mkdir(parents=True, exist_ok=True)
            obsidian_path = target_dir / f"{sanitize_title(new_title)}.md"
            obsidian_path.write_text(content, encoding="utf-8")
            logger.info(f"Written to Obsidian: {obsidian_path}")
        except Exception as e:
            logger.error(f"Failed to update Obsidian: {e}")

    # === UPDATE 4: Re-embed with reclassified content ===
    with TracingSpan("reclassify_embedding"):
        try:
            embed_text = f"{new_title}\n{content}"
            with EmbeddingAdapter() as adapter:
                embedding = adapter.generate_embedding(embed_text)
            if embedding:
                store_embedding(entry_id, embedding)
                logger.info(f"Re-embedded after reclassify: {entry_id}")
            else:
                logger.warning(f"Reclassify embedding returned None for: {entry_id}")
        except Exception as e:
            logger.warning(f"Reclassify embedding failed (non-blocking): {e}")

    langfuse_context.update_current_observation(
        metadata={
            "note_id": entry_id,
            "old_category": old_category,
            "new_category": new_category,
            "category_changed": category_changed,
            "action": "reclassify"
        }
    )

    return obsidian_path, entry_id


def log_receipt(
    source_file: Optional[str],
    classification: dict,
    action: str,
    destination: Path
) -> None:
    """Log a receipt entry for auditing.

    Args:
        source_file: Source file path
        classification: Classification result
        action: What was done (classified, misc, updated)
        destination: Where file was written
    """
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOGS_DIR / "receipt.jsonl"

    timestamp = datetime.now(timezone.utc)
    receipt = {
        "id": f"receipt-{timestamp.strftime('%Y%m%d%H%M%S')}",
        "timestamp": timestamp.isoformat(),
        "source_file": source_file or "direct",
        "action": action,
        "category": classification.get("category"),
        "confidence": classification.get("confidence"),
        "destination": str(destination),
        "classifier": OllamaAdapter.FAST_MODEL
    }

    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(receipt) + "\n")
