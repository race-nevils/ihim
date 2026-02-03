"""LLM adapters for Second Brain orchestration."""
from .ollama import OllamaAdapter
from .embeddings import EmbeddingAdapter

__all__ = ["OllamaAdapter", "EmbeddingAdapter"]
