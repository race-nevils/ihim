"""Knowledge Graph API — traversal, health, and curation endpoints.

Endpoints:
    GET  /neighborhood/{entry_id}  — Connected entries within N hops
    GET  /path                     — Shortest path via BFS
    GET  /clusters                 — Connected components
    GET  /timeline/{entry_id}      — Temporal evolution of connections
    GET  /drift                    — Recurring themes across unlinked entries
    GET  /stats                    — Counts, averages, distributions
    GET  /health                   — SEO-informed graph health
    GET  /bridges                  — High betweenness centrality entries
    GET  /orphans                  — Zero-relation entries
    POST /relations                — Manual curation (add relation)
    DELETE /relations/{id}         — Remove relation
    PATCH /relations/{id}          — Retype/reconfidence
    POST /bootstrap                — Trigger retroactive extraction
"""

import asyncio
import math
import logging
from collections import defaultdict, deque
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from api.errors import problem
from data.database import (
    get_connection,
    get_relations,
    get_graph_stats,
    get_orphan_entries,
    link_entries,
    delete_relation as db_delete_relation,
    count_relations,
)
from data.jsonld import RELATION_TYPES, RELATION_SOURCES

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/graph", tags=["Knowledge Graph"])


# =============================================================================
# Request/Response Models
# =============================================================================

class RelationCreate(BaseModel):
    source_id: str = Field(..., description="Source entry ID")
    target_id: str = Field(..., description="Target entry ID")
    relation_type: str = Field("relatedTo", description="Relation type")
    confidence: float = Field(0.9, ge=0.0, le=1.0)
    reasoning: Optional[str] = Field(None, max_length=500)


class RelationPatch(BaseModel):
    relation_type: Optional[str] = None
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0)


# =============================================================================
# Graph Traversal Endpoints
# =============================================================================

@router.get("/neighborhood/{entry_id}")
async def get_neighborhood(
    request: Request,
    entry_id: str,
    hops: int = Query(1, ge=1, le=5),
    min_confidence: float = Query(0.0, ge=0.0, le=1.0),
):
    """Get connected entries within N hops of a given entry."""
    conn = get_connection()
    try:
        # Verify entry exists
        entry = conn.execute(
            "SELECT id, title, category FROM entries WHERE id = ?", (entry_id,)
        ).fetchone()
        if not entry:
            return problem(404, "Entry not found", instance=request.url.path)

        # BFS traversal
        visited = {entry_id}
        frontier = {entry_id}
        nodes = {entry_id: {"id": entry_id, "title": entry["title"],
                            "category": entry["category"], "depth": 0}}
        edges = []

        for depth in range(1, hops + 1):
            next_frontier = set()
            for node_id in frontier:
                rows = conn.execute("""
                    SELECT r.source_id, r.target_id, r.relation_type,
                           r.confidence, r.extraction_source,
                           e_s.title as source_title, e_s.category as source_category,
                           e_t.title as target_title, e_t.category as target_category
                    FROM entry_relations r
                    JOIN entries e_s ON e_s.id = r.source_id
                    JOIN entries e_t ON e_t.id = r.target_id
                    WHERE (r.source_id = ? OR r.target_id = ?)
                    AND r.confidence >= ?
                """, (node_id, node_id, min_confidence)).fetchall()

                for row in rows:
                    neighbor_id = row["target_id"] if row["source_id"] == node_id else row["source_id"]
                    neighbor_title = row["target_title"] if row["source_id"] == node_id else row["source_title"]
                    neighbor_cat = row["target_category"] if row["source_id"] == node_id else row["source_category"]

                    edges.append({
                        "source": row["source_id"],
                        "target": row["target_id"],
                        "type": row["relation_type"],
                        "confidence": row["confidence"],
                    })

                    if neighbor_id not in visited:
                        visited.add(neighbor_id)
                        next_frontier.add(neighbor_id)
                        nodes[neighbor_id] = {
                            "id": neighbor_id,
                            "title": neighbor_title,
                            "category": neighbor_cat,
                            "depth": depth,
                        }

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


