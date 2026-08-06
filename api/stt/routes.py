"""FastAPI router for the STT dictation system.

Endpoints: history, correct, stats, start, status, status/stream (SSE).
"""

import asyncio
import json
import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from api.errors import problem

from api.stt.models import (
    DictationRecord, HistoryResponse, StatsResponse,
    StatusResponse, CorrectionRequest, MuteUpdateRequest,
    SuccessResponse, VocabResponse, VocabUpdateRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/stt", tags=["stt"])


# ═══════════════════════════════════════════════════════════════════════
# SSE STATUS BROADCAST
# ═══════════════════════════════════════════════════════════════════════

_sse_queues: set[asyncio.Queue] = set()
_sse_loop: Optional[asyncio.AbstractEventLoop] = None
_sse_callback_installed = False
_SSE_HEARTBEAT_S = 30.0
_SSE_MAX_QUEUES = 50


def _build_status_payload(status: str) -> str:
    """Build JSON payload matching StatusResponse shape."""
    from tools.stt.engine import get_engine
    from api.recorder.transcribe import _model_cache
    engine = get_engine()
    last_id = engine.last_result["id"] if engine.last_result else None
    return json.dumps({
        "status": status,
        "active": engine._listener is not None and engine._listener.is_running,
        "model_loaded": bool(_model_cache),
        "last_result_id": last_id,
        "mute_on_dictate": engine.mute_on_dictate,
    })


def _broadcast_status(status: str) -> None:
    """Push status to all SSE clients. Called from engine threads."""
    loop = _sse_loop
    if loop is None or not _sse_queues:
        return
    payload = _build_status_payload(status)
    for q in list(_sse_queues):
        try:
            loop.call_soon_threadsafe(q.put_nowait, payload)
        except Exception:
            pass


def _install_sse_callback() -> None:
    """Wire engine state changes to SSE broadcast (idempotent).

    Always refreshes _sse_loop — after sleep/wake the event loop reference
    can go stale, causing call_soon_threadsafe to silently fail.
    """
    global _sse_callback_installed, _sse_loop
    _sse_loop = asyncio.get_running_loop()
    if _sse_callback_installed:
        return
    _sse_callback_installed = True
    from tools.stt.engine import get_engine
    get_engine().set_state_callback(_broadcast_status)


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
        total_words=stats.get("total_words", 0),
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


@router.get("/stats", response_model=StatsResponse)
async def stt_stats():
    """Dictation statistics."""
    from tools.stt.logger import get_stats

    loop = asyncio.get_event_loop()
    stats = await loop.run_in_executor(None, get_stats)

    return StatsResponse(**stats)


VOCAB_FILE = Path(__file__).resolve().parent.parent.parent / "tools" / "stt" / "data" / "vocab.txt"


def _read_vocab() -> list[str]:
    """Read vocabulary terms from vocab.txt."""
    if not VOCAB_FILE.exists():
        return []
    return [t.strip() for t in VOCAB_FILE.read_text(encoding="utf-8").splitlines() if t.strip()]


def _write_vocab(terms: list[str]) -> None:
    """Write vocabulary terms to vocab.txt."""
    VOCAB_FILE.parent.mkdir(parents=True, exist_ok=True)
    VOCAB_FILE.write_text("\n".join(terms) + "\n", encoding="utf-8")


@router.get("/vocab", response_model=VocabResponse)
async def stt_vocab():
    """List vocabulary priming terms."""
    loop = asyncio.get_event_loop()
    terms = await loop.run_in_executor(None, _read_vocab)
    return VocabResponse(terms=terms)


@router.put("/vocab", response_model=VocabResponse)
async def stt_vocab_update(body: VocabUpdateRequest):
    """Add/remove vocabulary terms."""
    def _update():
        terms = _read_vocab()
        for term in body.add:
            term = term.strip()
            if term and term not in terms:
                terms.append(term)
        for term in body.remove:
            term = term.strip()
            if term in terms:
                terms.remove(term)
        _write_vocab(terms)
        return terms

    loop = asyncio.get_event_loop()
    terms = await loop.run_in_executor(None, _update)
    return VocabResponse(terms=terms)


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


@router.put("/mute", response_model=SuccessResponse)
async def stt_mute(body: MuteUpdateRequest, request: Request):
    """Enable/disable muting system audio while dictating.

    Applies immediately, even mid-dictation (call vs music workflow),
    and persists to config. Broadcast keeps every open client in sync.
    """
    try:
        from tools.stt.engine import get_engine
        engine = get_engine()
        engine.set_mute_on_dictate(body.enabled)
        _broadcast_status(engine.status)
        return SuccessResponse(
            success=True,
            message=f"Dictation mute {'enabled' if body.enabled else 'disabled'}",
        )
    except Exception as e:
        logger.error("Failed to set dictation mute: %s", e)
        return problem(503, f"Failed to set dictation mute: {e}", instance=request.url.path)


@router.post("/unload", response_model=SuccessResponse)
async def stt_unload(request: Request):
    """Unload the transcription model on demand to free VRAM.

    Weights-only unload (same as the idle path) — next dictation reloads
    transparently. Refused with 409 while a dictation is live.
    """
    try:
        from tools.stt.engine import get_engine
        engine = get_engine()
        loop = asyncio.get_event_loop()
        ok = await loop.run_in_executor(None, engine.unload_model_now)
        if not ok:
            return problem(
                409, "Dictation in progress — model is busy",
                instance=request.url.path,
            )
        return SuccessResponse(success=True, message="Transcription model unloaded — VRAM freed")
    except Exception as e:
        logger.error("Failed to unload transcription model: %s", e)
        return problem(503, f"Failed to unload model: {e}", instance=request.url.path)


@router.get("/status/stream")
async def stt_status_stream():
    """SSE stream — pushes status changes instantly.

    Heartbeat timeout ensures dead queues get cleaned up even if
    the ASGI server doesn't deliver CancelledError on disconnect.
    """
    _install_sse_callback()

    # Evict oldest queues if at capacity
    while len(_sse_queues) >= _SSE_MAX_QUEUES:
        try:
            stale = next(iter(_sse_queues))
            _sse_queues.discard(stale)
            logger.debug("SSE queue evicted (at cap %d)", _SSE_MAX_QUEUES)
        except StopIteration:
            break

    q: asyncio.Queue[str] = asyncio.Queue()
    _sse_queues.add(q)

    async def generate():
        try:
            from tools.stt.engine import get_engine
            engine = get_engine()
            yield f"data: {_build_status_payload(engine.status)}\n\n"

            while True:
                try:
                    payload = await asyncio.wait_for(
                        q.get(), timeout=_SSE_HEARTBEAT_S,
                    )
                    yield f"data: {payload}\n\n"
                except asyncio.TimeoutError:
                    # Keepalive — if client is gone, yield raises on write
                    yield ": keepalive\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            _sse_queues.discard(q)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/status", response_model=StatusResponse)
