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

TRAINING_DIR = DATA_DIR / "voice-training"
MANIFEST_FILE = TRAINING_DIR / "manifest.jsonl"
METADATA_FILE = TRAINING_DIR / "metadata.json"


def _ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def log_dictation(
    raw_transcript: str,
    cleaned_text: str,
    latency_ms: int,
    whisper_model: str = "small",
    cleanup_model: str = "llama3.2:3b",
    dictation_id: Optional[str] = None,
    audio_path: Optional[str] = None,
    duration_s: float = 0.0,
) -> dict:
    """Append a dictation record to the JSONL log.

    Returns the logged record dict (includes generated id).
    If audio_path is provided, also appends a manifest entry for
    voice model training.
    """
    _ensure_data_dir()

    record = {
        "id": dictation_id or uuid.uuid4().hex[:8],
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "raw_transcript": raw_transcript,
        "cleaned_text": cleaned_text,
        "whisper_model": whisper_model,
        "cleanup_model": cleanup_model,
        "latency_ms": latency_ms,
        "audio_path": audio_path,
        "correction": None,
        "flagged": False,
    }

    with DICTATIONS_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")

    # Append manifest entry if audio was retained
    if audio_path:
        _append_manifest(record, duration_s)

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

        # Propagate correction to voice training manifest
        _update_manifest_correction(dictation_id, corrected_text)

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


def _append_manifest(record: dict, duration_s: float) -> None:
    """Append a training manifest entry linking audio to transcript."""
    TRAINING_DIR.mkdir(parents=True, exist_ok=True)

    audio_path = record.get("audio_path", "")
    # Store relative path from training dir (segments/xxx.flac)
    try:
        rel_path = str(Path(audio_path).relative_to(TRAINING_DIR))
    except (ValueError, TypeError):
        rel_path = audio_path

    entry = {
        "id": record["id"],
        "audio_path": rel_path,
        "raw_transcript": record.get("raw_transcript", ""),
        "corrected_text": None,
        "timestamp": record.get("timestamp"),
        "duration_s": round(duration_s, 2),
        "whisper_model": record.get("whisper_model"),
    }

    try:
        with MANIFEST_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
        _update_metadata(duration_s)
        logger.debug("Manifest entry added: %s", entry["id"])
    except Exception as exc:
        logger.debug("Failed to write manifest entry: %s", exc)


def _update_metadata(duration_s: float) -> None:
    """Update voice-training metadata.json with running stats."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    meta = {"total_segments": 0, "total_duration_s": 0.0,
            "date_range": [today, today], "format": "flac"}
    if METADATA_FILE.exists():
        try:
            meta = json.loads(METADATA_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass

    meta["total_segments"] = meta.get("total_segments", 0) + 1
    meta["total_duration_s"] = round(
        meta.get("total_duration_s", 0.0) + duration_s, 2
    )
    date_range = meta.get("date_range", [today, today])
    if not date_range:
        date_range = [today, today]
    date_range[1] = today
    meta["date_range"] = date_range

    try:
        METADATA_FILE.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    except Exception as exc:
        logger.debug("Failed to update metadata: %s", exc)


def _update_manifest_correction(dictation_id: str, corrected_text: str) -> None:
    """Update a manifest entry's corrected_text field."""
    if not MANIFEST_FILE.exists():
        return

    lines = MANIFEST_FILE.read_text(encoding="utf-8").splitlines()
    new_lines = []
    updated = False

    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
            if entry.get("id") == dictation_id:
                entry["corrected_text"] = corrected_text
                updated = True
            new_lines.append(json.dumps(entry))
        except json.JSONDecodeError:
            new_lines.append(line)

    if updated:
        MANIFEST_FILE.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        logger.debug("Manifest correction updated: %s", dictation_id)


