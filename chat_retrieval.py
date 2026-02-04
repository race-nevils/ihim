"""Modular retrieval pipeline for RAG over the Second Brain.

Designed for extension: add stages (reranking, GraphRAG) by implementing
RetrievalStage and registering with RetrievalPipeline.
"""
import logging
from dataclasses import dataclass, field
from typing import Optional, Protocol

from adapters.embeddings import EmbeddingAdapter
from data.database import search_semantic, search_entries

logger = logging.getLogger(__name__)


@dataclass
class RetrievalResult:
    """Single retrieval hit from any stage."""
    entry_id: str
    title: str
    content: str
    category: str
    score: float
    match_type: str  # "semantic", "keyword", etc.
    metadata: dict = field(default_factory=dict)


class RetrievalStage(Protocol):
    """Protocol for pluggable retrieval stages."""
    def retrieve(self, query: str, limit: int) -> list[RetrievalResult]: ...


class SemanticStage:
    """Vector similarity search via embeddings + sqlite-vec."""

    def __init__(self):
        self.embedder = EmbeddingAdapter()

    def retrieve(self, query: str, limit: int) -> list[RetrievalResult]:
        embedding = self.embedder.generate_embedding(query)
        if not embedding:
            logger.warning("Semantic stage: embedding generation failed")
            return []

        rows = search_semantic(embedding, limit=limit)
        results = []
        for row in rows:
            results.append(RetrievalResult(
                entry_id=row["id"],
                title=row.get("title", ""),
                content=row.get("content", "")[:500],
                category=row.get("category", ""),
                score=row.get("similarity_score", 0.0),
                match_type="semantic",
                metadata={"distance": row.get("distance", 0)},
            ))
        return results

    def close(self):
        self.embedder.close()


class KeywordStage:
    """SQL LIKE search over title/content/summary."""

    def retrieve(self, query: str, limit: int) -> list[RetrievalResult]:
        rows = search_entries(query)
        results = []
        for i, row in enumerate(rows[:limit]):
            # Score descends from 0.8 so keyword results rank below strong semantic hits
            score = max(0.1, 0.8 - (i * 0.05))
            results.append(RetrievalResult(
                entry_id=row["id"],
                title=row.get("title", ""),
                content=row.get("content", "")[:500],
                category=row.get("category", ""),
                score=score,
                match_type="keyword",
                metadata={},
            ))
        return results


class RetrievalPipeline:
    """Runs multiple retrieval stages, merges and ranks results."""

    def __init__(self):
        self.stages: list[RetrievalStage] = []

    def add_stage(self, stage: RetrievalStage) -> "RetrievalPipeline":
        self.stages.append(stage)
        return self

    def run(self, query: str, limit: int = 5) -> list[RetrievalResult]:
        """Run all stages, merge by entry_id (keep highest score), sort, truncate."""
        merged: dict[str, RetrievalResult] = {}

        for stage in self.stages:
            try:
                hits = stage.retrieve(query, limit=limit * 2)
                for hit in hits:
                    existing = merged.get(hit.entry_id)
                    if existing is None or hit.score > existing.score:
                        merged[hit.entry_id] = hit
            except Exception as e:
                logger.error(f"Retrieval stage {stage.__class__.__name__} failed: {e}")

        ranked = sorted(merged.values(), key=lambda r: r.score, reverse=True)
        return ranked[:limit]

    def close(self):
        for stage in self.stages:
            if hasattr(stage, "close"):
                stage.close()


def build_default_pipeline() -> RetrievalPipeline:
    """Build the standard hybrid retrieval pipeline (semantic + keyword)."""
    pipeline = RetrievalPipeline()
    pipeline.add_stage(SemanticStage())
    pipeline.add_stage(KeywordStage())
    return pipeline
