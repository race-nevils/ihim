"""Adapter for heuristics.json → brain entries.

Source: IHIM/data/heuristics.json
Granularity: 1 entry per heuristic
Category: Reference
"""
import json
from pathlib import Path
from typing import Iterator

from .base import ContentAdapter


class HeuristicsAdapter(ContentAdapter):

    def can_handle(self, file_path: Path) -> bool:
        return file_path.name == "heuristics.json"

    def extract_entries(self, file_path: Path) -> Iterator[dict]:
        data = json.loads(file_path.read_text(encoding="utf-8"))
        heuristics = data.get("heuristics", [])

        for h in heuristics:
            hid = h.get("id", "unknown")
            trigger = h.get("trigger", "")
            action = h.get("action", "")
            pattern = h.get("pattern", "")
            status = h.get("status", "unknown")
            confidence = h.get("confidence")
            fire_count = h.get("fire_count", 0)
            miss_count = h.get("miss_count", 0)

            title = f"Heuristic {hid}: {trigger[:60]}"
            summary = f"{hid} — {action[:100]}"

            content_lines = [
                f"# Heuristic {hid}",
                "",
                f"**Trigger:** {trigger}",
                f"**Action:** {action}",
                f"**Pattern:** {pattern}",
                f"**Status:** {status}",
                f"**Confidence:** {confidence if confidence is not None else 'unscored'}",
                f"**Fire count:** {fire_count}",
                f"**Miss count:** {miss_count}",
            ]

            yield {
                "title": title,
                "category": "Reference",
                "summary": summary,
                "content": "\n".join(content_lines),
                "source_id": hid,
            }
