"""JSONL dictation logger — append-only log with correction support."""

import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent / "data"
DICTATIONS_FILE = DATA_DIR / "dictations.jsonl"
CORRECTIONS_FILE = DATA_DIR / "corrections.jsonl"

# Vocab reload interval — check for new terms every N dictations.
_VOCAB_RELOAD_INTERVAL = 10
_dictation_count = 0


def _ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def log_dictation(
    raw_transcript: str,
    cleaned_text: str,
    latency_ms: int,
    whisper_model: str = "small",
    cleanup_model: str = "llama3.2:3b",
) -> dict:
    """Append a dictation record to the JSONL log.

    Returns the logged record dict (includes generated id).
    """
    _ensure_data_dir()

    record = {
        "id": uuid.uuid4().hex[:8],
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "raw_transcript": raw_transcript,
        "cleaned_text": cleaned_text,
        "whisper_model": whisper_model,
        "cleanup_model": cleanup_model,
        "latency_ms": latency_ms,
        "correction": None,
        "flagged": False,
    }

    with DICTATIONS_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")

    logger.info("Dictation logged: %s (%dms)", record["id"], latency_ms)
    return record


def get_history(limit: int = 50, offset: int = 0) -> list[dict]:
    """Read dictation history, newest first, with pagination."""
    if not DICTATIONS_FILE.exists():
        return []

    records = []
    for line in DICTATIONS_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    # Newest first
    records.reverse()
    return records[offset:offset + limit]


def get_dictation(dictation_id: str) -> Optional[dict]:
    """Get a single dictation record by ID."""
    if not DICTATIONS_FILE.exists():
        return None

    for line in DICTATIONS_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
            if record.get("id") == dictation_id:
                return record
        except json.JSONDecodeError:
            continue

    return None


def mark_correction(dictation_id: str, corrected_text: str) -> Optional[dict]:
    """Update a dictation record with a correction.

    Rewrites the JSONL file with the correction applied.
    Returns the updated record, or None if not found.
    """
    if not DICTATIONS_FILE.exists():
        return None

    lines = DICTATIONS_FILE.read_text(encoding="utf-8").splitlines()
    updated_record = None
    new_lines = []

    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
            if record.get("id") == dictation_id:
                record["correction"] = {
                    "text": corrected_text,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "sha256": hashlib.sha256(corrected_text.encode("utf-8")).hexdigest(),
                }
                updated_record = record
            new_lines.append(json.dumps(record))
        except json.JSONDecodeError:
            new_lines.append(line)

    if updated_record:
        DICTATIONS_FILE.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        logger.info("Correction applied to dictation %s", dictation_id)

        # Auto-learn vocabulary from correction
        _learn_vocab_from_correction(updated_record)

    return updated_record


def toggle_flag(dictation_id: str) -> Optional[dict]:
    """Toggle the flagged status of a dictation record."""
    if not DICTATIONS_FILE.exists():
        return None

    lines = DICTATIONS_FILE.read_text(encoding="utf-8").splitlines()
    updated_record = None
    new_lines = []

    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
            if record.get("id") == dictation_id:
                record["flagged"] = not record.get("flagged", False)
                updated_record = record
            new_lines.append(json.dumps(record))
        except json.JSONDecodeError:
            new_lines.append(line)

    if updated_record:
        DICTATIONS_FILE.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

    return updated_record


def get_stats() -> dict:
    """Compute dictation stats."""
    if not DICTATIONS_FILE.exists():
        return {"total": 0, "corrections": 0, "flagged": 0}

    total = 0
    corrections = 0
    flagged = 0
    total_latency = 0

    for line in DICTATIONS_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
            total += 1
            if record.get("correction"):
                corrections += 1
            if record.get("flagged"):
                flagged += 1
            total_latency += record.get("latency_ms", 0)
        except json.JSONDecodeError:
            continue

    return {
        "total": total,
        "corrections": corrections,
        "flagged": flagged,
        "avg_latency_ms": round(total_latency / total) if total else 0,
    }


def _learn_vocab_from_correction(record: dict) -> None:
    """Detect word substitution patterns and auto-add to vocab.txt.

    Compares cleaned_text to correction text. If a single word was
    substituted (e.g., "Cloud" -> "the agent"), add the correct word to vocab.
    Also saves the raw → corrected pair to corrections.jsonl for future
    fine-tuning (Phase 4 prep).
    """
    from tools.stt.transcribe import VOCAB_FILE

    correction = record.get("correction", {})
    if not correction:
        return

    original_words = record.get("cleaned_text", "").split()
    corrected_words = correction.get("text", "").split()

    # Save correction pair for future fine-tuning (regardless of word count match)
    _save_correction_pair(record)

    if len(original_words) != len(corrected_words):
        return  # Not a simple word substitution

    new_terms = []
    for orig, corr in zip(original_words, corrected_words):
        if orig.lower() != corr.lower():
            new_terms.append(corr)

    if not new_terms:
        return

    # Read existing vocab
    existing = set()
    if VOCAB_FILE.exists():
        for line in VOCAB_FILE.read_text(encoding="utf-8").splitlines():
            t = line.strip()
            if t:
                existing.add(t.lower())

    # Append new terms (append-only per recursive principle)
    added = []
    for term in new_terms:
        if term.lower() not in existing:
            with VOCAB_FILE.open("a", encoding="utf-8") as f:
                f.write(term + "\n")
            existing.add(term.lower())
            added.append(term)

    if added:
        logger.info("Auto-learned vocab from correction: %s", added)


def _save_correction_pair(record: dict) -> None:
    """Save raw → corrected pair to corrections.jsonl for future fine-tuning."""
    _ensure_data_dir()

    correction = record.get("correction", {})
    if not correction:
        return

    pair = {
        "id": record.get("id"),
        "timestamp": correction.get("timestamp"),
        "raw_transcript": record.get("raw_transcript", ""),
        "cleaned_text": record.get("cleaned_text", ""),
        "corrected_text": correction.get("text", ""),
    }

    try:
        with CORRECTIONS_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(pair) + "\n")
        logger.debug("Correction pair saved for fine-tuning: %s", pair["id"])
    except Exception as exc:
        logger.debug("Failed to save correction pair: %s", exc)


def trigger_vocab_reload() -> None:
    """Signal that vocab.txt should be reloaded on the next transcription.

    Called periodically (every N dictations) to pick up new terms added
    by auto-learning without requiring an app restart.
    """
    global _dictation_count
    _dictation_count += 1
    if _dictation_count >= _VOCAB_RELOAD_INTERVAL:
        _dictation_count = 0
        try:
            from tools.stt.transcribe import load_vocab
            load_vocab.cache_clear()  # noqa: no-op if not cached, that's fine
        except (AttributeError, ImportError):
            pass  # load_vocab doesn't use cache yet — this is forward-compatible
