"""Pipeline Observability — IETF Health Check (draft-inadarei-api-health-check-06).

GET /api/pipeline/status → application/health+json

Aggregates brain pipeline health from 5 sources:
  1. rebuild_log table — last 10 rebuilds for trend data
  2. Watcher lock/log — inbox_watcher running status
  3. Graph stats — entries, relations, orphan rate
  4. Embedding coverage — vec_entries vs entries
  5. Error log — last 5 from rebuild_errors.jsonl

Response conforms to the IETF health check draft:
  - Content-Type: application/health+json
  - HTTP 200 for pass/warn, 503 for fail
  - status values: "pass", "warn", "fail"
  - checks keyed as "component:measurement"
  - Extensions prefixed with _ (_trends, _errors)
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Response

from data.database import get_connection

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])

IHIM_ROOT = Path(__file__).parent.parent.parent
DATA_DIR = IHIM_ROOT / "data"
WATCHER_LOCK = DATA_DIR / "watcher.lock"
WATCHER_LOG = DATA_DIR / "watcher.log"
REBUILD_LOGS_DIR = DATA_DIR / "local" / "brain" / "logs"
ERRORS_JSONL = REBUILD_LOGS_DIR / "rebuild_errors.jsonl"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _watcher_check() -> dict[str, Any]:
    """Check inbox watcher status via lock file and log tail."""
    now = datetime.now(timezone.utc)
    check: dict[str, Any] = {
        "componentId": "inbox-watcher",
        "componentType": "component",
        "time": _now_iso(),
    }

    if not WATCHER_LOCK.exists():
        check["observedValue"] = False
        check["status"] = "fail"
        check["output"] = "Lock file not found — watcher not running"
        return check

    # Lock file exists — check how recent it is
    try:
        mtime = datetime.fromtimestamp(WATCHER_LOCK.stat().st_mtime, tz=timezone.utc)
        age_seconds = (now - mtime).total_seconds()
    except OSError:
        check["observedValue"] = False
        check["status"] = "fail"
        check["output"] = "Cannot read lock file"
        return check

    # Also check log file for last activity
    last_log_age = None
    if WATCHER_LOG.exists():
        try:
            log_mtime = datetime.fromtimestamp(WATCHER_LOG.stat().st_mtime, tz=timezone.utc)
            last_log_age = (now - log_mtime).total_seconds()
        except OSError:
            pass

    effective_age = min(age_seconds, last_log_age) if last_log_age is not None else age_seconds

    check["observedValue"] = True
    if effective_age < 600:  # < 10 min
        check["status"] = "pass"
        check["output"] = f"Last activity {int(effective_age)}s ago"
    else:
        check["status"] = "warn"
        check["output"] = f"Stale — last activity {int(effective_age)}s ago (>{int(600)}s threshold)"

    return check


def _rebuild_checks(conn) -> tuple[dict[str, Any], list[int], list[int], list[str]]:
    """Get last rebuild status + trend data from rebuild_log table.

    Returns (check_dict, entry_trend, relation_trend, timestamps).
    """
    check: dict[str, Any] = {
        "componentId": "rebuild-engine",
        "componentType": "component",
        "time": _now_iso(),
    }

    entry_trend: list[int] = []
    relation_trend: list[int] = []
    timestamps: list[str] = []

    try:
        rows = conn.execute(
            "SELECT * FROM rebuild_log ORDER BY completed_at DESC LIMIT 10"
        ).fetchall()
    except Exception as e:
        logger.warning("rebuild_log query failed: %s", e)
        check["observedValue"] = None
        check["status"] = "fail"
        check["output"] = f"Cannot read rebuild_log: {e}"
        return check, entry_trend, relation_trend, timestamps

    if not rows:
        check["observedValue"] = None
        check["status"] = "fail"
        check["output"] = "No rebuild records found"
        return check, entry_trend, relation_trend, timestamps

    latest = dict(rows[0])
    check["observedValue"] = latest.get("completed_at")

    error_count = latest.get("error_count", 0) or 0
    in_sync = latest.get("in_sync", 0)

    if in_sync and error_count == 0:
        check["status"] = "pass"
        check["output"] = f"In sync, 0 errors"
    elif error_count > 0:
        check["status"] = "warn"
        check["output"] = f"{error_count} error(s) in last rebuild"
    else:
        check["status"] = "warn"
        check["output"] = "Not in sync"

    # Build trend arrays (oldest first)
    for row in reversed(rows):
        r = dict(row)
        entry_trend.append(r.get("db_after") or 0)
        # Relations aren't stored in rebuild_log — will be filled from graph stats
        timestamps.append(r.get("completed_at", ""))

    return check, entry_trend, relation_trend, timestamps


def _graph_checks(conn) -> tuple[list[dict], int, int, int]:
    """Graph health checks: entries, relations, orphan rate.

    Returns (list_of_checks, total_entries, total_relations, orphan_count).
    """
    checks = []
    total_entries = 0
    total_relations = 0
    orphan_count = 0

    try:
        total_entries = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
        total_relations = conn.execute("SELECT COUNT(*) FROM entry_relations").fetchone()[0]

        orphan_count = conn.execute("""
            SELECT COUNT(*) FROM entries e
            WHERE e.id NOT IN (
                SELECT source_id FROM entry_relations
                UNION
                SELECT target_id FROM entry_relations
            )
        """).fetchone()[0]
    except Exception as e:
        logger.warning("Graph stats query failed: %s", e)
        checks.append({
            "componentType": "datastore",
            "observedValue": None,
            "status": "fail",
            "output": f"Graph query failed: {e}",
        })
        return checks, 0, 0, 0

    # Entries check
    checks.append({
        "componentType": "datastore",
        "observedValue": total_entries,
        "observedUnit": "{entry}",
        "status": "pass" if total_entries > 0 else "fail",
    })

    # Relations check
    checks.append({
        "componentType": "datastore",
        "observedValue": total_relations,
        "observedUnit": "{relation}",
        "status": "pass" if total_relations > 0 else "warn",
    })

    # Orphan rate check
    orphan_rate = round(orphan_count / total_entries, 4) if total_entries > 0 else 0.0
    orphan_status = "pass" if orphan_rate < 0.05 else ("warn" if orphan_rate < 0.2 else "fail")
    checks.append({
        "componentType": "datastore",
        "observedValue": orphan_rate,
        "observedUnit": "1",
        "status": orphan_status,
        "output": f"{orphan_rate:.0%} orphan rate ({orphan_count} entries)",
    })

    return checks, total_entries, total_relations, orphan_count


def _embedding_check(conn, total_entries: int) -> dict[str, Any]:
    """Embedding coverage check."""
    check: dict[str, Any] = {
        "componentType": "datastore",
        "time": _now_iso(),
    }

    try:
        vec_count = conn.execute("SELECT COUNT(*) FROM vec_entries").fetchone()[0]
    except Exception:
        vec_count = 0

    coverage = round((vec_count / total_entries) * 100, 1) if total_entries > 0 else 0.0
    check["observedValue"] = coverage
    check["observedUnit"] = "%"
    check["status"] = "pass" if coverage >= 90 else ("warn" if coverage >= 50 else "fail")

    return check


def _recent_errors(max_count: int = 5) -> list[dict]:
    """Read last N errors from rebuild_errors.jsonl."""
    if not ERRORS_JSONL.exists():
        return []

    errors = []
    try:
        with open(ERRORS_JSONL, "r", encoding="utf-8") as f:
            lines = f.readlines()
        for line in lines[-max_count:]:
            line = line.strip()
            if line:
                try:
                    errors.append(json.loads(line))
                except json.JSONDecodeError:
                    errors.append({"error": line})
    except OSError as e:
        logger.warning("Cannot read error log: %s", e)

    return errors


def _overall_status(*checks_list: dict[str, Any]) -> str:
    """Derive overall status from individual checks (worst wins).

    Per health check draft: "pass" < "warn" < "fail".
    """
    severity = {"pass": 0, "warn": 1, "fail": 2}
    worst = 0
    for check in checks_list:
        status = check.get("status", "pass")
        worst = max(worst, severity.get(status, 0))
    return ["pass", "warn", "fail"][worst]


@router.get("/status")
async def pipeline_status():
    """Pipeline health — draft-inadarei-api-health-check-06.

    Returns application/health+json with aggregated pipeline status.
    HTTP 200 for pass/warn, 503 for fail.
    """
    conn = get_connection()
    try:
        # 1. Watcher
        watcher = _watcher_check()

        # 2. Rebuild
        rebuild, entry_trend, _, rebuild_timestamps = _rebuild_checks(conn)

        # 3. Graph
        graph_checks, total_entries, total_relations, orphan_count = _graph_checks(conn)
        entries_check, relations_check, orphan_check = (
            graph_checks[0] if len(graph_checks) > 0 else {},
            graph_checks[1] if len(graph_checks) > 1 else {},
            graph_checks[2] if len(graph_checks) > 2 else {},
        )

        # 4. Embeddings
        embeddings = _embedding_check(conn, total_entries)

        # 5. Errors
        errors = _recent_errors()

        # Build relation trend from rebuild_log (not stored there, use current count)
        # For now, just repeat current — trend will build over future rebuilds
        relation_trend = [total_relations]

        # Overall status
        all_checks = [watcher, rebuild, entries_check, relations_check, orphan_check, embeddings]
        status = _overall_status(*all_checks)

        body = {
            "status": status,
            "version": "1",
            "serviceId": "ihim-brain-pipeline",
            "description": "iHIM brain pipeline health",
            "checks": {
                "watcher:heartbeat": [watcher],
                "rebuild:lastRun": [rebuild],
                "graph:entries": [entries_check],
                "graph:relations": [relations_check],
                "graph:orphanRate": [orphan_check],
                "embeddings:coverage": [embeddings],
            },
            "notes": [],
            "output": "",
            "links": {
                "self": "/api/pipeline/status",
                "graph-health": "/api/graph/health",
            },
            "_trends": {
                "entries": entry_trend,
                "relations": relation_trend,
                "timestamps": rebuild_timestamps,
            },
            "_errors": errors,
        }

        http_status = 200 if status in ("pass", "warn") else 503

        return Response(
            content=json.dumps(body, default=str),
            status_code=http_status,
            media_type="application/health+json",
            headers={
                "Cache-Control": "max-age=10, stale-while-revalidate=20",
            },
        )
    finally:
        conn.close()
