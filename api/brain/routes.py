"""FastAPI routes for brain search and entry management."""
import asyncio
import logging
from enum import Enum
from typing import Any, Optional

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field

from adapters.embeddings import EmbeddingAdapter
from api.calendar.google_auth import token_health
from api.errors import problem
from data.database import (
    get_all_entries,
    get_entries_by_category,
    get_entry_by_id,
    get_latest_rebuild,
    search_entries,
    search_semantic,
    count_by_category,
    count_embeddings,
    has_embedding,
    store_embedding,
)
from data.integrity import spot_check_drift

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/brain", tags=["Brain"])


# --- Response models ---

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


class IntegrityResponse(BaseModel):
    checked: int
    drifted: int
    drift_ids: list[str]
    drift_pct: float
    missing: int
    hash_mismatch: int
    errors: int
    unhashed: int
    status: str


class BackfillResponse(BaseModel):
    success: bool
    generated: int
    skipped: int
    failed: int
    total: int


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
    """Unified search across brain entries.

    Modes:
    - keyword: LIKE-based text search on title/content/summary
    - semantic: KNN embedding search (requires Ollama running)
    - hybrid: runs both, merges and deduplicates by entry ID
    """
    results = []
    actual_mode = mode.value
    warnings = []

    if mode in (SearchMode.keyword, SearchMode.hybrid):
        keyword_results = search_entries(q)
        for entry in keyword_results[:limit]:
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
                semantic_results = search_semantic(query_embedding, limit=limit)
                for entry in semantic_results:
                    entry["match_type"] = "semantic"
                    results.append(entry)
            else:
                semantic_failed = True
                if mode == SearchMode.semantic:
                    return problem(503, "Embedding generation failed - is Ollama running?",
                                   instance=request.url.path)
        except Exception as e:
            semantic_failed = True
            logger.error(f"Semantic search failed: {e}")
            if mode == SearchMode.semantic:
                return problem(503, f"Semantic search failed: {e}",
                               instance=request.url.path)

    if mode == SearchMode.hybrid and semantic_failed:
        actual_mode = "keyword_only"
        warnings.append("Semantic search unavailable, results are keyword-only")

    # Deduplicate hybrid results (prefer semantic if entry appears in both)
    if mode == SearchMode.hybrid:
        seen = {}  # eid -> (entry, index)
        deduped = []
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
):
    """List all brain entries, optionally filtered by category."""
    if category:
        entries = get_entries_by_category(category)
    else:
        entries = get_all_entries()
    return {
        "count": len(entries),
        "entries": entries,
    }


@router.get("/entries/{entry_id}")
async def get_entry(entry_id: str, request: Request):
    """Get a single brain entry by ID."""
    entry = get_entry_by_id(entry_id)
    if not entry:
        return problem(404, f"Entry not found: {entry_id}", instance=request.url.path)
    entry["has_embedding"] = has_embedding(entry_id)
    return entry


@router.get("/stats", response_model=BrainStatsResponse)
async def brain_stats():
    """Brain statistics: category counts and embedding coverage."""
    categories = count_by_category()
    total_entries = sum(categories.values())
    total_embeddings = count_embeddings()
    return {
        "total_entries": total_entries,
        "total_embeddings": total_embeddings,
        "embedding_coverage": f"{total_embeddings}/{total_entries}",
        "embedding_pct": round(total_embeddings / total_entries * 100, 1) if total_entries > 0 else 0,
        "categories": categories,
    }


@router.get("/integrity", response_model=IntegrityResponse)
async def brain_integrity():
    """Spot-check content hash drift between JSON-LD files and DB."""
    result = spot_check_drift(20)
    has_issues = result["drifted"] > 0 or result["errors"] > 0
    result["status"] = "drift_detected" if has_issues else "clean"
    return result


@router.get("/status")
async def brain_status():
    """System health: entry count, embeddings, Ollama, calendar, rebuild, drift."""
    response = {}

    # Entry count
    try:
        categories = count_by_category()
        entry_count = sum(categories.values())
        response["entry_count"] = entry_count
    except Exception:
        response["entry_count"] = 0
        entry_count = 0

    # Embedding coverage
    try:
        embeddings = count_embeddings()
        response["embedding_coverage_pct"] = (
            round(embeddings / entry_count * 100, 1) if entry_count > 0 else 0.0
        )
    except Exception:
        response["embedding_coverage_pct"] = 0.0

    # Ollama health (sync httpx — run in executor to avoid blocking event loop)
    try:
        loop = asyncio.get_event_loop()
        with EmbeddingAdapter() as adapter:
            alive = await loop.run_in_executor(None, adapter.health_check)
        response["ollama"] = "alive" if alive else "down"
    except Exception:
        response["ollama"] = "unknown"

    # Calendar auth
    try:
        health = token_health()
        if health.get("valid"):
            response["calendar_auth"] = "valid"
        elif health.get("expired"):
            response["calendar_auth"] = "expired"
        else:
            response["calendar_auth"] = "missing"
    except Exception:
        response["calendar_auth"] = "unknown"

    # Last rebuild
    try:
        rebuild_record = get_latest_rebuild()
        response["last_rebuild"] = rebuild_record["completed_at"] if rebuild_record else None
    except Exception:
        response["last_rebuild"] = None

    # Drift sample
    try:
        drift = spot_check_drift(5)
        response["drift_sample"] = {
            "status": "clean" if drift["drifted"] == 0 and drift["errors"] == 0 else "drift_detected",
            "checked": drift["checked"],
            "drifted": drift["drifted"],
            "missing": drift["missing"],
            "hash_mismatch": drift["hash_mismatch"],
            "errors": drift["errors"],
        }
    except Exception as e:
        logger.warning(f"Drift sample failed: {e}")
        response["drift_sample"] = {"status": "error", "checked": 0, "drifted": 0}

    return response


@router.post("/embeddings/backfill", response_model=BackfillResponse)
async def backfill_embeddings():
    """Generate embeddings for all entries that don't have one yet.

    Safe to call multiple times - skips entries that already have embeddings.
    """
    entries = get_all_entries()
    generated = 0
    skipped = 0
    failed = 0

    loop = asyncio.get_event_loop()
    with EmbeddingAdapter() as adapter:
        for entry in entries:
            entry_id = entry["id"]
            if has_embedding(entry_id):
                skipped += 1
                continue
            embed_text = f"{entry.get('title', '')}\n{entry.get('content', '')}"
            embedding = await loop.run_in_executor(None, adapter.generate_embedding, embed_text)
            if embedding:
                stored = store_embedding(entry_id, embedding)
                if stored:
                    generated += 1
                else:
                    failed += 1
            else:
                failed += 1

    return {
        "success": True,
        "generated": generated,
        "skipped": skipped,
        "failed": failed,
        "total": len(entries),
    }
