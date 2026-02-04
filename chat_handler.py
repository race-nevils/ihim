"""Chat orchestration -- sessions, RAG context injection, streaming generation.

Manages conversation history, builds per-turn system prompts with fresh RAG
context, and streams tokens from the 14B model via AsyncOllamaAdapter.
"""
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import AsyncGenerator, Optional

from adapters.ollama import AsyncOllamaAdapter
from chat_retrieval import RetrievalPipeline, RetrievalResult, build_default_pipeline

logger = logging.getLogger(__name__)

CHAT_MODEL = "qwen2.5:14b-reason"
CHAT_TEMPERATURE = 0.7
SESSION_TTL_MINUTES = 60

SYSTEM_PROMPT_TEMPLATE = """You are the iHIM Brain Assistant -- the operator's personal AI with access to his Second Brain.

Your role:
- Answer questions using the provided brain context
- Be conversational but precise
- When drawing from brain entries, mention which entry
- If brain context doesn't cover the question, say so and answer from general knowledge
- Keep responses concise unless asked for detail

Style: Direct, no filler. Use the operator's terminology from his notes.

{rag_context}"""


@dataclass
class ChatSession:
    """Holds conversation history for one session."""
    session_id: str
    messages: list[dict] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_active: datetime = field(default_factory=datetime.utcnow)

    def add_message(self, role: str, content: str):
        self.messages.append({"role": role, "content": content})
        self.last_active = datetime.utcnow()

    def get_messages(self, system_prompt: str) -> list[dict]:
        """Return messages array with system prompt prepended (OpenAI format)."""
        return [{"role": "system", "content": system_prompt}] + self.messages

    @property
    def is_expired(self) -> bool:
        return datetime.utcnow() - self.last_active > timedelta(minutes=SESSION_TTL_MINUTES)


class ChatSessionManager:
    """In-memory session store with TTL expiry."""

    def __init__(self):
        self._sessions: dict[str, ChatSession] = {}

    def get_or_create(self, session_id: str) -> ChatSession:
        session = self._sessions.get(session_id)
        if session and not session.is_expired:
            return session
        # Expired or new
        session = ChatSession(session_id=session_id)
        self._sessions[session_id] = session
        return session

    def clear_session(self, session_id: str):
        if session_id in self._sessions:
            self._sessions[session_id] = ChatSession(session_id=session_id)

    def list_sessions(self) -> list[dict]:
        self.cleanup_expired()
        return [
            {
                "session_id": s.session_id,
                "message_count": len(s.messages),
                "created_at": s.created_at.isoformat(),
                "last_active": s.last_active.isoformat(),
            }
            for s in self._sessions.values()
        ]

    def cleanup_expired(self):
        expired = [sid for sid, s in self._sessions.items() if s.is_expired]
        for sid in expired:
            del self._sessions[sid]


def build_system_prompt(rag_results: list[RetrievalResult]) -> str:
    """Inject RAG context into the system prompt."""
    if not rag_results:
        rag_block = "No relevant brain entries found for this query."
    else:
        entries = []
        for r in rag_results:
            entries.append(
                f"[{r.category}] {r.title} (score: {r.score:.2f}, match: {r.match_type})\n{r.content}"
            )
        rag_block = "Relevant brain entries:\n\n" + "\n\n---\n\n".join(entries)

    return SYSTEM_PROMPT_TEMPLATE.format(rag_context=rag_block)


async def handle_chat_message(
    session: ChatSession,
    user_message: str,
    pipeline: RetrievalPipeline,
    ollama: AsyncOllamaAdapter,
) -> AsyncGenerator[dict, None]:
    """Full chat turn: RAG retrieval -> system prompt -> stream response.

    Yields event dicts for the WebSocket to forward to the client.
    """
    # 1. Add user message to history
    session.add_message("user", user_message)

    # 2. RAG retrieval
    yield {"type": "retrieval_start"}
    try:
        rag_results = pipeline.run(user_message, limit=5)
    except Exception as e:
        logger.error(f"Retrieval failed: {e}")
        rag_results = []

    yield {
        "type": "retrieval_result",
        "count": len(rag_results),
        "entries": [
            {"title": r.title, "category": r.category, "score": round(r.score, 2)}
            for r in rag_results
        ],
    }

    # 3. Build system prompt with fresh RAG context
    system_prompt = build_system_prompt(rag_results)
    messages = session.get_messages(system_prompt)

    # 4. Stream generation
    yield {"type": "generation_start"}
    full_response = ""
    try:
        async for token in ollama.stream_chat(
            messages=messages,
            model=CHAT_MODEL,
            temperature=CHAT_TEMPERATURE,
        ):
            full_response += token
            yield {"type": "token", "content": token}
    except Exception as e:
        logger.error(f"Generation failed: {e}")
        yield {"type": "error", "message": f"Generation failed: {e}"}
        return

    yield {"type": "generation_end"}

    # 5. Store assistant response in session history
    if full_response:
        session.add_message("assistant", full_response)
