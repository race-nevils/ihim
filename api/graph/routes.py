"""Knowlgraph-viewer API — lean traversal surface over entry_relations.

Two endpoints survive the 2026-06 refactor:

    GET /api/graph/neighborhood/{entry_id}?hops=&min_confidence=&relation_type=
        BFS over entry relations — used by the /challenge commands.
    GET /api/graph/stats
        Relation counts by type/source.

The maintenance/analysis endpoints (bridges, drift, triage, bootstrap,
relation CRUD, ...) were removed: nothing called them, and relation writes
belong to the rebuild pipeline.
"""

from typing import Optional

from fastapi import APIRouter, Query, Request

from api.errors import problem
from data.database import get_connection, get_graph_stats

router = APIRouter(prefix="/api/graph", tags=["Knowledge Graph"])


@router.get("/neighborhood/{entry_id}")
async def get_neighborhood(
    request: Request,
    entry_id: str,
    hops: int = Query(1, ge=1, le=5),
    min_confidence: float = Query(0.0, ge=0.0, le=1.0),
    relation_type: Optional[str] = Query(None, description="Filter by relation type"),
):
    """Connected entries within N hops (undirected BFS over entry_relations)."""
    conn = get_connection()
    try:
        entry = conn.execute(
            "SELECT id, title, category FROM entries WHERE id = ?", (entry_id,)
        ).fetchone()
        if not entry:
            return problem(404, "Entry not found", instance=request.url.path)

        visited = {entry_id}
        frontier = {entry_id}
        nodes = {entry_id: {"id": entry_id, "title": entry["title"],
                            "category": entry["category"], "depth": 0}}
        edges = []

        for depth in range(1, hops + 1):
            next_frontier = set()
            for node_id in frontier:
                rows = conn.execute(
                    """
                    SELECT r.source_id, r.target_id, r.relation_type, r.confidence,
                           e_s.title AS source_title, e_s.category AS source_category,
                           e_t.title AS target_title, e_t.category AS target_category
                    FROM entry_relations r
                    JOIN entries e_s ON e_s.id = r.source_id
                    JOIN entries e_t ON e_t.id = r.target_id
                    WHERE (r.source_id = ? OR r.target_id = ?)
                      AND r.confidence >= ?
                      AND (? IS NULL OR r.relation_type = ?)
                    """,
                    (node_id, node_id, min_confidence, relation_type, relation_type),
                ).fetchall()

                for row in rows:
                    if row["source_id"] == node_id:
                        neighbor_id, neighbor_title, neighbor_cat = (
                            row["target_id"], row["target_title"], row["target_category"])
                    else:
                        neighbor_id, neighbor_title, neighbor_cat = (
                            row["source_id"], row["source_title"], row["source_category"])

                    edges.append({
                        "source": row["source_id"],
                        "target": row["target_id"],
                        "type": row["relation_type"],
                        "confidence": row["confidence"],
                    })

                    if neighbor_id not in visited:
                        visited.add(neighbor_id)
                        next_frontier.add(neighbor_id)
                        nodes[neighbor_id] = {"id": neighbor_id, "title": neighbor_title,
                                              "category": neighbor_cat, "depth": depth}

            frontier = next_frontier
            if not frontier:
                break

        return {
            "entry_id": entry_id,
            "hops": hops,
            "nodes": list(nodes.values()),
            "edges": edges,
            "node_count": len(nodes),
            "edge_count": len(edges),
        }
    finally:
        conn.close()


@router.get("/stats")
async def graph_stats():
    """Relation counts and distribution."""
    return get_graph_stats()
