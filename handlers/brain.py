"""Brain handler: classify and store notes in the Second Brain.

Thin orchestration layer. All logic delegated to:
- dedup.py: Find existing entries
- classify.py: LLM classification
- storage.py: Triple-write (JSON-LD → SQLite → Obsidian)

All steps traced via Langfuse for observability.
"""
import logging
import time
import json
from pathlib import Path
from datetime import datetime, timezone

from handlers.tracing import observe

from orchestrator.state import OrchestratorState
from handlers.utils import compute_content_hash
from handlers.dedup import find_existing, is_unchanged
from handlers.classify import classify_content
from handlers.storage import store_new, update_existing, log_receipt
from handlers.relations import invalidate_entity_index

logger = logging.getLogger(__name__)

_BRAIN_METRICS_PATH = Path(__file__).parent.parent / "data" / "brain_metrics.jsonl"
_BRAIN_METRICS_CAP = 500


def _persist_brain_metric(entry: dict):
    """Append a metric entry to brain_metrics.jsonl, capped at 500 lines."""
    try:
        _BRAIN_METRICS_PATH.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(entry, default=str) + "\n"

        # Read existing, cap, append
        lines = []
        if _BRAIN_METRICS_PATH.exists():
            lines = _BRAIN_METRICS_PATH.read_text(encoding="utf-8").splitlines()

        # Keep last (cap - 1) lines, then append new one
        if len(lines) >= _BRAIN_METRICS_CAP:
            lines = lines[-((_BRAIN_METRICS_CAP) - 1):]

        lines.append(line.rstrip("\n"))
        _BRAIN_METRICS_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except Exception as e:
        logger.debug(f"Brain metrics write failed (non-blocking): {e}")


@observe(name="brain_handler")
def handle(state: OrchestratorState) -> OrchestratorState:
    """Classify and store the note.

    Flow:
    1. Check for existing entry (dedup)
    2. If unchanged → skip
    3. If changed → update existing
    4. If new → classify and store

    All stages are timed and metrics persisted to brain_metrics.jsonl.

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
    timing = {}
    t_total = time.time()
    metric_action = None
    metric_category = None
    metric_confidence = None
    metric_error = None

    try:
        # Step 1: Dedup check
        t0 = time.time()
        existing = find_existing(source_file, content)
        dedup_unchanged = False

        if existing:
            dedup_unchanged = is_unchanged(existing, content_hash)
        timing["dedup"] = round((time.time() - t0) * 1000)

        if existing and dedup_unchanged:
            state["result"] = {"action": "skipped", "reason": "unchanged"}
            metric_action = "skipped"
            timing["total"] = round((time.time() - t_total) * 1000)
            state["result"]["timing_ms"] = timing
            _persist_brain_metric({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "source_file": source_filename,
                "action": metric_action,
                "category": None,
                "confidence": None,
                "timing_ms": timing,
                "error": None,
            })
            return state

        if existing:
            # Step 3: Content changed - check if file is still live (in inbox)
            source_path = Path(source_file) if source_file else None
            is_live = source_path and source_path.exists() and "processed" not in str(source_path)

            if is_live:
                # Reclassify live files when content changes
                t0 = time.time()
                classification = classify_content(content, source_filename)
                timing["classify"] = round((time.time() - t0) * 1000)

                new_category = classification.get("category")
                old_category = existing.get("category")

                from handlers.storage import update_with_reclassify

                t0 = time.time()
                obsidian_path, note_id = update_with_reclassify(
                    existing, content, content_hash, classification
                )
                timing["store"] = round((time.time() - t0) * 1000)

                action = "updated_reclassified" if new_category != old_category else "updated"
                log_receipt(source_file, classification, action, obsidian_path)
                metric_action = action
                metric_category = new_category
                metric_confidence = classification.get("confidence")

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
                t0 = time.time()
                obsidian_path, note_id = update_existing(existing, content, content_hash)
                timing["store"] = round((time.time() - t0) * 1000)

                log_receipt(source_file, {
                    "category": existing.get("category"),
                    "title": existing.get("title"),
                    "confidence": existing.get("confidence", 0.0)
                }, "updated", obsidian_path)
                metric_action = "updated"
                metric_category = existing.get("category")
                metric_confidence = existing.get("confidence")

                state["result"] = {
                    "action": "updated",
                    "category": existing.get("category"),
                    "title": existing.get("title"),
                    "destination": str(obsidian_path),
                    "processed_id": note_id
                }

            timing["total"] = round((time.time() - t_total) * 1000)
            state["result"]["timing_ms"] = timing
            _persist_brain_metric({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "source_file": source_filename,
                "action": metric_action,
                "category": metric_category,
                "confidence": metric_confidence,
                "timing_ms": timing,
                "error": None,
            })
            return state

        # Step 4: Classify and store new entry
        t0 = time.time()
        classification = classify_content(content, source_filename)
        timing["classify"] = round((time.time() - t0) * 1000)

        t0 = time.time()
        obsidian_path, note_id = store_new(
            content, classification, source_file, source_filename
        )
        timing["store"] = round((time.time() - t0) * 1000)

        # Invalidate entity index after new entry stored
        invalidate_entity_index()

        action = "misc" if classification.get("confidence", 0) < 0.7 else "classified"
        log_receipt(source_file, classification, action, obsidian_path)
        metric_action = action
        metric_category = classification.get("category")
        metric_confidence = classification.get("confidence")

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
        metric_action = "error"
        metric_error = str(e)

    timing["total"] = round((time.time() - t_total) * 1000)
    if "result" in state:
        state["result"]["timing_ms"] = timing

    _persist_brain_metric({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source_file": source_filename,
        "action": metric_action,
        "category": metric_category,
        "confidence": metric_confidence,
        "timing_ms": timing,
        "error": metric_error,
    })

    return state
