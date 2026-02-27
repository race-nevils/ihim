"""Ollama adapter for local QWen2.5 models."""
import json
import logging
import os
import time
from typing import AsyncGenerator, Optional

import httpx

logger = logging.getLogger(__name__)


class OllamaAdapter:
    """Adapter for Ollama API with QWen2.5 models.

    Supports context manager for proper resource cleanup:
        with OllamaAdapter() as adapter:
            result = adapter.generate("Hello")
    """

    # Model aliases for convenience
    FAST_MODEL = "qwen2.5:7b-fast"
    REASON_MODEL = "qwen2.5:14b-reason"

    def __init__(self, base_url: Optional[str] = None):
        # Allow override via environment variable
        self.base_url = base_url or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        self.client = httpx.Client(timeout=120.0)  # Longer timeout for reasoning model

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    def close(self):
        """Close the HTTP client and release resources."""
        if self.client:
            self.client.close()

    def generate(
        self,
        prompt: str,
        model: Optional[str] = None,
        system: Optional[str] = None,
        keep_alive: Optional[str] = None,
    ) -> str:
        """Generate text response.

        Args:
            prompt: The user prompt
            model: Model name (defaults to FAST_MODEL)
            system: Optional system prompt
            keep_alive: Ollama keep_alive duration (e.g. "0" to unload immediately)

        Returns:
            Generated text response
        """
        model = model or self.FAST_MODEL
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0}  # Deterministic output
        }
        if system:
            payload["system"] = system
        if keep_alive is not None:
            payload["keep_alive"] = keep_alive

        last_exc = None
        for attempt in range(3):
            try:
                response = self.client.post(
                    f"{self.base_url}/api/generate",
                    json=payload
                )
                response.raise_for_status()
                result = response.json().get("response", "")
                if not result:
                    logger.warning("Ollama generate returned empty/missing 'response' field")
                return result
            except (httpx.TimeoutException, httpx.ConnectError) as e:
                last_exc = e
                if attempt < 2:
                    wait = 2 ** attempt  # 1s, 2s
                    logger.warning(f"Ollama generate attempt {attempt + 1} failed: {e}, retrying in {wait}s")
                    time.sleep(wait)
        raise last_exc

    def generate_json(
        self,
        prompt: str,
        model: Optional[str] = None,
        system: Optional[str] = None
    ) -> dict:
        """Generate JSON response.

        Args:
            prompt: The user prompt (should ask for JSON output)
            model: Model name (defaults to FAST_MODEL)
            system: Optional system prompt

        Returns:
            Parsed JSON dict
        """
        model = model or self.FAST_MODEL
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0},  # Deterministic output
            "keep_alive": "0",  # Unload immediately — frees VRAM for embedding model
        }
        if system:
            payload["system"] = system

        last_exc = None
        for attempt in range(3):
            try:
                response = self.client.post(
                    f"{self.base_url}/api/generate",
                    json=payload
                )
                response.raise_for_status()
                break
            except (httpx.TimeoutException, httpx.ConnectError) as e:
                last_exc = e
                if attempt < 2:
                    wait = 2 ** attempt  # 1s, 2s
                    logger.warning(f"Ollama generate_json attempt {attempt + 1} failed: {e}, retrying in {wait}s")
                    time.sleep(wait)
        else:
            raise last_exc
        raw = response.json().get("response", "")

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON from Ollama: {e}. Raw response: {raw[:500]}")
            return {"error": "json_parse_failed", "raw": raw}

        # Validate: callers expect a dict. LLMs sometimes return lists or scalars.
        if isinstance(parsed, dict):
            return parsed
        if isinstance(parsed, list) and len(parsed) == 1 and isinstance(parsed[0], dict):
            # Single-item list wrapping a dict — unwrap it
            logger.warning(f"LLM returned single-item list, unwrapping to dict")
            return parsed[0]
        if isinstance(parsed, list) and len(parsed) > 1:
            # Multi-item list — merge into first dict, preserve list in "_items" key
            logger.warning(f"LLM returned list of {len(parsed)} items, normalizing to dict")
            first = next((item for item in parsed if isinstance(item, dict)), {})
            first["_items"] = parsed
            return first

        logger.error(f"LLM returned unexpected JSON type {type(parsed).__name__}: {str(parsed)[:200]}")
        return {"error": "unexpected_json_type", "raw_type": type(parsed).__name__}

    def health_check(self, timeout: float = 5.0) -> bool:
        """Check if Ollama is running and accessible."""
        try:
            response = self.client.get(f"{self.base_url}/api/tags", timeout=timeout)
            return response.status_code == 200
        except Exception:
            return False

    def list_models(self) -> list[str]:
        """List available models."""
        response = self.client.get(f"{self.base_url}/api/tags")
        response.raise_for_status()
        return [m["name"] for m in response.json().get("models", [])]


class AsyncOllamaAdapter:
    """Async adapter for Ollama chat API with streaming.

    Used by Brain Chat for the 14B conversational model.
    The sync OllamaAdapter above continues serving 7B classification.
    """

    CHAT_MODEL = "qwen2.5:14b-reason"

    def __init__(self, base_url: Optional[str] = None):
        self.base_url = base_url or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        self.client = httpx.AsyncClient(timeout=300.0)  # 14B needs generous timeout

    async def stream_chat(
        self,
        messages: list[dict],
        model: Optional[str] = None,
        temperature: float = 0.7,
    ) -> AsyncGenerator[str, None]:
        """Stream chat completion tokens from Ollama /api/chat.

        Args:
            messages: OpenAI-format messages array [{role, content}, ...]
            model: Model name (defaults to 14b-reason)
            temperature: Sampling temperature (0.7 for conversational)

        Yields:
            Token strings as they arrive.
        """
        model = model or self.CHAT_MODEL
        payload = {
            "model": model,
            "messages": messages,
            "stream": True,
            "options": {"temperature": temperature},
        }

        async with self.client.stream(
            "POST",
            f"{self.base_url}/api/chat",
            json=payload,
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line:
                    continue
                try:
                    chunk = json.loads(line)
                    token = chunk.get("message", {}).get("content", "")
                    if token:
                        yield token
                    if chunk.get("done"):
                        break
                except json.JSONDecodeError:
                    continue

    async def health_check(self) -> bool:
        """Check if Ollama is running and accessible."""
        try:
            response = await self.client.get(f"{self.base_url}/api/tags")
            return response.status_code == 200
        except Exception:
            return False

    async def close(self):
        """Close the async HTTP client."""
        await self.client.aclose()
