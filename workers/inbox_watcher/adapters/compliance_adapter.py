"""Adapter for compliance module JSON files → brain entries.

Source: IHIM/data/compliance_modules/*.json (hipaa.json, osha.json, pci-dss.json)
Granularity: 1 entry per control (flattens catalog.groups[].controls[])
Category: Legal
"""
import json
from pathlib import Path
from typing import Iterator

from .base import ContentAdapter


class ComplianceAdapter(ContentAdapter):

    def can_handle(self, file_path: Path) -> bool:
        return (
            file_path.suffix == ".json"
            and "compliance_modules" in str(file_path)
        )

    def extract_entries(self, file_path: Path) -> Iterator[dict]:
        data = json.loads(file_path.read_text(encoding="utf-8"))

        metadata = data.get("module_metadata", {})
        framework = metadata.get("framework", metadata.get("module_name", "Unknown"))
        catalog = data.get("catalog", {})
        groups = catalog.get("groups", [])

        for group in groups:
            group_title = group.get("title", "")
            controls = group.get("controls", [])

            for ctrl in controls:
                control_id = ctrl.get("control_id", "unknown")
                ctrl_title = ctrl.get("title", "")
                description = ctrl.get("description", "")
                requirements = ctrl.get("requirements", [])
                references = ctrl.get("references", [])

                title = f"Compliance {framework}-{control_id}: {ctrl_title}"
                summary = f"{framework} {control_id} — {ctrl_title}"

                content_lines = [
                    f"# {framework} — {control_id}: {ctrl_title}",
                    "",
                    f"**Framework:** {framework}",
                    f"**Control ID:** {control_id}",
                    f"**Group:** {group_title}",
                    "",
                    f"## Description",
                    "",
                    description,
                    "",
                ]

                if requirements:
                    content_lines.append("## Requirements")
                    content_lines.append("")
                    for req in requirements:
                        content_lines.append(f"- {req}")
                    content_lines.append("")

                if references:
                    content_lines.append("## References")
                    content_lines.append("")
                    for ref in references:
                        citation = ref.get("citation", "")
                        url = ref.get("url", "")
                        if citation and url:
                            content_lines.append(f"- {citation}: {url}")
                        elif citation:
                            content_lines.append(f"- {citation}")
                    content_lines.append("")

                yield {
                    "title": title,
                    "category": "Legal",
                    "summary": summary,
                    "content": "\n".join(content_lines),
                    "source_id": f"{framework}-{control_id}",
                }