async def stt_status():
    """Listener status (active, model loaded, etc.)."""
    from tools.stt.engine import get_engine
    from api.recorder.transcribe import _model_cache

    engine = get_engine()
    last_id = engine.last_result["id"] if engine.last_result else None
    return StatusResponse(
        active=engine._listener is not None and engine._listener.is_running,
        status=engine.status,
        model_loaded=bool(_model_cache),
        last_result_id=last_id,
        mute_on_dictate=engine.mute_on_dictate,
    )


@router.get("/health")
async def stt_health():
    """STT subsystem health — exposes resource counts for monitoring."""
    import threading as _threading
    from tools.stt.engine import get_engine
    from api.recorder.transcribe import _model_cache

    engine = get_engine()
    stt_threads = [
        t.name for t in _threading.enumerate() if "stt" in t.name.lower()
    ]
    return {
        "sse_queue_count": len(_sse_queues),
        "sse_queue_cap": _SSE_MAX_QUEUES,
        "sse_loop_alive": _sse_loop is not None and _sse_loop.is_running(),
        "listener_alive": (
            engine._listener is not None and engine._listener.is_running
        ),
        "model_cache_keys": list(str(k) for k in _model_cache.keys()),
        "stt_threads": stt_threads,
        "total_thread_count": _threading.active_count(),
    }