@router.get("/path")
async def find_path(
    request: Request,
    from_id: str = Query(..., alias="from"),
    to_id: str = Query(..., alias="to"),
    max_hops: int = Query(10, ge=1, le=20),
):
    """Find shortest path between two entries via BFS."""
    conn = get_connection()
    try:
        # Verify both entries exist
        for eid in (from_id, to_id):
            if not conn.execute("SELECT 1 FROM entries WHERE id = ?", (eid,)).fetchone():
                return problem(404, f"Entry not found: {eid}", instance=request.url.path)

        if from_id == to_id:
            return {"from": from_id, "to": to_id, "path": [from_id], "hops": 0}

        # BFS
        queue = deque([(from_id, [from_id])])
        visited = {from_id}

        while queue:
            current, path = queue.popleft()
            if len(path) > max_hops + 1:
                break

            rows = conn.execute("""
                SELECT source_id, target_id FROM entry_relations
                WHERE source_id = ? OR target_id = ?
            """, (current, current)).fetchall()

            for row in rows:
                neighbor = row["target_id"] if row["source_id"] == current else row["source_id"]
                if neighbor == to_id:
                    final_path = path + [neighbor]
                    # Build detailed path with edge info
                    path_details = []
                    for i in range(len(final_path) - 1):
                        edge = conn.execute("""
                            SELECT r.*, e.title as next_title
                            FROM entry_relations r
                            JOIN entries e ON e.id = ?
                            WHERE (r.source_id = ? AND r.target_id = ?)
                            OR (r.source_id = ? AND r.target_id = ?)
                        """, (final_path[i+1], final_path[i], final_path[i+1],
                              final_path[i+1], final_path[i])).fetchone()
                        if edge:
                            path_details.append({
                                "from": final_path[i],
                                "to": final_path[i+1],
                                "type": edge["relation_type"],
                                "confidence": edge["confidence"],
                            })

                    return {
                        "from": from_id,
                        "to": to_id,
                        "path": final_path,
                        "path_details": path_details,
                        "hops": len(final_path) - 1,
                    }

                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, path + [neighbor]))

        return {"from": from_id, "to": to_id, "path": None, "hops": -1,
                "message": "No path found within max_hops"}
    finally:
        conn.close()


@router.get("/clusters")
async def get_clusters(min_size: int = Query(2, ge=1)):
    """Get connected components using union-find."""
    conn = get_connection()
    try:
        # Load all entries
        entries = {
            row["id"]: {"title": row["title"], "category": row["category"]}
            for row in conn.execute("SELECT id, title, category FROM entries").fetchall()
        }

        # Union-find
        parent = {eid: eid for eid in entries}

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(x, y):
            px, py = find(x), find(y)
            if px != py:
                parent[px] = py

        # Process all relations
        rows = conn.execute("SELECT source_id, target_id FROM entry_relations").fetchall()
        for row in rows:
            s, t = row["source_id"], row["target_id"]
            if s in parent and t in parent:
                union(s, t)

        # Group by component
        components = defaultdict(list)
        for eid in entries:
            root = find(eid)
            components[root].append(eid)

        # Build response
        clusters = []
        for root, members in sorted(components.items(), key=lambda x: len(x[1]), reverse=True):
            if len(members) < min_size:
                continue

            # Category distribution
            cat_dist = defaultdict(int)
            for m in members:
                cat_dist[entries[m]["category"]] += 1

            clusters.append({
                "id": root,
                "size": len(members),
                "members": [
                    {"id": m, "title": entries[m]["title"], "category": entries[m]["category"]}
                    for m in members[:50]  # Cap member list
                ],
                "categories": dict(cat_dist),
            })

        return {
            "total_clusters": len(clusters),
            "largest_cluster": clusters[0]["size"] if clusters else 0,
            "clusters": clusters,
        }
    finally:
        conn.close()


