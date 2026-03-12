"""WebSocket + REST routes for Brain Chat.

Pattern follows api/terminal/routes.py -- APIRouter with prefix,
WebSocket endpoint for streaming, REST for health/sessions.
"""
import asyncio
import json
import logging
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from adapters.ollama import AsyncOllamaAdapter
from chat_handler import ChatSessionManager, handle_chat_message
from chat_retrieval import build_default_pipeline

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["Chat"])

# Singletons -- created once, shared across requests
session_manager = ChatSessionManager()
retrieval_pipeline = build_default_pipeline()
ollama_adapter = AsyncOllamaAdapter()


# =============================================================================
# REST ENDPOINTS
# =============================================================================

@router.get("/health")
async def chat_health():
    """Check Ollama reachable, 14B model available, embeddings working."""
    ollama_ok = await ollama_adapter.health_check()
    from adapters.embeddings import EmbeddingAdapter
    embed_adapter = EmbeddingAdapter()
    embed_ok = embed_adapter.health_check()
    embed_adapter.close()

    model_name = "qwen2.5:14b-reason"
    all_ok = ollama_ok and embed_ok

    return {
        "success": True,
        "healthy": all_ok,
        "ollama": "ok" if ollama_ok else "unreachable",
        "model": model_name,
        "embeddings": "ok" if embed_ok else "unavailable",
    }


@router.get("/sessions")
async def list_sessions():
    """List active chat sessions."""
    sessions = session_manager.list_sessions()
    return {"count": len(sessions), "sessions": sessions}


# =============================================================================
# WEBSOCKET ENDPOINT
# =============================================================================

@router.websocket("/ws/{session_id}")
async def chat_websocket(websocket: WebSocket, session_id: str):
    """Streaming chat WebSocket.

    Client sends:
        {"type": "message", "content": "..."}
        {"type": "clear"}
        {"type": "ping"}

    Server sends:
        {"type": "connected", "session_id": "...", "model": "..."}
        {"type": "retrieval_start"}
        {"type": "retrieval_result", "count": N, "entries": [...]}
        {"type": "generation_start"}
        {"type": "token", "content": "..."}
        {"type": "generation_end"}
        {"type": "error", "message": "..."}
        {"type": "pong"}
    """
    await websocket.accept()

    session = session_manager.get_or_create(session_id)

    await websocket.send_json({
        "type": "connected",
        "session_id": session_id,
        "model": "qwen2.5:14b-reason",
    })

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "message": "Invalid JSON"})
                continue

            msg_type = data.get("type")

            if msg_type == "ping":
                await websocket.send_json({"type": "pong"})
                continue

            if msg_type == "clear":
                session_manager.clear_session(session_id)
                session = session_manager.get_or_create(session_id)
                await websocket.send_json({"type": "cleared", "session_id": session_id})
                continue

            if msg_type == "message":
                content = data.get("content", "").strip()
                if not content:
                    await websocket.send_json({"type": "error", "message": "Empty message"})
                    continue

                async for event in handle_chat_message(
                    session=session,
                    user_message=content,
                    pipeline=retrieval_pipeline,
                    ollama=ollama_adapter,
                ):
                    await websocket.send_json(event)
                continue

            await websocket.send_json({"type": "error", "message": f"Unknown type: {msg_type}"})

    except WebSocketDisconnect:
        logger.info(f"Chat WS disconnected: {session_id}")
    except Exception as e:
        logger.error(f"Chat WS error: {e}")
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except Exception as send_err:
            logger.debug("Chat WS: failed to send error to client: %s", send_err)
