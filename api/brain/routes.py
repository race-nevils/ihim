"""Brain API — lean read surface over the JSON-LD-derived SQLite index.

Kept endpoints serve the dashboard plus the agent harness commands that
depend on them (/graduate, /closeday, /challenge):

    GET /api/brain/search?q=&mode=hybrid&limit=
    GET /api/brain/entries?category=&sort=&order=&limit=
    GET /api/brain/entries/{id}
    GET /api/brain/stats

Maintenance surfaces (integrity, status aggregator, embedding backfill) were
removed in the 2026-06 refactor — /rebuild owns derived-store maintenance.
"""

import logging
from enum import Enum
from typing import Any, Optional

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field

from adapters.embeddings import EmbeddingAdapter
from api.errors import problem
from data.database import (
    count_by_category,
    count_embeddings,
    get_all_entries,
    get_entries_by_category,
    get_entry_by_id,
    has_embedding,
    search_entries,
    search_semantic,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/brain", tags=["Brain"])


class BrainSearchResponse(BaseModel):
    query: str
    mode: str
    search_mode_actual: str
    count: int
    results: list[dict[str, Any]]
    warnings: list[str] = Field(default_factory=list)


class BrainEntryListResponse(BaseModel):
    count: int
    entries: list[dict[str, Any]]


class BrainStatsResponse(BaseModel):
    total_entries: int
    total_embeddings: int
    embedding_coverage: str
    embedding_pct: float
    categories: dict[str, int]


class SearchMode(str, Enum):
    keyword = "keyword"
    semantic = "semantic"
    hybrid = "hybrid"


@router.get("/search", response_model=BrainSearchResponse)
async def brain_search(
    request: Request,
    q: str = Query(..., min_length=1, description="Search query"),
    mode: SearchMode = Query(SearchMode.hybrid, description="Search mode"),
    limit: int = Query(10, ge=1, le=50, description="Max results"),
):
    """Search brain entries.

    keyword: LIKE search on title/content/summary.
    semantic: KNN embedding search (requires Ollama).
    hybrid: both, deduplicated by entry ID (semantic wins ties).
    """
    results: list[dict] = []
    actual_mode = mode.value
    warnings: list[str] = []

    if mode in (SearchMode.keyword, SearchMode.hybrid):
        for entry in search_entries(q)[:limit]:
            entry["match_type"] = "keyword"
            entry["similarity_score"] = None
            entry["distance"] = None
            results.append(entry)

    semantic_failed = False
    if mode in (SearchMode.semantic, SearchMode.hybrid):
        try:
            with EmbeddingAdapter() as adapter:
                query_embedding = adapter.generate_embedding(q)
            if query_embedding:
                for entry in search_semantic(query_embedding, limit=limit):
                    entry["match_type"] = "semantic"
                    results.append(entry)
            else:
                semantic_failed = True
                if mode == SearchMode.semantic:
                    return problem(503, "Embedding generation failed - is Ollama running?",
                                   instance=request.url.path)
        except Exception as e:
            semantic_failed = True
            logger.error("Semantic search failed: %s", e)
            if mode == SearchMode.semantic:
                return problem(503, f"Semantic search failed: {e}", instance=request.url.path)

    if mode == SearchMode.hybrid and semantic_failed:
        actual_mode = "keyword_only"
        warnings.append("Semantic search unavailable, results are keyword-only")

    if mode == SearchMode.hybrid:
        seen: dict[str, tuple[dict, int]] = {}
        deduped: list[dict] = []
        for entry in results:
            eid = entry["id"]
            if eid not in seen:
                seen[eid] = (entry, len(deduped))
                deduped.append(entry)
            elif entry["match_type"] == "semantic" and seen[eid][0]["match_type"] == "keyword":
                entry["match_type"] = "both"
                idx = seen[eid][1]
                deduped[idx] = entry
                seen[eid] = (entry, idx)
            elif entry["match_type"] == "keyword" and seen[eid][0]["match_type"] == "semantic":
                seen[eid][0]["match_type"] = "both"
        results = deduped[:limit]

    return {
        "query": q,
        "mode": mode.value,
        "search_mode_actual": actual_mode,
        "count": len(results),
        "results": results,
        "warnings": warnings,
    }


@router.get("/entries", response_model=BrainEntryListResponse)
async def list_entries(
    category: Optional[str] = Query(None, description="Filter by category"),
    sort: str = Query("created_at", description="Sort field (created_at|modified_at|title)"),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    limit: int = Query(0, ge=0, le=500, description="0 = no limit"),
):
    """List brain entries, optionally filtered/sorted/limited.

    sort/order/limit exist for the /graduate and /closeday commands
    (`?sort=created_at&order=desc&limit=50`).
    """
    entries = get_entries_by_category(category) if category else get_all_entries()
    sort_key = sort if sort in ("created_at", "modified_at", "title") else "created_at"
    entries.sort(key=lambda e: (e.get(sort_key) is None, e.get(sort_key) or ""),
                 reverse=(order == "desc"))
    if limit:
        entries = entries[:limit]
    return {"count": len(entries), "entries": entries}


@router.get("/entries/{entry_id}")
async def get_entry(entry_id: str, request: Request):
    """Single brain entry by ID."""
    entry = get_entry_by_id(entry_id)
    if not entry:
        return problem(404, f"Entry not found: {entry_id}", instance=request.url.path)
    entry["has_embedding"] = has_embedding(entry_id)
    return entry


@router.get("/stats", response_model=BrainStatsResponse)
async def brain_stats():
    """Category counts + embedding coverage."""
    categories = count_by_category()
    total_entries = sum(categories.values())
    total_embeddings = count_embeddings()
    return {
        "total_entries": total_entries,
        "total_embeddings": total_embeddings,
        "embedding_coverage": f"{total_embeddings}/{total_entries}",
        "embedding_pct": round(total_embeddings / total_entries * 100, 1) if total_entries else 0,
        "categories": categories,
    }