@router.get("/timeline/{entry_id}")
async def get_timeline(request: Request, entry_id: str):
    """Temporal evolution of an entry's connections."""
    conn = get_connection()
    try:
        entry = conn.execute(
            "SELECT id, title, created_at FROM entries WHERE id = ?", (entry_id,)
        ).fetchone()
        if not entry:
            return problem(404, "Entry not found", instance=request.url.path)

        rows = conn.execute("""
            SELECT r.*, e.title as linked_title, e.created_at as linked_created_at
            FROM entry_relations r
            JOIN entries e ON e.id = CASE
                WHEN r.source_id = ? THEN r.target_id
                ELSE r.source_id
            END
            WHERE r.source_id = ? OR r.target_id = ?
            ORDER BY r.created_at
        """, (entry_id, entry_id, entry_id)).fetchall()

        timeline = []
        for row in rows:
            linked_id = row["target_id"] if row["source_id"] == entry_id else row["source_id"]
            timeline.append({
                "relation_id": row["id"],
                "linked_id": linked_id,
                "linked_title": row["linked_title"],
                "relation_type": row["relation_type"],
                "confidence": row["confidence"],
                "extraction_source": row["extraction_source"],
                "created_at": row["created_at"],
                "direction": "outgoing" if row["source_id"] == entry_id else "incoming",
            })

        return {
            "entry_id": entry_id,
            "title": entry["title"],
            "entry_created_at": entry["created_at"],
            "connections": timeline,
            "total": len(timeline),
        }
    finally:
        conn.close()


@router.get("/drift")
async def get_drift(limit: int = Query(20, ge=1, le=100)):
    """Find recurring themes across unlinked entries (potential missing relations)."""
    conn = get_connection()
    try:
        # Get orphan entries (no relations)
        orphans = conn.execute("""
            SELECT e.id, e.title, e.category, e.content
            FROM entries e
            WHERE e.id NOT IN (
                SELECT source_id FROM entry_relations
                UNION
                SELECT target_id FROM entry_relations
            )
            LIMIT ?
        """, (limit,)).fetchall()

        # Simple keyword overlap analysis between orphans
        from handlers.relations import _tokenize

        drift_pairs = []
        orphan_list = [dict(row) for row in orphans]

        for i, a in enumerate(orphan_list):
            a_tokens = set(_tokenize(a.get("content", "") or ""))
            for b in orphan_list[i+1:]:
                b_tokens = set(_tokenize(b.get("content", "") or ""))
                overlap = a_tokens & b_tokens
                # Filter common words
                if len(overlap) > 5:
                    drift_pairs.append({
                        "entry_a": {"id": a["id"], "title": a["title"]},
                        "entry_b": {"id": b["id"], "title": b["title"]},
                        "shared_terms": len(overlap),
                        "sample_terms": sorted(overlap)[:10],
                    })

        drift_pairs.sort(key=lambda x: x["shared_terms"], reverse=True)

        return {
            "orphan_count": len(orphan_list),
            "drift_pairs": drift_pairs[:limit],
            "message": "Entries with shared themes but no formal relations",
        }
    finally:
        conn.close()


# =============================================================================
# Stats & Health Endpoints
# =============================================================================

@router.get("/stats")
async def graph_stats():
    """Comprehensive graph statistics."""
    return get_graph_stats()


