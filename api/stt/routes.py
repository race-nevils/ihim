"""FastAPI router for the STT dictation system.

Endpoints: history, correct, vocab, stats, start, status.
"""

import asyncio
import logging
from pathlib import Path

from fastapi import APIRouter, Request
from api.errors import problem

from api.stt.models import (
    DictationRecord, HistoryResponse, StatsResponse,
    VocabResponse, StatusResponse, CorrectionRequest,
    VocabUpdateRequest, SuccessResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/stt", tags=["stt"])


# ═══════════════════════════════════════════════════════════════════════
# ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════

@router.get("/history", response_model=HistoryResponse)
async def stt_history(limit: int = 50, offset: int = 0):
    """List dictations (paginated, newest first)."""
    from tools.stt.logger import get_history, get_stats

    loop = asyncio.get_event_loop()
    records = await loop.run_in_executor(None, lambda: get_history(limit, offset))
    stats = await loop.run_in_executor(None, get_stats)

    return HistoryResponse(
        dictations=[DictationRecord(**r) for r in records],
        total=stats["total"],
    )


@router.get("/history/{dictation_id}", response_model=DictationRecord)
async def stt_history_detail(dictation_id: str, request: Request):
    """Single dictation detail."""
    from tools.stt.logger import get_dictation

    loop = asyncio.get_event_loop()
    record = await loop.run_in_executor(None, lambda: get_dictation(dictation_id))

    if record is None:
        return problem(404, f"Dictation '{dictation_id}' not found", instance=request.url.path)

    return DictationRecord(**record)


@router.post("/correct/{dictation_id}", response_model=DictationRecord)
async def stt_correct(dictation_id: str, body: CorrectionRequest, request: Request):
    """Submit correction for a dictation."""
    from tools.stt.logger import mark_correction

    loop = asyncio.get_event_loop()
    record = await loop.run_in_executor(
        None, lambda: mark_correction(dictation_id, body.corrected_text)
    )

    if record is None:
        return problem(404, f"Dictation '{dictation_id}' not found", instance=request.url.path)

    return DictationRecord(**record)


@router.post("/flag/{dictation_id}", response_model=DictationRecord)
async def stt_flag(dictation_id: str, request: Request):
    """Toggle flag on a dictation."""
    from tools.stt.logger import toggle_flag

    loop = asyncio.get_event_loop()
    record = await loop.run_in_executor(None, lambda: toggle_flag(dictation_id))

    if record is None:
        return problem(404, f"Dictation '{dictation_id}' not found", instance=request.url.path)

    return DictationRecord(**record)


@router.get("/vocab", response_model=VocabResponse)
async def stt_vocab():
    """List vocabulary priming terms."""
    from tools.stt.transcribe import VOCAB_FILE

    terms = []
    if VOCAB_FILE.exists():
        for line in VOCAB_FILE.read_text(encoding="utf-8").splitlines():
            t = line.strip()
            if t:
                terms.append(t)

    return VocabResponse(terms=terms)


@router.put("/vocab", response_model=VocabResponse)
async def stt_vocab_update(body: VocabUpdateRequest, request: Request):
    """Add/remove vocabulary terms (append-only: removals are logged)."""
    from tools.stt.transcribe import VOCAB_FILE, DATA_DIR

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Read current terms
    existing = []
    if VOCAB_FILE.exists():
        existing = [
            line.strip()
            for line in VOCAB_FILE.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    existing_lower = {t.lower() for t in existing}

    # Add new terms
    for term in body.add:
        term = term.strip()
        if term and term.lower() not in existing_lower:
            existing.append(term)
            existing_lower.add(term.lower())

    # Remove terms
    if body.remove:
        remove_lower = {t.lower().strip() for t in body.remove}
        existing = [t for t in existing if t.lower() not in remove_lower]

    # Write back
    VOCAB_FILE.write_text("\n".join(existing) + "\n", encoding="utf-8")

    return VocabResponse(terms=existing)


@router.get("/stats", response_model=StatsResponse)
async def stt_stats():
    """Dictation statistics."""
    from tools.stt.logger import get_stats

    loop = asyncio.get_event_loop()
    stats = await loop.run_in_executor(None, get_stats)

    return StatsResponse(**stats)


@router.post("/start", response_model=SuccessResponse)
async def stt_start(request: Request):
    """Start the hotkey listener (if not running)."""
    try:
        from tools.stt.engine import get_engine
        engine = get_engine()
        engine.start_listening()
        return SuccessResponse(success=True, message="Hotkey listener started")
    except Exception as e:
        logger.error("Failed to start STT engine: %s", e)
        return problem(503, f"Failed to start STT: {e}", instance=request.url.path)


@router.post("/stop", response_model=SuccessResponse)
async def stt_stop(request: Request):
    """Stop the hotkey listener."""
    try:
        from tools.stt.engine import get_engine
        engine = get_engine()
        engine.stop_listening()
        return SuccessResponse(success=True, message="Hotkey listener stopped")
    except Exception as e:
        logger.error("Failed to stop STT engine: %s", e)
        return problem(503, f"Failed to stop STT: {e}", instance=request.url.path)


@router.get("/status", response_model=StatusResponse)
async def stt_status():
    """Listener status (active, model loaded, etc.)."""
    from tools.stt.engine import get_engine
    from api.recorder.transcribe import _model_cache

    engine = get_engine()
    return StatusResponse(
        active=engine._listener is not None and engine._listener.is_running,
        status=engine.status,
        model_loaded="small" in _model_cache,
    )
