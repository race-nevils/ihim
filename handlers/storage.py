"""Triple-write storage for brain handler.

Architecture: JSON-LD (source) → SQLite (index) → Obsidian (view)

Single responsibility: write brain entries to all three layers.
All storage operations are traced via Langfuse.

Write ordering guarantees:
- JSON-LD fails → StorageError (nothing persisted)
- SQLite fails after JSON-LD → PartialWriteError (SSOT safe, invisible to queries)
- Obsidian/Embedding fail → warning only (derived, rebuildable)
"""
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from handlers.tracing import observe, langfuse_context, TracingSpan
from handlers.models import (
    BrainEntry,
    ClassificationResult,
    CalendarEvent,
    StorageError,
    PartialWriteError,
)

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
OBSIDIAN_MEMORY = WORKSPACE_ROOT / "iHIM Vault" / "iHIM Memory"
LOGS_DIR = IHIM_ROOT / "data" / "local" / "brain" / "logs"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_calendar_fields(calendar: Optional[CalendarEvent]) -> Optional[dict]:
    """Convert CalendarEvent model to SQLite update dict."""
    if calendar is None or not calendar.is_event:
        return None
    fields = {
        "event_date": calendar.date,
        "event_start_time": calendar.time,
        "event_end_time": calendar.end_time,
        "event_all_day": 1 if calendar.all_day else 0,
    }
    if calendar.rrule:
        fields["event_rrule"] = calendar.rrule
    return fields


def _build_frontmatter(brain_id: str, jsonld_path: str, category: str,
                       created_at: str, content_hash: str) -> str:
    """YAML frontmatter for Obsidian files. Links back to source of truth."""
    return (
        f"---\n"
        f"brain_id: {brain_id}\n"
        f"jsonld_path: {jsonld_path}\n"
        f"category: {category}\n"
        f"created_at: {created_at}\n"
        f"content_hash: {content_hash}\n"
        f"---\n"
    )


# ---------------------------------------------------------------------------
# store_new — Create a new brain entry (triple-write)
# ---------------------------------------------------------------------------

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

    Raises:
        ValidationError: If content or classification fields are invalid
        StorageError: If JSON-LD write fails (nothing persisted)
        PartialWriteError: If SQLite fails after JSON-LD success
    """
    # === VALIDATE INPUTS ===
    entry = BrainEntry(
        content=content,
        source_file=source_file,
        source_filename=source_filename,
    )
    cls = ClassificationResult(**classification)

    # Route category — model already coerced invalid → Misc
    original_category = cls.category
    category = cls.category
    reroute_reason = None

    if cls.category == "Misc" and classification.get("category") not in (None, "Misc"):
        reroute_reason = "invalid_category"

    if cls.confidence < CONFIDENCE_THRESHOLD:
        category = "Misc"
        if reroute_reason is None:
            reroute_reason = "low_confidence"

    title = cls.title
    summary = cls.summary
    confidence = cls.confidence

    # Generate identifiers
    timestamp = datetime.now(timezone.utc)
    date_str = timestamp.strftime("%Y%m%d")
    slug = slugify(title)
    prefix = "misc" if category == "Misc" else "brain"
    note_id = f"{prefix}-{timestamp.strftime('%Y%m%d%H%M%S')}-{slug[:8]}"
    content_hash = compute_content_hash(content)

    # === WRITE 1: JSON-LD (Source of Truth) ===
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
            if category == "Misc" and original_category != "Misc":
                jsonld_doc["ihim:suggestedCategory"] = original_category

            jsonld_path = write_jsonld(jsonld_doc, category, slug, date_str)
            logger.info(f"Written to JSON-LD: {jsonld_path}")
        except Exception as e:
            raise StorageError(f"JSON-LD write failed for '{title}': {e}") from e

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
                "jsonld_path": str(jsonld_path),
                "first_seen_at": timestamp.isoformat()
            })
            logger.info(f"Written to SQLite: {note_id}")
        except Exception as e:
            raise PartialWriteError(
                f"SQLite write failed for '{title}' (JSON-LD safe at {jsonld_path}): {e}",
                jsonld_path=str(jsonld_path),
            ) from e

    # === WRITE 3: Obsidian Memory (Human View) — non-fatal ===
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

            fm = _build_frontmatter(note_id, str(jsonld_path), category,
                                    timestamp.isoformat(), content_hash)
            obsidian_path.write_text(fm + content, encoding="utf-8")
            logger.info(f"Written to Obsidian: {obsidian_path}")
        except Exception as e:
            logger.warning(f"Obsidian write failed (non-blocking, rebuild regenerates): {e}")

    # === WRITE 4: Embedding (Derived Vector Index) — non-fatal ===
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

    # === WRITE 5: Calendar event fields in SQLite — non-fatal ===
    cal_fields = _extract_calendar_fields(cls.calendar)
    if cal_fields:
        try:
            update_entry(note_id, cal_fields)
            logger.info(f"Stored calendar fields for: {note_id}")
        except Exception as e:
            logger.error(f"Failed to store calendar fields for {note_id} (non-blocking): {e}")

    # Log metadata to Langfuse (enriched with rerouting details)
    langfuse_context.update_current_observation(
        metadata={
            "note_id": note_id,
            "category": category,
            "original_category": original_category,
            "confidence": confidence,
            "confidence_threshold": CONFIDENCE_THRESHOLD,
            "rerouted": category != original_category,
            "reroute_reason": reroute_reason,
        }
    )

    return obsidian_path, note_id


# ---------------------------------------------------------------------------
# update_existing — Update content only (no reclassification)
# ---------------------------------------------------------------------------

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

    Raises:
        StorageError: If JSON-LD update fails
        PartialWriteError: If SQLite fails after JSON-LD success
    """
    if not content or not content.strip():
        raise StorageError("Cannot update entry with empty content")

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
                raise StorageError(
                    f"JSON-LD update failed for '{entry_id}': {e}"
                ) from e

    # === UPDATE 2: SQLite Database ===
    with TracingSpan("update_sqlite"):
        try:
            update_entry(entry_id, {
                "content": content,
                "content_hash": content_hash
            })
            logger.info(f"Updated database entry: {entry_id}")
        except Exception as e:
            raise PartialWriteError(
                f"SQLite update failed for '{entry_id}' (JSON-LD safe at {jsonld_path}): {e}",
                jsonld_path=str(jsonld_path) if jsonld_path else "unknown",
            ) from e

    # === UPDATE 3: Obsidian Memory (Regenerate) — non-fatal ===
    obsidian_path = None
    with TracingSpan("update_obsidian"):
        try:
            obsidian_path = OBSIDIAN_MEMORY / category / f"{sanitize_title(title)}.md"
            obsidian_path.parent.mkdir(parents=True, exist_ok=True)
            fm = _build_frontmatter(entry_id, str(jsonld_path) if jsonld_path else "",
                                    category, existing.get("created_at", ""), content_hash)
            obsidian_path.write_text(fm + content, encoding="utf-8")
            logger.info(f"Updated Obsidian: {obsidian_path}")
        except Exception as e:
            logger.warning(f"Obsidian update failed (non-blocking): {e}")

    # === UPDATE 4: Re-embed with new content — non-fatal ===
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


