"""Embedding adapter for Qwen3-Embedding via Ollama."""
import logging
import os
import struct
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# Model config
EMBED_MODEL = "qwen3-embedding:0.6b"
EMBED_DIM = 1024


class EmbeddingAdapter:
    """Generate embeddings via Ollama's /api/embeddings endpoint.

    Supports context manager for proper resource cleanup:
        with EmbeddingAdapter() as adapter:
            vec = adapter.generate_embedding("some text")
    """

    def __init__(self, base_url: Optional[str] = None):
        self.base_url = base_url or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        self.client = httpx.Client(timeout=30.0)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    def close(self):
        """Close the HTTP client and release resources."""
        if self.client:
            self.client.close()

    def generate_embedding(self, text: str) -> Optional[list[float]]:
        """Generate embedding vector for text.

        Args:
            text: Input text to embed (Qwen3-Embedding supports up to 32K tokens)

        Returns:
            List of 1024 floats, or None on failure (non-blocking)
        """
        try:
            response = self.client.post(
                f"{self.base_url}/api/embeddings",
                json={"model": EMBED_MODEL, "prompt": text, "keep_alive": "0"}
            )
            response.raise_for_status()
            embedding = response.json().get("embedding")
            if embedding and len(embedding) == EMBED_DIM:
                return embedding
            logger.warning(f"Unexpected embedding dimension: {len(embedding) if embedding else 0}")
            return None
        except Exception as e:
            logger.warning(f"Embedding generation failed: {e}")
            return None

    def embedding_to_blob(self, embedding: list[float]) -> bytes:
        """Convert embedding list to binary blob for sqlite-vec storage."""
        return struct.pack(f"{len(embedding)}f", *embedding)

    def health_check(self) -> bool:
        """Check if embedding model is available."""
        try:
            response = self.client.post(
                f"{self.base_url}/api/embeddings",
                json={"model": EMBED_MODEL, "prompt": "health check"}
            )
            return response.status_code == 200
        except Exception:
            return False