@router.get("/health")
async def graph_health():
    """SEO-informed graph health report.

    Metrics from KNOWLEDGE-GRAPH.md Section 7 / SEO-FOR-KNOWLEDGE-GRAPHS.md:
    - Orphan rate (target: 0%)
    - Average shortest path (target: ≤5 hops)
    - Clustering coefficient (target: 0.4-0.7)
    - Hub entries (target: ~12, one per category)
    - Bridge entries (target: 5-10 cross-category connectors)
    - Staleness (freshness scoring on relations)
    """
    conn = get_connection()
    try:
        stats = get_graph_stats()
        total_entries = stats["total_entries"]
        total_relations = stats["total_relations"]

        # Orphan rate
        orphan_rate = stats["orphan_rate"]
        orphan_status = "healthy" if orphan_rate < 0.05 else ("warning" if orphan_rate < 0.2 else "critical")

        # Average degree (relations per connected entry)
        avg_degree = stats["avg_relations_per_entry"]

        # Sampling-based average shortest path
        avg_path = _sample_avg_shortest_path(conn, sample_size=30)

        # Clustering coefficient (per category)
        clustering = _compute_clustering_coefficient(conn)

        # Hub detection (entries with most relations)
        hubs = conn.execute("""
            SELECT eid, COUNT(*) as degree, e.title, e.category
            FROM (
                SELECT source_id as eid FROM entry_relations
                UNION ALL
                SELECT target_id as eid FROM entry_relations
            ) r
            JOIN entries e ON e.id = r.eid
            GROUP BY eid
            ORDER BY degree DESC
            LIMIT 15
        """).fetchall()
        hub_list = [dict(h) for h in hubs]

        # Bridge detection (entries connecting different categories)
        bridges = _find_bridges(conn)

        # Freshness: average age of relations
        freshness = _compute_freshness(conn)

        health = {
            "overall": "healthy",
            "metrics": {
                "orphan_rate": {"value": orphan_rate, "target": 0.0,
                                "status": orphan_status},
                "avg_path_length": {"value": avg_path, "target": 5.0,
                                    "status": "healthy" if avg_path <= 5 else "warning"},
                "clustering_coefficient": {"value": clustering["global"],
                                           "target": "0.4-0.7",
                                           "per_category": clustering["per_category"]},
                "total_relations": total_relations,
                "total_entries": total_entries,
                "avg_degree": avg_degree,
                "graph_density": round(
                    total_relations / (total_entries * (total_entries - 1))
                    if total_entries > 1 else 0, 4),
            },
            "hubs": hub_list[:12],
            "bridges": bridges[:10],
            "freshness": freshness,
            "distribution": stats["by_type"],
        }

        # Overall health
        issues = sum(1 for m in health["metrics"].values()
                     if isinstance(m, dict) and m.get("status") == "critical")
        if issues > 0:
            health["overall"] = "critical"
        elif sum(1 for m in health["metrics"].values()
                 if isinstance(m, dict) and m.get("status") == "warning") > 1:
            health["overall"] = "warning"

        return health
    finally:
        conn.close()


@router.get("/bridges")
async def get_bridges():
    """High betweenness centrality entries — cross-category connectors."""
    conn = get_connection()
    try:
        bridges = _find_bridges(conn)
        return {"bridges": bridges, "total": len(bridges)}
    finally:
        conn.close()


@router.get("/orphans")
async def get_orphans():
    """Entries with zero relations."""
    orphans = get_orphan_entries()
    return {"orphans": orphans, "total": len(orphans)}


# =============================================================================
# Curation Endpoints
# =============================================================================

@router.post("/relations", status_code=201)
async def create_relation(request: Request, body: RelationCreate):
    """Manually add a relation (source: 'manual')."""
    conn = get_connection()
    try:
        # Verify both entries exist
        for eid in (body.source_id, body.target_id):
            if not conn.execute("SELECT 1 FROM entries WHERE id = ?", (eid,)).fetchone():
                return problem(404, f"Entry not found: {eid}", instance=request.url.path)

        if body.relation_type not in RELATION_TYPES:
            return problem(422, f"Invalid relation type: {body.relation_type}. "
                          f"Valid types: {RELATION_TYPES}", instance=request.url.path)

        row_id = link_entries(
            source_id=body.source_id,
            target_id=body.target_id,
            relation_type=body.relation_type,
            confidence=body.confidence,
            extraction_source="manual",
            reasoning=body.reasoning,
        )

        return {
            "id": row_id,
            "source_id": body.source_id,
            "target_id": body.target_id,
            "relation_type": body.relation_type,
            "confidence": body.confidence,
            "extraction_source": "manual",
        }
    finally:
        conn.close()