# ---------------------------------------------------------------------------
# update_with_reclassify — Update content AND reclassify
# ---------------------------------------------------------------------------

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

    Raises:
        ValidationError: If classification fields are invalid
        StorageError: If JSON-LD update fails
        PartialWriteError: If SQLite fails after JSON-LD success
    """
    # === VALIDATE ===
    cls = ClassificationResult(**classification)

    entry_id = existing["id"]
    old_category = existing.get("category", "Ideas")
    old_title = existing.get("title", "untitled")
    jsonld_path = existing.get("jsonld_path")

    # Route category
    original_category = cls.category
    new_category = cls.category
    reroute_reason = None

    if cls.category == "Misc" and classification.get("category") not in (None, "Misc"):
        reroute_reason = "invalid_category"

    if cls.confidence < CONFIDENCE_THRESHOLD:
        new_category = "Misc"
        if reroute_reason is None:
            reroute_reason = "low_confidence"

    new_title = cls.title
    new_summary = cls.summary
    new_confidence = cls.confidence

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
                raise StorageError(
                    f"JSON-LD update failed for '{entry_id}': {e}"
                ) from e

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
            raise PartialWriteError(
                f"SQLite update failed for '{entry_id}' (JSON-LD safe at {jsonld_path}): {e}",
                jsonld_path=str(jsonld_path) if jsonld_path else "unknown",
            ) from e

    # === UPDATE 2b: Calendar event fields — non-fatal ===
    cal_fields = _extract_calendar_fields(cls.calendar)
    if cal_fields:
        try:
            update_entry(entry_id, cal_fields)
            logger.info(f"Updated calendar fields for: {entry_id}")
        except Exception as e:
            logger.error(f"Failed to update calendar fields for {entry_id} (non-blocking): {e}")

    # === UPDATE 3: Obsidian Memory — non-fatal ===
    obsidian_path = None
    with TracingSpan("update_obsidian_reclassify"):
        try:
            # Remove old file if category changed
            if category_changed:
                old_dir = OBSIDIAN_MEMORY / old_category
                old_obsidian = old_dir / f"{sanitize_title(old_title)}.md"
                if old_obsidian.exists():
                    old_obsidian.unlink()
                    logger.info(f"Removed old Obsidian file: {old_obsidian}")
                elif old_dir.exists():
                    # Fallback: glob for fuzzy match (catches collision suffixes, unicode mismatches)
                    for f in old_dir.glob("*.md"):
                        if old_title.lower() in f.stem.lower():
                            f.unlink()
                            logger.info(f"Removed old Obsidian file (fuzzy match): {f}")
                            break

            # Write to new location
            target_dir = OBSIDIAN_MEMORY / new_category
            target_dir.mkdir(parents=True, exist_ok=True)
            obsidian_path = target_dir / f"{sanitize_title(new_title)}.md"
            fm = _build_frontmatter(entry_id, str(jsonld_path) if jsonld_path else "",
                                    new_category, existing.get("created_at", ""), content_hash)
            obsidian_path.write_text(fm + content, encoding="utf-8")
            logger.info(f"Written to Obsidian: {obsidian_path}")
        except Exception as e:
            logger.warning(f"Obsidian update failed (non-blocking): {e}")

    # === UPDATE 4: Re-embed with reclassified content — non-fatal ===
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
            "original_category": original_category,
            "category_changed": category_changed,
            "confidence": new_confidence,
            "confidence_threshold": CONFIDENCE_THRESHOLD,
            "rerouted": new_category != original_category,
            "reroute_reason": reroute_reason,
            "action": "reclassify"
        }
    )

    return obsidian_path, entry_id


# ---------------------------------------------------------------------------
# log_receipt — Audit trail
# ---------------------------------------------------------------------------

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
