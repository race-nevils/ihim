"""Ollama adapter for local QWen2.5 models."""
import json
import logging
import os
import httpx
from typing import Optional

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
        system: Optional[str] = None
    ) -> str:
        """Generate text response.

        Args:
            prompt: The user prompt
            model: Model name (defaults to FAST_MODEL)
            system: Optional system prompt

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

        response = self.client.post(
            f"{self.base_url}/api/generate",
            json=payload
        )
        response.raise_for_status()
        return response.json()["response"]

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
            "options": {"temperature": 0}  # Deterministic output
        }
        if system:
            payload["system"] = system

        response = self.client.post(
            f"{self.base_url}/api/generate",
            json=payload
        )
        response.raise_for_status()
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

    def health_check(self) -> bool:
        """Check if Ollama is running and accessible."""
        try:
            response = self.client.get(f"{self.base_url}/api/tags")
            return response.status_code == 200
        except Exception:
            return False

    def list_models(self) -> list[str]:
        """List available models."""
        response = self.client.get(f"{self.base_url}/api/tags")
        response.raise_for_status()
        return [m["name"] for m in response.json().get("models", [])]