@router.delete("/relations/{relation_id}")
async def remove_relation(request: Request, relation_id: int):
    """Remove a relation by ID."""
    if db_delete_relation(relation_id):
        return {"deleted": True, "id": relation_id}
    return problem(404, "Relation not found", instance=request.url.path)


@router.patch("/relations/{relation_id}")
async def patch_relation(request: Request, relation_id: int, body: RelationPatch):
    """Update relation type or confidence."""
    conn = get_connection()
    try:
        existing = conn.execute(
            "SELECT * FROM entry_relations WHERE id = ?", (relation_id,)
        ).fetchone()
        if not existing:
            return problem(404, "Relation not found", instance=request.url.path)

        updates = {}
        if body.relation_type is not None:
            if body.relation_type not in RELATION_TYPES:
                return problem(422, f"Invalid relation type: {body.relation_type}",
                              instance=request.url.path)
            updates["relation_type"] = body.relation_type
        if body.confidence is not None:
            updates["confidence"] = body.confidence

        if updates:
            set_clause = ", ".join(f"{k} = ?" for k in updates)
            conn.execute(
                f"UPDATE entry_relations SET {set_clause} WHERE id = ?",
                list(updates.values()) + [relation_id]
            )
            conn.commit()

        return {"updated": True, "id": relation_id, "changes": updates}
    finally:
        conn.close()


@router.post("/bootstrap")
async def bootstrap_graph(
    request: Request,
    dry_run: bool = Query(False),
    use_llm: bool = Query(False),
    batch_size: int = Query(50, ge=1, le=500),
):
    """Trigger retroactive relation extraction over all entries."""
    try:
        from handlers.relations import bootstrap_relations

        result = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: bootstrap_relations(
                dry_run=dry_run,
                batch_size=batch_size,
                use_llm=use_llm,
            )
        )
        return result

    except ImportError:
        return problem(501, "Bootstrap function not available",
                      instance=request.url.path)
    except Exception as e:
        logger.error(f"Bootstrap failed: {e}", exc_info=True)
        return problem(500, f"Bootstrap failed: {e}", instance=request.url.path)


# =============================================================================
# Graph Algorithm Helpers
# =============================================================================

def _sample_avg_shortest_path(conn, sample_size: int = 30) -> float:
    """Estimate average shortest path via sampled BFS."""
    import random

    ids = [row[0] for row in conn.execute("SELECT id FROM entries").fetchall()]
    if len(ids) < 2:
        return 0.0

    # Build adjacency list
    adj = defaultdict(set)
    rows = conn.execute("SELECT source_id, target_id FROM entry_relations").fetchall()
    for row in rows:
        adj[row["source_id"]].add(row["target_id"])
        adj[row["target_id"]].add(row["source_id"])

    samples = random.sample(ids, min(sample_size, len(ids)))
    total_dist = 0
    path_count = 0

    for start in samples:
        # BFS from start
        visited = {start: 0}
        queue = deque([start])
        while queue:
            current = queue.popleft()
            for neighbor in adj.get(current, []):
                if neighbor not in visited:
                    visited[neighbor] = visited[current] + 1
                    queue.append(neighbor)

        # Sum distances to all reachable nodes
        for dist in visited.values():
            if dist > 0:
                total_dist += dist
                path_count += 1

    return round(total_dist / path_count, 2) if path_count > 0 else 0.0


