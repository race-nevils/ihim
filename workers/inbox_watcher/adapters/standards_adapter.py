"""Adapter for standards_library references.json → brain entries.

Source: IHIM/data/standards_library/references/references.json
Granularity: 1 entry per standard (references listed in content)
Category: Reference
"""
import json
from pathlib import Path
from typing import Iterator

from .base import ContentAdapter


class StandardsAdapter(ContentAdapter):

    def can_handle(self, file_path: Path) -> bool:
        # Match specifically the references.json inside standards_library
        return (
            file_path.name == "references.json"
            and "standards_library" in str(file_path)
        )

    def extract_entries(self, file_path: Path) -> Iterator[dict]:
        data = json.loads(file_path.read_text(encoding="utf-8"))
        standards = data.get("standards", [])

        for std in standards:
            sid = std.get("id", "unknown")
            name = std.get("name", sid)
            description = std.get("description", "")
            references = std.get("references", [])

            title = f"Standard {sid}: {name} References"
            summary = f"{name} — {description[:100]}"

            content_lines = [
                f"# {name}",
                "",
                f"{description}",
                "",
                f"## References ({len(references)})",
                "",
            ]

            for i, ref in enumerate(references, 1):
                ref_title = ref.get("title", "Untitled")
                ref_url = ref.get("url", "")
                ref_type = ref.get("type", "")
                ref_desc = ref.get("description", "")
                content_lines.append(f"{i}. **{ref_title}** [{ref_type}]")
                if ref_url:
                    content_lines.append(f"   URL: {ref_url}")
                if ref_desc:
                    content_lines.append(f"   {ref_desc}")
                content_lines.append("")

            yield {
                "title": title,
                "category": "Reference",
                "summary": summary,
                "content": "\n".join(content_lines),
                "source_id": sid,
            }
