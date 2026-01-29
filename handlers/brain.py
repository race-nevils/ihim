"""Brain handler: classify and store notes in the Second Brain.

Thin orchestration layer (~50 lines). All logic delegated to:
- dedup.py: Find existing entries
- classify.py: LLM classification
- storage.py: Triple-write (JSON-LD → SQLite → Obsidian)

All steps traced via Langfuse for observability.
"""
import logging
from pathlib import Path

from handlers.tracing import observe

from orchestrator.state import OrchestratorState
from handlers.utils import compute_content_hash
from handlers.dedup import find_existing, is_unchanged
from handlers.classify import classify_content
from handlers.storage import store_new, update_existing, log_receipt

logger = logging.getLogger(__name__)


@observe(name="brain_handler")
def handle(state: OrchestratorState) -> OrchestratorState:
    """Handle brain intent: classify and store the note.

    Flow:
    1. Check for existing entry (dedup)
    2. If unchanged → skip
    3. If changed → update existing
    4. If new → classify and store

    Args:
        state: Current orchestrator state

    Returns:
        Updated state with processing result
    """
    content = state.get("input_text", "")
    source_file = state.get("source_file")

    # Empty content check
    if not content.strip():
        state["error"] = "Empty content, nothing to classify"
        state["result"] = {"action": "skipped", "reason": "empty_content"}
        return state

    source_filename = Path(source_file).name if source_file else None
    content_hash = compute_content_hash(content)

    try:
        # Step 1: Check for existing entry
        existing = find_existing(source_file, content)

        if existing:
            # Step 2: Check if unchanged
            if is_unchanged(existing, content_hash):
                state["result"] = {"action": "skipped", "reason": "unchanged"}
                return state

            # Step 3: Content changed - check if file is still live (in inbox)
            # Live files get reclassified, archived files just update content
            source_path = Path(source_file) if source_file else None
            is_live = source_path and source_path.exists() and "processed" not in str(source_path)

            if is_live:
                # Reclassify live files when content changes
                classification = classify_content(content, source_filename)
                new_category = classification.get("category")
                old_category = existing.get("category")

                from handlers.storage import update_with_reclassify
                obsidian_path, note_id = update_with_reclassify(
                    existing, content, content_hash, classification
                )

                action = "updated_reclassified" if new_category != old_category else "updated"
                log_receipt(source_file, classification, action, obsidian_path)

                state["result"] = {
                    "action": action,
                    "category": new_category,
                    "old_category": old_category if new_category != old_category else None,
                    "confidence": classification.get("confidence"),
                    "title": classification.get("title"),
                    "destination": str(obsidian_path),
                    "processed_id": note_id
                }
            else:
                # Archived/stale files just update content, keep category
                obsidian_path, note_id = update_existing(existing, content, content_hash)

                log_receipt(source_file, {
                    "category": existing.get("category"),
                    "title": existing.get("title"),
                    "confidence": existing.get("confidence", 0.0)
                }, "updated", obsidian_path)

                state["result"] = {
                    "action": "updated",
                    "category": existing.get("category"),
                    "title": existing.get("title"),
                    "destination": str(obsidian_path),
                    "processed_id": note_id
                }
            return state

        # Step 4: Classify and store new entry
        classification = classify_content(content, source_filename)
        obsidian_path, note_id = store_new(
            content, classification, source_file, source_filename
        )

        action = "misc" if classification.get("confidence", 0) < 0.7 else "classified"
        log_receipt(source_file, classification, action, obsidian_path)

        state["result"] = {
            "action": action,
            "category": classification.get("category"),
            "confidence": classification.get("confidence"),
            "title": classification.get("title"),
            "summary": classification.get("summary"),
            "destination": str(obsidian_path),
            "processed_id": note_id
        }

    except Exception as e:
        logger.error(f"Brain handler error: {e}", exc_info=True)
        state["error"] = f"Brain handler error: {str(e)}"
        state["result"] = {"action": "error", "error": str(e)}

    return state