def _compute_clustering_coefficient(conn) -> dict:
    """Compute global and per-category clustering coefficients.

    Skip categories with <10 entries (not enough for meaningful coefficient).
    """
    # Build adjacency list
    adj = defaultdict(set)
    rows = conn.execute("SELECT source_id, target_id FROM entry_relations").fetchall()
    for row in rows:
        adj[row["source_id"]].add(row["target_id"])
        adj[row["target_id"]].add(row["source_id"])

    # Entry categories
    entry_cats = {}
    for row in conn.execute("SELECT id, category FROM entries").fetchall():
        entry_cats[row["id"]] = row["category"]

    def _node_clustering(node):
        neighbors = adj.get(node, set())
        k = len(neighbors)
        if k < 2:
            return 0.0
        # Count edges between neighbors
        edges = sum(1 for n in neighbors for m in neighbors if m in adj.get(n, set()) and n < m)
        max_edges = k * (k - 1) / 2
        return edges / max_edges if max_edges > 0 else 0.0

    # Global
    coefficients = [_node_clustering(n) for n in adj if len(adj[n]) >= 2]
    global_cc = round(sum(coefficients) / len(coefficients), 3) if coefficients else 0.0

    # Per category
    cat_groups = defaultdict(list)
    for node in adj:
        cat = entry_cats.get(node)
        if cat:
            cat_groups[cat].append(node)

    per_cat = {}
    for cat, nodes in cat_groups.items():
        if len(nodes) < 10:
            continue
        cat_ccs = [_node_clustering(n) for n in nodes if len(adj[n]) >= 2]
        per_cat[cat] = round(sum(cat_ccs) / len(cat_ccs), 3) if cat_ccs else 0.0

    return {"global": global_cc, "per_category": per_cat}


def _find_bridges(conn) -> list[dict]:
    """Find bridge entries — high cross-category connection counts.

    Simple approximation: entries that connect to entries in 3+ different categories.
    """
    adj = defaultdict(set)
    rows = conn.execute("SELECT source_id, target_id FROM entry_relations").fetchall()
    for row in rows:
        adj[row["source_id"]].add(row["target_id"])
        adj[row["target_id"]].add(row["source_id"])

    entry_info = {}
    for row in conn.execute("SELECT id, title, category FROM entries").fetchall():
        entry_info[row["id"]] = {"title": row["title"], "category": row["category"]}

    bridges = []
    for node, neighbors in adj.items():
        info = entry_info.get(node, {})
        node_cat = info.get("category", "")

        # Count distinct categories among neighbors (excluding own category)
        neighbor_cats = set()
        for n in neighbors:
            n_info = entry_info.get(n, {})
            n_cat = n_info.get("category", "")
            if n_cat and n_cat != node_cat:
                neighbor_cats.add(n_cat)

        if len(neighbor_cats) >= 2:
            bridges.append({
                "id": node,
                "title": info.get("title", ""),
                "category": node_cat,
                "cross_category_connections": len(neighbor_cats),
                "categories_connected": sorted(neighbor_cats),
                "total_connections": len(neighbors),
            })

    bridges.sort(key=lambda x: x["cross_category_connections"], reverse=True)
    return bridges


def _compute_freshness(conn) -> dict:
    """Compute freshness statistics for graph relations.

    Q11: Freshness computed on-the-fly from dateCreated.
    """
    now = datetime.now(timezone.utc)
    rows = conn.execute("SELECT created_at FROM entry_relations").fetchall()

    if not rows:
        return {"avg_age_days": 0, "newest_days": 0, "oldest_days": 0, "total": 0}

    ages = []
    for row in rows:
        try:
            created = datetime.fromisoformat(row["created_at"].replace("Z", "+00:00"))
            age = (now - created).days
            ages.append(age)
        except (ValueError, TypeError):
            pass

    if not ages:
        return {"avg_age_days": 0, "newest_days": 0, "oldest_days": 0, "total": 0}

    return {
        "avg_age_days": round(sum(ages) / len(ages), 1),
        "newest_days": min(ages),
        "oldest_days": max(ages),
        "total": len(ages),
    }
